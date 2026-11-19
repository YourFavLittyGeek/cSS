"""detectors.py - independent alternative-explanation detectors (surface vein, extracranial continuation, skull interface).

Each returns: support (evidence FOR the alternative), against (evidence against it), reliability, unresolved (conditions that
prevent a decision), status in {"confirmed", "not_confirmed", "unresolved"}. "confirmed" needs EVERY support criterion, no
contrary evidence, reliable inputs and stability under perturbation. A low cSS score is never an input: these detectors do not
see the model. Confidence in an alternative is kept separate from the cSS probability. Thresholds are PROVISIONAL (set from
first principles and synthetic tests, not from patient labels)."""
import numpy as np
from scipy import ndimage as ndi
from .features import S26, pca_mm, resolved_cross_section, VOID_FRAC
from .common import DETECTOR_VERSION

VEIN_MIN_REACH_MM = 3.0; VEIN_CENTRELINE_FRAC = 0.6; SHEET_RATIO = 3.0; SHEET_MIN_EXTENT_MM = 3.0
EXTRA_MIN_MM = 5.0
SKULL_MAX_DIST_MM = 2.0; SKULL_PARALLEL_COS = 0.8; SKULL_BAND_RATIO = 3.0; SKULL_MAX_VESSEL_OVERLAP = 0.2
SKULL_OUTSIDE_CORTEX_MM = 3.0   # beyond the subarachnoid layer where cSS lies (critical failure at 1.0 on a synthetic subarachnoid cSS)


def _out(name, support, against, unresolved, reliable, decisive=False):
    """decisive: contrary evidence that settles the question whatever the unresolved inputs (e.g. no vessel contact at all)."""
    if decisive: status = "not_confirmed"
    elif unresolved: status = "unresolved"
    elif support["all_met"] and not against: status = "confirmed"
    else: status = "not_confirmed"
    return dict(detector=name, version=DETECTOR_VERSION, status=status, support=support, against=against,
                unresolved=unresolved, reliability="reliable" if reliable else "unreliable")


def _skeleton(m, vox=(1.0, 1.0, 1.0)):
    """centreline proxy = distance-transform ridge: voxels of m whose distance to the outside is a local maximum (3x3x3).
    (skimage 3-D skeletonize returned EMPTY for even-thickness tubes in this environment, so it is not used.)"""
    if not m.any(): return m
    e = ndi.distance_transform_edt(m, sampling=vox)
    return m & (e >= ndi.maximum_filter(e, size=3) - 1e-6) & (e > 0)


def sheet_components(core, vox):
    """core pieces that are sheet-compatible: planar (lambda2 / lambda3 >= 3) and >= 3 mm across in-plane."""
    lab, n = ndi.label(core, S26); out = []
    for j in range(1, n + 1):
        m = lab == j
        if m.sum() < 6: continue
        p = pca_mm(m, vox)
        if p is None: continue
        w = p[0]
        if w[1] / max(w[2], 1e-6) >= SHEET_RATIO and 2 * np.sqrt(w[1]) * 2 >= SHEET_MIN_EXTENT_MM:
            out.append(dict(voxels=int(m.sum()), ratio=round(float(w[1] / max(w[2], 1e-6)), 1)))
    return out


def vein(F, D, cand, ves, vox, stability):
    """A surface-vein explanation is confirmed only for a resolved tube on the vessel centreline that enters AND exits."""
    x1 = F["x1_vessel_continuity_mm"]; unresolved = []; against = []
    if x1["status"] == "unavailable": unresolved.append("no vessel map")
    if x1["status"] == "unreliable": unresolved += [f"x1: {r}" for r in x1["reasons"]]
    core = D.get("core") if D.get("status") not in (None, "unavailable") else None
    if core is None or core.sum() < 6: unresolved.append("no usable dark core"); core = cand
    e = x1["extra"]; reaches = e.get("reaches", [])
    traverse = bool(e.get("traverse")) and len(reaches) >= 2 and min(reaches[:2]) >= VEIN_MIN_REACH_MM
    cl_frac = 0.0
    if ves is not None and e.get("contact"):
        sk = _skeleton(ves, vox)
        near = ndi.binary_dilation(sk, S26)
        cl_frac = float((core & near).sum() / max(core.sum(), 1))
    p = pca_mm(core, vox); tube = False; res = resolved_cross_section(core, vox)
    if p is not None:
        w = p[0]; tube = bool(w[1] / max(w[2], 1e-6) <= 2.0 and np.sqrt(w[0] / max(w[1], 1e-6)) >= 2.0)
    if not res and traverse: unresolved.append("cross-section not resolved at this voxel size")
    sheets = sheet_components(D["core"], vox) if core is not cand else []
    if sheets: against.append(f"sheet-compatible component(s) present: {sheets}")
    if e.get("contact") is False: against.append("no contact with the vessel map")
    if e.get("contact") and not e.get("traverse"): against.append("touches the vessel map but does not enter AND exit")
    stab = stability.get("traverse_kept_frac") if stability else None
    if traverse:
        if stab is None: unresolved.append("perturbation stability not measured")
        elif stab < 1.0: unresolved.append(f"traverse not stable under perturbation ({stab:.2f} of perturbations)")
    decisive = x1["status"] != "unavailable" and (e.get("contact") is False or not e.get("traverse"))
    support = dict(enters_and_exits=traverse, reaches_mm=reaches[:2], centreline_overlap_frac=round(cl_frac, 2),
                   tubular_cross_section=tube, resolved=res,
                   all_met=bool(traverse and cl_frac >= VEIN_CENTRELINE_FRAC and tube and res))
    return _out("surface_vein", support, against, unresolved, x1["status"] == "reliable", decisive)


