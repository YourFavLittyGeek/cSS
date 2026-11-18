"""Module B - surface-aware coordinates (CSS_SURFACE_COORDINATES=1). Recorded only.

Works on the detector's own signed distance to the labelled pial boundary (work/ID_pial_sd.nii.gz: < 0 tissue,
> 0 CSF), so it needs no FreeSurfer surface (route-independent; the recon-all mesh features stay in
surface_features.py, untouched). Per object:
  depth   = pial_sd of its voxels (p10 / median / p90), share in the subpial band (-2 < sd <= +0.5 mm), in CSF (> +0.5)
  frame   = mean outward normal n (gradient of pial_sd); tangential coordinates = voxel positions projected on the
            plane orthogonal to n, principal axes by PCA
  extents = normal thickness (p95 - p5 of the coordinate along n), tangential length / width (p95 - p5 along the two
            tangential axes), footprint area (projected 0.5 mm pixels), sc_width_mm = footprint / length
  normal_coherence = length of the mean unit normal (1 = one surface; ~0 = two opposite banks, e.g. a tram-track or
            an object crossing a sulcus)
Limits: a single mean frame is a poor model for objects that wrap around a gyrus crown (the curved-band phantom
quantifies this); the pial_sd surface is voxel-precise (label boundary), not sub-voxel."""
import numpy as np
from scipy import ndimage as ndi

def normals(psd, vox):
    g = np.gradient(psd.astype(np.float64), *vox)
    nrm = np.sqrt(sum(x ** 2 for x in g)) + 1e-9
    return np.stack([x / nrm for x in g], -1)          # unit outward normal (towards CSF)

def object_features(obj, psd, nrm, vox, pix_mm=0.5):
    p = np.argwhere(obj); n_ = len(p)
    if n_ < 3: return dict(sc_n_vox=n_)
    sd = psd[obj]; X = p * np.asarray(vox)
    nv = nrm[obj]; ok = np.isfinite(nv).all(1)
    m = nv[ok].mean(0); coh = float(np.linalg.norm(m)); n = m / (np.linalg.norm(m) + 1e-9)
    Xc = X - X.mean(0); a_n = Xc @ n; T = Xc - np.outer(a_n, n)
    if coh < 1e-6: T = Xc
    _, _, Vt = np.linalg.svd(T, full_matrices=False)
    u1, u2 = T @ Vt[0], T @ Vt[1]
    ext = lambda a: float(np.percentile(a, 95) - np.percentile(a, 5)) + float(np.mean(vox))   # + one voxel: extent of occupied voxels
    L, W, Tn = ext(u1), ext(u2), ext(a_n)
    fp = len(np.unique(np.stack([np.floor(u1 / pix_mm), np.floor(u2 / pix_mm)], 1), axis=0)) * pix_mm ** 2
    return dict(sc_n_vox=n_, sc_depth_p10=round(float(np.percentile(sd, 10)), 2), sc_depth_med=round(float(np.median(sd)), 2),
                sc_depth_p90=round(float(np.percentile(sd, 90)), 2), sc_subpial_frac=round(float(((sd > -2) & (sd <= 0.5)).mean()), 3),
                sc_csf_frac=round(float((sd > 0.5).mean()), 3), sc_normal_coherence=round(coh, 3),
                sc_normal_thickness_mm=round(Tn, 2), sc_tan_length_mm=round(L, 2), sc_tan_width_mm=round(W, 2),
                sc_footprint_mm2=round(fp, 1), sc_width_mm=round(fp / max(L, 1e-6), 2),
                sc_flatness=round(Tn / max(W, 1e-6), 3), sc_tan_aspect=round(W / max(L, 1e-6), 3))
