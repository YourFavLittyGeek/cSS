"""features.py - the five primary predictors of the unified cSS score, each with an explicit reliability status.

Status of every feature: "reliable" (measured and reliable) / "unreliable" (measured, value kept, NOT to be read as evidence) /
"unavailable" (not measurable). An unreliable or unavailable feature is never negative evidence: the model gives it zero
contribution (training mean) and the decision engine treats it as missing information.

Inputs (one candidate, on a local crop of the SWI grid; nothing is written back):
  cand   bool   candidate mask (the ORIGINAL detector mask; never modified)
  img    float  SWI used by the detector (brain-masked)              - required
  raw    float  unmasked whole-head SWI on the same grid, or None   - x5, skull detector
  ves    bool   detector vessel map (work/ID_vessels), or None      - x1, vein detector
  psd    float  signed pial distance mm (- tissue, + CSF; work/ID_pial_sd), or None - x3, x4
  brain  bool   brain mask (img != 0), or None                      - x5
  vox    (3,)   voxel size mm;  reg  registration_state() string;  crop_edge  bool array True on the crop border

Definitions (mm, noise units = robust SD of the 2-5 mm background shell from core_decompose):
  x1 vessel continuity (mm, 0..2x crop margin): vessel-map components V touching the candidate zone Z = voxels within
     max(1.5 mm, 1 voxel) of the candidate. The CENTRELINE of V (distance-transform ridge) outside Z falls into pieces (revision
     during development: with the full vessel mask and a 1-voxel zone, vessel voxels running ALONGSIDE a narrower dark candidate
     joined both ends into one piece); reach(piece) = max distance (mm) of its voxels from the candidate. TRAVERSE = at least two
     pieces whose contact centroids (piece voxels within 1.5 voxels of Z) are >= 2 mm apart. x1 = sum of the two largest
     reaches of such pieces if TRAVERSE, else 0 (contact without traverse = 0). Also reported: contact, overlap_frac
     (candidate voxels in V), reaches, censored (a piece reaches the crop border).
  x2 dark-core contrast (noise units, 0..~40): median of c = (mu_b - I)/sd_b over the decomposed core; with no core the median
     over the candidate is reported with status unreliable.
  x3 distance to the brain surface (mm, about -10..+10; - = inside tissue): median psd over the core (candidate if no core).
  x4 sulcal alignment / surface conformity (0..1): n = mean unit gradient of psd over the core (candidate if no core) = local
     surface normal; principal axes from the core coordinates in mm (lambda1 >= lambda2 >= lambda3).
       elongated (lambda1/lambda2 >= 2.25):  x4 = 1 - |t . n|, t = first axis (a line running along the surface scores 1)
       else planar (lambda2/lambda3 >= 2.25): x4 = |m . n|, m = third axis = plane normal (a sheet lying in the surface /
                                              sulcal wall scores 1)
       else: direction undefined -> unreliable.  0 = crosses the surface (e.g. a transcortical vessel).
     (revision during development, synthetic-driven: the first version used only the first axis and was undefined for
     square sheets; see CHANGES_DURING_DEVELOPMENT.md)
  x5 extracranial continuation (mm, 0..crop margin): on the UNMASKED SWI, c_raw = (mu_b - raw)/sd_b; region R = connected
     component of (c_raw >= 3 and raw >= 0.15 mu_b) | candidate that contains the candidate (26-connectivity); x5 = max distance
     (mm) from the brain mask over R outside the brain. Signal voids (raw < 0.15 mu_b: air / bone) are excluded here and used by
     the skull-interface detector instead.
"""
import numpy as np
from scipy import ndimage as ndi
from . import core_decompose as cdm
from .common import FEATURE_VERSION

S26 = cdm.S26
VOID_FRAC = 0.15


def _feat(value, unit, status, reasons=(), **extra):
    return dict(value=None if value is None else float(value), unit=unit, status=status, reasons=list(reasons), extra=extra)


