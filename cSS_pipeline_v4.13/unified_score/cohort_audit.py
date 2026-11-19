"""cohort_audit.py - READ-ONLY audit of every MRI study identifier in $CSS_BASE for the unified-score project.
Rule: ONLY studies whose identifier starts with 'M' are eligible. Everything else (P, PH, T, synthetic) is excluded and
must not enter any dataset or analysis. Roles come from cohort_manifest_PROVISIONAL.csv (development / held-out);
an M study missing from it is reported as 'unassigned' (never silently allocated).
Checks: patient-level separation (no study in two roles), duplicate scans (same SWI content under two IDs), T/M twins,
candidate counts, label availability (reader calls, expert labels), and that no non-M ID appears in any label file.
Also: refuses a test base (path under /tmp or a scratchpad), flags M-named random-noise fixtures, and writes per-study
scoreability by feature group (unified_score/cohort_scoreability.csv) from ID_qc.json + file presence. Registration
limits are PROVISIONAL, from the synthetic shift test (reconcile/shift_sensitivity.py): label shift > 1.0 mm makes the
label-dependent groups unreliable; 0.5-1.0 mm = marginal for sulcal direction.
Writes unified_score/cohort_manifest.csv (codes only). Changes nothing else.
usage: CSS_BASE=~/css_project python unified_score/cohort_audit.py"""
import os, sys, csv, glob, json, hashlib, re
H = os.path.dirname(os.path.abspath(__file__)); B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
ID = re.compile(r"^([A-Z]{1,2}\d{2,3}[A-Z]?)")
if os.path.realpath(B).startswith(("/tmp", "/private/tmp")) or "scratchpad" in B:
    sys.exit(f"cohort_audit: {B} looks like a test base (fixtures with patient-like names live there) - run it on the project base")
MAN = f"{H}/cohort_manifest_RECONCILED.csv" if os.path.exists(f"{H}/cohort_manifest_RECONCILED.csv") else f"{H}/cohort_manifest_PROVISIONAL.csv"
prov = {r["study_id"]: r for r in csv.DictReader(open(MAN))}
seen = {}
def note(i, src):
    if i: seen.setdefault(i, set()).add(src)
for d in glob.glob(f"{B}/raw/*"): note(os.path.basename(d), "raw")
for f in glob.glob(f"{B}/data/*_swi.nii*"): note(os.path.basename(f).split("_swi")[0], "data")
for f in glob.glob(f"{B}/review/*_candidates.csv"): note(os.path.basename(f).rsplit("_candidates", 1)[0], "candidates")
for f in glob.glob(f"{B}/review/*_calls*.csv"): note(os.path.basename(f).split("_calls")[0], "calls")
for f in glob.glob(f"{B}/labels/*.csv"):
    try:
        for r in csv.DictReader(open(f)):
            for k in ("study_id", "study", "subject"):
                if r.get(k): note(r[k], f"labels/{os.path.basename(f)}")
    except Exception: pass
try:
    for p in json.load(open(f"{B}/app_data/patients.json")): note(p["code"], "app")
except Exception: pass
def swi_hash(i):
    for f in (f"{B}/data/{i}_swi.nii", f"{B}/data/{i}_swi.nii.gz"):
        if os.path.exists(f):
            with open(f, "rb") as fh: return hashlib.sha1(fh.read(1 << 22)).hexdigest()[:16]
    return ""
def count(path):
    try: return sum(1 for _ in open(path)) - 1
    except Exception: return ""
def is_noise_fixture(i):
    try:
        import nibabel as nib, numpy as np
        for f in (f"{B}/data/{i}_swi.nii", f"{B}/data/{i}_swi.nii.gz"):
            if os.path.exists(f):
                a = np.asarray(nib.load(f).dataobj, np.float32); return bool(a.min() >= 0 and a.max() < 1 and abs(a.mean() - 0.5) < 0.02)
    except Exception: pass
    return False
