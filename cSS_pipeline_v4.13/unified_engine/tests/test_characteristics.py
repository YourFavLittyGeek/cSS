import unittest
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import characteristics_component as cc, feature_schema as fs


class TestCharacteristics(unittest.TestCase):
    def test_refuses_scores_flags_ids_model_outputs(self):
        for bad in (["score_v4"], ["confidence_pct"], ["cand_id"], ["review_tier"], ["struct_cls"], ["css_evidence"], ["nonexistent"]):
            with self.assertRaises(cc.NotACharacteristic): cc.characteristics({}, bad)

    def test_statuses(self):
        e = cc.characteristics(dict(darkness_z=3.0, tram_frac=np.nan, flair_csf_z=np.nan, cortex_frac=1.7, pial_dist_mm=np.nan),
                               ["darkness_z", "tram_frac", "flair_csf_z", "cortex_frac", "pial_dist_mm"])
        self.assertEqual(e.status, dict(darkness_z="ok", tram_frac="missing_structural", flair_csf_z="missing_input",
                                        cortex_frac="out_of_range", pial_dist_mm="missing_unexpected"))
        self.assertTrue(np.isnan(e.values["cortex_frac"])); self.assertAlmostEqual(e.completeness, 0.2)

    def test_gate_dropped_is_not_measured(self):
        e = cc.characteristics(dict(volume_mm3=10.0), ["volume_mm3", "darkness_z"], measured_complete=False)
        self.assertEqual(set(e.status.values()), {"not_measured"})

    def test_design_row_transforms_and_indicator(self):
        v, s = cc.design_row(dict(darkness_z=3, edge_contrast=2, pial_dist_mm=-.5, cortex_frac=.6, tram_frac=np.nan, tube_ratio=.3,
                                  elongation_3d=4, volume_mm3=np.e ** 4, local_cont_max_mm=3))
        self.assertAlmostEqual(v["log_volume_mm3"], 4.0); self.assertEqual(v["tram_frac_missing"], 1.0); self.assertTrue(np.isnan(v["tram_frac"]))
        v, s = cc.design_row(dict(darkness_z=3, tram_frac=0.4, volume_mm3=0.2)); self.assertEqual(v["tram_frac_missing"], 0.0)
        self.assertAlmostEqual(v["log_volume_mm3"], 0.0)                        # clipped at 1 mm3 as in css_confidence
        v, s = cc.design_row(dict(tram_frac=2.0)); self.assertTrue(np.isnan(v["tram_frac_missing"]))   # corrupt value is not 'structural'
        self.assertEqual(list(v), fs.INITIAL_COLUMNS)

    def test_design_matrix_marks_incomplete_rows(self):
        df = pd.DataFrame([dict(darkness_z=3.0, measurement_complete=True), dict(darkness_z=3.0, measurement_complete=False)])
        X, counts = cc.design_matrix(df)
        self.assertTrue(np.isfinite(X[0, 0])); self.assertTrue(np.isnan(X[1]).all())
        self.assertEqual(counts["darkness_z"].get("not_measured"), 1)


if __name__ == "__main__":
    unittest.main()
