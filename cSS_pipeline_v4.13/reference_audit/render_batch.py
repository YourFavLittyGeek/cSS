"""Blinded review material for one batch of sampled objects (no stage, reason, score or module output is shown).
usage: python reference_audit/render_batch.py BATCH [--crop-mm 40] [--masks]
writes reference_audit/batches/<BATCH>/review/<case_id>.png  (axial / coronal / sagittal crops through the object centre, the object
outlined in one neutral colour, an 8 mm axial minIP, the case id - nothing else), optional <case_id>_mask.nii.gz (the object alone,
for ITK-SNAP / freeview), and annotation_sheet.csv (one row per case, columns of EXPERT_ANNOTATION_TEMPLATE, prefilled ids only)."""
import sys, os, numpy as np, pandas as pd, nibabel as nib, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R
from annotation_schema import OBJECT_COLUMNS

a = sys.argv[1:]
if not a: sys.exit(__doc__)
NAME = a[0]; CROP = float(a[a.index("--crop-mm") + 1]) if "--crop-mm" in a else 40.0
bd = os.path.join(R.OUT, "batches", NAME); rv = os.path.join(bd, "review"); os.makedirs(rv, exist_ok=True)
cases = pd.read_csv(f"{bd}/cases_blinded.csv"); key = pd.read_csv(f"{bd}/key_CONCEALED.csv")[["case_id", "label_value"]]
cases = cases.merge(key, on="case_id")                 # label_value is used internally to draw the outline only
cache = {}
for r in cases.itertuples():
    if r.study_id not in cache:
        img = nib.load(f"{R.B}/data/{r.study_id}_swi.nii"); cache = {r.study_id: (img, np.asarray(img.dataobj, np.float32),
                       np.asarray(nib.load(f"{R.OUT}/inventory/{r.study_id}_audit_objects.nii.gz").dataobj).astype(np.int32))}
    img, I, L = cache[r.study_id]; vox = np.array(img.header.get_zooms()[:3], float); m = L == r.label_value
    c = np.array([r.vox_i, r.vox_j, r.vox_k]); h = np.ceil(CROP / 2 / vox).astype(int)
    lo = np.maximum(c - h, 0); hi = np.minimum(c + h + 1, I.shape)
    sub = I[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]; ms = m[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]; cc = c - lo
    vmin, vmax = np.percentile(I[I > 0], [1, 99]) if (I > 0).any() else (0, 1)
    kz = max(1, int(round(4 / vox[2])))
    views = [("axial", sub[:, :, cc[2]].T, ms[:, :, cc[2]].T, vox[1] / vox[0]), ("coronal", sub[:, cc[1], :].T, ms[:, cc[1], :].T, vox[2] / vox[0]),
             ("sagittal", sub[cc[0], :, :].T, ms[cc[0], :, :].T, vox[2] / vox[1]),
             ("axial minIP 8 mm", sub[:, :, max(cc[2] - kz, 0):cc[2] + kz + 1].min(2).T, ms[:, :, max(cc[2] - kz, 0):cc[2] + kz + 1].any(2).T, vox[1] / vox[0])]
    fig, ax = plt.subplots(1, 4, figsize=(14, 3.8))
    for a_, (t, im, mk, asp) in zip(ax, views):
        a_.imshow(im, cmap="gray", origin="lower", vmin=vmin, vmax=vmax, aspect=asp, interpolation="nearest")
        if mk.any(): a_.contour(mk.astype(float), levels=[0.5], colors="#00d0ff", linewidths=0.9)
        a_.set_title(t, fontsize=9); a_.axis("off")
    fig.suptitle(f"{r.case_id}   (outline = the object to judge; radiological orientation not applied: patient left/right as stored)", fontsize=9)
    fig.tight_layout(); fig.savefig(f"{rv}/{r.case_id}.png", dpi=130); plt.close(fig)
    if "--masks" in a: nib.save(nib.Nifti1Image(m.astype(np.uint8), img.affine), f"{rv}/{r.case_id}_mask.nii.gz")
sheet = pd.DataFrame({c: "" for c in OBJECT_COLUMNS}, index=range(len(cases)))
sheet["case_id"] = cases.case_id.values; sheet["patient_id"] = cases.study_id.values
sheet.to_csv(f"{rv}/annotation_sheet.csv", index=False)
print(f"{NAME}: {len(cases)} blinded review images + annotation_sheet.csv -> {rv}")
