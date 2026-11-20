"""perturb.py - stability of features, decomposition and score under small, plausible perturbations.

Perturbations (16): candidate erosion / dilation by one voxel (boundary change); darkness threshold +-0.25 noise units (image
shifted by -+0.25 sd, equivalent to moving every contrast threshold); registration shift +-1 voxel on x, y, z (pial distance map
and brain mask moved together: they come from the same labels); vessel-map alignment +-1 voxel on x, y, z (vessel map alone).
Instability only ever INCREASES uncertainty (a protective flag); it is never evidence against cSS."""
import numpy as np
from scipy import ndimage as ndi
from . import features as fe

TOL = {"x1_vessel_continuity_mm": 2.0, "x2_core_contrast_nu": 1.5, "x3_pial_distance_mm": 0.75, "x4_sulcal_alignment": 0.2,
       "x5_extracranial_mm": 2.0}       # change counted as unstable (PROVISIONAL)


def _shift(a, d, axis, fill):
    if a is None: return None
    s = [0, 0, 0]; s[axis] = d
    if a.dtype == bool: return ndi.shift(a.astype(np.uint8), s, order=0, mode="constant", cval=int(fill)) > 0
    return ndi.shift(a, s, order=1, mode="nearest")


def perturbations(cand, img, raw, ves, psd, brain, D0):
    sd = D0.get("sd", 1.0) if D0.get("status") != "unavailable" else 1.0
    er = ndi.binary_erosion(cand, fe.S26)
    yield "erode_1vox", dict(cand=er if er.sum() >= 3 else cand)
    yield "dilate_1vox", dict(cand=ndi.binary_dilation(cand, fe.S26))
    yield "threshold_+0.25", dict(img=img - 0.25 * sd, raw=None if raw is None else raw - 0.25 * sd)
    yield "threshold_-0.25", dict(img=img + 0.25 * sd, raw=None if raw is None else raw + 0.25 * sd)
    for ax in range(3):
        for d in (-1, 1):
            yield f"registration_{'xyz'[ax]}{d:+d}", dict(psd=_shift(psd, d, ax, 0), brain=_shift(brain, d, ax, 0))
            yield f"vessel_{'xyz'[ax]}{d:+d}", dict(ves=_shift(ves, d, ax, 0))


def stability(cand, img, vox, raw, ves, psd, brain, reg, crop_edge, F0, D0, scorer=None):
    """Re-extract the features under each perturbation. Returns a summary + per-perturbation rows."""
    base = dict(cand=cand, img=img, raw=raw, ves=ves, psd=psd, brain=brain)
    rows = []; core0 = D0["core"] if D0.get("status") != "unavailable" else None
    s0 = scorer(F0) if scorer else None
    for name, ch in perturbations(cand, img, raw, ves, psd, brain, D0):
        a = dict(base); a.update(ch)
        F, D = fe.extract(a["cand"], a["img"], vox, raw=a["raw"], ves=a["ves"], psd=a["psd"], brain=a["brain"], reg=reg, crop_edge=crop_edge)
        r = dict(perturbation=name)
        for k in TOL:
            v0, v = F0[k]["value"], F[k]["value"]
            r[k] = v; r[k + "_status"] = F[k]["status"]
            r[k + "_unstable"] = bool((F[k]["status"] != F0[k]["status"]) or (v0 is not None and v is not None and abs(v - v0) > TOL[k]))
        r["traverse"] = bool(F["x1_vessel_continuity_mm"]["extra"].get("traverse"))
        if core0 is not None and D.get("status") != "unavailable":
            u = core0 | D["core"]; r["core_jaccard"] = float((core0 & D["core"]).sum() / max(u.sum(), 1))
        else: r["core_jaccard"] = None
        r["F"] = {k: dict(value=F[k]["value"], status=F[k]["status"]) for k in TOL}
        if scorer: r["score"] = scorer(F)
        rows.append(r)
    S = dict(n=len(rows))
    for k in TOL:
        S[k + "_unstable_frac"] = float(np.mean([r[k + "_unstable"] for r in rows]))
        vals = [r[k] for r in rows if r[k] is not None]
        S[k + "_range"] = [float(min(vals)), float(max(vals))] if vals else None
    tr0 = bool(F0["x1_vessel_continuity_mm"]["extra"].get("traverse"))
    S["traverse_kept_frac"] = float(np.mean([r["traverse"] == tr0 for r in rows])) if tr0 else None
    x5 = [r["x5_extracranial_mm"] for r in rows if r["x5_extracranial_mm"] is not None]
    S["x5_min_mm"] = float(min(x5)) if x5 else None
    cj = [r["core_jaccard"] for r in rows if r["core_jaccard"] is not None]
    S["core_jaccard_median"] = float(np.median(cj)) if cj else None
    S["core_kept_frac"] = float(np.mean([c >= 0.5 for c in cj])) if cj else None
    if scorer and s0 is not None:
        sc = [r["score"] for r in rows if r["score"] is not None]
        S["score_range"] = [float(min(sc + [s0])), float(max(sc + [s0]))] if sc else None
    S["unstable"] = bool(any(S[k + "_unstable_frac"] > 0.25 for k in TOL) or (S["core_jaccard_median"] is not None and S["core_jaccard_median"] < 0.5)
                         or (S.get("score_range") and S["score_range"][1] - S["score_range"][0] > 0.2))
    return S, rows
