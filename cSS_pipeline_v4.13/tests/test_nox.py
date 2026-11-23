"""test_nox.py - Verification of NOX Quantitative Characteristics Engine"""
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory
from uengine.nox import NoxCharacteristicsEngine

class TestNoxEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nox_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_NOX")
        self.pensieve = PensieveCoreMemory(self.vault)
        self.nox = NoxCharacteristicsEngine(pensieve=self.pensieve)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_measurement_families(self):
        raw_data = {
            "volume_vox": 20,
            "volume_mm3": 10.0,
            "surface_area_mm2": 25.0,
            "tube_ratio": 1.4,
            "skeleton_length": 5.5,
            "darkness_z": -2.2,
            "edge_contrast": 0.5,
            "pial_distance": 0.3,
            "sulcal_alignment": 0.7,
            "cortex_frac": 0.8
        }
        meas = self.nox.measure_candidate("NOX01", 1, raw_data)
        
        self.assertEqual(meas.study_id, "NOX01")
        self.assertIn("volume_mm3", meas.morphology)
        self.assertIn("skeleton_length_mm", meas.topology)
        self.assertIn("darkness_z", meas.signal)
        self.assertIn("pial_distance_mm", meas.anatomy)
        self.assertEqual(meas.stability.get("pial_distance_mm"), "stable")

    def test_custom_experimental_feature_discovery(self):
        # Register an experimental curvature index
        self.nox.register_custom_feature("pial_curvature_index", lambda d: d.get("tube_ratio", 1.0) * 0.5, (0.0, 10.0))
        meas = self.nox.measure_candidate("NOX02", 2, {"tube_ratio": 2.0})
        self.assertIn("pial_curvature_index", meas.signal)
        self.assertEqual(meas.signal["pial_curvature_index"], 1.0)
        self.assertEqual(meas.stability["pial_curvature_index"], "experimental_stable")

if __name__ == "__main__":
    unittest.main()
