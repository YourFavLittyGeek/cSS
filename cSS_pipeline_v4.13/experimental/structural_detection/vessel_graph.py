"""Module C - vessel graph (CSS_VESSEL_GRAPH=1). Recorded only.

In a region around the object (object box + ROI_MM), dark tube-like voxels (module A class 'tube' at the voxel's best
scale, darker than the ROI background by DARK_Z robust SD) form a vessel map. It is skeletonised (skimage, 3-D) and
read as a graph (26-neighbourhood): end points (degree 1), branch points (degree >= 3), edge length in mm.
Per object:
  vg_connected           a skeleton component touches the object (1-voxel dilation)
  vg_ext_length_mm       skeleton length OUTSIDE the object in the touching components (continuation)
  vg_ext_branch_points   branch points outside the object in those components
  vg_ext_endpoints       end points outside
  vg_internal_length_mm  skeleton length inside the object (tube-like spine inside the object)
  vg_evidence            'vascular_continuation' if vg_ext_length_mm >= CONT_MM, else 'no_detectable_connection'
IMPORTANT: 'no_detectable_connection' is NOT evidence of cSS (veins can be interrupted by partial volume, slice
thickness or the ROI edge); the fusion layer treats it as neutral."""
import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

ROI_MM, DARK_Z, CONT_MM = 15.0, 2.0, 6.0
K26 = np.ones((3, 3, 3)); K26[1, 1, 1] = 0

def vessel_map(img, cls, region):
    """cls: module-A class array (crop) with -1 where not computed; region: bool crop where the map is allowed."""
    ref = img[region]; med = np.median(ref); mad = 1.4826 * np.median(np.abs(ref - med)) + 1e-6
    return region & (cls == 1) & ((img - med) / mad < -DARK_Z)

def skeleton_graph(vmap, vox):
    sk = skeletonize(vmap.astype(np.uint8)) > 0
    deg = ndi.convolve(sk.astype(np.uint8), K26.astype(np.uint8), mode="constant") * sk
    # length: sum over skeleton voxel pairs of their distance / 2 (each pair counted twice)
    L = np.zeros(sk.shape)
    for d in np.argwhere(np.ones((3, 3, 3))) - 1:
        if not d.any(): continue
        sh = np.roll(sk, tuple(-d), axis=(0, 1, 2))
        L += (sk & sh) * float(np.sqrt(((d * np.asarray(vox)) ** 2).sum())) / 2
    return sk, deg, L

def object_features(obj, sk, deg, L, vox):
    lab, n = ndi.label(sk, structure=np.ones((3, 3, 3)))
    touch = ndi.binary_dilation(obj, structure=np.ones((3, 3, 3)))
    ids = np.unique(lab[touch & sk]); ids = ids[ids > 0]
    comp = np.isin(lab, ids)
    outside = comp & ~obj
    ext = float(L[outside].sum()); inside = float(L[sk & obj].sum())
    out = dict(vg_connected=bool(len(ids)), vg_n_components=int(len(ids)), vg_ext_length_mm=round(ext, 1),
               vg_ext_branch_points=int(((deg >= 3) & outside).sum()), vg_ext_endpoints=int(((deg == 1) & outside).sum()),
               vg_internal_length_mm=round(inside, 1))
    out["vg_evidence"] = "vascular_continuation" if ext >= CONT_MM else "no_detectable_connection"
    return out