def pca_mm(mask, vox):
    P = np.argwhere(mask) * np.asarray(vox, float)
    if len(P) < 3: return None
    C = np.cov((P - P.mean(0)).T); w, V = np.linalg.eigh(C)
    return w[::-1].clip(0), V[:, ::-1]                       # descending eigenvalues, columns = axes


def resolved_cross_section(mask, vox):
    """True when the object spans >= 2 voxels of the coarsest axis in both minor directions (2*sqrt(lambda) as extent)."""
    p = pca_mm(mask, vox)
    if p is None: return False
    w = p[0]; return bool(2 * np.sqrt(w[1]) >= 2 * max(vox) and 2 * np.sqrt(w[2]) >= 1.0 * max(vox))


def shape_resolvable(mask, vox):
    """shape class can be determined: >= 8 voxels and the second principal axis spans >= 2 voxels of the coarsest axis.
    (Thin sheets are normal for cSS: the third axis is NOT required to be resolved.)"""
    p = pca_mm(mask, vox)
    return bool(p is not None and mask.sum() >= 8 and 2 * np.sqrt(p[0][1]) >= 2 * max(vox))


def reg_reasons(reg, strict=False):
    """strict (sulcal direction): marginal counts as unreliable."""
    bad = {"unreliable", "swi_only", "unverified"} | ({"marginal"} if strict else set())
    return [f"registration {reg}"] if reg in bad else []


def x1_vessel(cand, ves, vox, crop_edge, reg):
    if ves is None: return _feat(None, "mm", "unavailable", ["no vessel map"])
    vox = np.asarray(vox, float)
    dist = ndi.distance_transform_edt(~cand, sampling=vox)
    Z = dist <= max(1.5, float(vox.max()) * 1.01)
    lab, _ = ndi.label(ves, S26); T = np.unique(lab[Z & (lab > 0)]); T = T[T > 0]
    overlap = float((cand & ves).sum() / max(cand.sum(), 1))
    if not len(T):
        return _feat(0.0, "mm", "unreliable" if reg_reasons(reg) else "reliable", reg_reasons(reg),
                     contact=False, traverse=False, overlap_frac=overlap, reaches=[], censored=False)
    V = np.isin(lab, T)
    e = ndi.distance_transform_edt(V, sampling=vox); ridge = V & (e >= ndi.maximum_filter(e, size=3) - 1e-6)
    out = ridge & ~Z                                       # topology on the centreline ridge, not the full vessel mask
    pl, n = ndi.label(out, S26); near = ndi.binary_dilation(Z, S26, iterations=2)
    pieces = []
    for j in range(1, n + 1):
        m = pl == j; cpts = np.argwhere(m & near)
        if not len(cpts): continue
        pieces.append(dict(reach=float(dist[m].max()), ctr=cpts.mean(0) * vox, edge=bool((m & crop_edge).any())))
    pieces.sort(key=lambda p: -p["reach"])
    trav, val = False, 0.0
    for a in range(len(pieces)):
        for b in range(a + 1, len(pieces)):
            if np.linalg.norm(pieces[a]["ctr"] - pieces[b]["ctr"]) >= 2.0:
                trav, val = True, pieces[a]["reach"] + pieces[b]["reach"]; break
        if trav: break
    cens = any(p["edge"] for p in pieces[:2])
    rs = reg_reasons(reg)
    notes = ["vessel piece reaches the crop border: length is a LOWER BOUND"] if cens else []
    return _feat(val, "mm", "unreliable" if rs else "reliable", rs, notes=notes, contact=True, traverse=trav, overlap_frac=overlap,
                 reaches=[round(p["reach"], 2) for p in pieces[:4]], censored=cens)


def x2_core(D):
    if D["status"] == "unavailable": return _feat(None, "noise units", "unavailable", [D.get("reason", "")])
    if not D["core"].any():
        return _feat(float(np.median(D["c"][D["candidate"]])), "noise units", "unreliable",
                     ["no core (local peak contrast < 3 noise units)"], core_voxels=0)
    u = D["core_unstable_frac"]; rs = ["core unstable (> 50 % of core voxels unstable)"] if u is not None and u > 0.5 else []
    return _feat(float(np.median(D["c"][D["core"]])), "noise units", "unreliable" if rs else "reliable", rs,
                 core_voxels=int(D["core"].sum()), core_unstable_frac=u)


