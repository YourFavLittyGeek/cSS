"""albus_redetect.py - ALBUS re-detection of expert-marked missed cSS (2026-11-25, user decision; step 1 of the missed-cSS plan).

For every missed-cSS mark of a study:
  1. ALBUS's object for the mark: the detector's own excluded / gate-dropped object under the mark when there is one (ALBUS found the
     lesion and removed it), else the dark voxels inside the drawing (detector dark map first) - uengine.imaging.patches;
  2. those objects are measured by the production detector (scripts/albus_measure.py: detect_css.py verified against its pinned
     sha256, objects forced, rules recorded but not applied, gates soft) on a DISPOSABLE COPY of the study (APFS clones) - the project
     is never written by the detector; then the uScore x1 / x2 / x5 of the same objects (values only);
  3. result per mark: measured (all detector columns, the rule that would have excluded it, the gate it failed), the object's voxels
     (native + canonical for the viewer outline), or failed with the reason.
The reviewer confirms each ALBUS outline (correct / wrong) in the viewer; only CONFIRMED objects teach NOX and PERCIVAL.
Results: <project>/percival/albus_redetect/<study>.json (+ .npz with the object voxels). Research software."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
import numpy as np
import nibabel as nib
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
VERSION = "albus-redetect/1.0"
MIN_VOX = 5                                         # the detector drops objects of < 5 voxels (gate G0) even with soft gates


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def marks_key(marks, scripts):
    """content key: the marks (id, shape, plane, points) + the detector and wrapper versions"""
    m = sorted((str(k), str(v.get("shape")), str(v.get("plane")), json.dumps(v.get("strokes"))) for k, v in marks.items())
    return hashlib.sha256(json.dumps([VERSION, m, _sha_file(os.path.join(scripts, "detect_css.py")),
                                      _sha_file(os.path.join(scripts, "albus_measure.py"))]).encode()).hexdigest()[:20]


def _overlap_object(base, sid, rel, region):
    """the detector object of a label map (review/ID_excluded.nii.gz, work/ID_dropped.nii.gz) that overlaps the drawn region most"""
    p = os.path.join(base, rel.format(sid=sid))
    if not os.path.exists(p): return None
    L = np.asarray(nib.load(p).dataobj)
    if L.shape != region.shape: return None
    ids, n = np.unique(L[region & (L > 0)], return_counts=True)
    if not len(ids): return None
    return L == ids[int(np.argmax(n))]


def build_objects(base, sid, marks):
    """-> (label map int16 on the SWI grid, {mark key: dict(obj_id, source, n_vox)}, {mark key: reason skipped}, affine)"""
    sys.path.insert(0, os.path.join(ROOT, "unified_engine"))
    from uengine.imaging import patches as PT
    swi = nib.load(os.path.join(base, "data", f"{sid}_swi.nii")); A = np.asarray(swi.dataobj, np.float32)
    from scipy import ndimage as ndi
    brain = ndi.binary_fill_holes(A > 0); can = nib.as_closest_canonical(swi); c2n = np.linalg.inv(swi.affine) @ can.affine
    dp = os.path.join(base, "work", f"{sid}_dark.nii.gz")
    dark = (np.asarray(nib.load(dp).dataobj) > 0) if os.path.exists(dp) and nib.load(dp).shape[:3] == A.shape[:3] else None
    lab = np.zeros(A.shape[:3], np.int16); info, skipped = {}, {}
    for key, mk in marks.items():
        try:
            Rc = PT._mark_region(mk, can.shape); ijk = np.argwhere(Rc)
            nat = np.round((c2n[:3, :3] @ ijk.T).T + c2n[:3, 3]).astype(int)
            nat = nat[np.all((nat >= 0) & (nat < np.array(A.shape[:3])), axis=1)]
            Rn = np.zeros(A.shape[:3], bool); Rn[tuple(nat.T)] = True
            obj, src = None, ""
            for rel, what in (("review/{sid}_excluded.nii.gz", "ALBUS's own object, excluded by a rule"),
                              ("work/{sid}_dropped.nii.gz", "ALBUS's own object, below a generation gate")):
                o = _overlap_object(base, sid, rel, Rn)
                if o is not None and o.sum() >= MIN_VOX: obj, src = o, what; break
            if obj is None:
                obj, how = PT.mark_object(A, brain, Rn, dark=dark, min_vox=MIN_VOX); src = "new object: " + how
            obj = obj & (lab == 0)                                        # two marks on one lesion: the first keeps the voxels
            if obj.sum() < MIN_VOX: skipped[key] = "the same lesion as another mark"; continue
            oid = len(info) + 1; lab[obj] = oid; info[key] = dict(obj_id=oid, source=src, n_vox=int(obj.sum()))
        except (ValueError, IndexError) as e: skipped[key] = str(e)[:120]
    return lab, info, skipped, swi.affine


def _clone(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if sys.platform == "darwin" and subprocess.run(["cp", "-c", src, dst], capture_output=True).returncode == 0: return
    shutil.copy2(src, dst)


def disposable_copy(base, sid, dest):
    """the detector's inputs of one study, cloned (APFS copy-on-write) into dest - the detector writes only there"""
    import glob
    n = 0
    for pat in (f"data/{sid}_*", f"work/{sid}_*", f"review/{sid}_qc.json", f"review/{sid}_manifest.json"):
        for p in glob.glob(os.path.join(base, pat)):
            if os.path.isfile(p): _clone(p, os.path.join(dest, os.path.relpath(p, base))); n += 1
    os.makedirs(os.path.join(dest, "review"), exist_ok=True)
    return n


