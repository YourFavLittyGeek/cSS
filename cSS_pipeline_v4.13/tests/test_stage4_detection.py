"""Stage 4 - detection vs classification: sensitivity-gated ALBUS rule experiments (against the current detector output on the SAME studies,
any lost eligible cSS rejects), LUMOS pattern and component-interaction hypotheses, NOX stability selection -> hypotheses only, millimetre
matching tolerances. SYNTHETIC data only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
from uengine import shadow_governed as SG                                  # noqa: E402
from uengine.percival import component_registry as CR                       # noqa: E402
import css_common as CC                                                     # noqa: E402

BASE = ["darkness_z", "edge_contrast"]


def rows(n_pat=24, per=10, seed=0):
    """development rows; 'bad_rule_var' is high for some cSS (a rule on it loses lesions); 'fp_var' is high only for non-cSS"""
    r = np.random.default_rng(seed); out = []
    for p in range(n_pat):
        for c in range(per):
            y = int(r.random() < 0.4)
            out.append(dict(study=f"S{p:02d}", cand_id=c + 1, patient=f"P{p:02d}", partition="development", y=y,
                            features=dict(darkness_z=float(r.normal(-2 * y, 1)), edge_contrast=float(r.normal(y, 1)),
                                          fp_var=float(5 + r.random()) if (not y and r.random() < 0.3) else float(r.random()),
                                          bad_rule_var=float(r.normal(1.0 * y, 1)), informative=float(r.normal(2.5 * y, 0.7)),
                                          noise=float(r.normal(0, 1)), patch_minip_mean=float(r.normal(-0.5 * y, 0.5)))))
    return out


def store(): return tempfile.mkdtemp(prefix="st4_", dir=os.environ["CSS_BASE"])


class TestAlbusRules(unittest.TestCase):
    def test_rule_that_loses_a_lesion_is_rejected_whatever_the_fp_gain(self):
        st = store(); R = rows()
        H = SG.register(st, "ALBUS", "albus_rule", ["bad_rule_var"], "remove bright objects", params=dict(op=">", threshold=0.5))
        H = SG.run_discovery(st, H["id"], R, [])
        self.assertEqual(H["status"], "rejected_sensitivity"); self.assertGreater(H["discovery"]["result"]["lost_css"], 0)
        self.assertGreater(H["discovery"]["result"]["false_positives_removed"], 0)
        with self.assertRaises(SG.ShadowError): SG.confirm(st, H["id"], R)

    def test_sensitivity_preserving_rule_confirmed_then_recorded_never_applied(self):
        st = store(); R = rows()
        H = SG.register(st, "ALBUS", "albus_rule", ["fp_var"], "artifact zone objects", params=dict(op=">", threshold=4.0))
        H = SG.run_discovery(st, H["id"], R, []); self.assertEqual(H["status"], "discovery_done", H["discovery"]["result"])
        self.assertEqual(H["discovery"]["result"]["lost_css"], 0); self.assertEqual(H["discovery"]["result"]["sensitivity_retained"], 1.0)
        with self.assertRaises(SG.ShadowError): SG.confirm(st, H["id"], R, actor="SHADOW")         # SHADOW never confirms its own discovery
        H = SG.confirm(st, H["id"], R); self.assertTrue(H["confirmation"]["passed"], H["confirmation"])
        self.assertFalse(set(H["discovery"]["patients"]) & set(H["confirmation"]["patients"]))
        with self.assertRaises(CR.RegistryError): SG.approve(st, H["id"], "SHADOW", "self", CR.CONFIRM)
        H, V = SG.approve(st, H["id"], "Dr Neuro", "confirmed on unseen patients", CR.CONFIRM)
        rule = V["config"]["proposed_rules"][-1]; self.assertFalse(rule["applied_to_detector"]); self.assertEqual(rule["feature"], "fp_var")
        self.assertEqual(CR.active(st, "ALBUS")["version"], "v001")

    def test_rule_registration_is_validated(self):
        st = store()
        with self.assertRaises(SG.ShadowError): SG.register(st, "ALBUS", "albus_rule", ["fp_var"], "x", params=dict(op="!=", threshold=1))
        with self.assertRaises(SG.ShadowError): SG.register(st, "ALBUS", "albus_rule", ["fp_var"], "x", params=dict(op=">"))
        with self.assertRaises(SG.ShadowError): SG.register(st, "NOX", "albus_rule", ["fp_var"], "x", params=dict(op=">", threshold=1))
        with self.assertRaises(SG.ShadowError): SG.register(st, "ALBUS", "albus_rule", ["expert_call"], "x", params=dict(op=">", threshold=1))


class TestInteractionAndPatterns(unittest.TestCase):
    def test_interaction_and_lumos_pattern_run_and_approve_into_the_registry(self):
        st = store(); R = rows()
        H = SG.register(st, "NOX", "interaction", ["darkness_z", "edge_contrast"], "dark AND contrasted")
        H = SG.run_discovery(st, H["id"], [dict(r, features=dict(r["features"])) for r in R], BASE, synthetic=True)
        self.assertIn("darkness_z*edge_contrast", H["discovery"]["extended_features"])
        H = SG.confirm(st, H["id"], [dict(r, features=dict(r["features"])) for r in R])
        H, V = SG.approve(st, H["id"], "Dr Neuro", "test", CR.CONFIRM, override=not H["confirmation"]["passed"], allow_synthetic=True)
        self.assertIn("darkness_z*edge_contrast", V["config"]["feature_set"]); self.assertTrue(V["synthetic"])
        with self.assertRaises(SG.ShadowError): SG.register(st, "LUMOS", "lumos_pattern", ["darkness_z"], "not a patch statistic")
        P = SG.register(st, "LUMOS", "lumos_pattern", ["patch_minip_mean"], "dark core in the patch")
        P = SG.run_discovery(st, P["id"], R, BASE, synthetic=True); self.assertEqual(P["status"], "discovery_done")

    def test_stability_selection_only_registers_hypotheses_on_discovery_patients(self):
        st = store(); R = rows(30)
        out = SG.suggest_nox(st, R, BASE, ["informative", "noise", "fp_var", "expert_call"])
        self.assertTrue(out["ok"]); names = [d["measurement"] for d in out["selection"]]
        self.assertNotIn("expert_call", names)                            # label-like names never considered
        top = out["selection"][0]; self.assertEqual(top["measurement"], "informative")
        hs = {h["id"]: h for h in SG.listing(st)}
        self.assertTrue(out["registered"]); self.assertTrue(all(hs[i]["status"] == "registered" and "stability" in hs[i]["created_by"] for i in out["registered"]))
        self.assertEqual(CR.active(st, "NOX")["version"], "v000")          # nothing was added to training
        bad = [dict(R[0], partition="test")] + R[1:]
        with self.assertRaises(SG.ShadowError): SG.suggest_nox(st, bad, BASE, ["informative"])


class TestMillimetreMatching(unittest.TestCase):
    def test_same_physical_offset_same_decision_at_any_resolution(self):
        C = pd.DataFrame([dict(cand_id=1, vox_i=10, vox_j=10, vox_k=10, volume_mm3=30.0, hemi="L")])
        for vox, off in ((0.5, 2.4), (1.0, 1.2)):                         # 1.2 mm in both scans
            rec = [dict(vox_i=10 + off, vox_j=10, vox_k=10, volume_mm3=30.0, hemi="L")]
            m = CC.match_one_to_one(C, rec, voxel_mm=[vox, vox, vox])[0]
            self.assertEqual(m["status"], "matched", (vox, m)); self.assertAlmostEqual(m["distance_mm"], 1.2, places=3)
        # the voxel fallback (unknown voxel size) keeps the old behaviour: 2.4 voxels > 2 voxels
        self.assertEqual(CC.match_one_to_one(C, [dict(vox_i=12.4, vox_j=10, vox_k=10, volume_mm3=30.0, hemi="L")])[0]["status"], "no_candidate")
        far = CC.match_one_to_one(C, [dict(vox_i=10, vox_j=10, vox_k=11, volume_mm3=30.0, hemi="L")], voxel_mm=[0.5, 0.5, 2.0])[0]
        self.assertEqual(far["status"], "no_candidate")                    # one 2 mm slice away is beyond 1.5 mm


if __name__ == "__main__":
    unittest.main()
