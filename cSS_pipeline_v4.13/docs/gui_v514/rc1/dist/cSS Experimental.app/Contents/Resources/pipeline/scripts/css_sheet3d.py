"""3-D plate-ness (dark sheet) filter - recorded-only second seed source (audit finding F2, CSS_3D_SEEDS=1). Research software; expert review required.

The detector's generation stage runs a 2-D ridge filter (Sato) on every AXIAL slice. A dark sheet lying parallel to the slice is a plane, not a ridge, in
every slice and is under-responded; the response depends on the orientation of the structure to the acquisition. cSS is a thin sheet on the cortical
surface, whatever its orientation, so a 3-D measure is orientation-free.

plate_filter(If, vox, voxmask, sigmas_mm=(0.6, 1.2, 1.8), beta=0.5)
    -> (S, nz)   S  = scale-normalised dark-sheet measure at the voxels of voxmask (0 elsewhere), maximum over the scales
                 nz = |z component of the sheet normal| there (0 = vertical sheet, 1 = sheet parallel to the axial slices)
Hessian of the intensity at each scale (Gaussian derivatives in mm), eigenvalues ordered by absolute value |l1| <= |l2| <= |l3|. A DARK sheet has one
large POSITIVE curvature across it (l3 > 0) and two small ones along it:
    S = s^2 * l3 * exp(-(|l2| / l3)^2 / (2 beta^2)) * exp(-(|l1| / l3)^2 / (2 beta^2))     (l3 > 0, else 0)
A dark tube (vein) has |l2| ~ l3 and a blob has all three large: both are suppressed.
orientation_angle(nz) -> degrees between the sheet plane and the axial plane (0 = parallel to the slices, 90 = perpendicular)
"""
import numpy as np
from scipy import ndimage as ndi


def plate_filter(If, vox, voxmask, sigmas_mm=(0.6, 1.2, 1.8), beta=0.5):
    vox = np.asarray(vox, float); S = np.zeros(If.shape, np.float32); NZ = np.zeros(If.shape, np.float32)
    if not voxmask.any(): return S, NZ
    box = ndi.find_objects(voxmask.astype(np.uint8))[0]
    pad = [int(np.ceil(3 * max(sigmas_mm) / v)) + 1 for v in vox]
    sl = tuple(slice(max(s.start - p, 0), s.stop + p) for s, p in zip(box, pad))
    sub = If[sl].astype(np.float32); m = voxmask[sl]; idx = np.nonzero(m)
    best = np.zeros(len(idx[0]), np.float32); nzb = np.zeros(len(idx[0]), np.float32)
    for s_mm in sigmas_mm:
        sg = [s_mm / v for v in vox]; H = np.zeros((len(idx[0]), 3, 3), np.float32)
        for a in range(3):
            for b in range(a, 3):
                order = [0, 0, 0]; order[a] += 1; order[b] += 1
                h = ndi.gaussian_filter(sub, sg, order=order)[idx] / (vox[a] * vox[b]) * s_mm ** 2
                H[:, a, b] = h; H[:, b, a] = h
        w, v = np.linalg.eigh(H)                                       # ascending by value
        o = np.argsort(np.abs(w), axis=1); w = np.take_along_axis(w, o, 1)
        v = np.take_along_axis(v, o[:, None, :], 2)                    # columns follow the same order
        l1, l2, l3 = np.abs(w[:, 0]), np.abs(w[:, 1]), w[:, 2]
        ok = l3 > 1e-6
        l3s = np.where(ok, l3, 1.0)
        s = np.where(ok, l3 * np.exp(-(l2 / l3s) ** 2 / (2 * beta ** 2)) * np.exp(-(l1 / l3s) ** 2 / (2 * beta ** 2)), 0.0).astype(np.float32)
        upd = s > best; best[upd] = s[upd]; nzb[upd] = np.abs(v[upd, 2, 2])   # z component of the eigenvector of l3 = sheet normal
        del H, w, v
    S[sl][idx] = best; NZ[sl][idx] = nzb
    return S, NZ


def orientation_angle(nz):
    """angle between the sheet plane and the axial plane = angle between the sheet normal and the z axis: nz = 1 -> 0 degrees (parallel to the
    slices), nz = 0 -> 90 degrees (perpendicular)"""
    return np.degrees(np.arccos(np.clip(np.asarray(nz, float), 0.0, 1.0)))
