"""qc_gui.py - back end of the restored "Anatomy QC" screen (FreeSurfer / SynthSeg QC), v5.15. Research software.

What it reports (read only, except the QC snapshot image the app already makes after processing):
  - FreeSurfer installation: home folder, version (build-stamp.txt), the tools the pipeline uses, licence file present / readable
    (its CONTENTS are never read into a response, logged or transmitted)
  - per study: which anatomy route produced the labels, the expected FreeSurfer / SynthSeg / registration outputs (present, missing,
    older than the SWI), the Process Manager's stage verdicts (processing_manager.Study.audit), the detector's QC record
    (review/ID_qc.json: status, label shift, edge agreement, registration cost, obliquity) and the QC snapshot image
  - a verdict that is "ok" ONLY when the required files exist and the recorded QC status is ok; missing files are never reported as
    passed. Freeview can be opened locally with the labels on the SWI, or on the FreeSurfer recon (orig + aparc+aseg + surfaces)."""
import glob, json, os, shutil, subprocess, time

FS_FILES = ["mri/orig.mgz", "mri/brain.mgz", "mri/aseg.mgz", "mri/aparc+aseg.mgz", "mri/aparc.a2009s+aseg.mgz", "surf/lh.white", "surf/rh.white",
            "surf/lh.pial", "surf/rh.pial", "label/lh.aparc.a2009s.annot", "label/rh.aparc.a2009s.annot", "scripts/recon-all.done"]
FS_REQUIRED = ["mri/orig.mgz", "mri/brain.mgz", "mri/aparc.a2009s+aseg.mgz"]            # = processing_manager anatomy "need"
TOOLS = ["mri_synthseg", "mri_synthstrip", "recon-all", "mri_convert", "mri_vol2vol", "bbregister", "freeview"]


def _jl(p):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return None


def fs_home(SET):
    return (SET.get("freesurfer_home") or os.environ.get("FREESURFER_HOME") or "").rstrip("/")


def install(SET, find_license=None):
    h = fs_home(SET); out = dict(home=h, home_exists=bool(h) and os.path.isdir(h), version="", tools={}, license={})
    if out["home_exists"]:
        bs = os.path.join(h, "build-stamp.txt")
        if os.path.exists(bs):
            with open(bs, errors="replace") as f: out["version"] = f.read().strip()[:160]
        for t in TOOLS:
            p = os.path.join(h, "bin", t); out["tools"][t] = p if os.path.exists(p) else (shutil.which(t) or "")
    else: out["tools"] = {t: shutil.which(t) or "" for t in TOOLS}
    lic = (find_license(h) if find_license else "") or SET.get("fs_license") or (os.path.join(h, "license.txt") if h else "") or os.environ.get("FS_LICENSE", "")
    if lic:
        ok = os.path.isfile(lic) and os.access(lic, os.R_OK)
        out["license"] = dict(path=lic, exists=os.path.isfile(lic), readable=ok, size_bytes=os.path.getsize(lic) if os.path.isfile(lic) else 0)
    else: out["license"] = dict(path="", exists=False, readable=False, size_bytes=0)
    out["ready"] = out["home_exists"] and bool(out["version"]) and out["license"].get("readable") and bool(out["tools"].get("mri_synthseg"))
    return out


def _st(p, swi_t):
    if not os.path.exists(p): return "missing"
    return "older than the SWI" if swi_t and os.path.getmtime(p) < swi_t else "present"


