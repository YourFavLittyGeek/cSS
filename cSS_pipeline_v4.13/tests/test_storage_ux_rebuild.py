"""Tests for PERCIVAL Master Storage UX, Transfer Center, Sync Center, Settings & Reconciliation.

Mission ID: PERCIVAL-STORAGE-UX-REBUILD-2026
"""

import os
import shutil
import tempfile
import time
import unittest
import json

from uengine.unified_transfer_engine import (
    UnifiedTransferEngine,
    TransferProgress,
    TransferState,
    compute_sha256,
    flush_durability
)
from uengine.storage.models import (
    StorageCategory,
    DriveSafetyState,
    VolumeInfo,
    EjectCheckResult,
    SyncPreview
)
from uengine.storage.storage_paths import StoragePathsService, VAULT_DIRNAME
from uengine.storage.storage_state import StorageStateService
from uengine.storage.storage_intelligence import StorageIntelligence
from uengine.storage.eject_manager import EjectManager
from uengine.storage.sync_manager import SyncManager
from uengine.study_workspace_manager import StudyWorkspaceManager


class TestStorageUXRebuild(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="percival_storage_ux_test_")
        self.ssd_dir = os.path.join(self.tmp_dir, "ssd_workspace")
        self.hdd_mount = os.path.join(self.tmp_dir, "mock_hdd")
        self.hdd_vault = os.path.join(self.hdd_mount, VAULT_DIRNAME)
        os.makedirs(self.ssd_dir, exist_ok=True)
        os.makedirs(self.hdd_vault, exist_ok=True)

        self.transfer_dir = os.path.join(self.ssd_dir, "app_data", "transfers")
        self.transfer_engine = UnifiedTransferEngine(state_dir=self.transfer_dir)

        self.paths_service = StoragePathsService(
            workspace_root=self.ssd_dir,
            configured_vault_mount=self.hdd_vault
        )
        self.state_service = StorageStateService(paths_service=self.paths_service)
        self.intelligence = StorageIntelligence(self.paths_service)
        self.eject_manager = EjectManager(
            paths_service=self.paths_service,
            state_service=self.state_service
        )
        self.sync_manager = SyncManager(
            paths_service=self.paths_service,
            state_service=self.state_service
        )
        self.workspace_mgr = StudyWorkspaceManager(
            base_dir=self.ssd_dir,
            vault_root=self.hdd_vault
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_transfer_states_and_part_file_staging(self):
        """Test TransferState enumeration and staged .part file commit."""
        self.assertEqual(TransferState.QUEUED, "Queued")
        self.assertEqual(TransferState.COPYING, "Copying")
        self.assertEqual(TransferState.VERIFYING, "Verifying")
        self.assertEqual(TransferState.COMMITTING, "Committing")
        self.assertEqual(TransferState.COMPLETED, "Completed")
        self.assertEqual(TransferState.INTERRUPTED, "Interrupted")

        src_file = os.path.join(self.ssd_dir, "sample_brain.nii")
        data = b"PERCIVAL_NEUROIMAGING_REBUILD_2026_TEST_DATA" * 500
        with open(src_file, "wb") as f:
            f.write(data)

        dst_file = os.path.join(self.hdd_vault, "transferred_brain.nii")
        progress_events = []

        def on_prog(prog_dict):
            progress_events.append(prog_dict.get("current_phase"))

        ok, msg, res = self.transfer_engine.transfer_path(
            src=src_file,
            dst=dst_file,
            study_id="TEST_STUDY",
            verify_sha=True,
            on_progress=on_prog
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(dst_file))
        # Ensure temporary .part file was cleaned up and committed
        self.assertFalse(os.path.exists(dst_file + ".part"))
        self.assertEqual(compute_sha256(src_file), compute_sha256(dst_file))
        self.assertIn("Copying", progress_events)
        self.assertIn("Completed", progress_events)

    def test_durability_flushing(self):
        """Test durability flush on open file descriptor using F_FULLFSYNC or fsync."""
        test_file = os.path.join(self.ssd_dir, "flush_test.bin")
        with open(test_file, "wb") as f:
            f.write(b"DURABILITY_TEST" * 100)
            f.flush()
            # flush_durability should execute without error
            flush_durability(f.fileno())
        self.assertTrue(os.path.isfile(test_file))

    def test_scan_interrupted_transfers(self):
        """Test scanning and detecting dangling .part files as interrupted transfers."""
        # Create an orphaned .part file in vault
        orphaned_part = os.path.join(self.hdd_vault, "incomplete_study.nii.part")
        with open(orphaned_part, "wb") as f:
            f.write(b"INCOMPLETE_STREAM")

        interrupted = self.transfer_engine.scan_interrupted_transfers(search_dirs=[self.hdd_vault])
        self.assertGreaterEqual(len(interrupted), 1)
        part_items = [item for item in interrupted if item.get("has_part_file")]
        self.assertGreaterEqual(len(part_items), 1)
        target_names = [os.path.basename(item["destination"]) for item in part_items]
        self.assertIn("incomplete_study.nii", target_names)

    def test_drive_safety_states_and_emergency_eject(self):
        """Test DriveSafetyState 10 states and emergency unmount handling."""
        states = [
            DriveSafetyState.DRIVE_NOT_CONNECTED,
            DriveSafetyState.DETECTING,
            DriveSafetyState.READY,
            DriveSafetyState.BUSY,
            DriveSafetyState.TRANSFERRING,
            DriveSafetyState.VERIFYING,
            DriveSafetyState.PREPARING_TO_EJECT,
            DriveSafetyState.BLOCKED,
            DriveSafetyState.SAFE_TO_EJECT,
            DriveSafetyState.UNKNOWN,
        ]
        self.assertEqual(len(states), 10)

        # Check safety check on mounted test vault
        safety = self.eject_manager.check_ejection_safety()
        self.assertIsInstance(safety, EjectCheckResult)
        self.assertIn(safety.state, [DriveSafetyState.READY, DriveSafetyState.SAFE_TO_EJECT, DriveSafetyState.DRIVE_NOT_CONNECTED, DriveSafetyState.BLOCKED])

        # Emergency eject test with need_force_confirmation
        dry_eject = self.eject_manager.eject_vault(force=False)
        self.assertIn("ok", dry_eject)
        self.assertIn("state", dry_eject)

    def test_storage_intelligence_detailed_metrics(self):
        """Test detailed storage breakdown across SSD and HDD categories."""
        # Populate mock data in workspace
        mock_raw = os.path.join(self.ssd_dir, "raw", "import_source_preserved", "TEST_SUBJ_01")
        os.makedirs(mock_raw, exist_ok=True)
        with open(os.path.join(mock_raw, "study.dcm"), "wb") as f:
            f.write(b"0" * 4096)

        metrics = self.intelligence.get_detailed_storage_metrics()
        self.assertIn("mac_internal", metrics)
        self.assertIn("external_vault", metrics)
        self.assertIn("active_workspace_bytes", metrics["mac_internal"])
        self.assertIn("preserved_raw_bytes", metrics["mac_internal"])
        self.assertGreater(metrics["mac_internal"]["preserved_raw_bytes"], 0)

    def test_sync_manager_policy_and_overview(self):
        """Test Sync policy reading, updating, and overview generation."""
        overview = self.sync_manager.get_sync_overview()
        self.assertIn("external_connected", overview)
        self.assertIn("policy", overview)
        categories = overview["policy"]["categories"]
        self.assertEqual(len(categories), 7)

        policy = self.sync_manager.get_sync_policy()
        self.assertTrue(policy.get("enabled", True))
        categories_dict = policy.get("categories", {})
        self.assertIn("original_mri", categories_dict)

        # Test policy update
        updated = self.sync_manager.save_sync_policy({"categories": {"processed_mri": {"enabled": False}}})
        self.assertTrue(updated.get("ok"))
        self.assertFalse(updated["policy"]["categories"]["processed_mri"]["enabled"])

    def test_reconciliation_and_batch_registration(self):
        """Test ledger reconciliation and batch registration of discovered raw studies."""
        # Create 2 mock discovered studies on SSD and 1 in Vault
        ssd_raw = os.path.join(self.ssd_dir, "raw", "import_source_preserved", "M_TEST_01")
        ssd_app = os.path.join(self.ssd_dir, "app_data", "import_src", "M_TEST_02")
        vault_dicom = os.path.join(self.hdd_vault, "original_mri", "M_TEST_03")
        os.makedirs(ssd_raw, exist_ok=True)
        os.makedirs(ssd_app, exist_ok=True)
        os.makedirs(vault_dicom, exist_ok=True)

        for d in [ssd_raw, ssd_app, vault_dicom]:
            with open(os.path.join(d, "slice_001.dcm"), "wb") as f:
                f.write(b"DICOM_MOCK" * 10)

        recon = self.workspace_mgr.reconcile_studies()
        self.assertIn("total_discovered", recon)
        self.assertIn("total_registered", recon)
        self.assertIn("unregistered_count", recon)
        self.assertEqual(recon["total_registered"], 0)
        self.assertEqual(recon["unregistered_count"], 3)
        self.assertEqual(len(recon["unregistered"]), 3)

        # Batch register them
        res = self.workspace_mgr.batch_register_discovered(
            study_ids=["M_TEST_01", "M_TEST_02", "M_TEST_03"]
        )
        self.assertEqual(res["registered_count"], 3)
        self.assertEqual(res["total_ledger"], 3)

        # Re-verify ledger shows them registered
        ledger_path = os.path.join(self.ssd_dir, "app_data", "study_workspace_ledger.json")
        self.assertTrue(os.path.isfile(ledger_path))
        with open(ledger_path, "r") as f:
            ledger_data = json.load(f)
        self.assertIn("M_TEST_01", ledger_data)
        self.assertEqual(ledger_data["M_TEST_01"]["state"], "Registered")

        # Second reconciliation should now report 0 unregistered
        recon2 = self.workspace_mgr.reconcile_studies()
        self.assertEqual(recon2["unregistered_count"], 0)
        self.assertEqual(recon2["total_registered"], 3)

    def test_css_app_storage_and_transfer_api_endpoints(self):
        """Test css_app HTTP handler dispatch functions for storage, transfer, and reconciliation."""
        from app.css_app import storage_get, transfer_get, workspace_get, workspace_post

        # 1. Detailed storage metrics
        st_res = storage_get("detailed_metrics", {})
        self.assertTrue(st_res.get("ok"))
        self.assertIn("mac_internal", st_res)
        self.assertIn("external_vault", st_res)

        # 2. Sync overview
        sync_res = storage_get("sync_overview", {})
        self.assertTrue(sync_res.get("ok"))
        self.assertIn("policy", sync_res)

        # 3. Transfer summary and active jobs
        trans_res = transfer_get("summary", {})
        self.assertTrue(trans_res.get("ok"))
        self.assertIn("active_count", trans_res)
        self.assertIn("queued_count", trans_res)

        interrupted_res = transfer_get("interrupted", {})
        self.assertTrue(interrupted_res.get("ok"))
        self.assertIn("interrupted", interrupted_res)

        # 4. Workspace reconcile
        rec_res = workspace_get("reconcile", {})
        self.assertTrue(rec_res.get("ok"))
        self.assertIn("total_discovered", rec_res)
        self.assertIn("total_registered", rec_res)


if __name__ == "__main__":
    unittest.main()
