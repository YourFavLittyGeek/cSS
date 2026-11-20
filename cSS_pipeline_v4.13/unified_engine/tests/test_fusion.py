import unittest
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import unified_fusion as uf, math_component as mc, characteristics_component as cc, ml_component as ml, patient_split as ps


def bundle(rule="", inc=None, conf=None, reg="ok", complete=True):
    me = mc.MathEvidence(1.2, .6, .4, .2, rule, 1, 1)
    ce = cc.characteristics(dict(darkness_z=3.0), ["darkness_z"])
    return uf.ComponentBundle("SYN1#1", me, ce, uf.LearnedEvidence("increment_lr_v0", inc, legacy_confidence_pct=conf),
                              uf.QualityIndicators(registration=reg, measurement_complete=complete))


class TestFusion(unittest.TestCase):
    def test_no_unified_score_without_gate_d(self):
        r = uf.fuse(bundle()); self.assertIsNone(r.unified_score); self.assertIn("NOT AUTHORIZED", r.status)
        auth = uf.GateDAuthorization({k: "x" for k in uf.GATE_D_CHECKLIST[:-1]}, "abc", "someone", "2026-11-20")   # one item missing
        self.assertIsNone(uf.fuse(bundle(), auth, fusion_fn=lambda b: 0.5).unified_score)
        self.assertIsNone(uf.fuse(bundle(), None, fusion_fn=lambda b: 0.5).unified_score)

    def test_components_kept_separate_and_quality_withholds(self):
        auth = uf.GateDAuthorization({k: "x" for k in uf.GATE_D_CHECKLIST}, "abc", "someone", "2026-11-20")
        r = uf.fuse(bundle(reg="unreliable"), auth, fusion_fn=lambda b: 0.5)
        self.assertIsNone(r.unified_score); self.assertIn("WITHHELD", r.status)
        self.assertEqual(set(r.components), {"math", "characteristics", "learned"})
        r = uf.fuse(bundle(), auth, fusion_fn=lambda b: 0.5); self.assertEqual(r.unified_score, 0.5)   # mechanism only (synthetic fusion_fn)
        self.assertTrue(uf.fuse(bundle(complete=False)).quality_flags)

    def test_disagreement_visible(self):
        self.assertTrue(uf.fuse(bundle(rule="E5", inc=2.0)).disagreement)
        self.assertTrue(uf.fuse(bundle(conf=3.0)).disagreement)
        self.assertTrue(uf.fuse(bundle(), rank_math=0.9, rank_learned=0.2).disagreement)
        self.assertFalse(uf.fuse(bundle(), rank_math=0.9, rank_learned=0.8).disagreement)

    def test_offset_design_prevents_double_counting(self):
        """truth depends ONLY on the math score; the characteristics are its inputs. The offset model must not improve on math and
        must stay calibrated; the naive 'add the two scores' fusion becomes over-confident (slope < 1)."""
        r = np.random.default_rng(0); rows = []
        for p in range(40):
            for i in range(25):
                f = dict(darkness_z=r.normal(3, 1), pial_dist_mm=r.normal(0, 1), tube_ratio=r.uniform(), surface_alignment=r.uniform(),
                         tram_frac=r.uniform(), artifact_zone=0, midline_zone=0, long_structure=0, infratentorial=0)
                f["score_v4"] = mc.score_v4(f); f["patient_key"] = f"SYNP{p}"; rows.append(f)
        D = pd.DataFrame(rows); lp = -2.5 + 2.2 * np.log(D.score_v4 + .05)
        y = (r.random(len(D)) < ml.sigmoid(lp)).astype(float)
        cols = ["darkness_z", "pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac"]
        a = ps.grouped_folds(D.patient_key, 5, 1, 0)
        res = uf.incremental_value(D, y, D.patient_key, a, cols, lambda d: d[cols].to_numpy(float), B=100)
        print("\n   incremental value (math-only truth):", {k: (round(v["within_patient_auc"], 3), round(v["cal_slope"], 2)) for k, v in res.items() if isinstance(v, dict)})
        self.assertLess(abs(res["delta_within_auc"]), 0.03)
        self.assertGreater(res["math_plus_learned"]["cal_slope"], 0.8)
        self.assertLess(res["naive_sum"]["cal_slope"], res["math_plus_learned"]["cal_slope"] - 0.15)
        self.assertTrue(res["synthetic_only"])

    def test_incremental_value_detects_real_increment(self):
        r = np.random.default_rng(1); n = 1000; pid = np.repeat([f"SYNP{i}" for i in range(40)], 25)
        D = pd.DataFrame(dict(score_v4=np.abs(r.normal(1, .5, n)), extra=r.normal(size=n), patient_key=pid))
        y = (r.random(n) < ml.sigmoid(-1 + 1.5 * np.log(D.score_v4 + .05) + 1.2 * D.extra)).astype(float)
        res = uf.incremental_value(D, y, pid, ps.grouped_folds(pid, 5, 1, 0), ["extra"], lambda d: d[["extra"]].to_numpy(float), B=100)
        self.assertGreater(res["delta_within_auc"], 0.05); self.assertGreater(res["delta_within_auc_ci"][0], 0)


if __name__ == "__main__":
    unittest.main()
