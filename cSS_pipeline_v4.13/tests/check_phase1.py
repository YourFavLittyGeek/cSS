"""Phase 1 safety fixes - regression tests on phantoms ($CSS_BASE with PH3 prepared; no patient data). usage: check_phase1.py
1. Slice gate in mm. PH3 (1.2 mm slices): CSS_SLICE_GATE=legacy and the default give IDENTICAL lists (nothing changes on thin slices).
   PHK = PH3 with 3 slices averaged into one (3.6 mm slices): the default keeps every object of the legacy run and ADDS objects that span one slice,
   each marked single_slice = 1 with n_slices = 1; the legacy run logs those as G2_slices drops, the default run logs no G2 drop of >= 2.4 mm.
2. Registration gate. Labels moved 4 voxels (> 1.5 mm): detect exits 5, review/ID_qc.json has registration_ok false, the existing lists keep their bytes,
   the manifest gets a detect_refused entry, score_css.py exits 5. CSS_ALLOW_BAD_REG=1: detect runs (exit 0) and score_css runs.
3. Confidence cut. A model whose cut_method is not lopo_min is NOT applied with CSS_CONF=1 (message printed, nobody excluded for low confidence) unless
   CSS_CONF_ALLOW_OPTIMISTIC=1; the manifest records role (development / evaluation), cut and method. fit_confidence.py refuses a study listed in
   review/evaluation_studies.txt; eval_confidence.py refuses a study the model was fitted on, runs read-only on an evaluation study."""
import os, sys, json, glob, shutil, hashlib, subprocess, numpy as np, pandas as pd, nibabel as nib
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]; py = sys.executable
def fail(m): print("FAIL:", m); sys.exit(1)
def run(args, ok=(0,), **env):
    r = subprocess.run([py] + args, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, **env))
    if r.returncode not in ok: fail(f"{' '.join(os.path.basename(x) for x in args[:3])} exit {r.returncode} (expected {ok})\n{r.stdout[-600:]}\n{r.stderr[-600:]}")
    return r
md5 = lambda f: hashlib.md5(open(f, "rb").read()).hexdigest()
made = []
def copy_case(src, dst, f=None):
    """derived phantom dst from src; f(array, kind) transforms the volumes (kind: 'img' or 'lab')"""
    for rel, kind in ((f"data/{src}_swi.nii", "img"), (f"work/{src}_seg_swispace.nii.gz", "lab"), (f"work/{src}_t1seg_swispace.nii.gz", "lab"), (f"work/{src}_truth.nii.gz", "lab")):
        p = f"{B}/{rel}"
        if not os.path.exists(p): continue
        im = nib.load(p); a = np.asanyarray(im.dataobj); aff = im.affine.copy()
        if f is not None: a, aff = f(a, aff, kind)
        q = f"{B}/{rel.replace(src, dst)}"; nib.save(nib.Nifti1Image(a.astype(np.float32 if kind == "img" else np.int32), aff), q); made.append(q)
def cleanup(name):
    for d in ("data", "work", "review", "synthseg"):
        for f in glob.glob(f"{B}/{d}/{name}_*"): os.remove(f)
