"""train_demo.py - trains the SYNTHETIC demonstration model shipped with the engine. Synthetic data only (generator seed fixed).
The model card records the patient-grouped CV results of the SAME procedure on the training cohort (synthetic; not a clinical estimate)
and the decision-rule caveat (incremental value needs the permutation test, not the bootstrap CI)."""
import datetime
from . import ENGINE_VERSION, ablation as ab, experiment as ex, synthetic as sy, registry
from .prototype.fusion import UnifiedScorer


def train(out_path, seed=500, n_patients=60, n_boot=30):
    O, E, P = sy.make_cohort(n_patients, seed=seed, signal=1.0); D = ex.population(O); y = D.y.to_numpy(float)
    cv = ab.run_scenario("baseline", seed, n_repeats=1, B=200, n_patients=n_patients)      # same generator + seed: CV of the procedure
    keep = ("within", "within_ci", "fold_auc_mean", "pooled", "ap", "logloss", "brier", "cal_slope", "cal_citl", "ece", "sensitivity",
            "specificity", "delta_vs_math", "delta_vs_math_ci")
    u = UnifiedScorer("offset", n_boot=n_boot, seed=seed).fit(D, y, data_kind="synthetic")
    card = dict(name="synthetic_demo_offset", version="1.0.0", created=datetime.datetime.now().isoformat(timespec="seconds"), data_kind="synthetic",
                engine=ENGINE_VERSION, fusion="offset: p = sigmoid(MATH logit + learned increment)",
                training=dict(generator="uengine.synthetic.make_cohort", seed=seed, n_patients=n_patients, n_candidates=int(len(D)), n_cSS=int(y.sum()),
                              population="measurement-complete labelled objects (shown + audited excluded)", n_boot=n_boot),
                intended_use="software testing and GUI demonstration on SYN studies ONLY. Never applied to a real study (the engine refuses).",
                synthetic_cv={k: {kk: cv["models"][k].get(kk) for kk in keep} for k in ("math_only", "offset", "naive", "learned_only")},
                caveats=["synthetic generator decides every number; no clinical meaning",
                         "incremental value over MATH must be tested by within-patient permutation, not by the bootstrap CI (false positives on noise)",
                         "categories are reading aids; nothing is excluded or suppressed"])
    return registry.save_with_card(u, out_path, card)
