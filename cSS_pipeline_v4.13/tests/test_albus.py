"""test_albus.py - Verification of ALBUS Discovery Engine"""
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory
from uengine.albus import AlbusDiscoveryEngine, FORMULAS

class TestAlbusDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="albus_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_ALBUS")
        self.pensieve = PensieveCoreMemory(self.vault)
        self.albus = AlbusDiscoveryEngine(formula_id="formula_v4_baseline", threshold=0.5, pensieve=self.pensieve)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_formulas(self):
        features = {
            "pial_distance": 0.2,
            "darkness_z": -2.5,
            "tube_ratio": 1.1,
            "tram_frac": 0.4,
            "cortex_frac": 0.8,
            "edge_contrast": 0.6,
            "skeleton_length": 6.0
        }
        for fid in FORMULAS:
            self.albus.set_formula(fid)
            score = self.albus.calculate_score(features)
            self.assertGreater(score, 0.5)

    def test_candidate_discovery_and_pensieve_registration(self):
        self.pensieve.remember_study("ALB01", "pt_01", "synthetic", "development")
        cand = self.albus.discover_candidate(
            study_id="ALB01",
            cand_id=1,
            hemi="L",
            centroid_vox=(80.0, 90.0, 40.0),
            centroid_mm=(40.0, 45.0, 80.0),
            volume_vox=25,
            volume_mm3=12.5,
            bbox=(78, 88, 39, 82, 92, 41),
            raw_features={"pial_distance": 0.1, "darkness_z": -3.0, "tube_ratio": 1.0}
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand.study_id, "ALB01")
        self.assertGreater(cand.math_score, 0.5)

    def test_learning_from_pensieve(self):
        # Register a missed lesion in PENSIEVE
        self.pensieve.remember_study("ALB02", "pt_02", "synthetic", "development")
        self.pensieve.record_expert_annotation("ALB02", "Dr_Reviewer", "missed_lesion")
        
        info = self.albus.learn_from_pensieve()
        self.assertEqual(info["missed_lesions_to_recover"], 1)
        self.assertGreater(len(info["recommendations"]), 0)

if __name__ == "__main__":
    unittest.main()