if not os.path.exists(f"{B}/work/PH3_t1seg_swispace.nii.gz"): shutil.copy(f"{B}/work/PH3_seg_swispace.nii.gz", f"{B}/work/PH3_t1seg_swispace.nii.gz"); made.append(f"{B}/work/PH3_t1seg_swispace.nii.gz")
try:
    # ---------- 1. slice gate
    copy_case("PH3", "PHT")
    run([f"{S}/detect_css.py", "PHT"], CSS_SLICE_GATE="legacy"); a = pd.read_csv(f"{B}/review/PHT_candidates.csv"); ha = md5(f"{B}/review/PHT_candidates.nii.gz")
    run([f"{S}/detect_css.py", "PHT"]); b = pd.read_csv(f"{B}/review/PHT_candidates.csv")
    cmpc = [c for c in a.columns if c not in ("single_slice",)]
    if len(a) != len(b) or ha != md5(f"{B}/review/PHT_candidates.nii.gz") or not all(a[c].astype(str).equals(b[c].astype(str)) for c in cmpc): fail("thin slices (1.2 mm): the mm gate must not change the list")
    if b.single_slice.sum() != 0: fail("thin slices: no object may be marked single_slice")
    def thick(arr, aff, kind):
        n = arr.shape[2] // 3; arr = arr[:, :, :n * 3]
        out = arr.reshape(arr.shape[0], arr.shape[1], n, 3).mean(3) if kind == "img" else arr[:, :, 1::3]
        A = aff.copy(); A[:3, 3] = aff[:3, 3] + aff[:3, 2]; A[:3, 2] = aff[:3, 2] * 3; return out, A
    copy_case("PH3", "PHK", thick)
    vz = float(nib.load(f"{B}/data/PHK_swi.nii").header.get_zooms()[2])
    run([f"{S}/detect_css.py", "PHK"], CSS_SLICE_GATE="legacy")
    L0 = np.asanyarray(nib.load(f"{B}/review/PHK_candidates.nii.gz").dataobj).astype(int); X0 = np.asanyarray(nib.load(f"{B}/review/PHK_excluded.nii.gz").dataobj).astype(int)
    c0 = pd.read_csv(f"{B}/review/PHK_candidates.csv"); d0 = pd.read_csv(f"{B}/work/PHK_dropped.csv"); n0 = len(c0) + len(pd.read_csv(f"{B}/review/PHK_excluded.csv"))
    run([f"{S}/detect_css.py", "PHK"])
    L1 = np.asanyarray(nib.load(f"{B}/review/PHK_candidates.nii.gz").dataobj).astype(int); X1 = np.asanyarray(nib.load(f"{B}/review/PHK_excluded.nii.gz").dataobj).astype(int)
    c1 = pd.read_csv(f"{B}/review/PHK_candidates.csv"); x1 = pd.read_csv(f"{B}/review/PHK_excluded.csv"); d1 = pd.read_csv(f"{B}/work/PHK_dropped.csv"); n1 = len(c1) + len(x1)
    if not (((L0 > 0) | (X0 > 0)) <= ((L1 > 0) | (X1 > 0))).all(): fail("thick slices: an object of the legacy run is missing with the mm gate")
    g0 = int((d0.gate_id == "G2_slices").sum()); g1 = d1[d1.gate_id == "G2_slices"]
    if n1 - n0 != g0 - len(g1) or n1 <= n0: fail(f"thick slices: objects {n0} -> {n1}, G2 drops {g0} -> {len(g1)} (the difference must be the single-slice objects)")
    allo = pd.concat([c1, x1], ignore_index=True); ss = allo[allo.single_slice == 1]
    if len(ss) != n1 - n0 or not (ss.n_slices == 1).all() or (allo[allo.single_slice == 0].n_slices < 2).any(): fail("single_slice must mark exactly the one-slice objects")
    if len(g1) and (g1.measured.astype(float) * vz >= 2.4).any(): fail("the mm gate dropped an object spanning >= 2.4 mm")
    print(f"slice gate: 1.2 mm slices unchanged ({len(a)} candidates); {vz:.1f} mm slices: objects {n0} -> {n1}, the {len(ss)} added span one slice (single_slice = 1), nothing of the legacy run lost")
    # ---------- 2. registration gate
    copy_case("PH3", "PHG"); run([f"{S}/detect_css.py", "PHG"])
    q = json.load(open(f"{B}/review/PHG_qc.json"))
    if q.get("registration_ok") is not True: fail(f"aligned phantom: registration_ok {q.get('registration_ok')}")
    keep = {f: md5(f) for f in glob.glob(f"{B}/review/PHG_candidates*") + glob.glob(f"{B}/review/PHG_excluded*")}
    for nm in ("seg_swispace", "t1seg_swispace"):
        p = f"{B}/work/PHG_{nm}.nii.gz"; im = nib.load(p); nib.save(nib.Nifti1Image(np.roll(np.asanyarray(im.dataobj), (4, 4, 2), axis=(0, 1, 2)).astype(np.int32), im.affine), p)
    r = run([f"{S}/detect_css.py", "PHG"], ok=(5,)); q = json.load(open(f"{B}/review/PHG_qc.json")); mf = json.load(open(f"{B}/review/PHG_manifest.json"))
    if q.get("registration_ok") is not False or "STOPPED" not in r.stdout: fail("shifted labels: registration_ok must be false and the detector must say STOPPED")
    if keep != {f: md5(f) for f in keep}: fail("registration gate: existing lists were changed")
    if "detect_refused" not in mf or mf["detect_refused"].get("reason") != "registration_failed": fail("manifest must record the refusal")
    rs = run([f"{S}/score_css.py", "PHG", "--truth"], ok=(5,))
    if "NOT SCORED" not in rs.stdout: fail("score_css must refuse a failed registration")
    run([f"{S}/detect_css.py", "PHG"], CSS_ALLOW_BAD_REG="1"); run([f"{S}/score_css.py", "PHG", "--truth"], CSS_ALLOW_BAD_REG="1")
    print(f"registration gate: label shift {q['label_shift_mm']} mm -> detect exit 5, lists untouched, refusal in the manifest, score refused; CSS_ALLOW_BAD_REG=1 proceeds")
    # ---------- 3. confidence cut method, roles, development / evaluation separation
    run([f"{S}/detect_css.py", "PH3"]); c = pd.read_csv(f"{B}/review/PH3_candidates.csv"); L = np.asanyarray(nib.load(f"{B}/review/PH3_candidates.nii.gz").dataobj).astype(int)
    truth = nib.load(f"{B}/work/PH3_truth.nii.gz").get_fdata().astype(int); tl = {int(i) for i in c.cand_id if ((L == i) & (truth > 0)).any()}
    x = c[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy(); x["call"] = ["cSS" if int(i) in tl else "Vessel" for i in c.cand_id]; x["comment"] = ""
    ids = [f"Q{k}" for k in range(1, 10)]
    for qn in ids:
        for ext in ("candidates.csv", "candidates.nii.gz"): shutil.copy(f"{B}/review/PH3_{ext}", f"{B}/review/{qn}_{ext}"); made.append(f"{B}/review/{qn}_{ext}")
        x.to_csv(f"{B}/review/{qn}_calls_P1.csv", index=False); made.append(f"{B}/review/{qn}_calls_P1.csv")
    ev = f"{B}/review/evaluation_studies.txt"; open(ev, "w").write("# evaluation studies\nQ9,examined once\n"); made.append(ev)
    r = run([f"{S}/fit_confidence.py", ",".join(ids), "--reads", "P1"], ok=(1,))
    if "evaluation studies" not in (r.stdout + r.stderr): fail("fit_confidence must refuse an evaluation study")
    run([f"{S}/fit_confidence.py", ",".join(ids[:8]), "--reads", "P1"]); made += [f"{B}/review/confidence_fit.csv", f"{B}/review/confidence_fit_summary.txt", f"{B}/review/confidence_model.json"]
    mj = json.load(open(f"{B}/review/confidence_model.json"))
    if mj.get("cut_method") != "lopo_min" or mj.get("evaluation_studies_excluded") != ["Q9"]: fail(f"model record: {mj.get('cut_method')}, {mj.get('evaluation_studies_excluded')}")
    json.dump(dict(mj, cut_pct=101.0, cut_method="insample_min"), open(f"{B}/review/confidence_model.json", "w"))
    r = run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1", CSS_CONF_GUARD="0"); n_off = len(pd.read_csv(f"{B}/review/PH3_candidates.csv"))
    m = json.load(open(f"{B}/review/PH3_manifest.json"))["detect"]["parameters"]["confidence"]
    if n_off != len(c) or "NOT applied" not in r.stdout or m["exclusion_applied"] or m["cut_method"] != "insample_min" or m["role"] != "evaluation": fail(f"an in-sample cut must not be applied: shown {n_off}/{len(c)}, {m}")
    run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1", CSS_CONF_GUARD="0", CSS_CONF_ALLOW_OPTIMISTIC="1")
    if len(pd.read_csv(f"{B}/review/PH3_candidates.csv")) != 0: fail("with CSS_CONF_ALLOW_OPTIMISTIC=1 the in-sample cut (101 %) must exclude everything")
    json.dump(dict(mj, cut_pct=101.0), open(f"{B}/review/confidence_model.json", "w"))                       # lopo_min: applied
    run([f"{S}/detect_css.py", "PH3"], CSS_CONF="1", CSS_CONF_GUARD="0")
    if len(pd.read_csv(f"{B}/review/PH3_candidates.csv")) != 0: fail("a lopo_min cut must be applied with CSS_CONF=1")
    json.dump(mj, open(f"{B}/review/confidence_model.json", "w")); run([f"{S}/detect_css.py", "PH3"])
    r = run([f"{S}/eval_confidence.py", "Q1"], ok=(1,))
    if "used to fit" not in (r.stdout + r.stderr): fail("eval_confidence must refuse a fit study")
    before = {f: md5(f) for f in glob.glob(f"{B}/review/PH3_*") if os.path.isfile(f) and "confidence_eval" not in f}
    r = run([f"{S}/eval_confidence.py", "PH3", "--reads", "P1"]); made += [f"{B}/review/confidence_eval.csv", f"{B}/review/confidence_eval_summary.txt"]
    if before != {f: md5(f) for f in before} or "Nothing was changed" not in r.stdout: fail("eval_confidence must be read-only")
    print("confidence: in-sample / manual cut not applied without CSS_CONF_ALLOW_OPTIMISTIC=1 (lopo_min is), role + method in the manifest; fit refuses evaluation studies; eval is read-only and refuses fit studies")
finally:
    for n in ("PHT", "PHK", "PHG"): cleanup(n)
    for f in made:
        if os.path.exists(f): os.remove(f)
    subprocess.run([py, f"{S}/detect_css.py", "PH3"], capture_output=True, env=dict(os.environ, CSS_BASE=B))
print("RESULT phase1 OK")
