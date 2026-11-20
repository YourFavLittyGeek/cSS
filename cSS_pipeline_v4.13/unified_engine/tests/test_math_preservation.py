"""MATH preserved: the verbatim detector code reproduces an independent replica; each exclusion rule fires on a constructed row;
first-match order; switches; E30 never produced by the MATH engine; recorded values are authoritative."""
import unittest
import numpy as np
import _common  # noqa: F401
from uengine import math_component as mc


def random_row(rng):
    nan = lambda v, p=0.15: np.nan if rng.random() < p else v
    return dict(darkness_z=rng.normal(3, 1.5), pial_dist_mm=rng.normal(0, 1.5), tube_ratio=nan(rng.random()), surface_alignment=nan(rng.random()),
                tram_frac=nan(rng.random(), 0.3), bank_frac=rng.random(), axis_normal=rng.random(), vessel_wm_mm=abs(rng.normal(0, 4)),
                artifact_zone=int(rng.random() < .2), midline_zone=int(rng.random() < .2), long_structure=int(rng.random() < .1),
                infratentorial=int(rng.random() < .1), vein_like=int(rng.random() < .3), cmb_like=int(rng.random() < .1))


BASE = dict(infratentorial=0, infra_frac=0.0, basal_frac=0.0, rel_height=0.6, extent_mm=20.0, skull_frac=0.0, pial_dist_mm=-0.5,
            vent_frac=0.0, out_frac=0.1, cortex_frac=0.7, tram_frac=0.5, volume_mm3=100.0, darkness_z=3.0, edge_contrast=2.5,
            zone2_frac=0.9, sylvian_frac=0.0, struct_cls="RIBBON", struct_ctx_frac=0.8, struct_s1_mm=20.0, struct_cont=0.5,
            struct_surf_cos=0.2, dual_contact_frac=0.0, midline_frac=0.0, piece_sheet=0, plane_dist_mm=40.0, cos_plane=0.1,
            ext_major_mm=20.0, skullbase_frac=0.0, region="ctx-lh-superiorparietal", mask_edge_mm=20.0, tube_ratio=0.3,
            vessel_wm_mm=0.0, axis_normal=0.2, artifact_zone=0, mimic_class="none", mimic_score=0.0, mb_cluster_n=0)


