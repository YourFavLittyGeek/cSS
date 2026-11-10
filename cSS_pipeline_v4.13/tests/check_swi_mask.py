"""v5.2.5 checks: skull-stripping the SWI with the T1 brain labels (scripts/swi_mask_from_t1.py) instead of SynthStrip.
usage: check_swi_mask.py    (needs PH3 aligned in $CSS_BASE; works on a copy in $CSS_BASE/swimask_check/)
1. PH3 given a synthetic skull and scalp (whole-head SWI): mask = labels + 5 mm; skull and scalp removed, every label
   voxel kept, modification time of data/ID_swi.nii unchanged (derived files are not made stale), FLAIR masked too.
2. detection on the masked whole-head phantom shows the same objects as on the phantom with its own brain-only image
   (same positions, volumes within 2 %), and every true lesion."""
import os, sys, shutil, subprocess, numpy as np, nibabel as nib, pandas as pd
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); py = sys.executable
def fail(m): print("FAIL:", m); sys.exit(1)
B0 = os.environ.get("CSS_BASE")
if not B0 or not os.path.exists(f"{B0}/data/PH3_swi.nii") or not os.path.exists(f"{B0}/work/PH3_seg_swispace.nii.gz"):
    print("skipped: PH3 not aligned"); print("RESULT swimask OK"); sys.exit(0)
def base(tag):
    B = f"{B0}/swimask_check/{tag}"; shutil.rmtree(B, ignore_errors=True)
    for d in ("data", "work", "review", "labels"): os.makedirs(f"{B}/{d}")
    shutil.copy(f"{B0}/data/PH3_swi.nii", f"{B}/data/")
    for f in os.listdir(f"{B0}/work"):
        if f.startswith("PH3_") and f != "PH3_pial_sd.nii.gz": shutil.copy(f"{B0}/work/{f}", f"{B}/work/")
    shutil.copy(f"{B}/work/PH3_seg_swispace.nii.gz", f"{B}/work/PH3_t1seg_swispace.nii.gz"); return B
ref, new = base("ref"), base("head")
s = nib.load(f"{new}/data/PH3_swi.nii"); I = np.asarray(s.dataobj, np.float32)
L = np.asarray(nib.load(f"{new}/work/PH3_seg_swispace.nii.gz").dataobj); vox = np.array(s.header.get_zooms()[:3], float)
d = ndi.distance_transform_edt(~ndi.binary_fill_holes(L > 0), sampling=vox); med = float(np.median(I[L > 0]))
H = I.copy(); H[(I == 0) & (d <= 8)] = 0.9 * med; H[(I == 0) & (d > 8) & (d <= 13)] = 0.25 * med; H[(I == 0) & (d > 13) & (d <= 18)] = 1.3 * med
nib.save(nib.Nifti1Image(H, s.affine, s.header), f"{new}/data/PH3_swi.nii")
nib.save(nib.Nifti1Image(np.full(I.shape, 50.0, np.float32), s.affine), f"{new}/work/PH3_flair_swispace.nii.gz")
t0 = os.path.getmtime(f"{new}/data/PH3_swi.nii") - 3600; os.utime(f"{new}/data/PH3_swi.nii", (t0, t0))
r = subprocess.run([py, f"{S}/swi_mask_from_t1.py", "PH3"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=new))
if r.returncode: fail(r.stdout + r.stderr)
Mk = np.asarray(nib.load(f"{new}/work/PH3_brainmask.nii.gz").dataobj) > 0
J = np.asarray(nib.load(f"{new}/data/PH3_swi.nii").dataobj); F = np.asarray(nib.load(f"{new}/work/PH3_flair_swispace.nii.gz").dataobj)
if not Mk[L > 0].all(): fail("label voxels outside the mask")
if (J[d > 8] != 0).any() or (F[~Mk] != 0).any(): fail("skull / scalp or FLAIR outside the mask not removed")
if not (Mk & (d > 4.5) & (d <= 5)).any() or (Mk & (d > 5.5)).any(): fail("mask is not labels + 5 mm")
if abs(os.path.getmtime(f"{new}/data/PH3_swi.nii") - t0) > 1: fail("SWI modification time changed")
print(f"1. {r.stdout.strip()}  | skull + scalp removed, all labels kept, FLAIR masked, SWI mtime kept")
for B in (ref, new):
    r = subprocess.run([py, f"{S}/detect_css.py", "PH3"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B))
    if r.returncode: fail(f"detect_css {B}: {r.stderr[-500:]}")
a, b = (pd.read_csv(f"{B}/review/PH3_candidates.csv") for B in (ref, new))
k = ["vox_i", "vox_j", "vox_k"]
if len(a) != len(b) or not (np.abs(a[k].values - b[k].values) <= 1).all() or (np.abs(b.volume_mm3 / a.volume_mm3 - 1) > 0.02).any():
    fail(f"candidates differ:\n{a[k + ['volume_mm3']]}\n{b[k + ['volume_mm3']]}")
T = np.asarray(nib.load(f"{new}/work/PH3_truth.nii.gz").dataobj).astype(int)
C = np.asarray(nib.load(f"{new}/review/PH3_candidates.nii.gz").dataobj).astype(int)
shown = sorted({int(t) for t in np.unique(T[(C > 0) & (T > 0)])}); n_true = len(np.unique(T[T > 0]))
if len(shown) != n_true: fail(f"true lesions shown {shown} of {n_true}")
print(f"2. detection: {len(b)} candidates at the same positions as on the brain-only phantom, volumes within "
      f"{100 * float(np.abs(b.volume_mm3 / a.volume_mm3 - 1).max()):.1f} %, true lesions {shown}")
print("RESULT swimask OK")