def study(B, AD, code, PM=None, subjects_dir=None):
    sd = subjects_dir or os.environ.get("CSS_SUBJECTS_DIR") or os.path.join(B, "subjects")
    swi = next((q for q in (f"{B}/data/{code}_swi.nii", f"{B}/data/{code}_swi.nii.gz") if os.path.exists(q)), None)
    swi_t = os.path.getmtime(swi) if swi else None
    fsd = os.path.join(sd, code); has_fs = os.path.isdir(fsd)
    work = {k: _st(f"{B}/work/{code}_{k}", swi_t) for k in ("seg_swispace.nii.gz", "t1seg_swispace.nii.gz", "a2009s_swispace.nii.gz", "swi2t1.lta", "reg.json",
                                                             "pial_sd.nii.gz")}
    work["synthseg (SWI)"] = "present" if glob.glob(f"{B}/synthseg/{code}_seg.nii*") else "missing"
    fs = {}
    if has_fs:
        for f in FS_FILES: fs[f] = "present" if os.path.exists(os.path.join(fsd, f)) else "missing"
        if os.path.exists(os.path.join(fsd, "scripts", "recon-all.error")): fs["scripts/recon-all.error"] = "PRESENT (FreeSurfer reported an error)"
        if glob.glob(os.path.join(fsd, "scripts", "IsRunning*")): fs["scripts/IsRunning"] = "PRESENT (recon-all marked as running)"
    route = ("FreeSurfer recon-all" if has_fs else "T1 SynthSeg" if work["t1seg_swispace.nii.gz"] != "missing" else
             "SWI SynthSeg (no T1)" if work["synthseg (SWI)"] == "present" or work["seg_swispace.nii.gz"] != "missing" else "none")
    qc = _jl(f"{B}/review/{code}_qc.json") or {}
    metrics = {k: qc.get(k) for k in ("status", "anatomy", "label_shift_mm", "edge_agreement_mm", "edge_bias_mm", "obliquity_deg", "orientation", "voxel_mm",
                                      "label_slice_coverage", "label_voxel_frac", "registration_ok") if qc.get(k) is not None}
    if qc.get("registration"): metrics["registration"] = {k: qc["registration"].get(k) for k in ("method", "cost")}
    if qc.get("reasons"): metrics["reasons"] = qc["reasons"][:6]
    snap = os.path.join(AD, "qc", f"{code}.png"); seg = f"{B}/work/{code}_seg_swispace.nii.gz"
    snapshot = dict(exists=os.path.exists(snap), can_make=bool(swi) and os.path.exists(seg),
                    stale=os.path.exists(snap) and any(os.path.exists(x) and os.path.getmtime(x) > os.path.getmtime(snap) for x in (swi or "", seg)),
                    why_not="" if swi and os.path.exists(seg) else "needs data/ID_swi.nii and work/ID_seg_swispace.nii.gz")
    stages = {}
    if PM is not None:
        try:
            a = PM.Study(B, code, subjects_dir).audit()["stages"]
            stages = {k: dict(status=a[k]["status"], label=a[k]["label"], why=a[k]["why"]) for k in ("anatomy", "registration", "align") if k in a}
        except Exception as e: stages = dict(error=f"{type(e).__name__}: {e}"[-200:])
    missing = [f"subjects/{code}/{f}" for f in FS_REQUIRED if has_fs and fs.get(f) != "present"]
    if not os.path.exists(seg): missing.append(f"work/{code}_seg_swispace.nii.gz")
    if not swi: missing.append(f"data/{code}_swi.nii")
    if not qc: missing.append(f"review/{code}_qc.json")
    try:                                                   # 2026-11-25: moved to Pensieve after its review -> not "missing"
        import pensieve_move as _PMV
        away = _PMV.in_pensieve(B, code) and not swi
    except ImportError:
        away = False
    if away:
        work = {k: ("in Pensieve" if v == "missing" else v) for k, v in work.items()}
        fs = {k: ("in Pensieve" if v == "missing" else v) for k, v in fs.items()}
        missing = []
    if away: verdict, why = "in_pensieve", "moved to the Pensieve drive after its review - opening it (Freeview / QC image) brings it back"
    elif route == "none" and not swi: verdict, why = "not_processed", "no SWI and no anatomy outputs yet"
    elif missing: verdict, why = "missing_outputs", "missing: " + ", ".join(missing)
    elif any("PRESENT" in v for v in fs.values()): verdict, why = "failed", "FreeSurfer reported an error or is still marked as running"
    elif qc.get("status") == "insufficient_quality": verdict, why = "insufficient_quality", "; ".join(qc.get("reasons", [])[:3]) or "detector QC: insufficient quality"
    elif qc.get("status") == "low_confidence_review": verdict, why = "low_confidence", "; ".join(qc.get("reasons", [])[:3]) or "detector QC: low confidence"
    elif qc.get("status") == "ok": verdict, why = "ok", "required outputs present and the recorded QC status is ok" + ("" if snapshot["exists"] else " (no QC image yet)")
    else: verdict, why = "unknown", f"QC status not recorded ({qc.get('status')!r})"
    return dict(code=code, route=route, freesurfer_dir=os.path.relpath(fsd, B) if has_fs else "", freesurfer=fs, work=work, metrics=metrics, snapshot=snapshot,
                stages=stages, verdict=verdict, why=why, missing=missing,
                freesurfer_version=(open(os.path.join(fsd, "scripts", "build-stamp.txt"), errors="replace").read().strip()[:120]
                                    if has_fs and os.path.exists(os.path.join(fsd, "scripts", "build-stamp.txt")) else ""))