class TestMath(unittest.TestCase):
    def test_score_and_evidence_verbatim_equals_replica(self):
        rng = np.random.default_rng(0); n_nan = 0
        for _ in range(5000):
            r = random_row(rng)
            a, b = mc.score_v4(r), mc.replica_score_v4(r)
            self.assertTrue(np.isclose(a, b, rtol=1e-12, atol=1e-12), (r, a, b))
            (c1, v1), (c2, v2) = mc.evidence(r), mc.replica_evidence(r)
            self.assertTrue(np.isclose(c1, c2, equal_nan=True) and np.isclose(v1, v2, equal_nan=True))
            n_nan += np.isnan(r["tram_frac"])
        self.assertGreater(n_nan, 1000)                            # the NaN branches were exercised

    def test_review_tier_verbatim(self):
        r = dict(artifact_zone=0, vein_like=0, cmb_like=0, css_evidence=0.6, vein_evidence=0.4); self.assertEqual(mc.review_tier(r)[0], 1)
        r["vein_evidence"] = 0.7; t, why = mc.review_tier(r); self.assertEqual((t, why), (2, "vein evidence > cSS evidence"))

    def test_review_priority_is_the_snapshot_function(self):
        self.assertEqual(mc.review_priority(dict(BASE), "insufficient_quality")[0], 5)
        self.assertEqual(mc.review_priority(dict(BASE, cmb_like=1))[0], 4)

    def test_each_rule_fires(self):
        E = mc.ExclusionEngine(mc.ScanContext(STRUCT=True))
        cases = {"E1": dict(infra_frac=0.5), "E2": dict(basal_frac=0.4), "E3": dict(rel_height=0.1), "E4": dict(extent_mm=4.0),
                 "E15": dict(skull_frac=0.8, pial_dist_mm=0.5), "E16": dict(vent_frac=0.5),
                 "E17": dict(out_frac=0.7, cortex_frac=0.3, tram_frac=0.1), "E20": dict(volume_mm3=1500, skull_frac=0.4),
                 "E19": dict(darkness_z=5.0, skull_frac=0.4), "E21": dict(cortex_frac=0.3, skull_frac=0.4), "E18": dict(edge_contrast=1.2),
                 "E27": dict(sylvian_frac=0.3), "E28": dict(struct_cls="BALL", struct_ctx_frac=0.2),
                 "E29": dict(struct_cls="TUBE", struct_cont=4.0, struct_surf_cos=0.9), "E25": dict(dual_contact_frac=0.4),
                 "E13": dict(midline_frac=0.6), "E22": dict(piece_sheet=1), "E24": dict(skullbase_frac=0.3),
                 "E14": dict(region="ctx-lh-lateralorbitofrontal", mask_edge_mm=5.0), "E5": dict(pial_dist_mm=0.8, tube_ratio=0.6, tram_frac=0.1),
                 "E6": dict(vessel_wm_mm=5.0, axis_normal=0.7, tram_frac=0.1), "E7": dict(cortex_frac=0.2, pial_dist_mm=0.5, tram_frac=0.1, out_frac=0.1),
                 "E8": dict(artifact_zone=1, rel_height=0.3), "E9": dict(edge_contrast=0.6)}
        self.assertEqual(E.fate(BASE), ("", ""))
        for rule, upd in cases.items():
            ctx = mc.ScanContext(STRUCT=True, V53=rule not in ("E9", "E5", "E6", "E7", "E8"))
            rv, why = mc.ExclusionEngine(ctx).fate(dict(BASE, **upd))
            self.assertEqual(rv.split("@")[0], rule, (rule, rv, why))

    def test_first_match_order_and_switches(self):
        r = dict(BASE, infra_frac=0.5, extent_mm=4.0)              # E1 and E4 both apply: E1 first
        self.assertTrue(mc.ExclusionEngine().fate(r)[0].startswith("E1@"))
        r = dict(BASE, skull_frac=0.8, pial_dist_mm=0.5)
        self.assertTrue(mc.ExclusionEngine(mc.ScanContext(V53=True)).fate(r)[0].startswith("E15@"))
        self.assertNotEqual(mc.ExclusionEngine(mc.ScanContext(V53=False)).fate(r)[0][:4], "E15@")
        r = dict(BASE, rel_height=0.1)
        self.assertEqual(mc.ExclusionEngine(mc.ScanContext(T1_ANAT=False)).fate(r)[0], "")     # E3 needs T1 anatomy
        self.assertEqual(mc.ExclusionEngine(mc.ScanContext(FULL_BOTTOM=False)).fate(r)[0], "")  # ... and skull-base coverage
        r = dict(BASE, zone2_frac=0.05)
        self.assertEqual(mc.ExclusionEngine().fate(r)[0], "")                                   # E26 is OFF (threshold 0)
        r = dict(BASE, struct_cls="BALL", struct_ctx_frac=0.2)
        self.assertEqual(mc.ExclusionEngine(mc.ScanContext(STRUCT=False)).fate(r)[0], "")      # E28 opt-in
        self.assertEqual(mc.ExclusionEngine(mc.ScanContext(KEEP_ALL=True)).fate(dict(BASE, infra_frac=0.9))[0], "")

    def test_engine_never_produces_e30(self):
        rng = np.random.default_rng(1); E = mc.ExclusionEngine()
        for _ in range(500):
            r = dict(BASE, **{k: v for k, v in random_row(rng).items() if k in BASE}, confidence_pct=0.0)
            self.assertFalse(E.fate(r)[0].startswith("E30"))

    def test_recorded_values_authoritative_and_consistency(self):
        rng = np.random.default_rng(2)
        for _ in range(300):
            r = random_row(rng); r = {k: (round(v, 1) if k == "darkness_z" else round(v, 2)) if isinstance(v, float) and np.isfinite(v) else v for k, v in r.items()}
            r["score_v4"] = round(mc.score_v4(r), 2); ce, ve = mc.evidence(r); r["css_evidence"], r["vein_evidence"] = round(ce, 2), round(ve, 2)
            me = mc.from_row(dict(r, rule_version="E30@v5.10"))
            self.assertEqual(me.score_v4, r["score_v4"]); self.assertEqual(me.rule_fate, "E30-is-learned")
            self.assertTrue(mc.consistency_ok(me), me.consistency)
        me = mc.from_row(dict(random_row(rng), score_v4=99.0)); self.assertFalse(mc.consistency_ok(me))   # tampered score is visible

    def test_patient_score_parse(self):
        self.assertEqual(mc.patient_score(dict(L=1, R=2)), dict(L=1, R=2, total=3))
        self.assertIsNone(mc.patient_score({}))


if __name__ == "__main__":
    unittest.main()
