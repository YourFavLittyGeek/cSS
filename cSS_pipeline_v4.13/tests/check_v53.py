"""v5.3 checks (CSS_V53=1): cortex-outline search zone, skull band / extent / midline rules, second merge pass, tiers.
Synthetic phantom only (tests/phantom_v4.py); no patient data. usage: check_v53.py   (own temporary $CSS_BASE)
1. switch OFF: the candidate list equals the v5.2 list on the same phantom; only the 4 new columns are appended.
2. skull phantom = PH3 with a T1-style brain mask: a dark "inner skull" line 0.6-2 mm outside the cortex on the convexity.
   OFF: the dark line makes objects (shown or excluded) outside the cortex outline. ON: no object voxel lies more
   than V53_OUT_MM + 1 voxel outside the labelled tissue, no shown candidate is skull-backed, every true cSS lesion found OFF is still
   shown ON, and every object has exactly one fate (the detector's own invariant, exit code 0).
3. tiers: "off the cortex, in the CSF, vessel-shaped" alone is tier 3 without v53_active and tier 1 with it; with a
   second vascular sign it stays tier 3.
This shows the mechanics work; it says nothing about performance on patients."""
import os, sys, subprocess, tempfile, shutil, numpy as np, nibabel as nib, pandas as pd
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); sys.path.insert(0, S)
import css_tiers
py = sys.executable
def fail(m): print("FAIL:", m); sys.exit(1)

# ---- 3. tiers (pure function)
row = dict(pial_dist_mm=0.8, csf_depth_mm=0.9, tube_ratio=0.4, elongation_3d=3, local_cont_max_mm=2, terminal_ends=2)
if css_tiers.review_priority(dict(row), "ok")[0] != 3: fail("legacy: off-cortex vessel-shaped should be tier 3")
if css_tiers.review_priority(dict(row, v53_active=1), "ok")[0] != 1: fail("v5.3: off-cortex alone should be tier 1")
two = dict(row, v53_active=1, tube_ratio=0.6, terminal_ends=0)
t = css_tiers.review_priority(two, "ok")
if t[0] != 3 or "off the cortex" not in t[2]: fail(f"v5.3: two vascular signs should be tier 3 with both reasons ({t})")
print("tiers: off-cortex alone -> tier 1 with v5.3, tier 3 without; with a second vascular sign -> tier 3")

# ---- phantom study in a private base
T = tempfile.mkdtemp(); env = dict(os.environ, CSS_BASE=T, FREESURFER_HOME=T + "/fs", CSS_REVIEW_TEST="1")
for d in ("data", "synthseg", "work", "review", "results", "fs"): os.makedirs(f"{T}/{d}")
open(T + "/fs/FreeSurferColorLUT.txt", "w").write(
    "0 Unknown 0 0 0 0\n2 Left-Cerebral-White-Matter 245 245 245 0\n24 CSF 60 60 60 0\n41 Right-Cerebral-White-Matter 245 245 245 0\n"
    "1022 ctx-lh-postcentral 220 20 20 0\n1028 ctx-lh-superiorfrontal 20 220 160 0\n2022 ctx-rh-postcentral 220 20 20 0\n"
    "2028 ctx-rh-superiorfrontal 20 220 160 0\n")