def extracranial(F, D, cand, raw, brain, vox, stability):
    x5 = F["x5_extracranial_mm"]; unresolved = []; against = []
    if x5["status"] == "unavailable": unresolved += x5["reasons"] or ["x5 unavailable"]
    elif x5["status"] == "unreliable": unresolved += [f"x5: {r}" for r in x5["reasons"]]
    v = x5["value"] or 0.0; e = x5["extra"]
    contact_core = False
    if raw is not None and brain is not None and D.get("status") != "unavailable" and D["core"].any() and v > 0:
        mu, sd = D["mu"], D["sd"]; dark = (((mu - raw) / sd >= 3) & (raw >= VOID_FRAC * mu)) | cand
        lab, _ = ndi.label(dark, S26); ids = np.unique(lab[D["core"]]); ext = np.isin(lab, ids[ids > 0]) & ~brain
        contact_core = bool(ext.any())
    stab = stability.get("x5_min_mm") if stability else None
    if stab is None and v >= EXTRA_MIN_MM: unresolved.append("perturbation stability not measured")
    elif stab < EXTRA_MIN_MM and v >= EXTRA_MIN_MM: unresolved.append(f"continuation not stable (min {stab:.1f} mm under perturbation)")
    if v < EXTRA_MIN_MM: against.append(f"continuation {v:.1f} mm < {EXTRA_MIN_MM} mm")
    if e.get("pieces", 0) > 1: against.append("extracranial part is fragmented")
    support = dict(length_mm=round(v, 2), continuous=e.get("pieces", 0) == 1, connected_to_core=contact_core,
                   all_met=bool(v >= EXTRA_MIN_MM and e.get("pieces", 0) == 1 and contact_core))
    decisive = x5["status"] == "reliable" and v < EXTRA_MIN_MM
    return _out("extracranial_continuation", support, against, unresolved, x5["status"] == "reliable", decisive)


def skull_interface(F, D, cand, raw, brain, vox, stability):
    unresolved = []; against = []
    if raw is None or brain is None: return _out("skull_interface", dict(all_met=False), [], ["no unmasked SWI / brain mask"], False)
    if D.get("status") == "unavailable" or not D["core"].any():
        return _out("skull_interface", dict(all_met=False), [], ["no usable dark core"], False)
    core = D["core"]; mu = D["mu"]; void = (raw < VOID_FRAC * mu) & ~brain
    if not void.any():
        return _out("skull_interface", dict(all_met=False, void_present=False), ["no air / bone signal void in the crop"], [], True)
    dv = ndi.distance_transform_edt(~void, sampling=vox); dmed = float(np.median(dv[core]))
    g = np.stack(np.gradient(dv, *vox), -1)[core]; nrm = np.linalg.norm(g, axis=1); ok = nrm > 1e-6
    p = pca_mm(core, vox); par = None
    if p is not None and ok.sum() >= 3:
        gu = (g[ok] / nrm[ok, None]).mean(0); gu /= np.linalg.norm(gu) + 1e-9
        par = abs(float(p[1][:, 2] @ gu))           # core plane normal vs direction to the interface
    band = bool(p is not None and p[0][1] / max(p[0][2], 1e-6) >= SKULL_BAND_RATIO and np.sqrt(p[0][0] / max(p[0][1], 1e-6)) < 2.0)
    if not band: against.append("not a broad band (tube- or line-like): a susceptibility band is planar")
    x1 = F["x1_vessel_continuity_mm"]; ov = x1["extra"].get("overlap_frac") if x1["status"] != "unavailable" else None
    if ov is None: unresolved.append("vessel map unavailable (cannot exclude a vessel)")
    elif ov > SKULL_MAX_VESSEL_OVERLAP: against.append(f"lies on the vessel map (overlap {ov:.2f})")
    x3 = F["x3_pial_distance_mm"]
    if x3["status"] != "reliable": unresolved.append(f"cortical relation not reliable ({x3['status']})")
    outside = x3["value"] is not None and x3["value"] > SKULL_OUTSIDE_CORTEX_MM
    if x3["status"] == "reliable" and not outside: against.append(f"core conforms to the cortex (pial distance {x3['value']:.2f} mm)")
    if dmed > SKULL_MAX_DIST_MM: against.append(f"core {dmed:.1f} mm from the signal void")
    if par is None: unresolved.append("band orientation undefined")
    elif par < SKULL_PARALLEL_COS: against.append(f"band not parallel to the interface (|cos| {par:.2f})")
    stab = stability.get("core_kept_frac") if stability else None
    if stab is None: unresolved.append("perturbation stability not measured")
    elif stab < 0.8: unresolved.append(f"core unstable under perturbation ({stab:.2f})")
    decisive = dmed > 2 * SKULL_MAX_DIST_MM          # far from any signal void: settles it
    support = dict(void_distance_mm=round(dmed, 2), parallel_cos=None if par is None else round(par, 2), outside_cortex=outside,
                   band_shaped=band, vessel_overlap=ov,
                   all_met=bool(dmed <= SKULL_MAX_DIST_MM and par is not None and par >= SKULL_PARALLEL_COS and outside and band
                                and ov is not None and ov <= SKULL_MAX_VESSEL_OVERLAP))
    return _out("skull_interface", support, against, unresolved, x3["status"] == "reliable", decisive)


def run_all(F, D, cand, ves, raw, brain, vox, stability):
    return [vein(F, D, cand, ves, vox, stability), extracranial(F, D, cand, raw, brain, vox, stability),
            skull_interface(F, D, cand, raw, brain, vox, stability)]
