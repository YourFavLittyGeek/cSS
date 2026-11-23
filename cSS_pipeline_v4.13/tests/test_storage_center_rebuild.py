"""Tests for Master Storage Architecture Rebuild, Unified Transfer Engine, Sync Center, and Ejection.

Mission ID: PERCIVAL-STORAGE-CENTER-REBUILD-2026
"""

import os
import shutil
import tempfile
import time
import unittest

from uengine.unified_transfer_engine import (
    UnifiedTransferEngine,
    TransferProgress,
    compute_sha256,
    is_same_filesystem
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


class TestStorageCenterRebuild(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="percival_storage_test_")
        self.ssd_dir = os.path.join(self.tmp_dir, "ssd_workspace")
        self.hdd_mount = os.path.join(self.tmp_dir, "mock_hdd")
        self.hdd_vault = os.path.join(self.hdd_mount, VAULT_DIRNAME)
        os.makedirs(self.ssd_dir, exist_ok=True)
        os.makedirs(self.hdd_vault, exist_ok=True)

        self.transfer_engine = UnifiedTransferEngine(
            state_dir=os.path.join(self.ssd_dir, "app_data", "transfers")
        )
        self.paths_service = StoragePathsService(
            workspace_root=self.ssd_dir,
            configured_vault_mount=self.hdd_vault
        )
        self.state_service = StorageStateService(
            paths_service=self.paths_service
        )
        self.intelligence = StorageIntelligence(self.paths_service)
        self.eject_manager = EjectManager(
            paths_service=self.paths_service,
            state_service=self.state_service
        )
        self.sync_manager = SyncManager(
            paths_service=self.paths_service,
            state_service=self.state_service
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_unified_transfer_engine_streaming_and_sha256(self):
        """Test bounded streaming copy with in-flight SHA-256 computation and atomic commit."""
        src_file = os.path.join(self.ssd_dir, "sample.nii")
        data = b"PERCIVAL_NEURO_DATA_TEST_STREAMING" * 1000  # ~35 KB
        with open(src_file, "wb") as f:
            f.write(data)

        dst_file = os.path.join(self.hdd_vault, "sample.nii")
        rates = []

        def progress_cb(bytes_done, rate):
            rates.append((bytes_done, rate))

        ok, sha, bytes_copied = self.transfer_engine.copy_file_streaming(
            src=src_file,
            dst=dst_file,
            verify_sha=True,
            progress_callback=progress_cb,
            chunk_size=4096
        )

        self.assertTrue(ok)
        self.assertEqual(bytes_copied, len(data))
        self.assertEqual(sha, compute_sha256(src_file))
        self.assertEqual(sha, compute_sha256(dst_file))
        self.assertTrue(os.path.isfile(dst_file))
        # Ensure temporary file does not remain
        self.assertFalse(os.path.exists(dst_file + ".tmp"))

    def test_unified_transfer_engine_directory_transfer(self):
        """Test recursive directory transfer with progress ledger and verification."""
        src_study = os.path.join(self.ssd_dir, "STUDY_DIR_01")
        os.makedirs(os.path.join(src_study, "sub_dir"), exist_ok=True)
        with open(os.path.join(src_study, "file_a.dcm"), "wb") as f:
            f.write(b"DICOM_HEADER_A" * 50)
        with open(os.path.join(src_study, "sub_dir", "file_b.dcm"), "wb") as f:
            f.write(b"DICOM_HEADER_B" * 100)

        dst_study = os.path.join(self.hdd_vault, "STUDY_DIR_01")
        ok, msg, p_info = self.transfer_engine.transfer_path(
            src=src_study,
            dst=dst_study,
            operation="archive",
            study_id="STUDY_DIR_01",
            verify_sha=True
        )

        self.assertTrue(ok, msg)
        self.assertEqual(p_info["completed_files"], 2)
        self.assertTrue(os.path.isfile(os.path.join(dst_study, "file_a.dcm")))
        self.assertTrue(os.path.isfile(os.path.join(dst_study, "sub_dir", "file_b.dcm")))

    def test_storage_paths_containment_and_safety(self):
        """Test storage path normalization, containment checks, and directory resolution."""
        # Check valid containment within workspace
        valid_ssd_path = os.path.join(self.ssd_dir, "work", "STUDY-001")
        self.assertTrue(self.paths_service.is_contained_path(valid_ssd_path))

        # Check valid containment within vault
        valid_vault_path = os.path.join(self.hdd_vault, "ARCHIVE", "STUDY-001")
        self.assertTrue(self.paths_service.is_contained_path(valid_vault_path))

        # Check path traversal escape attempt
        escape_path = os.path.join(self.ssd_dir, "..", "..", "etc", "passwd")
        self.assertFalse(self.paths_service.is_contained_path(escape_path))

    def test_storage_state_service_journal(self):
        """Test transactional SQLite journal state recording and querying."""
        # 1. Record an auditable event
        self.state_service.record_audit_event(
            action="stage_started",
            result="success",
            study_id="STUDY-TEST-STATE",
            op_id="op_123",
            src="/mock/src",
            dst="/mock/dst",
            details={"notes": "test journal logging"}
        )

        events = self.state_service.get_audit_events(study_id="STUDY-TEST-STATE")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "stage_started")
        self.assertEqual(events[0]["result"], "success")

        # 2. Get storage overview
        overview = self.state_service.get_storage_overview()
        self.assertIn("mac_internal", overview)
        self.assertIn("external_vault", overview)
        self.assertEqual(overview["active_transfers"], 0)

    def test_storage_intelligence_classification(self):
        """Test categorization of files into the 16 recognized categories."""
        cat_dcm = self.intelligence.classify_path("/Volumes/Percival/Dicom/M01/MR.1.2.3.dcm")
        self.assertEqual(cat_dcm, StorageCategory.ORIGINAL_MRI)

        cat_cand = self.intelligence.classify_path("/Users/user/Percival_project/work/STUDY/candidates_albus.json")
        self.assertEqual(cat_cand, StorageCategory.ALBUS_CANDIDATES)

        cat_lum = self.intelligence.classify_path("/Users/user/Percival_project/work/STUDY/lumos_heatmap.nii.gz")
        self.assertEqual(cat_lum, StorageCategory.LUMOS_OUTPUTS)

        cat_db = self.intelligence.classify_path("/Users/user/Percival_project/app_data/pensieve.db")
        self.assertEqual(cat_db, StorageCategory.PENSIEVE_DATABASE)

    def test_eject_manager_safety_block_during_active_transfer(self):
        """Test that active transfer strictly blocks ejection."""
        # When no transfer is active
        check_idle = self.eject_manager.check_ejection_safety()
        self.assertTrue(check_idle.can_eject)
        self.assertEqual(check_idle.state, DriveSafetyState.SAFE_TO_EJECT)

        # Simulate active transfer job in state service journal
        with self.state_service._get_connection() as con:
            con.execute("""
                INSERT INTO transfer_jobs (job_id, study_id, operation, source_root, dest_root, status, created_at, updated_at)
                VALUES ('job_active_01', 'STUDY-ACTIVE', 'archive', '/ssd', '/vault', 'running', ?, ?)
            """, (time.time(), time.time()))

        check_busy = self.eject_manager.check_ejection_safety()
        self.assertFalse(check_busy.can_eject)
        self.assertEqual(check_busy.state, DriveSafetyState.IN_USE)
        self.assertEqual(check_busy.active_operations_count, 1)

    def test_sync_manager_preview_and_execution(self):
        """Test SyncManager calculating diffs and executing sync."""
        study_id = "STUDY_SYNC_01"
        ws_dir = os.path.join(self.ssd_dir, "work", study_id)
        os.makedirs(ws_dir, exist_ok=True)
        with open(os.path.join(ws_dir, "output.nii"), "wb") as f:
            f.write(b"GENERATED_SWI_OUTPUT" * 100)

        preview = self.sync_manager.generate_sync_preview(study_ids=[study_id])
        self.assertTrue(preview.can_proceed)
        self.assertGreater(preview.total_bytes, 0)
        self.assertEqual(len(preview.items_to_copy), 1)

        result = self.sync_manager.execute_sync(preview.to_dict())
        self.assertTrue(result["ok"])
        self.assertEqual(result["transferred_count"], 1)

        dest_file = os.path.join(self.hdd_vault, "studies", study_id, "output.nii")
        self.assertTrue(os.path.isfile(dest_file))


if __name__ == "__main__":
    unittest.main()
