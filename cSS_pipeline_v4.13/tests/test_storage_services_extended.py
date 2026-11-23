# test_storage_services_extended.py - Comprehensive verification for StorageService, CleaningManager, TransferManager
import os
import sys
import unittest
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))
sys.path.insert(0, os.path.join(ROOT, "app"))

from uengine.storage_service import StorageService
from uengine.cleaning_manager import CleaningManager
from uengine.transfer_manager import TransferManager
from uengine.vault import PercivalDataVault


class TestStorageServicesExtended(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="percival_storage_test_")
        self.workspace = os.path.join(self.tmp, "workspace")
        self.vault_dir = os.path.join(self.tmp, "PERCIVAL_VAULT")
        os.makedirs(self.workspace, exist_ok=True)
        self.vault = PercivalDataVault.create_vault(self.tmp, name="PERCIVAL_VAULT")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_storage_service_overview(self):
        ov = StorageService.get_overview(self.workspace, vault_root=self.vault.root_path, force_refresh=True)
        self.assertIn("mac_internal", ov)
        self.assertIn("external_vault", ov)
        self.assertIn("total_gb", ov["mac_internal"])
        self.assertIn("available_gb", ov["mac_internal"])
        self.assertIn("tier", ov["mac_internal"])
        self.assertTrue(ov["external_vault"]["connected"])
        self.assertEqual(ov["external_vault"]["root_path"], self.vault.root_path)

    def test_cleaning_manager_retention_and_quarantine(self):
        cm = CleaningManager(self.workspace)
        # Create temp file in app_data/scratch eligible for cleaning
        tmp_dir = os.path.join(self.workspace, "app_data", "scratch")
        os.makedirs(tmp_dir, exist_ok=True)
        test_file = os.path.join(tmp_dir, "test_temp.tmp")
        with open(test_file, "w") as f:
            f.write('{"test": 1}')
        # Set old mtime to exceed 7-day retention
        old_time = 1000000000
        os.utime(test_file, (old_time, old_time))

        dash = cm.get_dashboard()
        self.assertIn("categories", dash)
        self.assertIn("quarantine_count", dash)

        # Preview clean
        prev = cm.preview_clean(["temp_processing"])
        self.assertGreaterEqual(prev["total_items"], 1)

        # Execute clean with quarantine
        exec_res = cm.execute_clean(["temp_processing"], use_quarantine=True)
        self.assertTrue(exec_res["ok"])
        self.assertFalse(os.path.exists(test_file))

        # Check quarantine list
        qlist = cm.list_quarantine()
        self.assertGreaterEqual(len(qlist), 1)
        qid = qlist[0]["quarantine_id"]

        # Restore from quarantine
        res = cm.restore_quarantine(qid)
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.exists(test_file))

    def test_transfer_manager_policies_and_queue(self):
        tm = TransferManager(self.workspace, vault_root=self.vault.root_path)
        policies = tm.get_policies()
        self.assertIn("original_mri", policies)
        self.assertIn("pensieve_backups", policies)

        # Create dummy study files in review
        rev_dir = os.path.join(self.workspace, "review")
        os.makedirs(rev_dir, exist_ok=True)
        cand_csv = os.path.join(rev_dir, "SCAN01_candidates.csv")
        with open(cand_csv, "w") as f:
            f.write("cand_id,call\n1,cSS\n")

        # Enqueue study
        enq = tm.enqueue_study("SCAN01", action="archive")
        self.assertTrue(enq["ok"])
        q = tm.get_queue()
        self.assertEqual(len(q), 1)

        # Process next
        p = tm.process_next()
        self.assertTrue(p["ok"])
        self.assertEqual(p["status"], "completed")

    def test_detect_external_volumes_and_auto_vault(self):
        vols = PercivalDataVault.detect_external_volumes()
        self.assertIsInstance(vols, list)
        for v in vols:
            self.assertIn("mount_point", v)
            self.assertIn("has_vault", v)
            self.assertIn("read_only", v)

        # Test auto-create vault when connecting to mock drive directory
        mock_drive = os.path.join(self.tmp, "MockExternalDrive")
        os.makedirs(mock_drive, exist_ok=True)
        # Connect instance with auto_create_if_drive=True
        ok, msg = self.vault.connect(mock_drive, auto_create_if_drive=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.isdir(os.path.join(mock_drive, "PERCIVAL_VAULT")))
        self.assertEqual(self.vault.root_path, os.path.join(mock_drive, "PERCIVAL_VAULT"))
        self.assertTrue(os.path.exists(os.path.join(self.vault.root_path, "manifest", "vault_manifest.json")))

    def test_pensieve_flush_and_close(self):
        from uengine.pensieve import PensieveCoreMemory
        p = PensieveCoreMemory(self.vault)
        # Remember a test study
        res_rem = p.remember_study("TEST_CLEAN_01", "PSEUDO_01", "clean_slate", metadata={"notes": "Clean test"})
        self.assertIn(res_rem.get("status"), ("inserted", "idempotent_noop"))
        # Test flush and close
        res = p.flush_and_close()
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("closed"))



if __name__ == "__main__":
    unittest.main()