def make_snapshot(B, AD, code, qc_snapshot):
    s = study(B, AD, code)
    if not s["snapshot"]["can_make"]: return dict(ok=False, error=f"cannot make a QC image: {s['snapshot']['why_not']}")
    p = os.path.join(AD, "qc", f"{code}.png"); t0 = os.path.getmtime(p) if os.path.exists(p) else 0
    qc_snapshot(code)
    if not os.path.exists(p) or os.path.getmtime(p) <= t0: return dict(ok=False, error="the QC image was not made - see the study log (app_data/logs)")
    return dict(ok=True, path=os.path.relpath(p, B))


def freeview(B, code, SET, what="swi", subjects_dir=None, find_license=None):
    """open Freeview locally (a separate program; nothing is sent anywhere)"""
    inst = install(SET, find_license); fv = inst["tools"].get("freeview")
    if not fv: return dict(ok=False, error="Freeview not found (check the FreeSurfer folder in Settings)")
    sd = subjects_dir or os.path.join(B, "subjects")
    if what == "recon":
        d = os.path.join(sd, code); need = [os.path.join(d, "mri", "orig.mgz")]
        if not os.path.exists(need[0]): return dict(ok=False, error="no FreeSurfer recon for this study (subjects/ID/mri/orig.mgz missing)")
        args = [fv, "-v", need[0]] + ([f"{d}/mri/aparc+aseg.mgz:colormap=lut:opacity=0.3"] if os.path.exists(f"{d}/mri/aparc+aseg.mgz") else [])
        surf = [f"{d}/surf/{h}.{s}:edgecolor={c}" for h in ("lh", "rh") for s, c in (("white", "blue"), ("pial", "red")) if os.path.exists(f"{d}/surf/{h}.{s}")]
        if surf: args += ["-f"] + surf
    else:
        swi = next((q for q in (f"{B}/data/{code}_swi.nii", f"{B}/data/{code}_swi.nii.gz") if os.path.exists(q)), None)
        seg = f"{B}/work/{code}_seg_swispace.nii.gz"
        if not swi or not os.path.exists(seg): return dict(ok=False, error="needs data/ID_swi.nii and work/ID_seg_swispace.nii.gz")
        args = [fv, "-v", swi, f"{seg}:colormap=lut:opacity=0.35"]
        cand = f"{B}/review/{code}_candidates.nii.gz"
        if os.path.exists(cand): args.append(f"{cand}:colormap=lut:opacity=0.8")
    env = dict(os.environ, FREESURFER_HOME=inst["home"] or os.environ.get("FREESURFER_HOME", ""), SUBJECTS_DIR=sd)
    if os.environ.get("CSS_FREEVIEW_DRYRUN") == "1": return dict(ok=True, dry_run=True, args=args)
    subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return dict(ok=True, started=time.time())


def state(B, AD, PAT, SET, PM=None, on_disk=(), find_license=None):
    codes = sorted({p["code"] for p in PAT} | set(on_disk))
    return dict(install=install(SET, find_license), studies=[study(B, AD, c, PM) for c in codes])
