#!/usr/bin/env python3
"""READ-ONLY local audit of the existing cSS dataset. Runs on the lab Mac; makes no network connection.

usage:  python3 -B audit_local_dataset.py [CSS_BASE] [--out DIR]
        CSS_BASE defaults to $CSS_BASE or ~/css_project.
        The report goes to ~/cSS_audit_reports/ by default (OUTSIDE the dataset folder). An --out folder inside
        the dataset, inside ~/Desktop or ~/Documents, or inside a cloud-synced folder is refused.

What it does
  * opens files for READING only (it never writes inside data/, raw/, subjects/, review/, labels/, work/);
  * writes nothing inside CSS_BASE; writes exactly two report files (audit_<YYYYmmdd_HHMM>.json / .md) holding COUNTS ONLY: no study codes, no names,
    no file paths, no dates of birth, no DICOM headers, no feature values;
  * does NOT open reader calls of protected held-out / test studies (labels/study_meta.csv split == test,
    the unified-score manifest role == held-out, or the fixed list in HELDOUT_FIXED): those are only counted
    as "file present";
  * blocks every non-loopback network connection for its own process, as a safety net.
You read the report yourself before deciding whether to share any of it. Nothing is sent anywhere.
"""
import os, sys, json, glob, hashlib, socket, datetime, collections, re
sys.dont_write_bytecode = True

# ---- safety net: this process cannot open a network connection except to this computer ----
_orig_connect = socket.socket.connect
def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else addr
    if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
        raise PermissionError(f"audit_local_dataset: network connection to {host} blocked (local-only)")
    return _orig_connect(self, addr)
socket.socket.connect = _guard

VOCAB = {"css", "vessel", "vein", "normal", "artifact", "artefact", "microbleed", "unsure", "uncertain", "near ich", "other", "not css", "mimic"}
HELDOUT_FIXED = {f"M{i}" for i in range(27, 37)}    # protected held-out test set M27-M36 (user decision 2026-11-20; was M01, M12-M15)

a = sys.argv[1:]
out_dir = a[a.index("--out") + 1] if "--out" in a else None
pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--out")]
B = os.path.expanduser(pos[0] if pos else os.environ.get("CSS_BASE", "~/css_project"))
if not os.path.isdir(B): sys.exit(f"not a folder: {B}")
out_dir = os.path.realpath(os.path.expanduser(out_dir or "~/cSS_audit_reports"))
_home = os.path.realpath(os.path.expanduser("~")); _bR = os.path.realpath(B)
_cloud = ("/Library/Mobile Documents/", "/Library/CloudStorage/", "/Dropbox", "/Google Drive", "/OneDrive", "/iCloud", "/Box/", "/pCloud")
if out_dir == _bR or out_dir.startswith(_bR + "/"): sys.exit("refused: the report folder must be outside the dataset folder")
if any(out_dir == os.path.join(_home, d) or out_dir.startswith(os.path.join(_home, d) + "/") for d in ("Desktop", "Documents")):
    sys.exit("refused: ~/Desktop and ~/Documents may be synced by iCloud; choose another local folder with --out")
if any(m.lower() in (out_dir + "/").lower() for m in _cloud): sys.exit("refused: the report folder is inside a cloud-synced folder")

def rd_csv(p):
    import csv
    with open(p, newline="", encoding="utf-8", errors="replace") as f: return list(csv.DictReader(f))
