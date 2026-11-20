"""SYNTHETIC scenario tests: positive, negative, borderline, difficult mimics, missing / corrupted inputs, extreme and unexpected values"""
import unittest
import numpy as np
import _proto_fixtures as fx
from uengine.prototype.fusion import UnifiedScorer
from uengine.prototype.inputs import InputError


class TestScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tr, te, *_ = fx.cohort(seed=6, n=60)
        cls.u = UnifiedScorer("offset", n_boot=30, seed=0).fit(tr, tr.y.to_numpy())

    def one(self, **kw):
        kind = kw.pop("kind", "cSS"); return self.u.predict(fx.frame([fx.row(kind, 0, **kw)]))[0]

    def test_positive_and_negatives(self):
        P = {k: self.one(kind=k) for k in ("cSS", "vein", "normal", "microbleed")}
        self.assertEqual(P["cSS"].unified["category"], "likely_cSS")
        for k in ("vein", "normal", "microbleed"):
            self.assertLess(P[k].unified["p"], P["cSS"].unified["p"], k); self.assertNotEqual(P[k].unified["category"], "likely_cSS", k)

    def test_borderline_is_not_forced(self):
        r = self.one(kind=None, **fx.borderline())
        self.assertGreater(r.unified["p"], self.one(kind="vein").unified["p"]); self.assertLess(r.unified["p"], self.one().unified["p"])
        self.assertEqual(r.unified["category"], "uncertain")                 # a borderline case is never forced positive / negative
        print(f"\n   borderline: p {r.unified['p']:.2f} [{r.unified['p_lo']:.2f}, {r.unified['p_hi']:.2f}] -> {r.unified['category']}")

    def test_difficult_mimic_ranks_below_css(self):
        m, c = self.one(kind="mimic_vein"), self.one()
        self.assertLess(m.unified["p"], c.unified["p"])
        print(f"\n   mimic vein: p {m.unified['p']:.2f} ({m.unified['category']}); cSS p {c.unified['p']:.2f}")

    def test_missing_inputs_make_uncertain_not_negative(self):
        r = self.one(tram_frac=np.nan, cortex_frac=np.nan, edge_contrast=np.nan, local_cont_max_mm=np.nan)
        self.assertEqual(r.unified["category"], "uncertain"); self.assertTrue(any("missing" in f for f in r.quality_flags))
        self.assertTrue(np.isfinite(r.unified["p"]))                           # still scored (imputed), but not categorised

    def test_corrupted_inputs(self):
        r = self.one(edge_contrast="corrupt-text", tube_ratio=np.inf, cortex_frac=-3.0)
        self.assertEqual(r.trace["input_validation"], {"edge_contrast": "corrupt", "tube_ratio": "corrupt", "cortex_frac": "out_of_range"})
        self.assertEqual(r.unified["category"], "uncertain")
        r = self.one(score_v4=7.5)                                             # recorded MATH score inconsistent with its inputs
        self.assertEqual(r.math["status"], "inconsistent"); self.assertEqual(r.unified["category"], "uncertain")

    def test_extreme_values_are_clipped_and_flagged(self):
        for kw in (dict(darkness_z=1e6, score_v4=np.nan), dict(volume_mm3=1e12), dict(local_cont_max_mm=1e9), dict(elongation_3d=0.0)):
            r = self.one(**kw)
            self.assertTrue(np.isfinite(r.unified["p"]) or r.unified["category"] == "not_scorable", kw)
            self.assertEqual(r.unified["category"], "uncertain", kw)
            self.assertTrue(any("training range" in f for f in r.quality_flags), kw)

    def test_unscorable_and_outside_model(self):
        self.assertEqual(self.one(darkness_z=np.nan, score_v4=np.nan).unified["category"], "not_scorable")
        r = self.one(measurement_complete=False); self.assertEqual(r.unified["category"], "not_scorable")
        self.assertTrue(r.unified["p"] is None or np.isnan(r.unified["p"]))
        self.assertEqual(self.one(registration="unreliable").unified["category"], "uncertain")

    def test_unexpected_inputs(self):
        self.assertEqual(self.u.predict(fx.frame([fx.row("cSS", 0)]).iloc[:0]), [])
        r = self.u.predict(fx.frame([dict(fx.row("cSS", 0), totally_new_column="x", another=[1, 2])]))[0]
        self.assertEqual(r.unified["category"], "likely_cSS")
        bare = {k: v for k, v in fx.row("cSS", 0).items() if k not in ("tram_frac", "tube_ratio", "elongation_3d", "local_cont_max_mm")}
        r = self.u.predict(fx.frame([bare]))[0]                                # absent columns = missing, not a crash
        self.assertEqual(r.unified["category"], "uncertain")
        with self.assertRaises(InputError): self.u.predict(fx.frame([fx.row("cSS", 0)]).drop(columns=["patient_key"]))
        with self.assertRaises(InputError): self.u.predict(fx.frame([fx.row("cSS", 0)]), data_kind="clinical")
        with self.assertRaises(RuntimeError): UnifiedScorer("offset").predict(fx.frame([fx.row("cSS", 0)]))


if __name__ == "__main__":
    unittest.main()
