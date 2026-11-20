import unittest
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import funnel as fn, synthetic as sy, provenance as pv


class TestFunnel(unittest.TestCase):
    def test_fates_and_completeness(self):
        c = pd.DataFrame([dict(rule_version="v4.18")]); x = pd.DataFrame([dict(rule_version="E5@v4.8"), dict(rule_version="E30@v5.10")])
        d = pd.DataFrame([dict(gate_id="G1_volume", rule_version="")]); m = pd.DataFrame([dict(rule_version="")])
        P = fn.build_population(c, x, d, m, exam_id="SYN1")
        self.assertEqual(list(P.fate), ["shown", "rule_excluded", "learned_excluded", "gate_dropped", "not_generated"])
        self.assertEqual(list(P.measurement_complete), [True, True, True, False, False])
        self.assertEqual(list(P.selection), ["none", "fixed_rule", "learned_model", "generation_gate", "not_generated"])
        with self.assertRaises(ValueError): fn.build_population(excluded=pd.DataFrame([dict(rule_version="v4.18")]))
        with self.assertRaises(ValueError): fn.build_population(dropped=pd.DataFrame([dict(gate_id="G9_new", rule_version="")]))

    def test_review_web_design_matches_source(self):
        rw = pv.source(f"{pv.SCRIPTS}/review_web.py")
        self.assertRegex(rw, r"AUDIT_OFFSET, AUDIT_FRAC = 10000, 0\.20")
        self.assertIn('startswith("infratentorial")', rw)
        self.assertIn("n = max(1, int(round(AUDIT_FRAC * len(ids))))", rw)
        self.assertIn("rng.choice(ids, size=min(n, len(ids)), replace=False)", rw)

    def test_inclusion_probabilities(self):
        reasons = ["infratentorial / tentorial interface"] * 3 + ["vein: tubular"] * 7
        d = fn.review_web_audit_design(reasons, "audit")
        self.assertEqual((d.kind, d.N_eligible, d.n), ("srs", 7, 1))
        self.assertEqual(d.inclusion_probability("E1"), 0.0); self.assertAlmostEqual(d.inclusion_probability("E5"), 1 / 7)
        self.assertEqual(fn.review_web_audit_design(reasons, "show_excluded").inclusion_probability("E1"), 1.0)
        self.assertIsNone(fn.review_web_audit_design(reasons, None).inclusion_probability("E5"))

    def test_weights_never_invented(self):
        P = pd.DataFrame(dict(fate=["shown", "rule_excluded", "rule_excluded", "learned_excluded", "gate_dropped"], rule_id=["", "E5", "E1", "E30", ""],
                              exam_id=["A", "A", "A", "B", "A"]))
        w = fn.label_weights(P, {"A": fn.SamplingDesign("srs", 10, 2, ("E1",))})
        self.assertEqual(w[0], 1.0); self.assertAlmostEqual(w[1], 5.0)
        self.assertTrue(np.isnan(w[2]) and np.isnan(w[3]) and np.isnan(w[4]))   # p = 0, unknown design, gate-dropped

    def test_selection_report_on_synthetic(self):
        O, E, P = sy.make_cohort(20, seed=5, e30_rate=0.2)
        O.loc[O.fate == "learned_excluded", "y"] = np.nan
        rep = fn.selection_report(O)
        self.assertGreater(rep["learned_excluded"]["n"], 0)
        self.assertTrue(any("E30" in w for w in rep["warning"]))
        self.assertEqual(rep["gate_dropped"]["labelled"], 0)
        self.assertFalse(O.loc[O.fate == "gate_dropped", "measurement_complete"].any())


if __name__ == "__main__":
    unittest.main()
