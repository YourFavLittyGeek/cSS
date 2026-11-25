"""Temporary MRI copies on the Mac (v5.25 storage policy).

At import the app copies ONLY the chosen series (SWI / T1 / FLAIR, + phase) of each examination into app_data/import_src/<key>/ under
neutral names. The first pipeline step converts them into raw/<key>/<MOD>/*.nii.gz (dcm2niix); while doing so cohort.py makes a second,
decoded DICOM copy in raw/<key>/<MOD>/_dicom. After that, every pipeline step and every re-run reads only the NIfTI files in raw/
(cohort.py import skips a modality whose raw/ folder already has NIfTI), so both DICOM copies are dead weight - typically 100-800 MB per study.

Policy (Settings > Storage, SET["source_cleanup"]):
  after_processing (default) - delete the temporary DICOM copies as soon as the study is VERIFIABLY complete
  keep_days                  - keep them SET["source_keep_days"] days after completion, then delete
  keep                       - never delete automatically
"Verifiably complete" (verified()): status done AND the run finished after it started AND the candidate table and the run manifest exist and
were written by this run AND raw/<key>/SWI holds a converted NIfTI. A failed / stopped / running / waiting study is never cleaned
automatically (its copy is what Retry needs). The original files (external drive) are never touched. Results, review files, the NIfTI
conversions in raw/ and the processing outputs stay - they are what review, re-runs and export use."""
import glob, json
import os
import shutil
import time

POLICIES = ("after_processing", "keep_days", "keep")


def temp_paths(B, AD, code):
    """the temporary DICOM copies of one study (app-made only)"""
    out = []
    d = os.path.join(AD, "import_src", code)
    if os.path.isdir(d): out.append(d)
    out += [x for x in glob.glob(os.path.join(B, "raw", code, "*", "_dicom")) if os.path.isdir(x)]
    s = os.path.join(AD, "staging", code)
    if os.path.isdir(s) or os.path.islink(s): out.append(s)
    return out


def size_of(paths):
    n = 0
    for p in paths:
        if os.path.isfile(p) and not os.path.islink(p): n += os.path.getsize(p); continue
        for root, _, files in os.walk(p):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if not os.path.islink(fp): n += os.path.getsize(fp)
                except OSError: pass
    return n


def has_nifti(B, code, mod="SWI"):
    """converted NIfTI in raw/<code>/<mod>/ - on the Mac, or recorded in the Pensieve marker of a moved study (2026-11-25)"""
    d = os.path.join(B, "raw", code, mod)
    if glob.glob(os.path.join(d, "*.nii.gz")) + glob.glob(os.path.join(d, "*.nii")): return True
    try:
        with open(os.path.join(B, "review", f"{code}_pensieve.json")) as f:
            m = json.load(f)
        pre = f"raw/{code}/{mod}/"
        return m.get("state") in ("in_pensieve", "deleting") and any(x.get("rel", "").startswith(pre) and ".nii" in x["rel"] for x in m.get("files", []))
    except (OSError, ValueError):
        return False


def verified(B, p):
    """'' when the study is completely processed (safe to drop its DICOM copies), else the reason it is not"""
    c = p.get("code", "")
    if p.get("status") != "done": return f"status is {p.get('status') or 'unknown'}"
    st, fin = p.get("started") or 0, p.get("finished") or 0
    if not fin or (st and fin < st): return "no finished run recorded"
    cand, man = os.path.join(B, "review", f"{c}_candidates.csv"), os.path.join(B, "review", f"{c}_manifest.json")
    if not os.path.exists(cand): return "no candidate table"
    if not os.path.exists(man): return "no run manifest"
    if st and min(os.path.getmtime(cand), os.path.getmtime(man)) < st - 5: return "the result files are older than the last run"
    if not has_nifti(B, c, "SWI"): return "no converted SWI in raw/"
    return ""


def due(p, policy, keep_days, now=None):
    if policy == "keep": return False
    if policy == "keep_days": return (now or time.time()) - (p.get("finished") or 0) >= float(keep_days) * 86400
    return True


def clean(B, AD, p):
    """delete the temporary copies of one verified study -> bytes freed (0 when nothing to do or not verified)"""
    if verified(B, p): return 0
    paths = temp_paths(B, AD, p["code"])
    if not paths: return 0
    n = size_of(paths)
    for x in paths:
        if os.path.islink(x) or os.path.isfile(x): os.remove(x)
        else: shutil.rmtree(x, ignore_errors=True)
    p["source_cleaned"] = time.time(); p["source_freed_bytes"] = int(p.get("source_freed_bytes", 0)) + n
    return n


def sweep(B, AD, PAT, policy, keep_days, running=()):
    """every due, verified study (not running) -> (studies cleaned, bytes freed)"""
    k, freed = 0, 0
    if policy not in POLICIES or policy == "keep": return 0, 0
    for p in list(PAT):
        if p.get("code") in running or not temp_paths(B, AD, p.get("code", "")): continue
        if not due(p, policy, keep_days) or verified(B, p): continue
        n = clean(B, AD, p)
        if n or not temp_paths(B, AD, p["code"]): k += 1; freed += n
    return k, freed


def summary(B, AD, PAT, policy, keep_days):
    rows = []
    for p in PAT:
        c = p.get("code", ""); paths = temp_paths(B, AD, c)
        if not paths: continue
        why = verified(B, p)
        rows.append(dict(code=c, status=p.get("status"), bytes=size_of(paths), complete=not why, why_kept=why or ("kept by your setting" if not due(p, policy, keep_days) else "deleted at the next check"),
                         deletable_now=not why))
    return dict(policy=policy, keep_days=keep_days, studies=rows, total_bytes=sum(r["bytes"] for r in rows),
                deletable_bytes=sum(r["bytes"] for r in rows if r["deletable_now"]))
