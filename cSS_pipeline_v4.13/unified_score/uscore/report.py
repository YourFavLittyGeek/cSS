"""report.py - cohort-level markdown report from development_report.json, candidates.json (and heldout_report.json if present).
Development (nested LOPO, out-of-fold) and independent held-out estimates are kept in separate, labelled sections."""
import os, json, collections
import numpy as np
from .common import PREDICTORS


def _f(v, n=2):
    return "–" if v is None else (f"{v:.{n}f}" if isinstance(v, float) else str(v))


def cohort_report(out):
    D = json.load(open(f"{out}/development_report.json")); C = json.load(open(f"{out}/reports/candidates.json"))
    M = json.load(open(f"{out}/model_frozen.json")); HO = json.load(open(f"{out}/heldout_report.json")) if os.path.exists(f"{out}/heldout_report.json") else None
    L = []; a = L.append
    syn = M.get("synthetic_test")
    a("# Unified cSS score: cohort report" + (" — SYNTHETIC TEST (not a result)" if syn else ""))
    a(f"\nModel `{M['model_version']}` hash `{M['model_hash'][:16]}`; predictors {', '.join(M['predictors'])}; ridge lambda {M['lam']:.3g}; "
      f"effective df {M['edf']:.2f}. Probability output: **{'yes' if M['probability_output'] else 'NO (raw score + feature profile only)'}**. "
      "EXPERIMENTAL research output; not a diagnosis.\n")
    a(f"## 1. Development estimates (nested leave-one-patient-out, out-of-fold; {', '.join(M['train_studies'])})\n")
    if D.get("penalty_at_grid_boundary"): a("- **WARNING: the chosen penalty is at the edge of the search grid in some folds** (near-separable data: probabilities saturate)")
    a(f"- candidates {D['n_candidates']} ({D['n_cSS']} cSS) from {D['n_patients']} patients; fallback: {D['fallback_log'] or 'none'}")
    a(f"- discrimination: AUC {_f(D['outer_auc_calibrated'])} (patient-bootstrap 95 % CI {D['outer_auc_ci']}); raw-score AUC {_f(D['outer_auc_raw'])}")
    a(f"- calibration: slope {_f(D['calibration_slope'])}, intercept {_f(D['calibration_intercept'])}; Brier {_f(D['outer_brier'], 3)} (CI {D['outer_brier_ci']})")
    a("- reliability bins (mean predicted vs observed): " + "; ".join(f"{b['p_mean']:.2f}→{b['observed']:.2f} (n {b['n']})" for b in D["reliability_bins"]))
    if "candidate_sensitivity" in D:
        a(f"- at the ordering cut {_f(D['ordering_cut'])} (prioritisation only): candidate sensitivity {_f(D['candidate_sensitivity'])}, "
          f"specificity {_f(D['candidate_specificity'])}, FP per patient {_f(D['fp_per_patient'])}, patient sensitivity {_f(D['patient_sensitivity'])} "
          f"({D['cSS_positive_patients']} cSS-positive patients)")
    a(f"- v5.10 confidence_pct on the same candidates: AUC {_f(D['v510_auc_same_candidates'])} — {D['v510_note']}")
    a("\n### Coefficient stability across outer folds (standardised)\n")
    st = D["coefficient_stability"]
    a("| predictor | mean | SD | sign agreement |\n|---|---|---|---|")
    for k in M["predictors"]:
        a(f"| {k} | {_f(st['coef_mean'][k])} | {_f(st['coef_sd'][k])} | {_f(st['sign_agreement'][k])} |")
    a(f"\nPenalty per fold: {[round(x, 3) for x in st['lam']]}; effective df per fold: {[round(x, 2) for x in st['edf']]}")
    a("\n### Feature missingness (development candidates)\n")
    a("| predictor | reliable | unreliable | unavailable |\n|---|---|---|---|")
    for k, v in D["feature_missingness"].items(): a(f"| {k} | {v['reliable']:.2f} | {v['unreliable']:.2f} | {v['unavailable']:.2f} |")
    oof = D.get("oof", [])
    if oof:
        cut = D["ordering_cut"]; key = "p_cal" if M["probability_output"] else "p_raw"
        fps = sorted([o for o in oof if o["y"] == 0 and cut is not None and o[key] >= cut], key=lambda o: -o[key])[:10]
        fns = sorted([o for o in oof if o["y"] == 1 and cut is not None and o[key] < cut], key=lambda o: o[key])[:10]
        byc = {(c["study"], c["cand_id"]): c for c in C}
        def prof(o):
            c = byc.get((o["study"], o["cand_id"]))
            return "" if c is None else ", ".join(f"{k.split('_')[0]}={_f(c['predictors'][k]['value'])}{'' if c['predictors'][k]['status'] == 'reliable' else '*'}" for k in PREDICTORS)
        a("\n### False positives / false negatives at the ordering cut (out-of-fold; * = not reliable)\n")
        for nm, lst in (("FP", fps), ("FN", fns)):
            for o in lst: a(f"- {nm} {o['study']} #{o['cand_id']} p {o[key]:.2f}: {prof(o)}")
    a("\n## 2. Candidate categories (all included studies scored by the frozen model)\n")
    roles = collections.defaultdict(collections.Counter)
    for c in C: roles["development" if c["study"] in M["train_studies"] else "held-out"][c["category"]] += 1
    for r, cnt in roles.items(): a(f"- {r}: {dict(cnt)}")
    fl = collections.Counter(f for c in C for f in c["protective_flags"])
    a("- protective conditions: " + "; ".join(f"{k} ({v})" for k, v in fl.most_common()))
    unst = [c for c in C if c["stability"] and c["stability"].get("unstable")]
    a(f"- perturbation-unstable candidates: {len(unst)} / {len(C)}")
    by = collections.defaultdict(list)
    for c in C: by[c["registration"]].append(c["category"])
    a("- categories by registration state: " + "; ".join(f"{k}: {dict(collections.Counter(v))}" for k, v in by.items()))
    a("\n## 3. Independent held-out results (frozen model)\n")
    if HO is None: a("**Not run.** Held-out labels have not been opened. This needs the user's approval and the frozen model hash.")
    else:
        a(f"- {HO['estimate_type']}: n {HO['n']} ({HO['n_cSS']} cSS, {HO['patients']} patients); AUC {_f(HO['auc'])} (CI {HO['auc_ci']}); "
          f"Brier {_f(HO['brier'], 3)}; calibration slope {_f(HO.get('calibration_slope'))}")
        if "candidate_sensitivity" in HO:
            a(f"- at the frozen ordering cut: sensitivity {_f(HO['candidate_sensitivity'])}, specificity {_f(HO['candidate_specificity'])}, "
              f"patient sensitivity {_f(HO['patient_sensitivity'])}")
    open(f"{out}/COHORT_REPORT.md", "w").write("\n".join(L))
    return f"{out}/COHORT_REPORT.md"
