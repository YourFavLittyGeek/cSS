"""Module A - Hessian fingerprint (CSS_HESSIAN_FINGERPRINT=1). Recorded features only; no rule uses them.

Per voxel, at each scale sigma in SCALES_MM (physical mm, scale-normalised), the eigenvalues of the Hessian of the
SWI magnitude are classified for a DARK structure (intensity minimum: the largest-magnitude eigenvalue l3 > 0):
  plate  : l3 > 0, l2 <= T_LOW*l3                (curved across one axis: sheet / band)        -> cSS-like
  tube   : l3 > 0, l2 >  T_HIGH*l3, |l1| <= T_LOW*l3 (curved across two axes: cylinder)           -> vessel-like
  blob   : l3 > 0, l2 > T_HIGH*l3, l1 > T_HIGH*l3     (curved across three axes)                  -> microbleed-like
  saddle : l3 > 0, l2 < -T_LOW*l3               (intensity rises along a second axis)           -> edge / junction
  mixed  : l3 > 0, anything else
  bright : l3 <= 0 (not a dark structure at this scale)
The per-voxel class at the voxel's best scale (largest positive l3, as production) gives object fractions.
Columns keep the production value (tube_ratio_prod, |l2|/l3) next to the corrected signed value
(tube_ratio_signed, max(l2,0)/l3) so that historical values are never replaced.
Anisotropy: each scale is flagged unreliable along an axis if sigma < 0.5 voxel there (aniso_unreliable_scales)."""
import numpy as np
from .common import hessian_eigs, production_tube_ratio, signed_tube_ratio

SCALES_MM = (0.6, 0.8, 1.2, 1.6, 2.4)
T_LOW, T_HIGH = 0.25, 0.5
CLASSES = ("plate", "tube", "blob", "saddle", "mixed", "bright")

def classify(w):
    l1, l2, l3 = w[:, 0], w[:, 1], w[:, 2]
    c = np.full(len(w), 4, np.int8)                         # mixed
    dark = l3 > 0
    c[~dark] = 5
    c[dark & (l2 < -T_LOW * l3)] = 3
    c[dark & (np.abs(l2) <= T_LOW * l3)] = 0
    tub = dark & (l2 > T_HIGH * l3)
    c[tub & (np.abs(l1) <= T_LOW * l3)] = 1
    c[tub & (l1 > T_HIGH * l3)] = 2
    return c

def voxel_maps(img, vox, mask, scales=SCALES_MM):
    """Best-scale eigenvalues/vectors at `mask` voxels. Returns dict of flat arrays aligned with idx."""
    best = None
    for s in scales:
        idx, w, v = hessian_eigs(img, vox, s, mask)
        if best is None:
            best = dict(idx=idx, l3=np.full(len(w), -np.inf), w=np.zeros_like(w), v3=np.zeros((len(w), 3)), v1=np.zeros((len(w), 3)),
                        scale=np.full(len(w), np.nan), per_scale={})
        upd = w[:, 2] > best["l3"]
        best["l3"][upd] = w[upd, 2]; best["w"][upd] = w[upd]; best["v3"][upd] = v[upd, :, 2]; best["v1"][upd] = v[upd, :, 0]
        best["scale"][upd] = s
        best["per_scale"][s] = dict(tube_prod=production_tube_ratio(w), tube_signed=signed_tube_ratio(w), cls=classify(w))
    best["cls"] = classify(best["w"])
    best["tube_prod"] = production_tube_ratio(best["w"]); best["tube_signed"] = signed_tube_ratio(best["w"])
    return best

def _q(a, p):
    a = a[np.isfinite(a)]
    return float(np.percentile(a, p)) if len(a) else np.nan

def object_features(maps, sel, vox, normal=None, scales=SCALES_MM):
    """Fingerprint of the voxels `sel` (boolean over maps' flat arrays)."""
    n = int(sel.sum()); out = dict(hf_n_vox=n)
    if n == 0: return out
    cls = maps["cls"][sel]
    for k, nm in enumerate(CLASSES): out[f"hf_{nm}_frac"] = round(float((cls == k).mean()), 4)
    dk = cls != 5
    out["hf_dark_valid_frac"] = round(float(dk.mean()), 4)
    tp, ts = maps["tube_prod"][sel], maps["tube_signed"][sel]
    out.update(tube_ratio_prod_med=_q(tp, 50), tube_ratio_signed_med=_q(ts, 50), tube_ratio_signed_p10=_q(ts, 10),
               tube_ratio_signed_p90=_q(ts, 90), tube_ratio_signed_iqr=_q(ts, 75) - _q(ts, 25),
               hf_saddle_inflation=_q(tp, 50) - _q(ts, 50))
    sc = maps["scale"][sel]
    out["hf_best_scale_med_mm"] = _q(sc, 50)
    for s in scales:
        ps = maps["per_scale"][s]
        out[f"hf_tube_signed_s{s:g}"] = _q(ps["tube_signed"][sel], 50)
        out[f"hf_plate_frac_s{s:g}"] = round(float((ps["cls"][sel] == 0).mean()), 4)
    # plate-vs-tube dominance (signed, in -1..1; > 0 = more plate than tube voxels); undefined if neither present
    p, t = (cls == 0).sum(), (cls == 1).sum()
    out["hf_plate_minus_tube"] = round(float((p - t) / (p + t)), 4) if p + t else np.nan
    if normal is not None:                                # |plate normal . surface normal| ~1 when the plate lies along the surface
        v3 = maps["v3"][sel]; nn = normal[sel]
        ok = (cls == 0) & np.isfinite(nn).all(1)
        out["hf_plate_surface_align"] = round(float(np.median(np.abs((v3[ok] * nn[ok]).sum(1)))), 4) if ok.any() else np.nan
    out["aniso_unreliable_scales"] = ";".join(f"{s:g}" for s in scales if s / max(vox) < 0.5) or "none"
    for k in ("tube_ratio_prod_med", "tube_ratio_signed_med", "tube_ratio_signed_p10", "tube_ratio_signed_p90",
              "tube_ratio_signed_iqr", "hf_saddle_inflation", "hf_best_scale_med_mm"):
        out[k] = round(out[k], 4) if np.isfinite(out[k]) else np.nan
    return out
