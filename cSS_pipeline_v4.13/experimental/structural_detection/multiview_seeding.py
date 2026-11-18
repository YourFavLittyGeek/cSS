"""Module D - multi-view seeding (CSS_MULTIVIEW_SEEDING=1). Recorded only; never adds a shown candidate.

Production seeds are 2-D Sato ridges in AXIAL slices. A sheet lying in the axial plane is a filled area there (no
ridge) and is seen as a line only in coronal / sagittal slices. Here the same ridge filter runs in all three
orientations; a view is valid only if its in-plane voxel sizes differ by <= VIEW_ANISO (on 0.8 x 0.8 x 3 mm data only
the axial view is valid - recorded as views_valid). A voxel is a multi-view seed if it is dark (< -SEED_Z robust SD
of the mask) and its ridge response exceeds the PCT percentile of the mask in >= 1 valid view.
Outputs: per-voxel vote map (0-3) and seed components (>= MIN_SEED_MM3) labelled 'new' when they do not touch any
production object (candidate, excluded or dropped) - a list for review, nothing more."""
import numpy as np
from scipy import ndimage as ndi
from skimage.filters import sato

VIEW_ANISO, PCT, SEED_Z, MIN_SEED_MM3 = 1.5, 85.0, 2.0, 10.0
SIGMAS_MM = (0.6, 1.2)

def valid_views(vox):
    v = np.asarray(vox, float); out = []
    for ax in range(3):                         # slicing axis; in-plane = the other two
        a, b = [v[i] for i in range(3) if i != ax]
        out.append(max(a, b) / min(a, b) <= VIEW_ANISO)
    return out                                  # [sagittal (slice axis 0), coronal (1), axial (2)]

def ridge_view(img, mask, vox, ax):
    R = np.zeros(img.shape, np.float32)
    inpl = float(np.sqrt(np.prod([vox[i] for i in range(3) if i != ax])))
    sig = [max(0.5, s / inpl) for s in SIGMAS_MM]
    for k in range(img.shape[ax]):
        sl = [slice(None)] * 3; sl[ax] = k; sl = tuple(sl)
        if mask[sl].any(): R[sl] = sato(img[sl], sigmas=sig, black_ridges=True)
    return R

def votes(img, mask, vox):
    ref = img[mask]; med = np.median(ref); mad = 1.4826 * np.median(np.abs(ref - med)) + 1e-6
    dark = mask & ((img - med) / mad < -SEED_Z)
    vv = valid_views(vox); V = np.zeros(img.shape, np.int8); per = {}
    for ax, ok in enumerate(vv):
        if not ok: per[ax] = None; continue
        R = ridge_view(img, mask, vox, ax); thr = np.percentile(R[mask], PCT)
        per[ax] = dark & (R > thr); V += per[ax]
    return V, per, vv

def seed_components(V, per, vox, production_mask=None, min_mm3=MIN_SEED_MM3):
    vv = float(np.prod(vox)); seeds = V >= 1
    lab, n = ndi.label(seeds, structure=np.ones((3, 3, 3))); rows = []
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        m = lab[sl] == i
        if m.sum() * vv < min_mm3: continue
        views = [nm for ax, nm in ((0, "sag"), (1, "cor"), (2, "ax")) if per.get(ax) is not None and per[ax][sl][m].any()]
        known = bool(production_mask is not None and production_mask[sl][m].any())
        c = np.argwhere(m).mean(0) + [s.start for s in sl]
        rows.append(dict(seed_id=len(rows) + 1, vol_mm3=round(float(m.sum() * vv), 1), views=";".join(views),
                         axial_seen=bool("ax" in views), status="overlaps production object" if known else "new",
                         vox_i=int(round(c[0])), vox_j=int(round(c[1])), vox_k=int(round(c[2]))))
    return lab, rows
