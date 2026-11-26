"""Stage 3 - model integration and improvement of the PERCIVAL Decision Engine (SYNTHETIC data only - never real-data performance):
learned uncertainty + disagreement inputs (stack_unc, neutral missing fill), per-candidate pairwise disagreement and explanations, missing-data
reporting, LUMOS small-data training (augmentation, balanced sampling, seed ensemble), learning curve, subgroup calibration, abstention policy,
study-level agreement, reproducible model hash, second-review priority (blind-gated)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.percival import meta as MT, analysis as AN, cnn as CNN                     # noqa: E402
import _engine_fixtures as FX                                                             # noqa: E402

MINS = dict(studies=1, candidates=1, per_class=1)
_CACHE = {}


def trained(key="plain", **kw):
    if key not in _CACHE:
        _CACHE[key] = MT.train_cycle(FX.rows(14, 12, **kw.pop("fx", {})), "v001", cnn_epochs=kw.pop("epochs", 0), mins=MINS, nested=False, **kw)
    return _CACHE[key]


class TestLearnedUncertainty(unittest.TestCase):
    def test_stack_unc_is_a_candidate_with_neutral_missing_fill(self):
        M = trained("miss", fx=dict(missing_char=0.3, tier2=0.3))
        self.assertIn("stack_unc", M["discovery"]["results"])
        Z = dict(math=np.array([1.0, 1.0]), char=np.array([-3.0, np.nan]), image=np.array([np.nan, 2.0]),
                 rel_albus_tier2=np.array([1.0, 0.0]), rel_nox_missing=np.array([0.5, 0.0]), rel_lumos_spread=np.array([np.nan, np.nan]))
        X = MT.meta_inputs(Z, "stack_unc"); cols = MT.meta_columns("stack_unc")
        self.assertEqual(X.shape, (2, len(cols)))
        self.assertEqual(X[0, cols.index("image")], 0.0)                   # missing -> neutral 0 (no evidence), not the median
        self.assertEqual(X[0, cols.index("image_missing")], 1.0)
        self.assertEqual(X[0, cols.index("gap_math_char")], 4.0); self.assertEqual(X[1, cols.index("gap_math_char")], 0.0)
        self.assertTrue(np.isfinite(X).all())

    def test_reliability_signals_flow_through_oof_and_scoring(self):
        R = FX.rows(8, 10, tier2=0.4)
        Z, _ = MT.component_oof(R, cnn_epochs=0)
        for k in MT.REL: self.assertIn(k, Z)
        M = trained()
        s = MT.score_rows(M, FX.rows(2, 5, seed=4))
        self.assertEqual(set(s[0]["pairwise"]), {f"{a}|{b}" for a, b in MT.PAIRS})
        self.assertIsNone(s[0]["pairwise"]["math|image"])                   # no image output: pair unavailable, not a value
        meas = [x for x in s if x["measurements"]]
        if M["components"]["char"] and M["components"]["kinds"]["char"] == "logistic":
            self.assertTrue(meas)
            for m in meas[0]["measurements"]: self.assertIn(m["measurement"], MT.CHAR)

    def test_missing_measurements_explain_nothing(self):
        M = trained()
        r = FX.rows(1, 1, seed=8)[0]; r["char"] = {k: (None if i % 2 else v) for i, (k, v) in enumerate(r["char"].items())}
        s = MT.score_rows(M, [r])[0]
        for m in (s["measurements"] or []): self.assertIsNotNone(r["char"][m["measurement"]])


class TestSmallDataHonesty(unittest.TestCase):
    def test_model_records_the_analyses(self):
        M = trained()
        self.assertIn("patterns", M["missing_data"]); self.assertTrue(M["learning_curve"]["points"])
        self.assertFalse(M["subgroup_calibration"]["applied"])
        self.assertEqual(set(M["subgroup_calibration"]["subgroups"]), set(MT.SUBGROUPS))
        self.assertEqual(len(M["abstention"]["development"]["points"]), 6); self.assertIn("review required", M["abstention"]["policy"])
        self.assertEqual(len(M["model_hash"]), 20)

    def test_retraining_reproduces_the_model_hash(self):
        R = FX.rows(10, 10, seed=5)
        a = MT.train_cycle(R, "v001", cnn_epochs=0, mins=MINS, nested=False); b = MT.train_cycle(R, "v002", cnn_epochs=0, mins=MINS, nested=False)
        rep = AN.reproducibility(a, b); self.assertTrue(rep["identical"], rep); self.assertEqual(a["model_hash"], b["model_hash"])
        c = MT.train_cycle(FX.rows(10, 10, seed=6), "v003", cnn_epochs=0, mins=MINS, nested=False)
        rep = AN.reproducibility(a, c); self.assertFalse(rep["identical"]); self.assertEqual(rep["why"], "different datasets")

    def test_abstention_curve_and_subgroups(self):
        y = np.array([1, 0] * 50, float); p = np.clip(y * 0.7 + 0.15, 0, 1); risk = np.r_[np.zeros(80), np.ones(20)]
        p[-20:] = 1 - p[-20:]                                              # the risky fifth is wrong
        c = AN.abstention_curve(y, p, risk)["points"]
        self.assertLess(c[0]["accuracy"], c[2]["accuracy"]); self.assertEqual(c[2]["review_required"], 20)
        sg = AN.subgroup_calibration(y, p, dict(field_strength=["1.5T"] * 50 + ["3T"] * 50))
        self.assertEqual(set(sg["subgroups"]["field_strength"]), {"1.5T", "3T"})
        self.assertIn("insufficient data", sg["subgroups"]["field_strength"]["3T"]["recalibration"])     # 50 < 100 candidates

    def test_study_agreement_kappa_and_bland_altman(self):
        a = AN.study_agreement({"S1": 0, "S2": 2, "S3": 4, "S4": 1}, {"S1": 0, "S2": 2, "S3": 4, "S4": 1, "S9": 3})
        self.assertEqual(a["n"], 4); self.assertAlmostEqual(a["kappa_quadratic"], 1.0); self.assertEqual(a["bland_altman"]["mean_difference"], 0.0)
        b = AN.study_agreement({"S1": 1, "S2": 3, "S3": 4}, {"S1": 0, "S2": 2, "S3": 3})
        self.assertEqual(b["bland_altman"]["mean_difference"], 1.0); self.assertLess(b["kappa_quadratic"], 1.0)
        self.assertFalse(AN.study_agreement({"S1": 1}, {})["available"])

    def test_priority_puts_uncertain_and_borderline_first(self):
        q = AN.prioritise([dict(cand_id=1, percival_score=95, status="reliable", disagreement=0.1),
                           dict(cand_id=2, percival_score=50, status="uncertain", disagreement=2.0, reasons=["the components disagree strongly"]),
                           dict(cand_id=3, percival_score=5, status="reliable", disagreement=0.2)])
        self.assertEqual(q[0]["cand_id"], 2)


class TestLumosSmallData(unittest.TestCase):
    def test_augmentation_is_plausible_and_deterministic(self):
        X = np.random.default_rng(0).normal(0, 0.3, (4,) + CNN.IN_SHAPE).astype(np.float32)
        a = CNN.augment(X, np.random.default_rng(1)); b = CNN.augment(X, np.random.default_rng(1))
        self.assertEqual(a.shape, X.shape); self.assertTrue(np.isfinite(a).all()); np.testing.assert_array_equal(a, b)
        self.assertFalse(np.allclose(a, X))

    def test_seed_ensemble_trains_reports_spread_and_round_trips(self):
        R = FX.rows(8, 10, maps=True)
        M = np.stack([r["maps"] for r in R]); y = np.array([r["y"] for r in R]); g = [r["patient"] for r in R]
        E = CNN.SeedEnsemble(0, k=2).fit(M, y, g, epochs=2)
        lg, sp = E.logit_tta(M[:5]); self.assertEqual(lg.shape, (5,)); self.assertTrue((sp >= 0).all())
        self.assertIsNotNone(E.member_variance(M[:5]))
        self.assertTrue(all(m.augmented and m.balanced for m in E.members))
        E2 = CNN.SeedEnsemble.from_json(json.loads(json.dumps(E.to_json()))); np.testing.assert_allclose(E2.logit(M[:5]), E.logit(M[:5]), rtol=1e-5)
        from uengine.lumos import LumosImageIntelligence
        L = LumosImageIntelligence.from_percival_model(dict(version="v009", components=dict(image=E.to_json())))
        self.assertTrue(L.trained)
        self.assertEqual(E.to_json()["channels"], CNN.CHANNELS)


class TestAppRoutes(unittest.TestCase):
    def test_analysis_study_level_and_blind_gated_second_review(self):
        import css_app; css_app.pg_init(); PG = css_app.PG; B = css_app.B
        PG._js(PG.P("registry", "v001", "model.json"), trained())
        A = css_app.pg_get("analysis", {}); self.assertTrue(A["available"]); self.assertTrue(A["model_hash"])
        os.makedirs(os.path.join(B, "labels"), exist_ok=True)
        open(os.path.join(B, "labels", "expert_grades.csv"), "w").write("study,total\nZZ1,2\n")
        st = css_app.pg_get("study_level", {}); self.assertEqual(st["n_expert"], 1); self.assertFalse(st["agreement"]["available"])
        os.makedirs(os.path.join(B, "review"), exist_ok=True); os.makedirs(PG.P("scores"), exist_ok=True)
        open(os.path.join(B, "review", "BG2_candidates.csv"), "w").write("cand_id,score_v4\n1,1.0\n")
        json.dump(dict(model="v001", candidates=[dict(cand_id=1, percival_score=50.0, status="uncertain", disagreement=2.0)]), open(PG.P("scores", "BG2.json"), "w"))
        r = css_app.pg_get("second_review", dict(code="BG2"))
        self.assertTrue(r.get("hidden"), r)                                    # blind first read not completed -> withheld


if __name__ == "__main__":
    unittest.main()
