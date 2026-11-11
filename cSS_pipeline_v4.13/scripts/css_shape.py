"""Shape measures for one object (a blob / microbleed vs a line along the cortex; a straight line in a sulcus vs one that tracks
into the adjacent cortex). Pure functions on numpy masks, used by shape_probe.py and tested on synthetic shapes (tests/check_shape.py).
Research software; expert review required.

All lengths in mm. `vox` = voxel size (3 values). A mask is a boolean 3-D array; `coords` = N x 3 voxel indices.

principal(coords, vox)            -> (e1, e2, e3, axes): extents (max - min of the projection + one voxel along that axis' voxel size
                                     proxy) along the principal axes, largest first, in mm. e3 is floored at the thickest voxel dimension
                                     so that a one-slice object is not called infinitely thin.
blob_measures(support, obj, vox)   -> dict(support_mm3, support_over_obj, e1, e2, e3, l_over_m, m_over_s, fill, esd_mm)
                                     l_over_m  = e1 / e2   (line >> 1; blob and disc about 1)
                                     m_over_s  = e2 / e3   (blob about 1; plate / disc large)
                                     fill      = support volume / volume of the ellipsoid with the same extents (blob high, curved line low)
dark_support(dark, obj, vox, cap_mm=10, grow=1)
                                  -> voxels of `dark` connected (26-neighbourhood) to the object through at most `grow` voxels of gap,
                                     no further than cap_mm from the object
bend(coords, vox)                  -> (rms_dev_mm, bend_ratio): RMS distance of the voxels from the best-fit straight line (first principal axis)
                                     and that value divided by the object length e1 (straight line ~0; arc / curve larger)
depth_stats(depth, coords)         -> dict(depth_p10, depth_p50, depth_p90, depth_range, crown_frac, deep_frac)
                                     depth = sulcal depth map in mm (0 at the outer envelope); crown = depth < 1.5 mm, deep = depth > 4 mm
touch_stats(cortex_labels, obj, vox, reach_mm=1.5)
                                  -> dict(n_labels, label_spread): number of cortical labels with >= 15 % of the object's neighbouring
                                     cortex voxels, and the share of that cortex that is NOT in the largest label
"""
import numpy as np
from scipy import ndimage as ndi


def principal(coords, vox):
    P = np.asarray(coords, float) * np.asarray(vox, float)
    if len(P) < 3: return 0.0, 0.0, 0.0, np.eye(3)
    Q = P - P.mean(0); w, v = np.linalg.eigh(np.cov(Q.T)); order = np.argsort(w)[::-1]; v = v[:, order]
    pr = Q @ v; ext = np.ptp(pr, axis=0)
    # one voxel diagonal-free correction: a single voxel row has extent 0, add the mean voxel size along the axis
    vd = np.abs(v) @ np.asarray(vox, float)
    e = ext + vd
    e[2] = max(e[2], float(np.max(vox)))
    return float(e[0]), float(e[1]), float(e[2]), v


def dark_support(dark, obj, vox, cap_mm=10.0, grow=1):
    if not obj.any(): return obj.copy()
    s26 = ndi.generate_binary_structure(3, 3)
    seed = ndi.binary_dilation(obj, structure=s26, iterations=grow) & dark | obj
    lab, n = ndi.label(dark | obj, structure=s26)
    ids = np.unique(lab[seed]); ids = ids[ids > 0]
    comp = np.isin(lab, ids)
    near = ndi.distance_transform_edt(~obj, sampling=vox) <= cap_mm
    return comp & near


def blob_measures(support, obj, vox):
    vox = np.asarray(vox, float); c = np.argwhere(support)
    vol_s = float(support.sum() * vox.prod()); vol_o = float(max(obj.sum(), 1) * vox.prod())
    e1, e2, e3, _ = principal(c, vox)
    ell = 4.0 / 3.0 * np.pi * (e1 / 2) * (e2 / 2) * (e3 / 2)
    return dict(support_mm3=round(vol_s, 1), support_over_obj=round(vol_s / vol_o, 2), e1=round(e1, 1), e2=round(e2, 1), e3=round(e3, 1),
                l_over_m=round(e1 / max(e2, 1e-6), 2), m_over_s=round(e2 / max(e3, 1e-6), 2),
                fill=round(float(min(vol_s / ell, 5.0)) if ell > 0 else np.nan, 2), esd_mm=round(float((6 * vol_s / np.pi) ** (1 / 3)), 1))


def bend(coords, vox):
    P = np.asarray(coords, float) * np.asarray(vox, float)
    if len(P) < 4: return 0.0, 0.0
    e1, _, _, v = principal(coords, vox); Q = P - P.mean(0)
    perp = Q - np.outer(Q @ v[:, 0], v[:, 0]); rms = float(np.sqrt((perp ** 2).sum(1).mean()))
    return round(rms, 2), round(rms / max(e1, 1e-6), 3)


def depth_stats(depth, coords):
    d = depth[tuple(np.asarray(coords).T)] if len(coords) else np.array([np.nan])
    p = np.nanpercentile(d, [10, 50, 90])
    return dict(depth_p10=round(float(p[0]), 1), depth_p50=round(float(p[1]), 1), depth_p90=round(float(p[2]), 1),
                depth_range=round(float(p[2] - p[0]), 1), crown_frac=round(float((d < 1.5).mean()), 2), deep_frac=round(float((d > 4.0).mean()), 2))


def touch_stats(cortex_labels, obj, vox, reach_mm=1.5):
    near = ndi.distance_transform_edt(~obj, sampling=vox) <= reach_mm
    lab = cortex_labels[near & (cortex_labels > 0)]
    if not len(lab): return dict(n_labels=0, label_spread=np.nan)
    u, n = np.unique(lab, return_counts=True); fr = n / n.sum()
    return dict(n_labels=int((fr >= 0.15).sum()), label_spread=round(float(1 - fr.max()), 2))