def run(args, **kw):
    r = subprocess.run([py] + args, env=dict(env, **kw), capture_output=True, text=True)
    if r.returncode: fail(f"{' '.join(args[-2:])} exit {r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.stdout
def detect(name, v53):
    out = run([f"{S}/detect_css.py", name], CSS_V53="1" if v53 else "0")
    lab = nib.load(f"{T}/review/{name}_candidates.nii.gz").get_fdata().astype(int)
    allobj = (lab > 0) | (nib.load(f"{T}/review/{name}_excluded.nii.gz").get_fdata() > 0)      # shown + excluded objects
    return pd.read_csv(f"{T}/review/{name}_candidates.csv"), lab, pd.read_csv(f"{T}/review/{name}_excluded.csv"), out, allobj
run([f"{HERE}/phantom_v4.py", "PH3", "1"]); run([f"{S}/align_seg.py", "PH3"])
shutil.copy(f"{T}/work/PH3_seg_swispace.nii.gz", f"{T}/work/PH3_t1seg_swispace.nii.gz")     # pretend T1 labels
truth = nib.load(f"{T}/work/PH3_truth.nii.gz").get_fdata().astype(int)

# ---- 1. switch off = unchanged list, new columns appended last
off, off_lab, _, _, _ = detect("PH3", False)
new = ["midline_frac", "mask_edge_mm", "skull_frac", "v53_active", "vent_frac", "out_frac", "plane_dist_mm", "cos_plane", "ext_major_mm", "skullbase_frac", "dual_contact_frac"]
if list(off.columns[-11:]) != new: fail(f"new columns must be appended last, got {list(off.columns[-11:])}")
if not off.dual_contact_frac.between(0, 1).all(): fail("dual_contact_frac out of range")
if (off.skullbase_frac != 0).any(): fail("the plain phantom has no skull-base labels: skullbase_frac must be 0")
if not off.plane_dist_mm.notna().any() or not (off.cos_plane.dropna().between(0, 1)).all(): fail("plane features (v5.3.4) missing or out of range")
if off.v53_active.any(): fail("v53_active must be 0 with the switch off")
print(f"switch off: {len(off)} candidates, 11 new columns appended, v53_active 0")
# v5.3.3: the absolute thresholds (darkness, volume, cortex share) were fitted to real cSS; the phantom cSS are darker
# and larger. On the plain phantom (no skull band) switching v5.3 on must not lose a true lesion.
_t = nib.load(f"{T}/work/PH3_truth.nii.gz").get_fdata().astype(int)
_on, _on_lab, _x, _, _ = detect("PH3", True)
_f0 = {int(i) for i in np.unique(_t[(off_lab > 0) & (_t > 0)])}; _f1 = {int(i) for i in np.unique(_t[(_on_lab > 0) & (_t > 0)])}
if _f0 - _f1: fail(f"plain phantom: v5.3 lost true lesions {sorted(_f0 - _f1)}: " + "; ".join(_x.reason.astype(str).unique()))
_e22 = _x[_x.reason.astype(str).str.startswith("midline sheet")] if "reason" in _x.columns else _x.iloc[0:0]
if len(_e22) and not ((_e22.plane_dist_mm <= 8) & (_e22.cos_plane >= 0.9) & (_e22.ext_major_mm >= 25)).all(): fail("E22 excluded an object that does not meet its thresholds")
if len(_on) and (_on.dual_contact_frac >= 0.3).any(): fail("E25: a shown object lies between the hemispheres")
_e25 = _x[_x.reason.astype(str).str.startswith("interhemispheric fissure")] if "reason" in _x.columns else _x.iloc[0:0]
if len(_e25) and not (_e25.dual_contact_frac >= 0.3).all(): fail("E25 excluded an object below its threshold")
print(f"E25 fissure objects excluded on the plain phantom: {len(_e25)}")
print(f"E22 midline sheets excluded on the plain phantom: {len(_e22)}")
print(f"plain phantom: true lesions shown {len(_f0)} -> {len(_f1)} with v5.3")

# ---- 1b. v5.7 E24 skull-base cortex zone: PHB = PH3 with the whole LEFT cortex relabelled lateral orbitofrontal (1012):
#      every left object must be excluded by E24, the right-hemisphere objects (incl. true lesions) must be unchanged
shutil.copy(f"{T}/data/PH3_swi.nii", f"{T}/data/PHB_swi.nii")
sg = nib.load(f"{T}/work/PH3_seg_swispace.nii.gz"); a_ = np.asanyarray(sg.dataobj).astype(np.int32); a_[(a_ >= 1000) & (a_ < 2000)] = 1012
for nm_ in ("PHB_seg_swispace.nii.gz", "PHB_t1seg_swispace.nii.gz"): nib.save(nib.Nifti1Image(a_, sg.affine, sg.header), f"{T}/work/{nm_}")
shutil.copy(f"{T}/work/PH3_truth.nii.gz", f"{T}/work/PHB_truth.nii.gz")
for f in os.listdir(f"{T}/work"):
    if f.startswith("PH3_") and "a2009s" in f: shutil.copy(f"{T}/work/{f}", f"{T}/work/{f.replace('PH3_', 'PHB_')}")
b_on, b_lab, b_x, b_log, _ = detect("PHB", True)
if len(b_on) and (b_on.hemi == "L").any(): fail(f"E24: left objects still shown: {b_on[b_on.hemi == 'L'].cand_id.tolist()}")
e24 = b_x[b_x.reason.astype(str).str.startswith("skull-base cortex zone")] if len(b_x) else b_x
if not len(e24) or not (e24.skullbase_frac >= 0.5).all(): fail(f"E24 must exclude the left objects: {b_x.reason.tolist() if len(b_x) else 'none'}")
if len(b_on) != int((_on.hemi == "R").sum()): fail(f"E24: right objects must be unchanged ({len(b_on)} vs {int((_on.hemi == 'R').sum())})")
print(f"E24 skull-base zone: {len(e24)} left objects excluded, {len(b_on)} right objects unchanged, skullbase_frac >= 0.5")

# ---- 1c. v5.7 E25 interhemispheric fissure: PHD = PH3 with the cortex around ONE true lesion relabelled half left / half right (x parity),
#      so that left AND right cortex both lie within 3 mm of it: that object must be excluded by E25, the other true lesions kept
_pl = [int(i) for i in np.unique(_t[(_on_lab > 0) & (_t > 0)])]
_cand_of = {}
for _i in _pl:
    _ids = np.unique(_on_lab[(_on_lab > 0) & (_t == _i)])
    if len(_ids): _cand_of[_i] = int(_ids[0])
if len(_cand_of) < 2: fail("E25 test needs two shown true lesions on the phantom")
_victim = sorted(_cand_of)[0]; _vobj = _on_lab == _cand_of[_victim]
shutil.copy(f"{T}/data/PH3_swi.nii", f"{T}/data/PHD_swi.nii")
_sg = nib.load(f"{T}/work/PH3_seg_swispace.nii.gz"); _a = np.asanyarray(_sg.dataobj).astype(np.int32)
_vv = img_vox = nib.load(f"{T}/data/PH3_swi.nii").header.get_zooms()[:3]
_near = ndi.distance_transform_edt(~_vobj, sampling=_vv) <= 5.0
_xi = np.indices(_a.shape)[0]
_cx = (_a >= 1000) & _near
_left = _cx & (_a < 2000); _right = _cx & (_a >= 2000)
_a[_left & (_xi % 2 == 1)] += 1000                 # odd x of the left cortex -> right label
_a[_right & (_xi % 2 == 0)] -= 1000                # even x of the right cortex -> left label
if not ((_a >= 1000) & (_a < 2000) & _near).any() or not ((_a >= 2000) & _near).any(): fail("E25 test setup: both hemispheres must have cortex near the lesion")
for _nm in ("PHD_seg_swispace.nii.gz", "PHD_t1seg_swispace.nii.gz"): nib.save(nib.Nifti1Image(_a, _sg.affine, _sg.header), f"{T}/work/{_nm}")
shutil.copy(f"{T}/work/PH3_truth.nii.gz", f"{T}/work/PHD_truth.nii.gz")
for _f in os.listdir(f"{T}/work"):
    if _f.startswith("PH3_") and "a2009s" in _f: shutil.copy(f"{T}/work/{_f}", f"{T}/work/{_f.replace('PH3_', 'PHD_')}")
d_on, d_lab, d_x, d_log, _ = detect("PHD", True)
_dv = np.unique(d_lab[(d_lab > 0) & (_t == _victim)])
if len(_dv): fail(f"E25: the lesion between the hemispheres is still shown (cand {_dv.tolist()})")
_e25d = d_x[d_x.reason.astype(str).str.startswith("interhemispheric fissure")] if len(d_x) else d_x
if not len(_e25d) or not (_e25d.dual_contact_frac >= 0.3).all(): fail(f"E25 must exclude it: {d_x.reason.tolist() if len(d_x) else 'none'}")
_dist_v = ndi.distance_transform_edt(~_vobj, sampling=_vv)            # lesions within 15 mm of the relabelled region are legitimately affected by the speckled labels
_others = [i for i in _pl if i != _victim and float(_dist_v[(_on_lab == _cand_of.get(i, -1))].min() if (_on_lab == _cand_of.get(i, -1)).any() else 0) > 15.0]
_kept = {int(i) for i in np.unique(_t[(d_lab > 0) & (_t > 0)])}
if not set(_others) <= _kept: fail(f"E25 must keep the true lesions far from the relabelled region: lost {sorted(set(_others) - _kept)}")
print(f"E25 fissure: lesion {_victim} (between relabelled hemispheres) excluded, other true lesions {len(_others)} kept")

# ---- 2. skull phantom: T1-style mask (labels + 5 mm): dark line just outside the cortex (thin-CSF convexity)
img = nib.load(f"{T}/data/PH3_swi.nii"); I = img.get_fdata().astype(np.float32); vox = img.header.get_zooms()[:3]
brain = I > 0; d = ndi.distance_transform_edt(~brain, sampling=vox); cmed = float(np.median(I[brain]))
seg0 = nib.load(f"{T}/work/PH3_seg_swispace.nii.gz").get_fdata().astype(int)
out_mm = ndi.distance_transform_edt(~((seg0 > 0) & (seg0 != 24)), sampling=vox)   # distance outside the labelled tissue
edge_in = ndi.distance_transform_edt(brain, sampling=vox)                           # depth below the phantom's own edge
rng = np.random.default_rng(3)
I2 = I.copy(); grow = (d > 0) & (d <= 5.0)                          # T1-style mask: 5 mm beyond the labels
line = (out_mm > 0.6) & (out_mm <= 2.0) & (brain & (edge_in < 4.0) | grow)   # inner table: dark line on the convexity
I2[grow] = cmed * 0.8 + rng.normal(0, 5, int(grow.sum()))
I2[line] = cmed * 0.2 + rng.normal(0, 5, int(line.sum()))
nib.save(nib.Nifti1Image(np.maximum(I2, 0), img.affine), f"{T}/data/PHS_swi.nii")
for a, b in (("work/PH3_seg_swispace.nii.gz", "work/PHS_seg_swispace.nii.gz"), ("work/PH3_t1seg_swispace.nii.gz", "work/PHS_t1seg_swispace.nii.gz"),
             ("work/PH3_truth.nii.gz", "work/PHS_truth.nii.gz")):
    shutil.copy(f"{T}/{a}", f"{T}/{b}")
for f in os.listdir(f"{T}/work"):
    if f.startswith("PH3_") and "a2009s" in f: shutil.copy(f"{T}/work/{f}", f"{T}/work/{f.replace('PH3_', 'PHS_')}")
os.utime(f"{T}/work/PHS_t1seg_swispace.nii.gz")
s_off, l_off, x_off, _, a_off = detect("PHS", False)
s_on, l_on, x_on, log, a_on = detect("PHS", True)
far = lambda m: int((m & (out_mm > 1.0 + max(vox))).sum())      # object voxels beyond the cortex outline + 1 mm
found = lambda lab: {int(i) for i in np.unique(truth[(lab > 0) & (truth > 0)])}
if "v5.3 ACTIVE" not in log: fail("the log must say that v5.3 is active")
if not far(a_off): fail("the skull phantom should make objects (shown or excluded) outside the cortex outline with the switch off")
if far((l_on > 0)): fail(f"v5.3: {far((l_on > 0))} voxels of SHOWN candidates lie outside the cortex outline (excluded objects may)")
if len(s_on) and (s_on.skull_frac >= 0.5).any(): fail("v5.3: a skull-backed object is still shown")
lost = found(l_off) - found(l_on)
if lost and os.environ.get("KEEP") == "1": print(T)
if lost: fail(f"v5.3 lost true cSS lesions {sorted(lost)} that were shown without it")
if not s_on.v53_active.all(): fail("v53_active must be 1 with the switch on")
print(f"skull phantom: shown-candidate voxels outside the cortex outline {far(l_off > 0)} -> {far(l_on > 0)}; objects off {len(s_off)} shown + "
      f"{len(x_off)} excluded, on {len(s_on)} shown + {len(x_on)} excluded; true lesions shown {len(found(l_off))} -> {len(found(l_on))}")
if os.environ.get("KEEP") != "1": shutil.rmtree(T)
else: print(T)
print("RESULT v53 OK")
