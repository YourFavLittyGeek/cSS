"""Segmentation metrics against an EXPERT reference mask (2026-11-28, Milestone 3). Every distance is in millimetres (voxel size given).
Nothing here produces a reference: without an expert-drawn mask there is no accuracy to report (evaluate() says so).

overlap   Dice, IoU (Jaccard), sensitivity (= 1 - under-segmentation), precision (= 1 - over-segmentation), volumes and their ratio
surface   average symmetric surface distance (ASSD), 95th percentile Hausdorff (HD95), maximum Hausdorff, boundary F1 at a tolerance (mm)
extent    slices covered by reference / prediction, slice recall (reference slices that the prediction also covers)
lesions   connected components matched one-to-one by overlap (any voxel, greedy largest overlap first): lesion sensitivity / precision / F1
          and Dice of the matched pairs only (Metrics Reloaded: voxel Dice alone is a poor measure for tiny structures)"""
import numpy as np
from scipy import ndimage as ndi

VERSION = "percival-segmetrics/1.0"


def _surface(m):
    return m & ~ndi.binary_erosion(m, structure=ndi.generate_binary_structure(3, 1), border_value=0)


def surface_distances(ref, pred, vox):
    """distances (mm) from every reference surface voxel to the predicted surface and vice versa -> (d_ref_to_pred, d_pred_to_ref)"""
    sr, sp = _surface(ref), _surface(pred)
    if not sr.any() or not sp.any(): return np.array([]), np.array([])
    dt_p = ndi.distance_transform_edt(~sp, sampling=vox); dt_r = ndi.distance_transform_edt(~sr, sampling=vox)
    return dt_p[sr], dt_r[sp]


def overlap(ref, pred, vox, tol_mm=1.0):
    ref = np.asarray(ref, bool); pred = np.asarray(pred, bool); v3 = float(np.prod(vox)); tp = int((ref & pred).sum())
    nr, npd = int(ref.sum()), int(pred.sum())
    out = dict(ref_mm3=round(nr * v3, 2), pred_mm3=round(npd * v3, 2), volume_ratio=(round(npd / nr, 3) if nr else None),
               dice=(2 * tp / (nr + npd) if nr + npd else None), iou=(tp / (nr + npd - tp) if nr + npd - tp else None),
               sensitivity=(tp / nr if nr else None), precision=(tp / npd if npd else None))
    out["under_segmentation"] = None if out["sensitivity"] is None else 1 - out["sensitivity"]
    out["over_segmentation"] = None if out["precision"] is None else 1 - out["precision"]
    a, b = surface_distances(ref, pred, vox)
    if len(a) and len(b):
        both = np.r_[a, b]
        out.update(assd_mm=float(both.mean()), hd95_mm=float(np.percentile(both, 95)), hd_max_mm=float(both.max()),
                   boundary_f1=float(2 * (a <= tol_mm).mean() * (b <= tol_mm).mean() / max((a <= tol_mm).mean() + (b <= tol_mm).mean(), 1e-12)),
                   boundary_tol_mm=tol_mm)
    sr = set(np.unique(np.argwhere(ref)[:, 2]).tolist()); spp = set(np.unique(np.argwhere(pred)[:, 2]).tolist())
    out.update(ref_slices=len(sr), pred_slices=len(spp), slice_recall=(len(sr & spp) / len(sr) if sr else None))
    return out


def lesion_match(ref, pred, vox):
    """one-to-one matching of connected components (26-connectivity) by overlap -> dict"""
    st = np.ones((3, 3, 3), bool); R, nr = ndi.label(np.asarray(ref, bool), st); P, npd = ndi.label(np.asarray(pred, bool), st)
    pairs = {}
    m = (R > 0) & (P > 0)
    for r, p in zip(R[m], P[m]): pairs[(int(r), int(p))] = pairs.get((int(r), int(p)), 0) + 1
    used_r, used_p, matched = set(), set(), []
    for (r, p), n in sorted(pairs.items(), key=lambda t: -t[1]):
        if r in used_r or p in used_p: continue
        used_r.add(r); used_p.add(p); a, b = R == r, P == p; matched.append(2 * float((a & b).sum()) / float(a.sum() + b.sum()))
    tp = len(matched)
    sens = tp / nr if nr else None; prec = tp / npd if npd else None
    return dict(ref_lesions=int(nr), pred_lesions=int(npd), matched=tp, lesion_sensitivity=sens, lesion_precision=prec,
                lesion_f1=(2 * sens * prec / (sens + prec) if sens and prec else (0.0 if nr and npd else None)),
                matched_dice_mean=(float(np.mean(matched)) if matched else None), rule="any-voxel overlap, one-to-one, largest overlap first")


def evaluate(ref, pred, vox, tol_mm=1.0, size_bins_mm3=(20, 100)):
    """full report; ref None -> no reference (nothing is invented)"""
    if ref is None or not np.asarray(ref, bool).any():
        return dict(version=VERSION, available=False, note="no expert reference mask - segmentation accuracy cannot be reported")
    rep = dict(version=VERSION, available=True, overall=overlap(ref, pred, vox, tol_mm), lesions=lesion_match(ref, pred, vox))
    st = np.ones((3, 3, 3), bool); R, nr = ndi.label(np.asarray(ref, bool), st); v3 = float(np.prod(vox)); by = {}
    for r in range(1, nr + 1):
        a = R == r; size = a.sum() * v3
        k = "small" if size < size_bins_mm3[0] else "medium" if size < size_bins_mm3[1] else "large"
        dil = ndi.binary_dilation(a, iterations=2); o = overlap(a, np.asarray(pred, bool) & dil, vox, tol_mm)
        by.setdefault(k, []).append(o["dice"] or 0.0)
    rep["by_size"] = {k: dict(n=len(v), dice_mean=float(np.mean(v))) for k, v in by.items()}
    rep["size_bins_mm3"] = list(size_bins_mm3)
    return rep
