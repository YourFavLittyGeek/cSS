"""albus_detection.py - ALBUS · Mathematical Detection: the controlled improvement framework over the REAL detector (scripts/detect_css.py).

ALBUS owns candidate generation, rules E1-E30 and score_v4. This module never runs or changes the detector; it measures a detector VERSION
(review/ID_manifest.json: build + rule set + parameter hash) against eligible expert ground truth and records approved versions:

  evaluate()   per detector version, over the studies it produced:
                 detected cSS      candidates resolved cSS by eligible expert consensus (Phase 3A rules)
                 missed cSS        eligible expert missed-lesion marks (reviewer or whole-study search) = candidate-generation misses
                 sensitivity       detected / (detected + missed), Wilson 95 % CI - recall of the lesions experts FOUND (it cannot count
                                   lesions nobody found: studies with a completed whole-study search are reported so the denominator is
                                   honest)
                 false positives   candidates resolved not-cSS per study (FP burden), unreviewed candidates per study
  compare()    a new detector version against the previous one on the SAME studies: sensitivity is the non-negotiable criterion - a version
               that loses an eligible cSS the previous version detected, or whose sensitivity is lower, is rejected whatever its FP gain.
  propose_and_approve()  records an approved detector version in the component registry (person + phrase + reason); rollback is the
               registry's. Re-running the detector with the approved settings stays a deliberate, separate step (redetect.py)."""
import json
import os
import sys

FP_KEYS = ("vox_i", "vox_j", "vox_k", "volume_mm3")


def _scripts():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
    if os.path.isdir(d) and d not in sys.path: sys.path.insert(0, d)


def _wilson(k, n, z=1.96):
    if not n: return None
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def study_evidence(base, sid):
    """one study's detection evidence from the authoritative records (call ledger + missed marks + journals)"""
    _scripts()
    import glob
    import pandas as pd
    import call_ledger as CL
    import review_io as RIO
    import review_roles as RR
    from uengine.percival.architecture import detector_version
    dv = detector_version(base, sid); E = CL.effective(base, sid); roles = RR.current(base)
    det, fps, unrev = [], [], 0
    cand = pd.read_csv(os.path.join(base, "review", f"{sid}_candidates.csv"))
    fpr = {int(r.cand_id): tuple(float(getattr(r, k)) for k in FP_KEYS if hasattr(r, k)) for r in cand.itertuples()}
    for row in E.get("rows", []):
        cls = CL.call_class(row.get("effective_call") or "")
        if row.get("status") == "resolved" and row.get("primary_eligible"):
            (det if cls == "positive" else fps if cls == "negative" else []).append(dict(cand_id=int(row["cand_id"]), fingerprint=fpr.get(int(row["cand_id"]))))
        elif row.get("status") in ("missing", "no_expert", "pending_review"): unrev += 1
    missed = []
    mp = os.path.join(base, "review", f"{sid}_missed.csv")
    if os.path.exists(mp):
        verified = RR.verified_reviewers(base, sid)
        for mr in pd.read_csv(mp, dtype=str).fillna("").to_dict("records"):
            rev = mr.get("reviewer", ""); klass = ("verified_blind_post_3A" if mr.get("read_phase") == "initial" and mr.get("ai_visible") == "False" else
                                                   "not_blind_post_3A" if mr.get("read_phase") else
                                                   "historical_blinding_verified" if CL.slug(rev) in verified else "historical_blinding_unknown")
            if RR.role_of(base, rev, roles) == "expert" and klass in CL.PRIMARY_ELIGIBLE:
                missed.append(dict(missed_id=mr.get("missed_id"), detector_fate=mr.get("detector_fate", ""), context=mr.get("context", "")))
    ws = 0
    for jp in glob.glob(os.path.join(base, "review", f"{sid}_events_*.jsonl")):
        ev, _ = RIO.read_journal(jp)
        if any(e.get("kind") == "whole_study_completed" and RR.role_of(base, e.get("reviewer", ""), roles) == "expert" for e in ev): ws += 1
    return dict(study=sid, detector_version=dv.get("version"), detected_css=det, false_positives=fps, missed_css=missed, unreviewed=unrev,
                n_candidates=int(len(cand)), whole_study_searches=ws)


