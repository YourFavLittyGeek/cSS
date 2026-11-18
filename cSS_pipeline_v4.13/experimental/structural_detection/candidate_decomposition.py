"""Module F - candidate decomposition (CSS_CANDIDATE_SPLITTING=1). Recorded only; nothing is removed.

A detector object can join a plate-like piece (possible cSS) and a tube-like piece (possible vessel). This module
partitions the object's voxels into components by their Hessian class (module A, best scale):
  1. per-voxel class -> plate / tube / other; smoothed by a 3x3x3 majority vote inside the object;
  2. connected components of plate voxels and of tube voxels; components < MIN_COMP_MM3 are re-assigned to the
     neighbouring component that touches them most (distance transform);
  3. 'other' voxels go to the nearest component.
INVARIANT (asserted): the union of the components equals the parent object, components are disjoint, every voxel
keeps its parent id. A possible cSS component is therefore never discarded - at most it is reported next to a vessel
component (mixed_object = True)."""
import numpy as np
from scipy import ndimage as ndi

MIN_COMP_MM3 = 8.0

def decompose(obj, cls_local, vox, min_mm3=MIN_COMP_MM3):
    """obj: bool array (crop). cls_local: int8 array, same shape, module-A class at object voxels (0 plate, 1 tube, else other).
    Returns (comp_label int32 array, list of component dicts)."""
    vv = float(np.prod(vox)); obj = obj.astype(bool)
    base = np.full(obj.shape, -1, np.int8)
    base[obj & (cls_local == 0)] = 0; base[obj & (cls_local == 1)] = 1; base[obj & (base < 0)] = 2
    # majority smoothing inside the object (ties keep the voxel's own class)
    votes = np.stack([ndi.uniform_filter(((base == k) & obj).astype(np.float32), 3) for k in range(3)])
    sm = np.where(obj, np.argmax(votes, 0), -1).astype(np.int8)
    own = np.take_along_axis(votes, np.clip(base, 0, 2)[None].astype(np.int64), 0)[0]
    sm[obj & (own >= votes.max(0) - 1e-6)] = base[obj & (own >= votes.max(0) - 1e-6)]
    comp = np.zeros(obj.shape, np.int32); n = 0; kinds = {}
    for k in (0, 1):
        lab, m = ndi.label(sm == k, structure=np.ones((3, 3, 3)))
        for i in range(1, m + 1):
            n += 1; comp[lab == i] = n; kinds[n] = k
    # drop-free merge of small components into their largest touching neighbour (or nearest if none touches)
    changed = True
    while changed and n:
        changed = False
        sizes = np.bincount(comp.ravel(), minlength=n + 1)
        for i in [i for i in range(1, n + 1) if 0 < sizes[i] * vv < min_mm3]:
            if sizes.astype(bool)[1:].sum() <= 1: break
            ring = ndi.binary_dilation(comp == i, structure=np.ones((3, 3, 3))) & (comp > 0) & (comp != i)
            if ring.any(): tgt = np.bincount(comp[ring]).argmax()
            else:
                others = (comp > 0) & (comp != i)
                if not others.any(): continue
                _, ind = ndi.distance_transform_edt(~others, sampling=vox, return_indices=True)
                p = np.argwhere(comp == i)[0]; tgt = comp[tuple(ind[:, p[0], p[1], p[2]])]
            comp[comp == i] = tgt; changed = True; sizes = np.bincount(comp.ravel(), minlength=n + 1)
    # 'other' voxels -> nearest component; if no plate/tube component exists, the whole object is one 'other' component
    rest = obj & (comp == 0)
    if (comp > 0).any() and rest.any():
        _, ind = ndi.distance_transform_edt(comp == 0, sampling=vox, return_indices=True)
        comp[rest] = comp[tuple(ind[:, rest])]
    elif rest.any():
        n += 1; comp[rest] = n; kinds[n] = 2
    # renumber 1..K
    ids = [i for i in np.unique(comp) if i > 0]; out = np.zeros_like(comp); rows = []
    for j, i in enumerate(ids, 1):
        m = comp == i; out[m] = j
        c = cls_local[m]
        rows.append(dict(comp_id=j, comp_kind={0: "plate", 1: "tube", 2: "other"}[kinds.get(i, 2)], comp_n_vox=int(m.sum()),
                         comp_vol_mm3=round(float(m.sum() * vv), 1), comp_plate_frac=round(float((c == 0).mean()), 3),
                         comp_tube_frac=round(float((c == 1).mean()), 3)))
    assert ((out > 0) == obj).all(), "decomposition lost or added voxels"          # the invariant
    return out, rows

def summary(rows):
    k = [r["comp_kind"] for r in rows]
    big = [r for r in rows if r["comp_vol_mm3"] >= MIN_COMP_MM3]
    return dict(dec_n_components=len(rows), dec_n_plate=k.count("plate"), dec_n_tube=k.count("tube"),
                dec_plate_vol_mm3=round(sum(r["comp_vol_mm3"] for r in rows if r["comp_kind"] == "plate"), 1),
                dec_tube_vol_mm3=round(sum(r["comp_vol_mm3"] for r in rows if r["comp_kind"] == "tube"), 1),
                dec_mixed_object=bool(any(r["comp_kind"] == "plate" for r in big) and any(r["comp_kind"] == "tube" for r in big)))
