"""make_demo.py - prepare the Percival Demo project (SYNTHETIC phantoms only; started by the Percival Demo app, no Terminal).
usage: python make_demo.py <project> <run_imaging.py>
1. synthetic cohort (6 phantom studies) with run_imaging.py cohort, when the project has none yet;
2. the synthetic candidate lists only carry id / voxel / volume: add the columns the reviewer and Percival read, MEASURED on the
   synthetic SWI (demo values, not the clinical detector): hemi (world x of the centroid), region, darkness_z (candidate vs brain median
   in MAD units), edge_contrast (2-voxel shell minus candidate, MAD units), elongation_3d (PCA axis ratio), log volume, and MATH =
   score_v4 = sqrt(max(darkness_z, 0)) (the darkness term of the real formula only);
3. register the studies in the app as processed (cohort "Demo") so they can be reviewed at once.
Never touches anything outside <project>; refuses a project that already has non-synthetic studies."""
import glob, json, os, subprocess, sys, time
import numpy as np, nibabel as nib, pandas as pd
from scipy import ndimage as ndi

B, RUN = os.path.abspath(sys.argv[1]), sys.argv[2]
cands = glob.glob(os.path.join(B, "review", "*_candidates.csv"))
if [c for c in cands if not os.path.basename(c).startswith("SYN")]: sys.exit("refused: this project has non-synthetic studies")
if not cands:
    r = subprocess.run([sys.executable, RUN, "cohort", B, "--n", "6", "--seed", "42"]);
    if r.returncode: sys.exit(r.returncode)
studies = sorted(os.path.basename(p)[:-15] for p in glob.glob(os.path.join(B, "review", "SYN*_candidates.csv")))
for sid in studies:
    cp = os.path.join(B, "review", f"{sid}_candidates.csv"); c = pd.read_csv(cp)
    if "score_v4" in c.columns: continue
    im = nib.load(os.path.join(B, "data", f"{sid}_swi.nii")); I = np.asarray(im.dataobj, float)
    L = np.asarray(nib.load(os.path.join(B, "review", f"{sid}_candidates.nii.gz")).dataobj).astype(int)
    brain = I > np.percentile(I[I > 0], 20) if (I > 0).any() else I > 0
    med = float(np.median(I[brain])); mad = float(np.median(np.abs(I[brain] - med))) or 1.0
    vox = np.array(im.header.get_zooms()[:3], float); cols = dict(hemi=[], region=[], darkness_z=[], edge_contrast=[], elongation_3d=[], score_v4=[])
    for cid in c.cand_id:
        m = L == int(cid)
        if not m.any():
            for k in cols: cols[k].append(np.nan if k not in ("hemi", "region") else ""); continue
        dz = (med - I[m].mean()) / mad; sh = ndi.binary_dilation(m, iterations=2) & ~m & brain
        ec = ((I[sh].mean() - I[m].mean()) / mad) if sh.any() else np.nan
        P = np.argwhere(m) * vox; ev = np.sort(np.linalg.eigvalsh(np.cov(P.T))) if len(P) > 3 else np.array([1, 1, 1.0])
        x = (im.affine @ np.r_[np.argwhere(m).mean(0), 1])[0]
        cols["hemi"].append("L" if x < 0 else "R"); cols["region"].append("synthetic cortex (demo)")
        cols["darkness_z"].append(round(float(dz), 3)); cols["edge_contrast"].append(round(float(ec), 3))
        cols["elongation_3d"].append(round(float(np.sqrt(ev[-1] / max(ev[-2], 1e-6))), 3)); cols["score_v4"].append(round(float(np.sqrt(max(dz, 0))), 3))
    for k, v in cols.items(): c[k] = v
    c.to_csv(cp, index=False)
pp = os.path.join(B, "app_data", "patients.json"); os.makedirs(os.path.dirname(pp), exist_ok=True)
try: P = json.load(open(pp))
except Exception: P = []
have = {p["code"] for p in P}
for sid in studies:
    if sid not in have:
        P.append(dict(code=sid, cohort="Demo", status="done", fingerprint="", series={}, steps_done={}, added=time.time(), finished=time.time(),
                      mode="semi", anatomy="synthseg", pathway="synthseg", note="synthetic demo study (phantom) - not processed by the clinical pipeline"))
json.dump(P, open(pp, "w"), indent=1)
print(f"demo project ready: {len(studies)} synthetic studies in {B}")