def _ref(D, cand):
    return D["core"] if D["status"] != "unavailable" and D["core"].sum() >= 3 else cand


def x3_pial(D, cand, psd, reg):
    if psd is None: return _feat(None, "mm", "unavailable", ["no pial distance map (no anatomy)"])
    ref = _ref(D, cand); v = psd[ref]; rs = reg_reasons(reg)
    return _feat(float(np.median(v)), "mm", "unreliable" if rs else "reliable", rs,
                 iqr=float(np.subtract(*np.percentile(v, [75, 25]))), on="core" if ref is not cand else "candidate")


def x4_sulcal(D, cand, psd, vox, reg):
    if psd is None: return _feat(None, "-", "unavailable", ["no pial distance map (no anatomy)"])
    ref = _ref(D, cand); p = pca_mm(ref, vox)
    if p is None: return _feat(None, "-", "unavailable", ["fewer than 3 voxels"])
    w, V = p
    g = np.stack(np.gradient(psd, *vox), -1)[ref]; nrm = np.linalg.norm(g, axis=1)
    ok = nrm > 1e-6
    if ok.sum() < 3: return _feat(None, "-", "unavailable", ["flat pial distance field"])
    gu = g[ok] / nrm[ok, None]; mean = gu.mean(0); R = float(np.linalg.norm(mean)); n = mean / (R + 1e-9)
    e12 = float(w[0] / max(w[1], 1e-9)); e23 = float(w[1] / max(w[2], 1e-9)); rs = reg_reasons(reg, strict=True)
    if e12 >= 2.25: val, mode = 1.0 - abs(float(V[:, 0] @ n)), "line"
    elif e23 >= 2.25: val, mode = abs(float(V[:, 2] @ n)), "sheet"
    else: val, mode = None, "undefined"; rs.append(f"direction undefined (axis ratios {e12:.2f}, {e23:.2f} < 2.25)")
    if R < 0.5: rs.append(f"surface direction incoherent (resultant {R:.2f} < 0.5)")
    return _feat(val, "-", "unreliable" if rs else "reliable", rs, mode=mode, axis_ratio_12=e12, axis_ratio_23=e23, normal_coherence=R)


def x5_extracranial(D, cand, raw, brain, vox, crop_edge, reg):
    if raw is None: return _feat(None, "mm", "unavailable", ["no unmasked SWI"])
    if brain is None: return _feat(None, "mm", "unavailable", ["no brain mask"])
    if D["status"] == "unavailable": return _feat(None, "mm", "unavailable", ["no background statistics"])
    mu, sd = D["mu"], D["sd"]; c = (mu - raw) / sd
    dark = ((c >= 3) & (raw >= VOID_FRAC * mu)) | cand
    lab, _ = ndi.label(dark, S26); ids = np.unique(lab[cand]); R = np.isin(lab, ids[ids > 0])
    ext = R & ~brain
    if not ext.any():
        rs = reg_reasons(reg)
        return _feat(0.0, "mm", "unreliable" if rs else "reliable", rs, ext_voxels=0, censored=False, pieces=0)
    d = ndi.distance_transform_edt(~brain, sampling=vox)
    cens = bool((ext & crop_edge).any()); rs = reg_reasons(reg)
    notes = ["extracranial part reaches the crop border: length is a LOWER BOUND"] if cens else []
    return _feat(float(d[ext].max()), "mm", "unreliable" if rs else "reliable", rs, notes=notes, ext_voxels=int(ext.sum()),
                 censored=cens, pieces=int(ndi.label(ext, S26)[1]))