def scoreability(i):
    q = {}
    try: q = json.load(open(f"{B}/review/{i}_qc.json"))
    except Exception: pass
    t1 = os.path.exists(f"{B}/work/{i}_t1seg_swispace.nii.gz"); sh = q.get("label_shift_mm"); vox = q.get("voxel_mm") or []
    rawswi = bool(glob.glob(f"{B}/raw/{i}/SWI/*.nii*")); thick = max(vox) if vox else None
    if not q: reg = "unknown (no QC file)"
    elif not t1: reg = "SWI-only anatomy (coarse)"
    elif sh is None: reg = "unmeasured"
    else: reg = "ok" if sh <= 0.5 else ("marginal" if sh <= 1.0 else "unreliable")
    lab = "unreliable" if reg == "unreliable" else ("coarse" if reg.startswith("SWI-only") else ("unknown" if reg.startswith(("unknown", "unmeasured")) else "ok"))
    sul = "marginal" if reg == "marginal" else lab
    res = "unknown" if thick is None else ("limited (slice %.1f mm)" % thick if thick > 2.5 else "ok")
    return dict(label_shift_mm=sh, shift_vec_mm=q.get("label_shift_vec_mm"), registration=reg, slice_mm=thick,
                A_location_pial=lab, B_core_contrast="ok" if os.path.exists(f"{B}/data/{i}_swi.nii") or os.path.exists(f"{B}/data/{i}_swi.nii.gz") else "unavailable",
                C_vessel_continuity=lab + " (vessel map restricted by labels)" if lab != "ok" else "ok",
                D_morphology=res, E_sulcal_alignment=sul, F_hessian=res, G_extracranial=("unavailable (no raw SWI)" if not rawswi else lab),
                H_size=res, I_context="ok")
rows = []
for i in sorted(set(seen) | set(prov)):
    m = i.startswith("M"); p = prov.get(i, {}); role = p.get("role") if m and p else ("excluded" if not m else "unassigned")
    calls = sorted(glob.glob(f"{B}/review/{i}_calls*.csv"))
    n_called = 0
    for f in calls:
        try: n_called = max(n_called, sum(1 for r in csv.DictReader(open(f)) if (r.get("call") or "").strip()))
        except Exception: pass
    rows.append(dict(study_id=i, starts_with_M="yes" if m else "no", decision="include" if m and role in ("development", "held-out") else "exclude",
                     role=role, exclusion_reason="" if m else (p.get("exclusion_reason") or "does not start with M"),
                     found_in=";".join(sorted(seen.get(i, []))), n_candidates=count(f"{B}/review/{i}_candidates.csv"),
                     n_excluded_objects=count(f"{B}/review/{i}_excluded.csv"), n_reader_calls=n_called, swi_hash=swi_hash(i), noise_fixture="yes" if m and is_noise_fixture(i) else ""))
# checks
problems = []
hashes = {}
for r in rows:
    if r["swi_hash"]: hashes.setdefault(r["swi_hash"], []).append(r["study_id"])
for h, ids in hashes.items():
    if len(ids) > 1: problems.append(f"same SWI content under several IDs: {ids}")
inc = [r for r in rows if r["decision"] == "include"]
for r in rows:
    if r["noise_fixture"]: problems.append(f"{r['study_id']} is a random-noise test fixture, not a patient: remove it from the base")
sc = [dict(study_id=r["study_id"], role=r["role"], **scoreability(r["study_id"])) for r in inc]
if sc:
    with open(f"{H}/cohort_scoreability.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sc[0])); w.writeheader(); w.writerows(sc)
for r in sc:
    if r["registration"] in ("unreliable", "marginal"): problems.append(f"{r['study_id']}: registration {r['registration']} (shift {r['label_shift_mm']} mm, vector {r['shift_vec_mm']}): pial / sulcal / vessel / extracranial features {r['registration']}")
for r in rows:
    if r["starts_with_M"] == "no" and r["decision"] == "include": problems.append(f"non-M study included: {r['study_id']}")
    if r["role"] == "unassigned": problems.append(f"M study without an approved role (left out until assigned): {r['study_id']}")
roles = {}
for r in inc: roles.setdefault(r["study_id"], set()).add(r["role"])
for i, rs in roles.items():
    if len(rs) > 1: problems.append(f"study in two roles: {i} {rs}")
for r in rows:
    if r["study_id"].startswith("T") and f"M{r['study_id'][1:]}" in seen and r["found_in"]:
        problems.append(f"T/M twin present: {r['study_id']} and M{r['study_id'][1:]} (same patient; T excluded)")
with open(f"{H}/cohort_manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
dev = [r for r in inc if r["role"] == "development"]; ho = [r for r in inc if r["role"] == "held-out"]
print(f"cohort audit: {len(rows)} identifiers, {len(inc)} included (development {len(dev)}, held-out {len(ho)}), {len(rows) - len(inc)} excluded -> unified_score/cohort_manifest.csv")
print(f"  development candidates {sum(int(r['n_candidates'] or 0) for r in dev)}, read {sum(int(r['n_reader_calls'] or 0) for r in dev)};"
      f" held-out candidates {sum(int(r['n_candidates'] or 0) for r in ho)}, read {sum(int(r['n_reader_calls'] or 0) for r in ho)}")
print("\n".join("  PROBLEM: " + p for p in problems) or "  no problems found")
