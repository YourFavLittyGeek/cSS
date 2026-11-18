"""Shared helpers: physical-unit Hessian, eigen-decomposition, object iteration. No production import side effects."""
import numpy as np
from scipy import ndimage as ndi

def mm2vox(s_mm, vox):
    return [s_mm / v for v in vox]

def hessian_eigs(img, vox, sigma_mm, mask=None):
    """Scale-normalised (gamma=1, sigma^2) Hessian in physical mm units at voxels of `mask`.
    Returns (idx, w, v): w = eigenvalues sorted by |w| ascending (|l1|<=|l2|<=|l3|), v[:, :, k] = eigenvector of w[:, k].
    Identical maths to scripts/detect_css.py section 5 (verified in tests/test_hessian.py)."""
    if mask is None: mask = np.ones(img.shape, bool)
    idx = np.nonzero(mask); n = len(idx[0]); sg = mm2vox(sigma_mm, vox)
    H = np.zeros((n, 3, 3), np.float64)
    for a in range(3):
        for b in range(a, 3):
            order = [0, 0, 0]; order[a] += 1; order[b] += 1
            h = ndi.gaussian_filter(img.astype(np.float64), sg, order=order)[idx] / (vox[a] * vox[b]) * sigma_mm ** 2
            H[:, a, b] = h; H[:, b, a] = h
    w, v = np.linalg.eigh(H)
    o = np.argsort(np.abs(w), axis=1)
    w = np.take_along_axis(w, o, 1)
    v = np.take_along_axis(v, o[:, None, :], 2)
    return idx, w, v

def production_tube_ratio(w):
    """Production definition (detect_css.py l.529): |l2| / l3 if l3 > 0 else NaN."""
    l2, l3 = np.abs(w[:, 1]), w[:, 2]
    return np.where(l3 > 0, l2 / np.maximum(np.abs(l3), 1e-6), np.nan)

def signed_tube_ratio(w):
    """Corrected variant: max(l2, 0) / l3 if l3 > 0 else NaN. A saddle (l2 < 0: intensity rises along that axis)
    is not tube-like and scores 0, whereas the production |l2| counts it as tubular."""
    l2, l3 = w[:, 1], w[:, 2]
    return np.where(l3 > 0, np.maximum(l2, 0) / np.maximum(l3, 1e-6), np.nan)

def objects(labels):
    """Yield (object id, slice tuple, local boolean mask) for every positive label."""
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None: continue
        yield i, sl, labels[sl] == i
