"""geometry.py - header description and geometry gate of one image (Stage 2 P1). Refuse, never guess, never reslice.

describe(img)  -> plain-dict description (shape, zooms, affine + hash, header codes, axis codes, the detector's orientation result,
                  obliquity, world bounding box). The orientation / obliquity numbers come from css_qc.py's own block executed verbatim.
gate(desc)     -> dict(status, findings). status (worst finding wins):
                  geometry_refused  the geometry cannot be trusted or the detector would stop (header, affine, slice axis, 4-D)
                  quality_refused   geometry is valid but outside the image-learning envelope (voxel size; design proposal)
                  low_confidence    css_qc's provisional low-confidence conditions (thick slices, obliquity)
                  ok
World coordinates are scanner RAS mm through the image's own affine; sampling helpers work in world mm, so the storage order of the
array (LAS / RAS / LPS ...) does not change what is sampled."""
import hashlib, json
import numpy as np
import nibabel as nib
from scipy import ndimage as ndi
from .. import provenance as pv
from . import CSS_QC

# css_qc.py thresholds, read from the pinned file (provisional there, reported only)
_QC = pv.module_constants(CSS_QC, names=["THICK_SLICE_MM", "OBLIQUE_LOW_CONF_DEG", "EDGE_LOW_CONF_MM", "REG_COST_LOW_CONF"])
THICK_SLICE_MM = _QC["THICK_SLICE_MM"]
OBLIQUE_LOW_CONF_DEG = _QC["OBLIQUE_LOW_CONF_DEG"]

# Stage 2 design envelope (IMAGE_PIPELINE_DESIGN section 2; approved as proposed, NOT validated on clinical data)
MAX_INPLANE_MM = 1.0
MAX_SLICE_MM = 2.5
QS_AGREE_MM = 0.01          # qform and sform both coded: larger disagreement = ambiguous geometry
ZOOM_AGREE_MM = 1e-3        # header voxel size vs affine column norms
GRID_TOL_MM = 1e-4          # "same grid" tolerance (DATA_SCHEMA: on_swi_grid)

_RANK = {"ok": 0, "recorded": 0, "low_confidence": 1, "quality_refused": 2, "geometry_refused": 3}

# css_qc.case_qc orientation / obliquity block, executed verbatim (pinned file)
_QC_ORIENT_SRC = pv.extract_lines("si_axis = int(np.argmax(np.abs(swi.affine[2, :3])))", 'qc["orientation_ok"] = bool(', path=CSS_QC,
                                  include_end=True)
_QC_ORIENT = compile(_QC_ORIENT_SRC, CSS_QC, "exec")


def _detector_stop_expr():
    """the detector's stop condition, taken from detect_css.py (pinned) without its CSS_ALLOW_ORIENT override"""
    L = [ln.strip() for ln in pv.source().splitlines()]
    si = [ln for ln in L if ln == "_si = int(np.argmax(np.abs(swi.affine[2, :3])))"]
    cond = [ln for ln in L if ln.startswith("if (_si != 2 or vox[2] < max(vox[0], vox[1]) - 1e-3)")]
    if len(si) != 1 or len(cond) != 1: raise pv.ProvenanceError("detector orientation stop condition not found exactly once")
    si_line = si[0]
    expr = cond[0][len("if "):cond[0].index(' and os.environ.get("CSS_ALLOW_ORIENT")')]
    return si_line, expr


_DET_SI, _DET_EXPR = _detector_stop_expr()


class _Img:                                          # the attribute the verbatim blocks use (swi.affine)
    def __init__(self, affine): self.affine = np.asarray(affine, float)


def qc_orientation(affine, vox):
    """css_qc's own orientation block -> dict(si_axis, obliquity_deg, thickest_axis, orientation_ok, orientation)"""
    swi = _Img(affine); qc = {"orientation": "".join(nib.aff2axcodes(swi.affine))}
    exec(_QC_ORIENT, dict(np=np, nib=nib, swi=swi, vox=tuple(float(v) for v in vox), qc=qc))
    return dict(si_axis=qc["si_axis"], obliquity_deg=qc["obliquity_deg"], thickest_axis=qc["thickest_axis"],
                orientation_ok=qc["orientation_ok"], orientation=qc["orientation"])


def detector_would_stop(affine, vox):
    """True when detect_css.py stops on this geometry (its own condition, evaluated verbatim)"""
    ns = dict(np=np, swi=_Img(affine), vox=tuple(float(v) for v in vox)); exec(_DET_SI, ns)
    return bool(eval(_DET_EXPR, ns))


def affine_sha(affine):
    return hashlib.sha256(np.round(np.asarray(affine, float), 6).astype("<f8").tobytes()).hexdigest()


def _code(h, key):
    try: return int(h[key])
    except Exception: return None


