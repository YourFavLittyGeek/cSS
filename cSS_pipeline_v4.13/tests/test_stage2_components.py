"""Stage 2 - one component interface (ALBUS / NOX / LUMOS), the NOX feature list stored in the model and read from the component
registry, frozen component families with the meta-model refitted on top, per-component freeze / rollback. SYNTHETIC data only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import copy
import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.percival import meta as MT, component_api as CI, component_registry as CR   # noqa: E402
import _engine_fixtures as FX                                                             # noqa: E402

MINS = dict(studies=1, candidates=1, per_class=1)


class TestComponentInterface(unittest.TestCase):
    def test_interface_features_and_reliability(self):
        R = FX.rows(4, 6, tier2=0.5, missing_char=0.3)
        self.assertEqual(CI.ALBUS.features(R)["math"].shape, (24,))
        F = CI.NOX.features(R); self.assertEqual(F["char"].shape, (24, len(MT.CHAR))); self.assertNotIn("unified", F)   # 2026-11-25: NOX is one module
        rel = CI.reliability_table(R)
        self.assertEqual(set(rel), set(CI.RELIABILITY))
        self.assertTrue(((rel["albus_tier2"] == 0) | (rel["albus_tier2"] == 1)).all())
        self.assertTrue((rel["nox_missing"] > 0).any() and (rel["nox_missing"] <= 1).all())
        self.assertTrue(np.isnan(rel["lumos_spread"]).all())                 # no image output -> NaN, never a value

    def test_old_model_without_feature_list_loads_with_the_builtin_set(self):
        M = MT.train_cycle(FX.rows(10, 10), "v001", cnn_epochs=0, mins=MINS, nested=False, features=dict(char=MT.NOX_V000))
        d = copy.deepcopy(M["components"]); d.pop("char_cols")                 # a model saved before Stage 2 (trained on the original 9)
        C = MT.Components.from_json(d); self.assertEqual(C.char_cols, MT.NOX_V000)
        Z = C.predict(FX.rows(2, 5, seed=3)); self.assertTrue(np.isfinite(Z["char"]).all())

    def test_feature_list_is_part_of_the_model_and_used_for_scoring(self):
        cols = MT.CHAR + ["cos_plane"]
        R = FX.rows(12, 12, extra=dict(cos_plane=2.5))
        M = MT.train_cycle(R, "v001", cnn_epochs=0, mins=MINS, nested=False, features=dict(char=cols, nox_version="v001"))
        self.assertEqual(M["features"]["char"], cols); self.assertEqual(M["features"]["nox_version"], "v001")
        self.assertEqual(M["components"]["char_cols"], cols)
        self.assertEqual(M["component_config"]["NOX"]["feature_set"], cols)
        self.assertIn("NOX", M["component_interface"]); self.assertEqual(M["component_interface"]["NOX"]["columns"]["measurements"], cols)
        s = MT.score_rows(json.loads(json.dumps(M)), FX.rows(2, 4, seed=9, extra=dict(cos_plane=0.0)))
        self.assertEqual(len(s), 8)
        imp = M["intelligence"]["families"]["char"]["feature_auc"]; self.assertIn("cos_plane", imp)

    def test_frozen_family_is_not_reselected(self):
        R = FX.rows(12, 10)
        M = MT.train_cycle(R, "v001", cnn_epochs=0, mins=MINS, nested=False, frozen=dict(char="gbt"))
        self.assertEqual(M["component_config"]["NOX"]["char_kind"], "gbt"); self.assertTrue(M["component_config"]["NOX"]["frozen"])
        self.assertEqual(set(M["intelligence"]["families"]["char"]["results"]), {"gbt"})
        self.assertIn(M["meta"]["kind"], MT.SIMPLICITY)                      # meta-model refitted on top


class TestRegistryDrivenTraining(unittest.TestCase):
    def setUp(self):
        import css_app; css_app.pg_init(); self.PG = css_app.PG

    def test_active_nox_version_drives_the_feature_set_and_label_like_names_are_dropped(self):
        PG = self.PG
        self.assertEqual(PG.nox_feature_set(), (MT.CHAR, "v000")); self.assertEqual(PG.component_configs(), (None, None))
        CR.approve(PG.P(), "NOX", dict(feature_set=MT.CHAR + ["cos_plane", "expert_call"]), "Dr Reviewer", "test", CR.CONFIRM, evidence={}, synthetic=True)
        cols, v = PG.nox_feature_set()
        self.assertEqual(v, "v001"); self.assertIn("cos_plane", cols); self.assertNotIn("expert_call", cols)
        feats, frozen = PG.component_configs(); self.assertEqual(feats["nox_version"], "v001"); self.assertIsNone(frozen)
        CR.rollback(PG.P(), "NOX", "Dr Reviewer", "undo", CR.CONFIRM); self.assertEqual(PG.nox_feature_set()[1], "v000")

    def test_component_freeze_and_rollback_need_a_person(self):
        PG = self.PG
        self.assertFalse(PG.component_freeze("LUMOS", "Dr A", "x", CR.CONFIRM)["ok"])        # no model yet
        M = MT.train_cycle(FX.rows(10, 10), "v001", cnn_epochs=0, mins=MINS, nested=False)
        PG._js(PG.P("registry", "v001", "model.json"), M)
        self.assertFalse(PG.component_freeze("NOX", "percival", "auto", CR.CONFIRM)["ok"])      # automated actor refused
        self.assertFalse(PG.component_freeze("NOX", "Dr A", "x", "yes")["ok"])                  # typed phrase required
        self.assertFalse(PG.component_freeze("ALBUS", "Dr A", "x", CR.CONFIRM)["ok"])           # ALBUS changes only through SHADOW
        r = PG.component_freeze("NOX", "Dr A", "freeze the measurement model", CR.CONFIRM); self.assertTrue(r["ok"], r)
        feats, frozen = PG.component_configs()
        self.assertEqual(frozen, dict(char=M["component_config"]["NOX"]["char_kind"]))
        self.assertTrue(PG.component_rollback("NOX", "Dr A", "undo", CR.CONFIRM)["ok"])
        self.assertEqual(PG.component_configs(), (None, None))


if __name__ == "__main__":
    unittest.main()
