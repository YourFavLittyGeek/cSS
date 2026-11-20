import unittest
import numpy as np
from scipy.optimize import minimize
import _common  # noqa: F401
from uengine import ml_component as ml, synthetic as sy, characteristics_component as cc, feature_schema as fs


class TestML(unittest.TestCase):
    def test_irls_equals_direct_optimisation(self):
        r = np.random.default_rng(0); Z = r.normal(size=(300, 3)); y = (r.random(300) < ml.sigmoid(Z @ [1, -0.5, 0] - 0.3)).astype(float)
        for lam in (0.0, 1.0, 10.0):
            b, ok, _ = ml.irls(Z, y, lam); self.assertTrue(ok)
            A = np.c_[np.ones(300), Z]
            f = lambda bb: -(np.sum(y * (A @ bb) - np.logaddexp(0, A @ bb)) - 0.5 * lam * bb[1:] @ bb[1:])
            ref = minimize(f, np.zeros(4), method="BFGS", options=dict(gtol=1e-10)).x
            np.testing.assert_allclose(b, ref, atol=1e-5)

    def test_penalty_shrinks_and_intercept_unpenalised(self):
        r = np.random.default_rng(1); Z = r.normal(size=(200, 2)); y = (r.random(200) < 0.8).astype(float)
        b0 = ml.irls(Z, y, 0.0)[0]; b1 = ml.irls(Z, y, 1e6)[0]
        self.assertLess(np.abs(b1[1:]).max(), 1e-3); self.assertAlmostEqual(ml.sigmoid(b1[0]), y.mean(), places=3)
        self.assertGreater(np.abs(b0[1:]).max(), np.abs(b1[1:]).max())

    def test_offset_removes_double_counting(self):
        # truth = the offset alone; a feature identical in information to the offset must get ~0 learned weight
        r = np.random.default_rng(2); n = 3000; off = r.normal(0, 1.5, n); y = (r.random(n) < ml.sigmoid(off)).astype(float)
        X = np.c_[off + r.normal(0, 0.1, n), r.normal(size=n)]
        m = ml.PenalizedLogistic(["a", "b"]).fit(X, y, 0.1, offset=off)
        self.assertLess(np.abs(m.beta[1:]).max(), 0.15)
        m2 = ml.PenalizedLogistic(["a", "b"]).fit(X, y, 0.1)          # without the offset the same feature carries the signal
        self.assertGreater(m2.beta[1], 1.0)

    def test_preprocessing_fitted_on_training_rows_only(self):
        r = np.random.default_rng(3); X = r.normal(size=(100, 2)); X[::7, 0] = np.nan; y = (r.random(100) < .4).astype(float)
        m = ml.PenalizedLogistic(["a", "b"]).fit(X[:80], y[:80], 1.0)
        self.assertAlmostEqual(m.pre.median[0], np.nanmedian(X[:80, 0])); self.assertEqual(m.pre.n_imputed[0], int(np.isnan(X[:80, 0]).sum()))

    def test_contributions_sum(self):
        r = np.random.default_rng(4); X = r.normal(size=(120, 3)); y = (r.random(120) < .5).astype(float); off = r.normal(size=120)
        m = ml.PenalizedLogistic(["a", "b", "c"]).fit(X, y, 1.0, offset=off)
        np.testing.assert_allclose(m.contributions(X).sum(1) + m.beta[0] + off, m.logit(X, off))

    def test_nested_selection_and_balanced_option(self):
        O, E, P = sy.make_cohort(30, seed=4); sh = O[O.fate == "shown"].reset_index(drop=True)
        X, _ = cc.design_matrix(sh); y = sh.y.to_numpy(float)
        m = ml.PenalizedLogistic(fs.INITIAL_COLUMNS).fit_nested(X, y, sh.patient_key, seed=0)
        self.assertIn("chosen", m.selection_log[-1]); self.assertTrue(m.converged)
        mb = ml.PenalizedLogistic(fs.INITIAL_COLUMNS, class_weight="balanced").fit(X, y, 1.0)
        self.assertGreater(abs(mb.beta[0] - m.beta[0]), 0)

    def test_legacy_adapters_run_verbatim(self):
        O, E, P = sy.make_cohort(16, seed=6); sh = O[O.fate == "shown"].reset_index(drop=True); y = sh.y.to_numpy(int)
        for A in (ml.LegacyConfidence, ml.LegacyRanker, ml.LegacyUnified):
            s = np.asarray(A().fit(sh, y, sh.patient_key.to_numpy()).score(sh), float)
            self.assertEqual(len(s), len(sh)); self.assertTrue(np.all((s >= 0) & (s <= 1)), A.name)
        cc_ = ml.pv.load_legacy("css_confidence"); a = ml.LegacyConfidence().fit(sh, y, sh.patient_key.to_numpy())
        np.testing.assert_allclose(a.score(sh), cc_.confidence(cc_.fit(sh, y, a.l2), sh) / 100.0)   # adapter == verbatim procedure

    def test_math_recalibration_is_monotone(self):
        r = np.random.default_rng(7); s = np.abs(r.normal(1, .5, 400)); y = (r.random(400) < ml.sigmoid(2 * np.log(s + .05))).astype(float)
        rc = ml.MathRecalibration().fit(s, y); self.assertGreater(rc.b, 0)
        o = np.argsort(s); self.assertTrue(np.all(np.diff(rc.logit(s[o])) >= -1e-12))


if __name__ == "__main__":
    unittest.main()
