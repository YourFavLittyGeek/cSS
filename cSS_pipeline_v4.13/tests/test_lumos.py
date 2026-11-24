"""test_lumos.py - Verification of LUMOS 3D Image Intelligence Engine"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import shutil
import tempfile
import unittest
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory
from uengine.lumos import LumosImageIntelligence

class TestLumosIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="lumos_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_LUMOS")
        self.pensieve = PensieveCoreMemory(self.vault)
        # architecture integration: an UNTRAINED network never reports a probability; the mechanics are tested with explicit weights
        self.untrained = LumosImageIntelligence(pensieve=self.pensieve, vault=self.vault)
        self.lumos = LumosImageIntelligence(weights=__import__('uengine.percival.cnn', fromlist=['SmallCNN']).SmallCNN(7).p, pensieve=self.pensieve, vault=self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_patch_analysis_and_uncertainty(self):
        # Create synthetic 3D patch
        swi = np.random.normal(1.0, 0.2, (49, 25, 17)).astype(np.float32)
        valid = np.ones((49, 25, 17), dtype=bool)
        obj = np.zeros((49, 25, 17), dtype=bool)
        obj[20:30, 10:15, 6:10] = True
        
        # Inject dark blooming
        swi[obj] *= 0.2

        patch_data = {"image_swi": swi, "valid_swi": valid, "object_mask": obj}
        inf = self.lumos.analyze_patch("LUM01", 1, patch_data)
        
        self.assertEqual(inf.status, "ok")
        u = self.untrained.analyze_patch("LUM01", 1, patch_data)
        self.assertEqual((u.status, u.prob), ("untrained", None))
        self.assertGreaterEqual(inf.prob, 0.0)
        self.assertLessEqual(inf.prob, 1.0)
        self.assertGreaterEqual(inf.uncertainty, 0.0)
        self.assertEqual(inf.patch_shape, (49, 25, 17))

    def test_checkpoint_persistence_in_vault(self):
        dest = self.lumos.save_checkpoint("test_v1")
        self.assertTrue(os.path.exists(dest))
        self.assertTrue(dest.startswith(self.vault.root_path))

    def test_unavailable_handling(self):
        inf = self.lumos.analyze_patch("LUM02", 2, None)
        self.assertEqual(inf.status, "unavailable")
        self.assertEqual(inf.uncertainty, 1.0)

if __name__ == "__main__":
    unittest.main()
