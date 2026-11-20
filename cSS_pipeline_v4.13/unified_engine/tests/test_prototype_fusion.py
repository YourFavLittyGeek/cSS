"""integration tests of the Unified Score prototype: all modes, trace arithmetic, categories, reproducibility, persistence,
modularity, leakage / separation"""
import json, os, tempfile, unittest
import numpy as np
import _proto_fixtures as fx
from uengine import feature_schema as fs, patient_split as ps, model_evaluation as ev
from uengine.ml_component import sigmoid
from uengine.data_validation import LeakageError
from uengine.prototype.fusion import UnifiedScorer, MODES, to_rows
from uengine.prototype.components import NullPastExperience
from uengine.prototype.inputs import InputError
from uengine.prototype.patient import patient_summary, PatientResult


class TestFusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr, cls.te, *_ = fx.cohort()
        cls.u = UnifiedScorer("offset", n_boot=30, seed=1).fit(cls.tr, cls.tr.y.to_numpy())
        cls.R = cls.u.predict(cls.te)

    def test_all_modes_fit_and_predict(self):
        for m in MODES:
            u = UnifiedScorer(m, n_boot=5).fit(self.tr, self.tr.y.to_numpy()); R = u.predict(self.te)
            self.assertEqual(len(R), len(self.te)); p = np.array([r.unified["p"] for r in R], float)
            self.assertTrue(np.all((p[np.isfinite(p)] > 0) & (p[np.isfinite(p)] < 1)), m)
            a = ev.auc_decomposition(self.te.y.to_numpy()[np.isfinite(p)], p[np.isfinite(p)], self.te.patient_key.to_numpy()[np.isfinite(p)])
            self.assertGreater(a["within"], 0.8, m)

    def test_trace_arithmetic(self):
        for r in self.R:
            t = r.trace
            if t["final_logit"] is None: continue
            self.assertAlmostEqual(t["final_logit"], t["math_logit"] + t["learned_increment"], places=9)
            self.assertAlmostEqual(t["learned_increment"], t["learned_intercept"] + sum(t["contributions"].values()), places=9)
            self.assertAlmostEqual(r.unified["p"], float(sigmoid(t["final_logit"])), places=12)
            a, b = t["math_recalibration"]["a"], t["math_recalibration"]["b"]
            self.assertAlmostEqual(t["math_logit"], a + b * np.log(r.math["score_v4"] + 0.05), places=9)
            self.assertEqual(t["model_hash"], self.u.model_hash); self.assertEqual(set(t["inputs_used"]), set(fs.INITIAL_COLUMNS))
            self.assertTrue(t["category_rules"])

    def test_categories_follow_rules(self):
        for r in self.R:
            u = r.unified; c = u["category"]
            if c == "likely_cSS": self.assertTrue(u["p"] >= 0.7 and u["p_lo"] > 0.5)
            if c == "unlikely_cSS": self.assertTrue(u["p"] <= 0.3 and u["p_hi"] < 0.5)
            if u["p_lo"] is not None and u["p_lo"] <= 0.5 <= u["p_hi"]: self.assertIn(c, ("uncertain", "not_scorable"))
        self.assertTrue({"likely_cSS", "uncertain", "unlikely_cSS"} <= {r.unified["category"] for r in self.R})

    def test_reproducible_and_persistent(self):
        u2 = UnifiedScorer("offset", n_boot=30, seed=1).fit(self.tr, self.tr.y.to_numpy())
        self.assertEqual(u2.model_hash, self.u.model_hash)
        self.assertNotEqual(UnifiedScorer("offset", n_boot=30, seed=2).fit(self.tr, self.tr.y.to_numpy()).model_hash, self.u.model_hash)
        with tempfile.TemporaryDirectory() as d:
            f = self.u.save(os.path.join(d, "m.json")); v = UnifiedScorer.load(f); R2 = v.predict(self.te)
            for a, b in zip(self.R, R2):
                self.assertEqual(a.unified["category"], b.unified["category"])
                self.assertTrue(np.isclose(a.unified["p"], b.unified["p"], equal_nan=True))
            with open(f) as fh: j = json.load(fh)
            j["params"]["past"]["beta"][1] += 0.5
            with open(f, "w") as fh: json.dump(j, fh)
            with self.assertRaises(ValueError): UnifiedScorer.load(f)

    def test_component_swap(self):
        a = UnifiedScorer("math_only", n_boot=0).fit(self.tr, self.tr.y.to_numpy())
        b = UnifiedScorer("offset", n_boot=0, past=NullPastExperience()).fit(self.tr, self.tr.y.to_numpy())
        pa = [r.unified["p"] for r in a.predict(self.te)]; pb = [r.unified["p"] for r in b.predict(self.te)]
        np.testing.assert_allclose(pa, pb)                                  # replacing PAST EXPERIENCE needs no other change

    def test_math_only_preserves_math_order(self):
        a = UnifiedScorer("math_only", n_boot=0).fit(self.tr, self.tr.y.to_numpy()); p = np.array([r.unified["p"] for r in a.predict(self.te)])
        s = self.te.score_v4.to_numpy(); o = np.argsort(s, kind="stable"); self.assertTrue(np.all(np.diff(p[o]) >= -1e-12))

    def test_leakage_and_separation(self):
        with self.assertRaises(LeakageError): UnifiedScorer("offset", columns=fs.INITIAL_COLUMNS[:5] + ["score_v4"])
        with self.assertRaises(LeakageError): UnifiedScorer("offset", columns=["darkness_z", "confidence_pct"])
        T = ps.ProtectedTestSet(tuple(self.tr.patient_key.unique()[:2]))
        with self.assertRaises(LeakageError): UnifiedScorer("offset", n_boot=0).fit(self.tr, self.tr.y.to_numpy(), protected=T)
        base = [r.unified["p"] for r in self.u.predict(self.te)]
        tampered = self.te.assign(y=1 - self.te.y, y_true=0, positive=1, confidence_pct=99.0)        # labels / patient values / model outputs
        np.testing.assert_allclose(base, [r.unified["p"] for r in self.u.predict(tampered)], equal_nan=True)
        one = [r.unified["p"] for r in self.u.predict(self.te.iloc[[3]])]                             # batch-invariant: no row sees another
        self.assertTrue(np.isclose(one[0], base[3]))
        with self.assertRaises(InputError): UnifiedScorer("offset", n_boot=0).fit(self.tr, self.tr.y.where(self.tr.index > 2).to_numpy())
        with self.assertRaises(InputError): UnifiedScorer("offset", n_boot=0).fit(self.tr.assign(measurement_complete=False), self.tr.y.to_numpy())
        with self.assertRaises(InputError): UnifiedScorer("offset", n_boot=0).fit(self.tr, np.zeros(len(self.tr)))

    def test_patient_level_is_separate(self):
        S = patient_summary(self.R, math_scores={self.te.patient_key[0]: dict(L=1, R=0, total=1)})
        self.assertTrue(all(isinstance(s, PatientResult) for s in S))
        self.assertEqual(sum(s.n_candidates for s in S), len(self.R))
        s0 = next(s for s in S if s.patient_key == self.te.patient_key[0]); self.assertEqual(s0.math_patient_score, dict(L=1, R=0, total=1))
        self.assertTrue(all(sum(s.counts.values()) == s.n_candidates for s in S))
        self.assertEqual(len(to_rows(self.R)), len(self.R))


if __name__ == "__main__":
    unittest.main()
