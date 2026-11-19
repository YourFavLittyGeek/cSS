"""decision.py - candidate-level decision engine. Every candidate is preserved; the outcome is a reading category.

Categories:
  css_compatible             cSS score at or above the ordering cut, dark core and surface relation measured reliably, no
                             confirmed alternative explanation.
  uncertain                  everything else (insufficient, conflicting, unreliable or unstable evidence).
  alternative_high_confidence   an alternative detector is CONFIRMED and no protective condition holds.
A low cSS score alone never leads to alternative_high_confidence: that category needs a confirmed detector.

Suppression: implemented (record, audit log, restore) but DISABLED. propose_suppression() always returns action
"not_applied" while SUPPRESSION_ENABLED is False; there is no configuration switch in this stage."""
import os, json, datetime
from .common import DECISION_VERSION, SUPPRESSION_ENABLED, PREDICTORS


def protective_flags(F, D, detectors, stab, reg, cand_row=None):
    fl = []
    m = F["_meta"]
    if m["core_voxels"] < 8 or not D.get("status") == "ok": fl.append("morphology unresolved (no usable core)")
    elif not m.get("shape_resolvable", True): fl.append("morphology unresolved (shape below resolution)")
    if reg != "ok": fl.append(f"registration not adequate ({reg})")
    if stab is None: fl.append("perturbation stability not measured")
    elif stab.get("unstable"): fl.append("unstable under perturbation")
    vein = next(d for d in detectors if d["detector"] == "surface_vein")
    if vein["support"].get("enters_and_exits") and any("sheet-compatible" in a for a in vein["against"]): fl.append("mixed vessel / sheet object")
    if (m.get("core_unstable_frac") or 0) > 0.5: fl.append("dark-core decomposition unstable")
    for d in detectors:
        if d["status"] == "unresolved": fl.append(f"{d['detector']}: inputs unavailable or unresolved")
    if cand_row is not None:
        try:
            if float(cand_row.get("infra_frac", 0) or 0) >= 0.3 or str(cand_row.get("infratentorial", "")).lower() in ("1", "true"):
                fl.append("out of scope: infratentorial superficial siderosis pattern")
            if str(cand_row.get("near_ich_suggest", "")).lower() in ("1", "true"): fl.append("out of scope: near lobar ICH")
        except Exception: pass
    return fl


def categorise(F, flags, detectors, p, cut):
    conf = [d["detector"] for d in detectors if d["status"] == "confirmed"]; why = []
    if conf and not flags:
        cat = "alternative_high_confidence"; why.append(f"confirmed alternative: {', '.join(conf)}; no protective condition")
    elif conf:
        cat = "uncertain"; why.append(f"alternative suspected ({', '.join(conf)}) but protected: {'; '.join(flags)}")
    elif p is not None and cut is not None and p >= cut - 1e-9 and F["x2_core_contrast_nu"]["status"] == "reliable" \
            and F["x3_pial_distance_mm"]["status"] == "reliable":
        cat = "css_compatible"; why.append(f"score {p:.2f} >= ordering cut {cut:.2f}; core and surface relation reliable; no confirmed alternative")
    else:
        cat = "uncertain"
        if p is None: why.append("no statistically justified score")
        elif cut is not None and p < cut - 1e-9: why.append(f"score {p:.2f} below ordering cut {cut:.2f} (not evidence of an alternative)")
        for k in ("x2_core_contrast_nu", "x3_pial_distance_mm"):
            if F[k]["status"] != "reliable": why.append(f"{k} {F[k]['status']}")
    return dict(category=cat, reasons=why, protective_flags=list(flags), confirmed_alternatives=conf, decision_version=DECISION_VERSION)


def decide(F, D, detectors, stab, reg, p, cut, cand_row=None):
    return categorise(F, protective_flags(F, D, detectors, stab, reg, cand_row), detectors, p, cut)


def propose_suppression(study, cand_id, decision, p, detectors, F, model_hash, input_hash, log_path):
    """Writes an auditable record for a candidate that WOULD qualify for suppression. Never suppresses in this stage."""
    if decision["category"] != "alternative_high_confidence": return None
    rec = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), study=study, cand_id=int(cand_id),
               action="applied" if SUPPRESSION_ENABLED else "not_applied (suppression disabled)", model_hash=model_hash,
               decision_version=DECISION_VERSION, score=p, alternative=[d for d in detectors if d["status"] == "confirmed"],
               rationale=decision["reasons"], feature_reliability={k: F[k]["status"] for k in PREDICTORS}, input_hash=input_hash)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    return rec


def suppressed_view(log_path):
    """All suppression records (recoverable audit view)."""
    if not os.path.exists(log_path): return []
    return [json.loads(l) for l in open(log_path) if l.strip()]


def restore(log_path, study, cand_id):
    """Marks a record restored (append-only). With suppression disabled nothing was hidden; kept for the audit contract."""
    rec = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), study=study, cand_id=int(cand_id), action="restored")
    with open(log_path, "a") as f: f.write(json.dumps(rec) + "\n")
    return rec
