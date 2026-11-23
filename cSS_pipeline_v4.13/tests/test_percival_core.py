"""test_percival_core.py - Verification of PERCIVAL CORE Evidence Integration Engine"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory
from uengine.contracts import AlbusCandidate, LumosInference, NoxMeasurements
from uengine.percival_core import PercivalCoreIntelligence

class TestPercivalCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="core_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_CORE")
        self.pensieve = PensieveCoreMemory(self.vault)
        self.core = PercivalCoreIntelligence(pensieve=self.pensieve, vault=self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_evidence_evaluation(self):
        albus = AlbusCandidate(
            cand_id=1, study_id="CORE01", hemi="L",
            centroid_vox=(50.0, 50.0, 25.0), centroid_mm=(25.0, 25.0, 50.0),
            volume_vox=20, volume_mm3=10.0, bbox=(48, 48, 24, 52, 52, 26),
            math_score=4.0, detection_version="albus-1", formula_id="v4"
        )
        lumos = LumosInference(
            cand_id=1, study_id="CORE01", prob=0.85, logit=1.73,
            uncertainty=0.08, patch_shape=(49, 25, 17), model_version="lumos-1"
        )
        nox = NoxMeasurements(
            cand_id=1, study_id="CORE01",
            morphology={"volume_mm3": 10.0, "elongation": 1.1},
            signal={"darkness_z": -2.8},
            anatomy={"pial_distance_mm": 0.2, "cortex_fraction": 0.8}
        )

        ass = self.core.evaluate_candidate(albus, lumos, nox)
        self.assertEqual(ass.study_id, "CORE01")
        self.assertIsNotNone(ass.percival_score)
        self.assertGreaterEqual(ass.percival_score, 70)
        self.assertEqual(ass.band, "green")
        self.assertIn("interaction_synergy", ass.absorbed_epoximise)
        self.assertEqual(ass.status, "reliable")

    def test_missing_input_safeguard(self):
        # Only ALBUS provided -> must return 'insufficient'
        albus = AlbusCandidate(
            cand_id=2, study_id="CORE02", hemi="R",
            centroid_vox=(60.0, 60.0, 30.0), centroid_mm=(30.0, 30.0, 60.0),
            volume_vox=15, volume_mm3=7.5, bbox=(58, 58, 29, 62, 62, 31),
            math_score=2.0, detection_version="albus-1", formula_id="v4"
        )
        ass = self.core.evaluate_candidate(albus, None, None)
        self.assertIsNone(ass.percival_score)
        self.assertEqual(ass.status, "insufficient")
        self.assertEqual(ass.band, "insufficient")

    def test_epoximise_absorbed_interaction(self):
        albus = AlbusCandidate(
            cand_id=3, study_id="CORE03", hemi="L",
            centroid_vox=(10.0, 10.0, 10.0), centroid_mm=(5.0, 5.0, 20.0),
            volume_vox=10, volume_mm3=5.0, bbox=(9,9,9,11,11,11),
            math_score=1.5, detection_version="albus-1", formula_id="v4"
        )
        # Disagreeing LUMOS (very low prob) and NOX (high prob) -> triggers review status
        lumos = LumosInference(cand_id=3, study_id="CORE03", prob=0.1, logit=-2.2, uncertainty=0.3, patch_shape=(49,25,17), model_version="lumos-1")
        nox = NoxMeasurements(cand_id=3, study_id="CORE03", morphology={"elongation": 1.0}, signal={"darkness_z": -4.0}, anatomy={"pial_distance_mm": 0.1, "cortex_fraction": 0.9})
        
        ass = self.core.evaluate_candidate(albus, lumos, nox)
        self.assertGreater(ass.absorbed_epoximise["lumos_nox_disagreement"], 0.5)
        self.assertIn(ass.status, ("uncertain", "review"))

if __name__ == "__main__":
    unittest.main()
