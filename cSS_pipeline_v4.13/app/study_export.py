"""study_export.py - v5.18 export of studies WITH their files to a folder the user chooses. Local only; nothing is uploaded.

    <destination>/Percival_export_<YYYYmmdd_HHMM>/
        README.txt · export_manifest.json (every file + sha256) · results.xlsx (the exported studies, active-mode identifiers)
        <study folder>/                    Standard: <MRN>/<accession number>   Incognito: <de-identified study code> (no grouping)
            results/    candidate tables, reviewer calls (every reviewer), scores, QC, lineage, Unified / Shadow / Image ML outputs, QC image
            processed/  pipeline inputs (NIfTI) and outputs: registrations, segmentations, masks, candidate maps (+ run archive)
            freesurfer/ the study's FreeSurfer / SynthSeg subject folder (large; optional)
            mri/        the original MRI series (the study library copy, else the project's neutral import copy, else raw/);
                        Incognito exports NIfTI only - DICOM files are left out because their headers hold patient identifiers
            logs/       processing logs (optional; source paths hidden in Incognito)

What is included is chosen per export (results always). Rules: verified local destination only (no cloud-synced folder, not Desktop /
Documents, not a protected project); Standard mode needs the vault unlocked and an accession number for every exported study;
enough free space is checked first; files are copied, then verified (sha256); an existing export folder is never overwritten."""
import datetime, glob, hashlib, json, os, re, secrets, shutil, threading, time

PARTS = ("results", "processed", "freesurfer", "mri", "logs")
DEFAULT = dict(results=True, processed=True, freesurfer=False, mri=False, logs=False)
LOCK = threading.Lock(); JOBS = {}
SEG = re.compile(r"[^A-Za-z0-9._-]+")


def _seg(x): s = SEG.sub("_", str(x or "").strip()).strip("._"); return "" if s in ("", ".", "..") else s[:64]


def _tree(d):
    out = []
    for root, dirs, files in os.walk(d, followlinks=False):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            if not f.startswith("."): out.append(os.path.join(root, f))
    return out


def files_of(B, AD, code, parts, library=None, mode="standard"):
    """-> [(source, relative path inside the study folder)] for one study"""
    out = []
    def add(paths, sub, keep_rel_to=None):
        for p in paths:
            if os.path.isfile(p) and not os.path.islink(p):
                out.append((p, os.path.join(sub, os.path.relpath(p, keep_rel_to) if keep_rel_to else os.path.basename(p))))
            elif os.path.islink(p) and os.path.isfile(os.path.realpath(p)):
                out.append((os.path.realpath(p), os.path.join(sub, os.path.relpath(p, keep_rel_to) if keep_rel_to else os.path.basename(p))))
    if parts.get("results", True):
        add([f for f in glob.glob(f"{B}/review/{code}_*") if not f.endswith(("_manifest.json",)) and not f.endswith((".nii", ".nii.gz"))], "results")
        add(glob.glob(f"{B}/review/call_history/{code}_*"), os.path.join("results", "call_history"))
        add(glob.glob(f"{B}/uscore/reports/{code}.json"), os.path.join("results", "unified_score"))
        add(glob.glob(f"{B}/unified_engine/shadow/{code}.json"), os.path.join("results", "shadow_ml"))
        add(glob.glob(f"{B}/unified_engine/image_ml/{code}*.json"), os.path.join("results", "image_ml"))
        add(glob.glob(f"{AD}/qc/{code}.png"), "results")
        add(glob.glob(f"{B}/results/{code}_*") + glob.glob(f"{B}/results/*/{code}_*"), "results")
    if parts.get("processed"):
        add(glob.glob(f"{B}/review/{code}_*.nii*") + glob.glob(f"{B}/review/{code}_manifest.json"), "processed")
        add(glob.glob(f"{B}/data/{code}_*") + glob.glob(f"{B}/work/{code}_*"), "processed")
        for d in (f"{B}/data/{code}", f"{B}/work/{code}", f"{B}/runs/{code}"):
            if os.path.isdir(d): add(_tree(d), os.path.join("processed", os.path.basename(os.path.dirname(d)) + "_" + code), d)
    if parts.get("freesurfer"):
        for d in (f"{B}/subjects/{code}", f"{B}/synthseg/{code}"):
            if os.path.isdir(d): add(_tree(d), os.path.join("freesurfer", os.path.basename(os.path.dirname(d))), os.path.dirname(d))
        add(glob.glob(f"{B}/synthseg/{code}_*"), os.path.join("freesurfer", "synthseg"))
    if parts.get("mri"):
        src = ""
        if library and library.get("root") and library.get("rel") and os.path.isdir(os.path.join(library["root"], library["rel"])): src = os.path.join(library["root"], library["rel"])
        elif os.path.isdir(f"{AD}/import_src/{code}"): src = f"{AD}/import_src/{code}"
        elif os.path.isdir(f"{B}/raw/{code}"): src = f"{B}/raw/{code}"
        if src:
            fs = _tree(src)
            if mode != "standard": fs = [f for f in fs if f.endswith((".nii", ".nii.gz", ".json")) and not _is_dicom(f)]   # DICOM headers hold identifiers
            add(fs, "mri", src)
    if parts.get("logs"):
        add(glob.glob(f"{AD}/logs/{code}.log") + glob.glob(f"{B}/logs/{code}_*"), "logs")
    seen = set(); uniq = []
    for s, r in out:
        if r not in seen: seen.add(r); uniq.append((s, r))
    return uniq


