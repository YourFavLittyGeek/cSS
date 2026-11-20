"""the ablation machinery itself: negative control (truth = MATH only) shows no spurious learned gain; naive fusion double counts; reproducible"""
import unittest
import numpy as np
import _common  # noqa: F401
from uengine import ablation as ab


class TestAblation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = ab.run_scenario("truth_math_only", 31, n_repeats=1, B=100, n_patients=36)

    def test_negative_control(self):
        m = self.r["models"]
        self.assertEqual(self.r["failures"], {})
        lo, hi = m["offset"]["delta_vs_math_ci"]
        self.assertTrue(lo <= 0.0 <= hi or abs(m["offset"]["delta_vs_math"]) < 0.01, m["offset"]["delta_vs_math_ci"])
        self.assertLess(m["naive"]["cal_slope"], m["offset"]["cal_slope"] - 0.2)          # double counting -> over-confident
        self.assertGreater(m["offset"]["cal_slope"], 0.8)
        self.assertLess(m["learned_only"]["within"], m["math_only"]["within"])             # characteristics alone lose MATH's form

    def test_reproducible(self):
        r2 = ab.run_scenario("truth_math_only", 31, n_repeats=1, B=100, n_patients=36)
        self.assertEqual(r2["assignment_digest"], self.r["assignment_digest"])
        for k in self.r["models"]: self.assertTrue(np.isclose(r2["models"][k]["within"], self.r["models"][k]["within"]), k)

    def test_permutation_null(self):
        r = ab.permutation_test_increment("baseline", 33, n_perm=5, n_patients=30, B=50)
        self.assertGreater(r["observed_delta"], r["null_q95"])                # real increment clears the permutation null
        self.assertAlmostEqual(r["perm_p"], 1 / 6)                            # the smallest p possible with 5 permutations

    def test_permutation_keeps_math_and_patient_sets(self):
        D, E, P = ab.cohort(34, n_patients=12)
        pid = D.patient_key.to_numpy(); rng = np.random.default_rng(0); cols = ab.PERMUTE_SOURCES
        V = D[cols].to_numpy(copy=True)
        for q in sorted(set(pid)):
            g = np.where(pid == q)[0]; V[g] = V[rng.permutation(g)]
        Dp = D.copy(); Dp[cols] = V
        self.assertTrue((Dp.score_v4 == D.score_v4).all() and (Dp.y == D.y).all())
        for q in sorted(set(pid)):
            a_ = np.sort(D.loc[pid == q, "darkness_z"].to_numpy()); b_ = np.sort(Dp.loc[pid == q, "darkness_z"].to_numpy())
            np.testing.assert_array_equal(a_, b_)

    def test_nonoverlap_set(self):
        self.assertEqual(ab.NONOVERLAP, ["edge_contrast", "cortex_frac", "elongation_3d", "log_volume_mm3", "local_cont_max_mm"])


if __name__ == "__main__":
    unittest.main()