def describe(img):
    A = np.asarray(img.affine, float); shape = tuple(int(s) for s in img.shape); h = img.header
    zooms = tuple(float(z) for z in h.get_zooms()[:3])
    d = dict(shape=list(shape), ndim=len(shape), zooms_mm=[round(z, 6) for z in zooms], affine=np.round(A, 6).tolist(),
             affine_sha=affine_sha(A), affine_finite=bool(np.isfinite(A).all()),
             det=float(np.linalg.det(A[:3, :3])) if np.isfinite(A).all() else None,
             qform_code=_code(h, "qform_code"), sform_code=_code(h, "sform_code"))
    d["col_norms_mm"] = [round(float(v), 6) for v in np.linalg.norm(A[:3, :3], axis=0)] if d["affine_finite"] else None
    d["qform_sform_max_diff"] = None
    if d["qform_code"] and d["sform_code"]:
        q, s = h.get_qform(), h.get_sform(); d["qform_sform_max_diff"] = round(float(np.abs(q - s).max()), 6)
    ok_affine = d["affine_finite"] and d["det"] is not None and abs(d["det"]) > 1e-9
    d["axcodes"] = "".join(nib.aff2axcodes(A)) if ok_affine else None
    if ok_affine:
        d.update(qc_orientation(A, zooms)); d["detector_would_stop"] = detector_would_stop(A, zooms)
        n = np.array(shape[:3]) - 1
        corners = np.array([[i, j, k] for i in (0, n[0]) for j in (0, n[1]) for k in (0, n[2])], float)
        W = to_world(A, corners); d["world_min_mm"] = np.round(W.min(0), 4).tolist(); d["world_max_mm"] = np.round(W.max(0), 4).tolist()
        d["world_centre_mm"] = np.round(to_world(A, n / 2.0), 4).tolist()
    return d


def _f(check, result, detail): return dict(check=check, result=result, detail=detail)


def gate(d):
    """geometry gate of one description -> dict(status, findings, reasons)"""
    F = []
    if not (d.get("qform_code") or d.get("sform_code")):
        F.append(_f("header_codes", "geometry_refused", "neither qform nor sform has a valid code (> 0): world position unknown"))
    if not d["affine_finite"] or d["det"] is None or abs(d["det"]) <= 1e-9:
        F.append(_f("affine", "geometry_refused", "affine is non-finite or singular"))
        return _summary(F)
    if d["ndim"] > 3 and int(np.prod(d["shape"][3:])) > 1:
        F.append(_f("dimensions", "geometry_refused", f"{d['ndim']}-D image with {int(np.prod(d['shape'][3:]))} volumes"))
    if max(abs(a - b) for a, b in zip(d["zooms_mm"], d["col_norms_mm"])) > ZOOM_AGREE_MM:
        F.append(_f("zooms_vs_affine", "geometry_refused", f"header voxel size {d['zooms_mm']} disagrees with the affine {d['col_norms_mm']}"))
    if d["qform_sform_max_diff"] is not None and d["qform_sform_max_diff"] > QS_AGREE_MM:
        F.append(_f("qform_vs_sform", "geometry_refused", f"qform and sform disagree by {d['qform_sform_max_diff']} (ambiguous geometry)"))
    if not d["orientation_ok"] or d["detector_would_stop"]:
        F.append(_f("slice_axis", "geometry_refused", f"array axis 2 is not the S-I / thickest axis (orientation {d['axcodes']}, voxel "
                                                     f"{d['zooms_mm']}): the detector stops; reslicing is refused here, not guessed"))
    z = d["zooms_mm"]; inpl = max(z[0], z[1])
    if not any(f["check"] == "slice_axis" for f in F) and (inpl > MAX_INPLANE_MM or z[2] > MAX_SLICE_MM):
        F.append(_f("voxel_size", "quality_refused", f"voxel {z} outside the image-learning envelope (in-plane <= {MAX_INPLANE_MM}, "
                                                    f"slice <= {MAX_SLICE_MM} mm)"))
    if max(z) > THICK_SLICE_MM:
        F.append(_f("thick_slices", "low_confidence", f"slices {max(z)} mm > {THICK_SLICE_MM} mm (css_qc)"))
    if d.get("obliquity_deg") is not None and d["obliquity_deg"] > OBLIQUE_LOW_CONF_DEG:
        F.append(_f("obliquity", "low_confidence", f"slices tilted {d['obliquity_deg']} deg > {OBLIQUE_LOW_CONF_DEG} deg (css_qc)"))
    return _summary(F)


def _summary(F):
    status = max((f["result"] for f in F), key=lambda r: _RANK[r], default="ok")
    return dict(status=status if _RANK[status] else "ok", findings=F, reasons=[f["detail"] for f in F if _RANK[f["result"]] > 0])


def same_grid(d1, d2, tol=GRID_TOL_MM):
    return d1["shape"][:3] == d2["shape"][:3] and float(np.abs(np.array(d1["affine"]) - np.array(d2["affine"])).max()) <= tol


def to_world(A, ijk):
    x = np.asarray(ijk, float).reshape(-1, 3)
    return (np.asarray(A, float) @ np.c_[x, np.ones(len(x))].T).T[:, :3].reshape(np.asarray(ijk, float).shape)


def to_voxel(A, xyz):
    x = np.asarray(xyz, float).reshape(-1, 3)
    return (np.linalg.inv(np.asarray(A, float)) @ np.c_[x, np.ones(len(x))].T).T[:, :3].reshape(np.asarray(xyz, float).shape)


def sample_world(data, A, xyz, order=1):
    """values of a 3-D array at world points (mm); NaN outside the array"""
    v = to_voxel(A, np.asarray(xyz, float).reshape(-1, 3)).T
    return ndi.map_coordinates(np.asarray(data, np.float64), v, order=order, mode="constant", cval=np.nan)


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=float)