def rd_json(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def sha(p, n=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(n), b""): h.update(b)
    return h.hexdigest()
def dist(c): return dict(sorted(collections.Counter(c).items(), key=lambda kv: -kv[1]))

R = dict(generated=datetime.datetime.now().isoformat(timespec="seconds"), tool="audit_local_dataset.py (read-only, counts only)",
         notes=[])

# ---- 1. studies on disk ----
studies = set()
for pat, rx in ((f"{B}/data/*_swi.nii*", r"(.+)_swi\.nii"), (f"{B}/review/*_candidates.csv", r"(.+)_candidates\.csv"), (f"{B}/raw/*", r"(.+)")):
    for p in glob.glob(pat):
        m = re.match(rx, os.path.basename(p))
        if m and os.path.isdir(p) == pat.endswith("/*"): studies.add(m.group(1))
R["studies_found"] = len(studies)

# ---- 2. held-out / split definition (identifiers used only in memory) ----
held = set(HELDOUT_FIXED)
meta_p = f"{B}/labels/study_meta.csv"; meta = rd_csv(meta_p) if os.path.exists(meta_p) else []
if meta:
    R["study_meta"] = dict(rows=len(meta), columns=[c if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_ ]{0,30}", c) else "(unusual column name)" for c in meta[0].keys()], split=dist(r.get("split", "") if r.get("split", "") in ("dev", "test") else ("(blank)" if not r.get("split") else "(other)") for r in meta),
                           status=dist(r.get("status", "") if r.get("status", "") in ("pos", "neg", "uncertain") else ("(blank)" if not r.get("status") else "(other)") for r in meta if r.get("split") != "test"))
    held |= {r["study_id"] for r in meta if r.get("split") == "test" and r.get("study_id")}
else: R["notes"].append("labels/study_meta.csv not found: no recorded dev/test split")
for mp in glob.glob(f"{B}/unified_score/**/manifest*.csv", recursive=True) + glob.glob(f"{B}/uscore/**/manifest*.csv", recursive=True):
    try: held |= {r.get("study_id") for r in rd_csv(mp) if (r.get("role") or "").startswith("held")}
    except Exception: pass
held &= studies | HELDOUT_FIXED
R["protected_heldout_studies"] = dict(count=len(held & studies), labels_opened=False)

# ---- 3. MRI identity, duplicates, acquisition ----
swi_hash = collections.defaultdict(list); vox = []; dims = []
try: import nibabel as nib
except Exception: nib = None; R["notes"].append("nibabel not importable: voxel size / dimensions not audited")
for s in studies:
    p = next(iter(glob.glob(f"{B}/data/{s}_swi.nii*")), None)
    if not p: continue
    swi_hash[sha(p)].append(s)
    if nib:
        try:
            h = nib.load(p).header; z = [round(float(x), 2) for x in h.get_zooms()[:3]]
            vox.append("×".join(map(str, z))); dims.append("×".join(map(str, h.get_data_shape()[:3])))
        except Exception: vox.append("unreadable")
dup_groups = [g for g in swi_hash.values() if len(g) > 1]
R["mri"] = dict(with_swi=sum(len(g) for g in swi_hash.values()), unique_swi_files=len(swi_hash),
                identical_swi_duplicate_groups=len(dup_groups), studies_in_duplicate_groups=sum(len(g) for g in dup_groups),
                duplicates_touching_heldout=sum(1 for g in dup_groups if set(g) & held and set(g) - held),
                voxel_size_mm=dist(vox), dimensions=dist(dims))

# ---- 4. patient grouping: is there any patient identifier? ----
pat_cols = {}
for p in sorted(set([meta_p] + glob.glob(f"{B}/labels/*.csv"))):
    if os.path.exists(p):
        try:
            cols = list(rd_csv(p)[0].keys()) if rd_csv(p) else []
            pat_cols[f"label_table_{len(pat_cols) + 1}"] = [c for c in cols if re.search(r"patient|subject|mrn|pseudo|person", c, re.I)]
        except Exception: pass
R["patient_grouping"] = dict(candidate_patient_id_columns=pat_cols,
                             finding=("no patient-level identifier column found: repeat examinations of one patient cannot be grouped "
                                      "automatically; a pseudonymous patient key must be supplied before training") if not any(pat_cols.values()) else
                                     "patient-like columns found (names listed): verify they are a pseudonymous patient key")

# ---- 5. app records (grades, radiologist) ----
P = rd_json(f"{B}/app_data/patients.json", []) or []
R["app_patients"] = dict(records=len(P), fields=sorted({k for p in P for k in p}),
                         with_grade_R_or_L=sum(1 for p in P if str(p.get("grade_R", "")).strip() or str(p.get("grade_L", "")).strip()),
                         with_radiologist=sum(1 for p in P if str(p.get("radiologist", "")).strip()),
                         status=dist(p.get("status", "") for p in P), mode=dist(p.get("mode", "") for p in P),
                         duplicate_source_folder=sum(c - 1 for c in collections.Counter(p.get("source_folder_hash") for p in P if p.get("source_folder_hash")).values() if c > 1))

# ---- 6. candidate-level labels (development studies only) ----
cand_n = 0; calls_files = 0; calls_held = 0; call_vals = collections.Counter(); unread = 0; per_study_pos = []
cols_seen = collections.Counter(); has_fp = 0; studies_with_calls = 0
for s in studies:
    cp = f"{B}/review/{s}_candidates.csv"
    if os.path.exists(cp):
        try: cand_n += len(rd_csv(cp))
        except Exception: pass
    kp = f"{B}/review/{s}_calls.csv"
    if not os.path.exists(kp): continue
    calls_files += 1
    if s in held: calls_held += 1; continue                       # held-out: presence only, never opened
    rows = rd_csv(kp); studies_with_calls += 1
    for c in (rows[0].keys() if rows else []): cols_seen[c] += 1
    has_fp += any(k in (rows[0] if rows else {}) for k in ("cand_uid", "fingerprint"))
    v = [(r.get("call") or "").strip() or "(blank)" for r in rows]
    call_vals.update(x if x.lower() in VOCAB or x == "(blank)" else "(other free text)" for x in v)
    unread += sum(1 for x in v if x == "(blank)"); per_study_pos.append(sum(1 for x in v if x.lower() == "css"))
R["candidates"] = dict(total_candidates_all_studies=cand_n, studies_with_calls_file=calls_files,
                       calls_files_of_heldout_not_opened=calls_held, development_studies_with_calls=studies_with_calls,
                       call_values=dict(call_vals), blank_calls=unread,
                       call_file_columns={(c if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_ ]{0,30}", c) else "(unusual column name)"): n for c, n in cols_seen.items()},
                       calls_files_with_fingerprint=has_fp,
                       dev_studies_with_any_cSS_call=sum(1 for x in per_study_pos if x), dev_studies_without_cSS_call=sum(1 for x in per_study_pos if not x))

# ---- 7. provenance: AI outputs, model versions, reviewers, blinding ----
ai = [rd_json(p, {}) or {} for p in glob.glob(f"{B}/review/*_score_ai.json")]
man = [rd_json(p, {}) or {} for p in glob.glob(f"{B}/review/*_manifest.json")]
ver = [str((m.get("detect") or {}).get("pipeline_version", "unknown")) for m in man]
rv = rd_json(f"{B}/review/reviewers.json") or rd_json(f"{B}/app_data/reviewers.json")
R["provenance"] = dict(studies_with_ai_score_file=len(ai), ai_scoring_methods=dist(a_.get("scoring_method", "unknown") for a_ in ai),
                       studies_with_detection_manifest=len(man), detector_versions=dist(ver),
                       studies_with_confidence_model_output=sum(1 for p in glob.glob(f"{B}/review/*_candidates.csv")
                                                               if "confidence_pct" in open(p, errors="replace").readline()),
                       reviewers_file_present=rv is not None, reviewers_count=(len(rv) if isinstance(rv, (list, dict)) else None),
                       blind_read_packets=len(glob.glob(f"{B}/reference_audit/blind_read/*")),
                       review_condition_recorded=False,
                       finding="no per-label field records whether the reviewer saw the AI score; per your description the "
                               "existing grading is AI-ASSISTED and must be imported with provenance 'AI-assisted human review'")

# ---- 8. what is missing for supervised training ----
need = []
if not any(pat_cols.values()): need.append("a pseudonymous patient key per study (to group repeat examinations)")
if not R["candidates"]["development_studies_with_calls"]: need.append("candidate-level calls (review/<ID>_calls.csv) for development studies")
need.append("per-label review condition (AI shown or not) - existing labels will be marked AI-assisted")
need.append("independent blinded or adjudicated labels for a validation subset")
R["missing_for_training"] = need

os.makedirs(out_dir, exist_ok=True); stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
json.dump(R, open(os.path.join(out_dir, f"audit_{stamp}.json"), "w"), indent=1)
md = ["# Local dataset audit (counts only, read-only)", f"generated {R['generated']}", ""]
for k, v in R.items():
    if k in ("generated", "tool"): continue
    md += [f"## {k}", "```", json.dumps(v, indent=1, ensure_ascii=False), "```", ""]
open(os.path.join(out_dir, f"audit_{stamp}.md"), "w").write("\n".join(md))
print(f"audit written to {os.path.join(out_dir, 'audit_' + stamp)}.md / .json (counts only; nothing was sent anywhere - read it before sharing anything)")
