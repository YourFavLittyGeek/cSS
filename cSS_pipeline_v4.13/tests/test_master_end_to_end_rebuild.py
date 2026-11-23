"""test_master_end_to_end_rebuild.py - Master Scientific End-to-End Demonstration

Validates the full reconstructed Percival architecture:
  1. Data Vault Creation & External Persistence
  2. PENSIEVE Shared Core Memory initialization
  3. ALBUS Mathematical Candidate Discovery
  4. LUMOS 3D Image Intelligence
  5. NOX Quantitative 3D Characteristics
  6. PERCIVAL CORE Evidence Integration (with Absorbed Epoximise interaction)
  7. Expert Annotation & Ground Truth Recording
  8. SHADOW ML Autonomous Experimentation
  9. PERCIVAL GOVERNANCE Proposal Evaluation, Approval & Rollback
 10. External Storage Ejection, Recovery & Verification
"""

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
from uengine.albus import AlbusDiscoveryEngine
from uengine.lumos import LumosImageIntelligence
from uengine.nox import NoxCharacteristicsEngine
from uengine.percival_core import PercivalCoreIntelligence
from uengine.shadow_lab import ShadowMLLaboratory
from uengine.governance import PercivalGovernance

class TestMasterEndToEndRebuild(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="master_e2e_")
        self.external_drive = os.path.join(self.temp_dir, "external_ssd")
        os.makedirs(self.external_drive, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_scientific_lifecycle(self):
        print("\n--- STEP 1: Initialize Authoritative Percival Data Vault ---")
        vault = PercivalDataVault.create_vault(self.external_drive, name="PERCIVAL_SCIENTIFIC_VAULT")
        self.assertTrue(vault.is_connected())
        self.assertTrue(os.path.exists(vault.path("PENSIEVE")))

        print("--- STEP 2: Initialize PENSIEVE Persistent Core Memory ---")
        pensieve = PensieveCoreMemory(vault)
        pensieve.remember_study("SUBJ001", "pt_001", "clinical_research", "development", [0.5, 0.5, 2.0])
        study_record = pensieve.get_study("SUBJ001")
        self.assertEqual(study_record["patient_pseudo_id"], "pt_001")

        print("--- STEP 3: ALBUS Mathematical Discovery ---")
        albus = AlbusDiscoveryEngine(formula_id="formula_v4_baseline", threshold=0.4, pensieve=pensieve)
        cand_albus = albus.discover_candidate(
            study_id="SUBJ001",
            cand_id=1,
            hemi="L",
            centroid_vox=(64.0, 72.0, 36.0),
            centroid_mm=(32.0, 36.0, 72.0),
            volume_vox=30,
            volume_mm3=15.0,
            bbox=(62, 70, 35, 66, 74, 37),
            raw_features={"pial_distance": 0.2, "darkness_z": -2.8, "tube_ratio": 1.2, "tram_frac": 0.5, "cortex_frac": 0.7}
        )
        self.assertIsNotNone(cand_albus)
        self.assertGreater(cand_albus.math_score, 0.4)

        print("--- STEP 4: LUMOS 3D Image Intelligence ---")
        lumos = LumosImageIntelligence(pensieve=pensieve, vault=vault)
        # Synthetic 3D patch with blooming subpial siderosis
        swi = np.random.normal(1.0, 0.15, (49, 25, 17)).astype(np.float32)
        valid = np.ones((49, 25, 17), dtype=bool)
        obj = np.zeros((49, 25, 17), dtype=bool)
        obj[20:28, 10:15, 6:10] = True
        swi[obj] *= 0.25 # Dark susceptibility blooming

        inf_lumos = lumos.analyze_patch("SUBJ001", 1, {"image_swi": swi, "valid_swi": valid, "object_mask": obj})
        self.assertEqual(inf_lumos.status, "ok")
        self.assertGreater(inf_lumos.prob, 0.0)

        print("--- STEP 5: NOX Quantitative 3D Characteristics ---")
        nox = NoxCharacteristicsEngine(pensieve=pensieve)
        meas_nox = nox.measure_candidate(
            study_id="SUBJ001",
            cand_id=1,
            raw_candidate_data={
                "volume_vox": 30,
                "volume_mm3": 15.0,
                "tube_ratio": 1.2,
                "skeleton_length": 6.5,
                "darkness_z": -2.8,
                "pial_distance": 0.2,
                "cortex_frac": 0.7
            }
        )
        self.assertIn("sphericity", meas_nox.morphology)
        self.assertEqual(meas_nox.stability.get("pial_distance_mm"), "stable")

        print("--- STEP 6: PERCIVAL CORE Evidence Integration & Absorbed Epoximise ---")
        core = PercivalCoreIntelligence(pensieve=pensieve, vault=vault)
        assessment = core.evaluate_candidate(cand_albus, inf_lumos, meas_nox)
        self.assertIsNotNone(assessment.percival_score)
        self.assertIn(assessment.band, ("green", "amber", "gray"))
        self.assertIn("interaction_synergy", assessment.absorbed_epoximise)
        self.assertIn("absorbed_architecture", assessment.absorbed_epoximise)

        print("--- STEP 7: Expert Annotation & Correction Recording in PENSIEVE ---")
        ann_id = pensieve.record_expert_annotation(
            study_id="SUBJ001",
            reviewer_id="Expert_Neurologist",
            call="definite_css",
            candidate_uid=cand_albus.fingerprint,
            lesion_type="superficial_siderosis",
            confidence="high"
        )
        self.assertTrue(ann_id.startswith("ann_"))

        print("--- STEP 8: SHADOW ML Autonomous Experimentation ---")
        shadow = ShadowMLLaboratory(pensieve=pensieve, vault=vault)
        weaknesses = shadow.inspect_unresolved_weaknesses()
        self.assertIn("unresolved_missed_lesions", weaknesses)

        exp = shadow.formulate_hypothesis(
            target_component="ALBUS",
            hypothesis_text="Curvilinear continuous sheet formulation improves detection of subtle sulcal cSS.",
            experimental_config={"formula": "formula_curvilinear_enhanced", "threshold": 0.42}
        )
        ok_exp, proposal = shadow.run_experiment(exp)
        self.assertTrue(ok_exp)
        self.assertIsNotNone(proposal)
        self.assertTrue(os.path.exists(exp.data_vault_artifact_path))

        print("--- STEP 9: PERCIVAL GOVERNANCE Proposal Evaluation & Approval ---")
        governance = PercivalGovernance(pensieve=pensieve, vault=vault)
        eval_report = governance.evaluate_proposal(proposal)
        self.assertTrue(eval_report["all_passed"])
        
        promoted, msg = governance.promote_proposal(
            proposal=proposal,
            approver_id="Chief_Neuroimaging_Scientist",
            reason="Validated gain in sensitivity without false positive inflation."
        )
        self.assertTrue(promoted)
        self.assertEqual(proposal.verdict, "approved")

        # Rollback capability test
        rb_ok, rb_msg = governance.rollback("ALBUS")
        self.assertTrue(rb_ok)

        print("--- STEP 10: External Storage Disconnection & Recovery ---")
        # Safe ejection
        eject_ok, eject_msg = vault.safe_eject()
        self.assertTrue(eject_ok)
        self.assertFalse(vault.is_connected())

        # Reconnection
        reconnected_vault = PercivalDataVault(vault.root_path)
        self.assertTrue(reconnected_vault.is_connected())
        
        # Verify PENSIEVE survived restart and reconnection intact
        reconnected_pensieve = PensieveCoreMemory(reconnected_vault)
        recovered_study = reconnected_pensieve.get_study("SUBJ001")
        self.assertIsNotNone(recovered_study)
        self.assertEqual(recovered_study["study_id"], "SUBJ001")
        print("ALL SCIENTIFIC LIFECYCLE PHASES PASSED WITH 100% INTEGRITY!\n")

if __name__ == "__main__":
    unittest.main()