def extract(cand, img, vox, raw=None, ves=None, psd=None, brain=None, reg="unverified", crop_edge=None):
    """All five predictors + the decomposition. Returns (features dict, decomposition dict). Inputs are not modified."""
    vox = np.asarray(vox, float); cand = np.array(cand, bool, copy=True)
    if crop_edge is None:
        crop_edge = np.zeros(cand.shape, bool); crop_edge[[0, -1]] = crop_edge[:, [0, -1]] = crop_edge[:, :, [0, -1]] = True
    D = cdm.decompose_experimental(cand, img, vox, valid=brain); D["_vox"] = tuple(vox)
    F = {"x1_vessel_continuity_mm": x1_vessel(cand, ves, vox, crop_edge, reg),
         "x2_core_contrast_nu": x2_core(D),
         "x3_pial_distance_mm": x3_pial(D, cand, psd, reg),
         "x4_sulcal_alignment": x4_sulcal(D, cand, psd, vox, reg),
         "x5_extracranial_mm": x5_extracranial(D, cand, raw, brain, vox, crop_edge, reg)}
    F["_meta"] = dict(feature_version=FEATURE_VERSION, decomposition=D["status"], decomposition_label=D["label"],
                      candidate_voxels=int(cand.sum()), core_voxels=int(D["core"].sum()) if "core" in D else 0,
                      core_pieces=int(ndi.label(D["core"], S26)[1]) if "core" in D else 0,
                      core_unstable_frac=D.get("core_unstable_frac"), registration=reg,
                      shape_resolvable=bool(D.get("status") == "ok" and shape_resolvable(D["core"], vox)))
    return F, D


FEATURE_SPEC = {
    "x1_vessel_continuity_mm": dict(unit="mm", range="0 .. 2 x crop margin", inputs="candidate, vessel map",
        reliable_if="vessel map present; registration ok/marginal (map is restricted by labels); censoring at the crop border is noted (lower bound)",
        missing="unavailable without a vessel map", failure_modes="vessel map is a Hessian product (tubes only) and misses flat veins; "
        "a cSS lying next to a vein reads as contact; gaps in the map break continuity"),
    "x2_core_contrast_nu": dict(unit="noise units", range="0 .. ~40", inputs="candidate, SWI",
        reliable_if="decomposition available, a core exists, <= 50 % of core voxels unstable",
        missing="unavailable if the 2-5 mm shell has < 20 voxels", failure_modes="shell mixes tissues on real SWI (sigma inflated); "
        "low-contrast deposits (< ~5 noise units) lose core voxels; per-voxel noise fragments the core"),
    "x3_pial_distance_mm": dict(unit="mm (- tissue, + CSF)", range="-10 .. +10", inputs="core/candidate, pial distance map",
        reliable_if="T1 anatomy and label shift <= 1.0 mm", missing="unavailable without anatomy",
        failure_modes="a 3-4 mm shift gives 1.3-2.4 mm median error (synthetic test); SWI-only anatomy is coarse"),
    "x4_sulcal_alignment": dict(unit="0..1", range="0 (crosses the surface) .. 1 (runs along it)", inputs="core/candidate, pial distance map",
        reliable_if="T1 anatomy, label shift <= 0.5 mm, line or sheet shape (axis ratio >= 2.25), normal coherence >= 0.5", missing="unavailable without anatomy",
        failure_modes="surface veins running along a sulcus also score 1; direction errors 13-48 deg at 3-4 mm shift"),
    "x5_extracranial_mm": dict(unit="mm", range="0 .. crop margin", inputs="candidate, unmasked SWI, brain mask",
        reliable_if="unmasked SWI on the same grid; registration ok/marginal (mask from labels); censoring noted (lower bound)",
        missing="unavailable without the unmasked SWI", failure_modes="dark scalp / diploic veins next to the brain read as continuation; "
        "the brain-mask boundary moves with registration; continuation ACROSS a signal void (bone) is not followed - only "
        "continuation through non-void tissue is measured; blooming / noise at the end adds ~1-1.5 mm (unit test)"),
}
