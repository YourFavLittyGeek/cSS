"""Reproduction (SYNTHETIC) of a pooled AUC far below 0.5 on pure noise, with the ORIGINAL uscore nested LOPO, and its explanation"""
import unittest
import numpy as np
import _common  # noqa: F401
from uengine import auc_investigation as ai, model_evaluation as ev

SEEDS = range(8)


def collect(fn, **kw):
    out = []
    for sd in SEEDS:
        X, y, pid = ai.simulate(10, seed=sd, **kw); out.append(fn(X, y, pid))
    return out


class TestAUCInvestigation(unittest.TestCase):
    def test_original_uscore_pure_noise_varying_prevalence(self):
        def f(X, y, pid):
            p = ai.original_uscore_nested_lopo(X, y, pid); ok = np.isfinite(p); return ev.auc_decomposition(y[ok], p[ok], pid[ok])
        D = collect(f, prevalence="beta", signal=0.0)
        pooled = np.mean([d["pooled"] for d in D]); within = np.mean([d["within"] for d in D]); between = np.mean([d["between"] for d in D])
        print(f"\n   original uscore, pure noise, varying prevalence: pooled {pooled:.3f}, within {within:.3f}, between {between:.3f}")
        self.assertLess(pooled, 0.36)                  # reproduces the ~0.30 phenomenon
        self.assertLess(abs(within - 0.5), 0.08)       # no within-patient discrimination (there is none to find)
        self.assertLess(between, pooled + 1e-9)        # the depression sits in the between-patient pairs

    def test_mechanism_needs_no_features(self):
        D = collect(lambda X, y, pid: ev.auc_decomposition(y, ai.intercept_only_lopo(y, pid), pid), prevalence="beta")
        self.assertLess(np.mean([d["pooled"] for d in D]), 0.36)
        for d in D: self.assertTrue(np.isnan(d["within"]) or abs(d["within"] - 0.5) < 1e-12)   # a constant per patient: within = 0.5 exactly

    def test_equal_prevalence_much_smaller_effect(self):
        def f(X, y, pid):
            p = ai.original_uscore_nested_lopo(X, y, pid); ok = np.isfinite(p); return ev.auc_decomposition(y[ok], p[ok], pid[ok])["pooled"]
        v = np.mean(collect(f, prevalence="equal")); vb = np.mean(collect(f, prevalence="beta"))
        self.assertGreater(v, vb + 0.08)

    def test_patient_grouped_fold_wise_and_within_are_unbiased_on_noise(self):
        def f(X, y, pid):
            s, fo = ai.new_framework_cv(X, y, pid, n_splits=5, seed=0); ok = np.isfinite(s)
            return ai.fold_wise_auc(y[ok], s[ok], fo[ok])[0], ev.auc_decomposition(y[ok], s[ok], pid[ok])["within"]
        R = np.array(collect(f, prevalence="beta"))
        self.assertLess(abs(np.nanmean(R[:, 0]) - 0.5), 0.1); self.assertLess(abs(np.nanmean(R[:, 1]) - 0.5), 0.08)

    def test_genuine_signal_is_seen_within_patients(self):
        def f(X, y, pid):
            p = ai.original_uscore_nested_lopo(X, y, pid); ok = np.isfinite(p); return ev.auc_decomposition(y[ok], p[ok], pid[ok])
        D = collect(f, prevalence="beta", signal=1.0)
        self.assertGreater(np.mean([d["within"] for d in D]), 0.70)
        self.assertLess(np.mean([d["pooled"] for d in D]), np.mean([d["within"] for d in D]))   # pooling still drags it down

    def test_between_patient_confounder_is_not_discrimination(self):
        D = []
        for sd in SEEDS:
            X, y, pid = ai.simulate(30, seed=sd, prevalence="beta", confounder=1.5)
            D.append(ev.auc_decomposition(y, X[:, 1], pid))           # the confounded feature used as a fixed score (no fitting)
        self.assertGreater(np.mean([d["between"] for d in D]), 0.58)
        self.assertLess(abs(np.mean([d["within"] for d in D]) - 0.5), 0.05)


if __name__ == "__main__":
    unittest.main()
