"""Why did production miss each reference lesion? (read-only; uses the detector's own per-voxel generation record)
usage: python reference_audit/tools/why_missed.py RESULT_NAME --packet W1 [--radius-mm 3]
Reads results/<RESULT_NAME>/reference_lesions_with_production_fate.csv, whole_scan/<PACKET>/key_CONCEALED.csv, and per study
work/ID_gen.nii.gz (bits written by detect_css.py: 1 search zone, 2 skull-strip rim, 4 WM / deep-nucleus label, 8 z < -2,
16 z < strong threshold, 32 ridge > weak percentile, 64 ridge > strong percentile, 128 in a kept component),
work/ID_pial_sd.nii.gz and the inventory label map. For every lesion not retained it reports, in a sphere of --radius-mm around the mark:
the share of voxels reaching each generation step, the first step that fails (outside search zone / not dark enough / no ridge /
no strong seed / kept but removed later), the distance to the labelled pial surface, and the nearest production object of any stage.
Writes results/<RESULT_NAME>/why_missed.csv. Changes nothing."""
import sys, os, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); import ra_common as R
a = sys.argv[1:]
if not a: sys.exit(__doc__)
NAME = a[0]; PK = a[a.index("--packet") + 1]; RAD = float(a[a.index("--radius-mm") + 1]) if "--radius-mm" in a else 3.0
res = os.path.join(R.OUT, "results", NAME); F = pd.read_csv(f"{res}/reference_lesions_with_production_fate.csv")
key = pd.read_csv(os.path.join(R.OUT, "whole_scan", PK, "key_CONCEALED.csv")).set_index("case_code").study_id.to_dict()
F["study_id"] = F.patient_id.map(key)
cat_col = next(c for c in F.columns if c.endswith("_category") and "backup" not in c and c != "reference_category")
F["refcat"] = F[cat_col]; M = F[F.refcat.isin(["definite_cSS", "probable_cSS"]) & (F.fate != "retained (shown)")]
STEPS = [(1, "in search zone"), (8, "dark z < -2"), (16, "dark below strong threshold"), (32, "ridge > weak percentile"), (64, "ridge > strong percentile"), (128, "in a kept component")]
rows = []
for sid, g in M.groupby("study_id"):
    gp = f"{R.B}/work/{sid}_gen.nii.gz"
    if not os.path.exists(gp): print(f"{sid}: no work/{sid}_gen.nii.gz - skipped"); continue
    gi = nib.load(gp); G = np.asarray(gi.dataobj).astype(np.uint8); A = np.linalg.inv(gi.affine); vox = np.array(gi.header.get_zooms()[:3], float)
    psd = np.asarray(nib.load(f"{R.B}/work/{sid}_pial_sd.nii.gz").dataobj, np.float32) if os.path.exists(f"{R.B}/work/{sid}_pial_sd.nii.gz") else None
    L = np.asarray(nib.load(f"{R.OUT}/inventory/{sid}_audit_objects.nii.gz").dataobj).astype(np.int32)
    con = pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_concealed.csv").set_index("label_value")
    r_ = np.ceil(RAD / vox).astype(int); oo = np.stack(np.meshgrid(*[np.arange(-k, k + 1) for k in r_], indexing="ij"), -1).reshape(-1, 3)
    oo = oo[((oo * vox) ** 2).sum(1) <= RAD ** 2]
    objpts = np.argwhere(L > 0)
    for _, r in g.iterrows():
        c = np.round(A @ np.r_[r.x_mm, r.y_mm, r.z_mm, 1])[:3].astype(int); p = np.clip(c + oo, 0, np.array(G.shape) - 1); b = G[p[:, 0], p[:, 1], p[:, 2]]
        d = dict(study_id=sid, case=r.patient_id, cluster_id=r.cluster_id, category=r.refcat, fate=r.fate, mechanism=r.mechanism, rule_reason=r.get("reason", ""))
        for bit, nm in STEPS: d[f"frac {nm}"] = round(float(((b & bit) > 0).mean()), 2)
        d["frac skull-strip rim"] = round(float(((b & 2) > 0).mean()), 2); d["frac WM / deep label"] = round(float(((b & 4) > 0).mean()), 2)
        first = "kept, then removed later (gate or rule)"
        for bit, nm in STEPS:
            if not ((b & bit) > 0).any(): first = f"no voxel {nm}"; break
        d["first_failing_step"] = first if r.fate == "never generated" else f"generated -> {r.mechanism}"
        if psd is not None: d["pial_sd_mm_at_mark"] = round(float(psd[tuple(np.clip(c, 0, np.array(G.shape) - 1))]), 2)
        if len(objpts):
            dd = np.sqrt((((objpts - c) * vox) ** 2).sum(1)); k = dd.argmin(); lv = int(L[tuple(objpts[k])])
            d["nearest_object_mm"] = round(float(dd[k]), 1); d["nearest_object_stage"] = con.loc[lv, "stage"] if lv in con.index else ""
            d["nearest_object_reason"] = con.loc[lv, "reason"] if lv in con.index else ""; d["nearest_object_volume_mm3"] = con.loc[lv, "volume_mask_mm3"] if lv in con.index else ""
        rows.append(d)
out = pd.DataFrame(rows); out.to_csv(f"{res}/why_missed.csv", index=False)
print(out[["study_id", "case", "category", "fate", "first_failing_step", "nearest_object_mm", "nearest_object_stage"]].to_string(index=False) if len(out) else "nothing missed")
print(f"-> {res}/why_missed.csv")