def run(base, sid, marks, out_dir, scripts=None, python=None, timeout=3600, log=lambda *a: None):
    """re-detect the marks of one study -> result dict (also written to out_dir/<sid>.json + .npz)"""
    scripts = scripts or os.path.join(ROOT, "scripts"); python = python or sys.executable
    key = marks_key(marks, scripts)
    res = dict(version=VERSION, study=sid, key=key, at=time.strftime("%Y-%m-%d %H:%M:%S"), marks={}, detector_sha256=_sha_file(os.path.join(scripts, "detect_css.py")))
    lab, info, skipped, aff = build_objects(base, sid, marks)
    for k, why in skipped.items(): res["marks"][k] = dict(status="failed", reason=why)
    vox = {}
    if info:
        tmp = tempfile.mkdtemp(prefix=f"albus_{sid}_", dir=out_dir)
        try:
            disposable_copy(base, sid, tmp)
            fp = os.path.join(tmp, "forced.nii.gz"); nib.save(nib.Nifti1Image(lab, aff), fp)
            env = dict(os.environ, CSS_BASE=tmp, PYTHONWARNINGS="ignore"); env.pop("CSS_FORCE_OBJECTS", None)
            log(f"{sid}: ALBUS re-detection of {len(info)} mark(s)")
            r = subprocess.run(["nice", "-n", "10", python, os.path.join(scripts, "albus_measure.py"), sid, fp], env=env, capture_output=True,
                               text=True, timeout=timeout)
            cp = os.path.join(tmp, "review", f"{sid}_candidates.csv")
            if r.returncode or not os.path.exists(cp):
                for k in info: res["marks"][k] = dict(status="failed", reason=("detector stopped: " + (r.stderr or r.stdout)[-300:]).strip())
            else:
                df = pd.read_csv(cp)
                pred = {}
                try:                                                     # uScore x1 / x2 / x5 of the same objects (values only)
                    sys.path.insert(0, os.path.join(ROOT, "unified_score"))
                    from uscore import pipeline as PL, common as CM
                    class _C:
                        synthetic = False
                        def role(self, s): raise CM.CohortError("application")
                    PL.extract_study(tmp, sid, _C(), os.path.join(tmp, "uscore"), do_perturb=False, application=True)
                    U = json.load(open(os.path.join(tmp, "uscore", "features", f"{sid}.json")))
                    for rec in U.get("records", []):
                        F = rec.get("F", {})
                        pred[int(rec["cand_id"])] = {k: (float(F[k]["value"]) if F.get(k, {}).get("status") == "reliable" and F[k].get("value") is not None else None)
                                                     for k in ("x1_vessel_continuity_mm", "x2_core_contrast_nu", "x5_extracranial_mm")}
                except Exception as e: res["uscore_note"] = f"uScore x1 / x2 / x5 not extracted ({type(e).__name__})"
                by_obj = {int(row["forced_obj"]): row for _, row in df.iterrows() if "forced_obj" in df.columns}
                can = nib.as_closest_canonical(nib.load(os.path.join(base, "data", f"{sid}_swi.nii"))); n2c = np.linalg.inv(can.affine) @ aff
                for k, inf in info.items():
                    row = by_obj.get(inf["obj_id"])
                    if row is None: res["marks"][k] = dict(status="failed", reason="dropped by the detector (fewer than 5 voxels after its checks)", **inf); continue
                    meas = {c: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for c, v in row.items()}
                    v_ = np.argwhere(lab == inf["obj_id"]); vox[k] = v_.astype(np.int16)
                    c_ = np.round((n2c[:3, :3] @ v_.T).T + n2c[:3, 3]).astype(int)
                    res["marks"][k] = dict(status="measured", **inf, measurements=meas, uscore=pred.get(int(row["cand_id"]), {}),
                                           would_exclude=str(meas.get("forced_would_exclude") or ""), gate=str(meas.get("soft_gate_fail") or ""),
                                           object_sha=hashlib.sha256(v_.tobytes()).hexdigest()[:16],
                                           outline=c_[:: max(1, len(c_) // 4000)].tolist())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    zp = os.path.join(out_dir, f"{sid}.npz")
    with open(zp + ".tmp", "wb") as f: np.savez_compressed(f, **vox)
    os.replace(zp + ".tmp", zp)
    jp = os.path.join(out_dir, f"{sid}.json")
    with open(jp + ".tmp", "w") as f: json.dump(res, f, default=str)
    os.replace(jp + ".tmp", jp)
    return res


def fate_report(base, studies, results):
    """step 4: which detector rule or gate loses the expert-marked cSS. studies: [sid]; results: {sid: run() result or None}"""
    rows = []
    for sid in studies:
        mp = os.path.join(base, "review", f"{sid}_missed.csv")
        if not os.path.exists(mp): continue
        try: d = pd.read_csv(mp, dtype=str).fillna("")
        except Exception: continue
        R = (results.get(sid) or {}).get("marks") or {}
        for _, m in d.iterrows():
            k = f"missed_{m['missed_id']}"; r = R.get(k) or {}; fate = str(m.get("detector_fate", ""))
            if fate.startswith("overlaps shown candidate"): cat, what = "shown", "already a candidate"
            elif fate.startswith("excluded object"): cat, what = "excluded", (fate.split(":", 1)[1].strip() or "rule") if ":" in fate else "rule"
            elif fate.startswith("below a generation gate"): cat, what = "gate", r.get("gate") or "generation gate"
            else: cat, what = "not_generated", fate.replace("not generated by the detector", "").strip(" ()") or "not generated"
            rows.append(dict(study=sid, missed_id=m["missed_id"], reviewer=m.get("reviewer", ""), category=cat, cause=what,
                             would_exclude=(r.get("would_exclude") or "").split(":")[0], gate=r.get("gate", ""), status=r.get("status", "not re-detected yet")))
    by = {}
    for r in rows:
        if r["category"] == "shown": continue
        cause = (r["would_exclude"] or r["gate"] or r["cause"]) if r["category"] != "not_generated" else r["cause"]
        k = (r["category"], cause.split(" (")[0][:80]); by[k] = by.get(k, 0) + 1
    table = [dict(category=c, cause=w, n=n) for (c, w), n in sorted(by.items(), key=lambda t: -t[1])]
    return dict(marks=rows, table=table, n_marks=len(rows), n_missed=sum(1 for r in rows if r["category"] != "shown"),
                note="where ALBUS loses the lesions experts marked: a rule (excluded), a generation gate, or never generated. Evidence for a new "
                     "detector version, which must not lose any cSS the current version finds (ALBUS non-inferiority gate).")
