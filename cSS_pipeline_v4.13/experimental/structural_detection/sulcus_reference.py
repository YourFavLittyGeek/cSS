"""Module E - local sulcal / same-depth reference (CSS_SULCUS_REFERENCE=1). Recorded only.

Production darkness z compares a voxel with the cortex mean in a 10 mm Gaussian neighbourhood. Normal dark
structures (iron-rich motor cortex, a dark sulcal fundus, receive-coil shading) are dark together with the cortex
around them at the same depth; cSS is focally darker than its neighbours at the same depth. Reference = voxels within
REF_RADIUS_MM of the object, at the same depth (pial_sd inside the object's p10..p90 +- DEPTH_TOL_MM), in tissue or
CSF as the object, outside the object dilated by EXCL_MM and outside any other production object.
  sr_ref_n, sr_contrast_z  = (object median - reference median) / reference robust SD
  sr_ref_dark_frac         = share of reference voxels at least as dark as the object's median (high = darkness shared)
  sr_ref_valid             = reference has >= MIN_REF voxels"""
import numpy as np
from scipy import ndimage as ndi

REF_RADIUS_MM, DEPTH_TOL_MM, EXCL_MM, MIN_REF = 10.0, 0.5, 1.5, 50

def object_features(img, obj, psd, vox, others=None, brain=None):
    if obj.sum() < 3: return dict(sr_ref_valid=False)
    d_obj = ndi.distance_transform_edt(~obj, sampling=vox)
    sd = psd[obj]; lo, hi = np.percentile(sd, 10) - DEPTH_TOL_MM, np.percentile(sd, 90) + DEPTH_TOL_MM
    ref = (d_obj > EXCL_MM) & (d_obj <= REF_RADIUS_MM) & (psd >= lo) & (psd <= hi)
    if others is not None: ref &= ~ndi.binary_dilation(others, iterations=1)
    if brain is not None: ref &= brain
    r = img[ref]; out = dict(sr_ref_n=int(ref.sum()), sr_ref_valid=bool(ref.sum() >= MIN_REF))
    if ref.sum() < 5: return out
    med = np.median(r); mad = 1.4826 * np.median(np.abs(r - med)) + 1e-6; om = float(np.median(img[obj]))
    out.update(sr_obj_median=round(om, 2), sr_ref_median=round(float(med), 2), sr_contrast_z=round((om - med) / mad, 2),
               sr_ref_dark_frac=round(float((r <= om).mean()), 3))
    return out