def _is_dicom(p):
    if p.lower().endswith(".dcm"): return True
    try:
        with open(p, "rb") as f: return f.read(132)[128:132] == b"DICM"
    except OSError: return False


def place(mode, ident):
    """study folder inside the export: Standard MRN/accession, Incognito the study code only. -> (rel, reason)"""
    if mode == "standard":
        a, m = _seg(ident.get("accession")), _seg(ident.get("mrn"))
        if not a: return "", "accession number missing"
        return os.path.join(m or "no_MRN", a), ""
    return _seg(ident.get("deid_code")) or _seg(ident.get("file_key")), ""


def plan(B, AD, codes, parts, mode, ident_of, library_of):
    """-> dict(studies=[dict(code, rel, n, bytes, why)], n_files, bytes, problems)"""
    st = []; probs = []; tot = 0; nf = 0
    for c in codes:
        i = ident_of(c); rel, why = place(mode, i)
        if mode == "standard" and i.get("locked"): rel, why = "", "identity vault locked"
        fs = files_of(B, AD, c, parts, library_of(c), mode) if rel else []
        b = sum(os.path.getsize(s) for s, _ in fs)
        st.append(dict(code=c, study_id=i.get("study_id") or c, rel=rel, n=len(fs), bytes=b, why=why))
        if why: probs.append(f"{i.get('study_id') or i.get('deid_code') or c}: {why}")
        tot += b; nf += len(fs)
    rels = [s["rel"] for s in st if s["rel"]]
    for r in {r for r in rels if rels.count(r) > 1}: probs.append(f"two studies would share the export folder {r} - check the identifiers")
    return dict(studies=st, n_files=nf, bytes=tot, problems=probs)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def start(B, AD, dest, codes, parts, mode, ident_of, library_of, results_frame=None, redact=None, version=""):
    """background export. -> dict(ok, job, folder) or dict(ok=False, error)"""
    P = plan(B, AD, codes, parts, mode, ident_of, library_of)
    if P["problems"]: return dict(ok=False, error="; ".join(P["problems"][:6]), plan=P)
    if not codes: return dict(ok=False, error="no study selected")
    free = shutil.disk_usage(dest).free
    if free < P["bytes"] * 1.05 + 50e6: return dict(ok=False, error=f"not enough free space at the destination: {P['bytes'] / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free")
    out = os.path.join(dest, f"Percival_export_{datetime.datetime.now():%Y%m%d_%H%M%S}")
    if os.path.exists(out): return dict(ok=False, error="an export folder with this name already exists - try again in a second")
    jid = secrets.token_urlsafe(8)
    with LOCK: JOBS[jid] = dict(state="running", done_files=0, total_files=P["n_files"], bytes=P["bytes"], studies=len(codes), started=time.time(), folder=out, error="")
    def run():
        tmp = out + ".partial"; rec = []
        try:
            os.makedirs(tmp)
            for s in P["studies"]:
                for src, r in files_of(B, AD, s["code"], parts, library_of(s["code"]), mode):
                    t = os.path.join(tmp, s["rel"], r); os.makedirs(os.path.dirname(t), exist_ok=True)
                    if r.startswith("logs" + os.sep) and redact:
                        with open(src, errors="replace") as f: txt = redact(f.read())
                        with open(t, "w") as f: f.write(txt)
                    else:
                        shutil.copy2(src, t)
                        if sha256(src) != sha256(t): raise IOError(f"verification failed: {os.path.join(s['rel'], r)}")
                    rec.append(dict(file=os.path.join(s["rel"], r), sha256=sha256(t), bytes=os.path.getsize(t)))
                    with LOCK: JOBS[jid]["done_files"] += 1
            if results_frame is not None:
                try:
                    import pandas as pd
                    with pd.ExcelWriter(os.path.join(tmp, "results.xlsx")) as w: results_frame(codes).to_excel(w, index=False, sheet_name="results")
                except Exception as e: rec.append(dict(file="results.xlsx", error=f"{type(e).__name__}"))
            json.dump(dict(app="Percival", version=version, created=datetime.datetime.now().isoformat(timespec="seconds"), mode=mode, parts=parts,
                           studies=[dict(folder=s["rel"], files=s["n"]) for s in P["studies"]], files=rec), open(os.path.join(tmp, "export_manifest.json"), "w"), indent=1)
            with open(os.path.join(tmp, "README.txt"), "w") as f:
                f.write(f"Percival export ({'Standard: folders named MRN / accession number' if mode == 'standard' else 'Incognito: one folder per de-identified study code'})\n"
                        f"made {datetime.datetime.now():%Y-%m-%d %H:%M} · {len(codes)} studies · {len(rec)} files · pipeline {version}\n"
                        "Contents per study: results/ (always), processed/, freesurfer/, mri/, logs/ (as chosen). export_manifest.json lists every file with its sha256.\n"
                        "Research software output - AI scores are rule-based / experimental and not validated. This folder holds clinical-derived data"
                        + (" and patient identifiers in its folder names" if mode == "standard" else "") + ": keep it on approved local storage; never upload it.\n")
            os.rename(tmp, out)
            with LOCK: JOBS[jid].update(state="finished", finished=time.time())
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            with LOCK: JOBS[jid].update(state="failed", error=f"{type(e).__name__}: {str(e)[:200]}")
    threading.Thread(target=run, daemon=True).start()
    return dict(ok=True, job=jid, folder=out, plan=P)


def job(jid):
    with LOCK:
        j = JOBS.get(jid); return dict(j) if j else None
