"""test_pensieve.py - Unit and Integration Tests for PENSIEVE Core Memory"""
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory

class TestPensieveCoreMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="pensieve_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_TEST")
        self.pensieve = PensieveCoreMemory(self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_study_and_candidate_memory(self):
        self.pensieve.remember_study("SYN01", "pt_01", "synthetic", "development", [0.5, 0.5, 2.0])
        st = self.pensieve.get_study("SYN01")
        self.assertIsNotNone(st)
        self.assertEqual(st["patient_pseudo_id"], "pt_01")
        self.assertEqual(st["partition"], "development")

        uid = self.pensieve.remember_candidate(
            study_id="SYN01",
            cand_id=1,
            hemi="L",
            centroid_vox=(100.0, 120.0, 45.0),
            centroid_mm=(50.0, 60.0, 90.0),
            volume_vox=18,
            volume_mm3=9.0,
            bbox=(98, 118, 44, 102, 122, 46),
            albus_score=4.5,
            albus_formula="formula_v4",
            lumos_prob=0.88,
            percival_score=85
        )
        self.assertTrue(uid.startswith("SYN01_L_"))

    def test_expert_annotations_and_corrections(self):
        self.pensieve.remember_study("SYN02", "pt_02", "synthetic", "development")
        uid = self.pensieve.remember_candidate("SYN02", 2, "R", (50.0, 50.0, 20.0), (25.0, 25.0, 40.0), 10, 5.0, (48,48,19,52,52,21), 3.2)
        
        # Expert rejects candidate as sulcal vessel -> generates false positive correction
        ann_id = self.pensieve.record_expert_annotation("SYN02", "Dr_Smith", "not_css", candidate_uid=uid, lesion_type="sulcal_vessel")
        self.assertTrue(ann_id.startswith("ann_"))

        # Expert flags a missed lesion
        miss_id = self.pensieve.record_expert_annotation("SYN02", "Dr_Smith", "missed_lesion", candidate_uid=None, lesion_type="superficial_siderosis")
        self.assertTrue(miss_id.startswith("ann_"))

        corrections = self.pensieve.get_all_corrections()
        self.assertGreaterEqual(len(corrections), 2)
        event_types = {c["event_type"] for c in corrections}
        self.assertIn("false_positive_rejected", event_types)
        self.assertIn("missed_lesion_flagged", event_types)

    def test_component_query_interfaces(self):
        # Test inquiries
        alb = self.pensieve.ask_albus_memory()
        self.assertIn("missed_lesions_count", alb)
        self.assertIn("false_positive_corrections", alb)

        lum = self.pensieve.ask_lumos_memory()
        self.assertIn("expert_confirmed_cSS_count", lum)

        nox = self.pensieve.ask_nox_memory()
        self.assertIn("reproducibility_records", nox)

        core = self.pensieve.ask_core_memory()
        self.assertIn("absorbed_epoximise_status", core)

        shd = self.pensieve.ask_shadow_memory()
        self.assertIn("unresolved_missed_lesions", shd)

    def test_leak_free_partition_isolation(self):
        self.pensieve.remember_study("DEV01", "pt_dev", "synthetic", "development")
        self.pensieve.remember_study("TEST01", "pt_test", "synthetic", "locked_test")
        
        u_dev = self.pensieve.remember_candidate("DEV01", 1, "L", (10.0, 10.0, 10.0), (5.0, 5.0, 20.0), 10, 5.0, (9,9,9,11,11,11), 3.0)
        u_test = self.pensieve.remember_candidate("TEST01", 1, "R", (20.0, 20.0, 20.0), (10.0, 10.0, 40.0), 10, 5.0, (19,19,19,21,21,21), 4.0)

        self.pensieve.record_expert_annotation("DEV01", "Dr_A", "definite_css", candidate_uid=u_dev)
        self.pensieve.record_expert_annotation("TEST01", "Dr_A", "definite_css", candidate_uid=u_test)

        # Retrieval for development training
        dev_data = self.pensieve.get_training_dataset("development")
        test_data = self.pensieve.get_training_dataset("locked_test")

        self.assertEqual(len(dev_data), 1)
        self.assertEqual(dev_data[0]["study_id"], "DEV01")
        self.assertEqual(dev_data[0]["patient_pseudo_id"], "pt_dev")

        self.assertEqual(len(test_data), 1)
        self.assertEqual(test_data[0]["study_id"], "TEST01")
        self.assertEqual(test_data[0]["patient_pseudo_id"], "pt_test")

    def test_missed_lesion_recording_and_review_status(self):
        self.pensieve.remember_study("DEV02", "pt_dev2", "synthetic", "development")
        muid = self.pensieve.record_missed_lesion(
            study_id="DEV02",
            missed_id="1",
            reviewer_id="Dr_Smith",
            coords_vox=(120, 140, 35),
            coords_mm=(60.0, 70.0, 70.0),
            slice_idx=35,
            plane="0",
            shape="pen",
            points_json="[[[120, 140, 35]]]",
            comment="Subtle sulcal lining missed by detector",
            detector_fate="not generated by the detector"
        )
        self.assertEqual(muid, "DEV02_missed_1")
        missed = self.pensieve.get_missed_lesions("DEV02")
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["vox_i"], 120)
        self.assertEqual(missed[0]["reviewer_id"], "Dr_Smith")

        # Set and get review status
        self.pensieve.set_study_review_status(
            study_id="DEV02",
            candidate_review="all_reviewed",
            missed_assessment="missed_drawn",
            adjudication="not_needed",
            overall_status="expert_review_completed",
            reviewer_id="Dr_Smith"
        )
        st = self.pensieve.get_study_review_status("DEV02")
        self.assertEqual(st["overall_status"], "expert_review_completed")
        self.assertEqual(st["missed_assessment_status"], "missed_drawn")

        # Telemetry
        status = self.pensieve.get_status()
        self.assertTrue(status["connected"])
        self.assertGreaterEqual(status["missed_lesions_count"], 1)

        # Deletion
        ok = self.pensieve.delete_missed_lesion("DEV02", "1")
        self.assertTrue(ok)
        self.assertEqual(len(self.pensieve.get_missed_lesions("DEV02")), 0)

if __name__ == "__main__":
    unittest.main()
