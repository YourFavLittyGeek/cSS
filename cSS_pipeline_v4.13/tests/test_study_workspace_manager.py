"""test_study_workspace_manager.py - Unit tests for Central Study Workspace Manager & Queue"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)

import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.study_workspace_manager import StudyWorkspaceManager, StudyLifecycleState


class TestStudyWorkspaceManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swm_test_")
        self.base_dir = os.path.join(self.tmp, "workspace")
        self.vault_dir = os.path.join(self.tmp, "PERCIVAL_VAULT")
        os.makedirs(self.base_dir, exist_ok=True)
        self.vault = PercivalDataVault.create_vault(self.tmp, name="PERCIVAL_VAULT")
        self.swm = StudyWorkspaceManager(self.base_dir, vault_root=self.vault.root_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_study_registration_and_transitions(self):
        # Register study
        rec = self.swm.register_study("TEST_STUDY_01", "/fake/original/mri")
        self.assertEqual(rec["study_id"], "TEST_STUDY_01")
        self.assertEqual(rec["state"], StudyLifecycleState.REGISTERED.value)

        # Legal transition to AWAITING_STAGING
        ok, msg = self.swm.transition_state("TEST_STUDY_01", StudyLifecycleState.AWAITING_STAGING.value)
        self.assertTrue(ok)
        self.assertEqual(self.swm.get_study("TEST_STUDY_01")["state"], StudyLifecycleState.AWAITING_STAGING.value)

        # Illegal transition directly to ARCHIVED
        ok, msg = self.swm.transition_state("TEST_STUDY_01", StudyLifecycleState.ARCHIVED.value)
        self.assertFalse(ok)
        self.assertIn("Illegal state transition", msg)

    def test_capacity_estimation(self):
        # Create a mock source MRI file
        src_dir = os.path.join(self.tmp, "mock_source")
        os.makedirs(src_dir, exist_ok=True)
        src_file = os.path.join(src_dir, "t1.nii")
        with open(src_file, "wb") as f:
            f.write(b"\0" * (10 * 1024 * 1024)) # 10 MB

        self.swm.register_study("CAP_TEST", src_dir)
        cap = self.swm.estimate_capacity("CAP_TEST", [src_file])
        self.assertGreaterEqual(cap["source_mb"], 10.0)
        self.assertGreaterEqual(cap["projected_required_mb"], 50.0)
        self.assertTrue(cap["admissible"])

    def test_staging_processing_review_archival_and_clean_lifecycle(self):
        # 1. Setup mock source files
        # Phase 1b: staging sources must be inside the project or the Vault (here: the Vault's original MRI folder)
        src_dir = os.path.join(self.swm.vault_root, "original_mri", "SUBJ_FULL")
        os.makedirs(src_dir, exist_ok=True)
        swi_file = os.path.join(src_dir, "swi.nii")
        with open(swi_file, "w") as f:
            f.write("swi_test_data_content")

        self.swm.register_study("SUBJ_FULL", src_dir)

        # 2. Stage study
        ok, msg, rec = self.swm.stage_study("SUBJ_FULL", [swi_file], verify=True)
        self.assertTrue(ok)
        self.assertEqual(self.swm.get_study("SUBJ_FULL")["state"], StudyLifecycleState.READY_FOR_PROCESSING.value)

        # 3. Verify staged
        ok_v, _ = self.swm.verify_staged_study("SUBJ_FULL")
        self.assertTrue(ok_v)

        # 4. Processing transition
        self.swm.transition_state("SUBJ_FULL", StudyLifecycleState.PROCESSING.value)
        self.swm.transition_state("SUBJ_FULL", StudyLifecycleState.PROCESSING_COMPLETED.value)
        self.swm.transition_state("SUBJ_FULL", StudyLifecycleState.UNDER_EXPERT_REVIEW.value)

        # 5. Incomplete review cannot be cleaned
        ok_c, _ = self.swm.clean_eligible_workspace("SUBJ_FULL")
        self.assertFalse(ok_c)

        # 6. Record complete review
        ok_r, _ = self.swm.record_review_status("SUBJ_FULL", candidates_reviewed=True, missed_lesions_assessed=True, reviewer_id="Dr_Smith")
        self.assertTrue(ok_r)
        self.assertEqual(self.swm.get_study("SUBJ_FULL")["state"], StudyLifecycleState.AWAITING_ARCHIVAL.value)

        # 7. Archive study to Vault
        ok_a, msg_a = self.swm.archive_study("SUBJ_FULL", verify=True)
        self.assertTrue(ok_a)
        self.assertEqual(self.swm.get_study("SUBJ_FULL")["state"], StudyLifecycleState.ARCHIVED.value)

        # 8. Verify Archive
        ok_va, _ = self.swm.verify_archive("SUBJ_FULL")
        self.assertTrue(ok_va)

        # 9. Clean eligible workspace (now permitted because archived & verified)
        ok_cl, msg_cl = self.swm.clean_eligible_workspace("SUBJ_FULL")
        self.assertTrue(ok_cl)
        # Verify local workspace was removed
        ws_path = os.path.join(self.base_dir, "work", "SUBJ_FULL")
        self.assertFalse(os.path.exists(ws_path))

    def test_sequential_processing_queue(self):
        res1 = self.swm.enqueue_study("QUEUE_01", priority=1)
        res2 = self.swm.enqueue_study("QUEUE_02", priority=5)
        self.assertTrue(res1["ok"])
        self.assertTrue(res2["ok"])

        q = self.swm.get_queue()
        self.assertEqual(len(q), 2)

        # Process next in queue (QUEUE_02 has higher priority 5)
        ok, msg, current = self.swm.process_next_in_queue()
        self.assertTrue(ok)
        self.assertEqual(current["study_id"], "QUEUE_02")
        self.assertEqual(current["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