def evaluate(base, studies):
    """-> {detector_version: metrics} over the given studies (eligible expert ground truth only)"""
    out = {}
    for sid in studies:
        try: ev = study_evidence(base, sid)
        except Exception as e:
            out.setdefault("unreadable", dict(studies=[]))["studies"].append(f"{sid}: {type(e).__name__}"); continue
        v = ev["detector_version"] or "albus:unversioned"
        M = out.setdefault(v, dict(studies=[], detected=0, missed=0, false_positives=0, unreviewed=0, candidates=0, whole_study_searched=0, per_study={}))
        M["studies"].append(sid); M["detected"] += len(ev["detected_css"]); M["missed"] += len(ev["missed_css"]); M["false_positives"] += len(ev["false_positives"])
        M["unreviewed"] += ev["unreviewed"]; M["candidates"] += ev["n_candidates"]; M["whole_study_searched"] += int(ev["whole_study_searches"] > 0)
        M["per_study"][sid] = ev
    for v, M in out.items():
        if v == "unreadable": continue
        n = M["detected"] + M["missed"]; s = len(M["studies"])
        M.update(sensitivity=None if not n else round(M["detected"] / n, 3), sensitivity_ci=_wilson(M["detected"], n), expert_found_lesions=n,
                 fp_per_study=round(M["false_positives"] / s, 2) if s else None, candidates_per_study=round(M["candidates"] / s, 1) if s else None,
                 note=("sensitivity = detected / (detected + expert-marked missed) among lesions experts found; "
                       f"{M['whole_study_searched']} of {s} studies had a completed whole-study search"))
    return out


def compare(prev, new, studies_prev=None, studies_new=None):
    """non-inferiority on sensitivity first, then FP burden. prev/new: evaluate() entries of two detector versions on the same studies"""
    reasons = []
    if not prev or not new: return dict(verdict="not_comparable", reasons=["both versions need an evaluation on the same studies"])
    if set(prev["studies"]) != set(new["studies"]): reasons.append("evaluated on different studies - compare on the same studies")
    if prev.get("sensitivity") is not None and new.get("sensitivity") is not None and new["sensitivity"] < prev["sensitivity"]:
        reasons.append(f"sensitivity lower ({new['sensitivity']} < {prev['sensitivity']}) - rejected whatever the false-positive gain")
    if new["missed"] > prev["missed"]: reasons.append(f"more expert-marked missed lesions ({new['missed']} > {prev['missed']})")
    if new["detected"] < prev["detected"]: reasons.append(f"fewer eligible cSS detected ({new['detected']} < {prev['detected']})")
    fp_gain = None if prev.get("fp_per_study") is None or new.get("fp_per_study") is None else round(prev["fp_per_study"] - new["fp_per_study"], 2)
    verdict = "rejected" if reasons else ("improved" if (fp_gain or 0) > 0 else "non_inferior")
    return dict(verdict=verdict, reasons=reasons, fp_per_study_reduction=fp_gain, sensitivity=(prev.get("sensitivity"), new.get("sensitivity")),
                rule="sensitivity (and every eligible detected cSS) must be preserved; only then is a lower FP burden an improvement")


def propose_and_approve(store, detector_version, comparison, by, reason, confirm, override=False, synthetic=False):
    """record an approved ALBUS detector version; refused when the comparison rejected it (unless override with a reason)"""
    from uengine.percival import component_registry as CR
    if (comparison or {}).get("verdict") not in ("improved", "non_inferior") and not override:
        raise CR.RegistryError(f"refused: detector comparison verdict '{(comparison or {}).get('verdict')}' ({'; '.join((comparison or {}).get('reasons', []))})")
    return CR.approve(store, "ALBUS", dict(detector_version=detector_version), by, reason, confirm,
                      evidence=dict(comparison=comparison, override=bool(override)), synthetic=synthetic)
