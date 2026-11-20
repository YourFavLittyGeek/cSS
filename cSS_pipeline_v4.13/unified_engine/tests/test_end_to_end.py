"""integration: the whole synthetic path, reproducibility, the synthetic-only guard"""
import unittest
import numpy as np
import _common  # noqa: F401
from uengine import experiment as ex, synthetic as sy


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = ex.run(n_patients=36, seed=1, signal=1.0, n_repeats=2, B=100)

    def test_runs_without_fold_failures(self):
        self.assertEqual(self.R["failures"], {})
        self.assertGreater(self.R["n_candidates"], 200); self.assertGreater(self.R["repeat_exam_patients"], 0)

    def test_every_comparator_on_identical_population(self):
        cl = self.R["candidate_level"]
        for k in ("new_lr_initial10", "math_score_v4", "math_evidence_difference", "legacy_confidence_v5.10", "legacy_ranker_v5.2",
                  "legacy_unified_procedure_on_proxies", "char_darkness_z"):
            self.assertIn(k, cl); self.assertEqual(cl[k]["n_folds_scored"], 10, k)

    def test_signal_recovered_within_patients(self):
        cl = self.R["candidate_level"]["new_lr_initial10"]
        self.assertGreater(cl["within_patient_auc"], 0.75); self.assertGreater(cl["fold_auc_mean"], 0.75)
        self.assertIsNotNone(cl["within_patient_auc_ci_repeat0"])

    def test_checks_clean_on_clean_data(self):
        c = self.R["checks"]; self.assertEqual(c["near_perfect"], []); self.assertEqual(c["duplicates"], []); self.assertEqual(c["range_violations"], {})

    def test_reproducible(self):
        R2 = ex.run(n_patients=36, seed=1, signal=1.0, n_repeats=2, B=100)
        self.assertEqual(R2["assignment_digest"], self.R["assignment_digest"])
        for k, v in self.R["candidate_level"].items():
            self.assertTrue(np.isclose(v["pooled_auc"], R2["candidate_level"][k]["pooled_auc"], equal_nan=True), k)

    def test_pure_noise_end_to_end(self):
        R = ex.run(n_patients=30, seed=2, signal=0.0, n_repeats=1, B=50, legacy=False)
        w = R["candidate_level"]["new_lr_initial10"]["within_patient_auc"]
        self.assertLess(abs(w - 0.5), 0.1, w)

    def test_refuses_non_synthetic(self):
        O, _, _ = sy.make_cohort(4, seed=0); O.loc[0, "patient_key"] = "M02"
        with self.assertRaises(ex.NotSynthetic): ex._assert_synthetic(O)


if __name__ == "__main__":
    unittest.main()
