"""Experimental evidence fusion (CSS_EXPERIMENTAL_FUSION=1). Recorded only: a CATEGORY with its reasons, never a
probability, never an exclusion, never a change of rank. Rules are fixed in advance from the definition of cSS and
of its mimics (not fitted to any patient data); every threshold is PROVISIONAL.

Signals (each True / False / None = not available):
  plate      : hf_plate_minus_tube >= 0.2 and tube_ratio_signed_med < 0.40         (sheet-like)
  tube       : hf_plate_minus_tube <= -0.2 or tube_ratio_signed_med >= 0.55       (tube-like)
  blob       : hf_blob_frac >= 0.30                                                 (round, microbleed-like)
  surface    : sc_subpial_frac >= 0.6 and sc_csf_frac < 0.3                         (on the cortical surface)
  in_csf     : sc_depth_med > +0.5 mm                                               (out in the sulcal CSF)
  continues  : vg_evidence == 'vascular_continuation'
  focal      : sr_contrast_z <= -2 and sr_ref_dark_frac < 0.3                       (darker than same-depth neighbours)
  shared     : sr_ref_dark_frac >= 0.3                                              (darkness shared by the neighbours)
  split_mixed: dec_mixed_object                                                     (plate AND tube components)
Categories (first match wins, order fixed):
  not_evaluable        fewer than 3 of {shape, surface, reference} available
  mixed                split_mixed, or (plate|surface-supported) AND (tube & continues)
  vessel_supporting    tube and (continues or in_csf);  OR in_csf and continues (amendment 1, below)
  microbleed_like      blob and not surface
  normal_dark_cortex   shared and not focal
  css_supporting       plate and surface and focal and not continues
  indeterminate        anything else (incl. 'no detectable connection' alone - it is not cSS evidence)"""
import numpy as np

CATEGORIES = ("css_supporting", "vessel_supporting", "microbleed_like", "normal_dark_cortex", "mixed", "indeterminate", "not_evaluable")

def _get(r, k):
    v = r.get(k, None)
    if v is None: return None
    try:
        if isinstance(v, (bool, np.bool_)): return bool(v)
        if isinstance(v, str): return v
        return None if not np.isfinite(float(v)) else float(v)
    except (TypeError, ValueError): return None

def signals(r):
    g = lambda k: _get(r, k)
    pmt, ts, bf = g("hf_plate_minus_tube"), g("tube_ratio_signed_med"), g("hf_blob_frac")
    s = {}
    s["plate"] = None if pmt is None or ts is None else (pmt >= 0.2 and ts < 0.40)
    s["tube"] = None if pmt is None and ts is None else ((pmt is not None and pmt <= -0.2) or (ts is not None and ts >= 0.55))
    s["blob"] = None if bf is None else bf >= 0.30
    sp, cf, dm = g("sc_subpial_frac"), g("sc_csf_frac"), g("sc_depth_med")
    s["surface"] = None if sp is None or cf is None else (sp >= 0.6 and cf < 0.3)
    s["in_csf"] = None if dm is None else dm > 0.5
    ve = g("vg_evidence"); s["continues"] = None if ve is None else ve == "vascular_continuation"
    cz, df, ok = g("sr_contrast_z"), g("sr_ref_dark_frac"), g("sr_ref_valid")
    valid = ok is not False and cz is not None and df is not None
    s["focal"] = (cz <= -2 and df < 0.3) if valid else None
    s["shared"] = (df >= 0.3) if valid else None
    dm2 = g("dec_mixed_object"); s["split_mixed"] = None if dm2 is None else bool(dm2)
    return s

def categorise(r):
    s = signals(r); T = lambda k: s.get(k) is True
    avail = sum(x is not None for x in (s["plate"], s["surface"], s["focal"]))
    why = ";".join(f"{k}={'NA' if v is None else int(v)}" for k, v in s.items())
    if avail < 3 and not (s["plate"] is not None and s["surface"] is not None): return "not_evaluable", why
    if T("split_mixed") or ((T("plate") or T("surface")) and T("tube") and T("continues")): return "mixed", why
    if T("tube") and (T("continues") or T("in_csf")): return "vessel_supporting", why
    if T("in_csf") and T("continues"): return "vessel_supporting", why      # amendment 1 (PH6 phantom): surface veins whose
    # median voxel lies > 0.5 mm out in CSF and that continue >= 6 mm read plate-like to the Hessian (pressed against the
    # cortex, blooming); position + continuation is the vessel evidence then. Decided on a phantom, not on patient data.
    if T("blob") and not T("surface"): return "microbleed_like", why
    if T("shared") and not T("focal"): return "normal_dark_cortex", why
    if T("plate") and T("surface") and T("focal") and not T("continues"): return "css_supporting", why
    return "indeterminate", why
