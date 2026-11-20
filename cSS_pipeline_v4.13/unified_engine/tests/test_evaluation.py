import unittest
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import model_evaluation as ev, calibration as cal, patient_split as ps, ml_component as ml


def brute_auc(y, s):
    p, n = s[y == 1], s[y == 0]; return np.mean([(a > b) + 0.5 * (a == b) for a in p for b in n])


class TestMetrics(unittest.TestCase):
    def setUp(self):
        r = np.random.default_rng(0); self.pid = np.repeat([f"SYN{i}" for i in range(8)], 15)
        self.y = (r.random(120) < np.repeat(r.uniform(.1, .7, 8), 15)).astype(int); self.s = np.round(r.normal(size=120) + self.y * .8, 1)

    def test_auc_and_ap(self):
        self.assertAlmostEqual(ev.auc(self.y, self.s), brute_auc(self.y, self.s))
        o = np.argsort(-self.s, kind="stable"); yy = self.y[o]; prec = np.cumsum(yy) / np.arange(1, len(yy) + 1)
        self.assertAlmostEqual(ev.average_precision(self.y, self.s), prec[yy == 1].mean())

    def test_decomposition_identity(self):
        d = ev.auc_decomposition(self.y, self.s, self.pid)
        self.assertAlmostEqual(d["pooled"], ev.auc(self.y, self.s))
        self.assertAlmostEqual(d["pooled"], d["within_share"] * d["within"] + (1 - d["within_share"]) * d["between"])
        num = den = 0
        for q in set(self.pid):
            m = self.pid == q; p, n = self.s[m & (self.y == 1)], self.s[m & (self.y == 0)]
            num += sum((a > b) + .5 * (a == b) for a in p for b in n); den += len(p) * len(n)
        self.assertAlmostEqual(d["within"], num / den)

    def test_confusion_and_threshold(self):
        t = ev.threshold_for_sensitivity(self.y, self.s, 0.9); c = ev.confusion(self.y, self.s, t)
        self.assertGreaterEqual(c["sensitivity"], 0.9); self.assertEqual(c["tp"] + c["fn"], self.y.sum())

    def test_bootstrap_resamples_patients(self):
        ci = ev.cluster_bootstrap(lambda a, b, c: ev.auc(a, b), self.y, self.s, self.pid, B=300)
        self.assertLess(ci[0], ev.auc(self.y, self.s)); self.assertGreater(ci[1], ev.auc(self.y, self.s))

    def test_kappa(self):
        self.assertAlmostEqual(ev.quadratic_weighted_kappa([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]), 1.0)
        self.assertLess(ev.quadratic_weighted_kappa([0, 0, 4, 4], [4, 4, 0, 0]), 0)

    def test_calibration(self):
        r = np.random.default_rng(1); p = r.uniform(.02, .98, 4000); y = (r.random(4000) < p).astype(float)
        c = cal.calibration_slope_intercept(y, p); self.assertAlmostEqual(c["slope"], 1, delta=.1); self.assertAlmostEqual(c["citl"], 0, delta=.1)
        lp = np.log(p / (1 - p)); c2 = cal.calibration_slope_intercept(y, ml.sigmoid(2 * lp)); self.assertLess(c2["slope"], 0.6)
        self.assertIsNone(cal.calibration_slope_intercept(y[:10], p[:10])["slope"])
        bins, ece = cal.reliability(y, p); self.assertLess(ece, 0.05); self.assertEqual(sum(b["n"] for b in bins), 4000)

    def test_cross_validate_identical_folds_and_training_thresholds(self):
        df = pd.DataFrame(dict(a=self.s, b=np.random.default_rng(2).normal(size=120)))
        a = ps.grouped_folds(self.pid, 4, 2, 0)
        class M:
            def fit(self, d, y, p): self.m = ml.PenalizedLogistic(["a", "b"]).fit(d[["a", "b"]].to_numpy(), y, 1.0); return self
            def score(self, d): return self.m.predict(d[["a", "b"]].to_numpy())
        R = ev.cross_validate(df, self.y, self.pid, a, [ev.Scorer("lr", M), ev.Scorer("raw_a", lambda d: d.a.to_numpy(), fitted=False, is_probability=False)])
        for r in range(2): np.testing.assert_array_equal(R["lr"].fold[r], R["raw_a"].fold[r])
        self.assertEqual(len(R["lr"].thresholds), 8); self.assertFalse(R["lr"].failures)
        S = ev.summarise(R["lr"], self.y, self.pid, B=100); self.assertGreater(S["within_patient_auc"], 0.6)
        self.assertEqual(S["n_folds_scored"], 8); self.assertIsNotNone(S["cal_slope"])
        sub = ev.subgroup(R["lr"], self.y, self.pid, np.where(np.arange(120) < 60, "g1", "g2"), min_patients=5, B=50)
        self.assertEqual(sub["g1"]["status"], "insufficient")      # 4 patients < 5: no estimate shown
        pl = ev.patient_level(R["raw_a"], self.pid, {q: int(self.y[self.pid == q].max()) for q in set(self.pid)})
        self.assertEqual(pl["n_patients"], 8)


if __name__ == "__main__":
    unittest.main()
