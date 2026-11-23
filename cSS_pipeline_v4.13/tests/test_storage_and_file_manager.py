"""test_storage_and_file_manager.py - Comprehensive Unit & Integration Tests for
PERCIVAL File Manager, Category Explorer, and Working Directory Migration.
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest

from uengine.file_manager import FileManager
from uengine.working_dir_migration import WorkingDirMigrationEngine


class TestFileManagerAndStorage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="percival_fm_test_")
        self.workspace_dir = os.path.join(self.tmp_dir, "workspace")
        self.vault_dir = os.path.join(self.tmp_dir, "mock_vault")
        os.makedirs(self.workspace_dir, exist_ok=True)
        os.makedirs(os.path.join(self.vault_dir, "manifest"), exist_ok=True)

        with open(os.path.join(self.vault_dir, "manifest", "vault_manifest.json"), "w") as f:
            json.dump({"vault_id": "test_vault_001", "created_at": "2026-11-22"}, f)

        # Populate sample files in workspace
        os.makedirs(os.path.join(self.workspace_dir, "data"), exist_ok=True)
        os.makedirs(os.path.join(self.workspace_dir, "review"), exist_ok=True)
        os.makedirs(os.path.join(self.workspace_dir, "app_data"), exist_ok=True)

        self.sample_mri = os.path.join(self.workspace_dir, "data", "test_mri.nii.gz")
        with open(self.sample_mri, "wb") as f:
            f.write(b"NIFTI_MOCK_IMAGE_DATA_1234567890")

        self.fm = FileManager(self.workspace_dir, vault_root=self.vault_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_categories_enumeration(self):
        """Test category resolution, descriptions, and existence indicators."""
        cats = self.fm.get_categories()
        self.assertIn("working", cats)
        self.assertIn("vault", cats)
        self.assertIn("originals", cats)
        self.assertIn("processed", cats)
        self.assertIn("albus", cats)
        self.assertIn("lumos", cats)
        self.assertIn("nox", cats)
        self.assertIn("pensieve", cats)
        self.assertTrue(cats["working"]["exists"])
        self.assertTrue(cats["vault"]["exists"])

    def test_02_browse_category_path(self):
        """Test listing files within a category with size, date, and security containment."""
        res = self.fm.browse_category_path("originals")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["items"][0]["name"], "test_mri.nii.gz")
        self.assertFalse(res["items"][0]["is_dir"])

        # Path traversal prevention
        traversal = self.fm.browse_category_path("originals", subpath="../../etc")
        self.assertFalse(traversal["ok"])
        self.assertIn("Access denied", traversal["error"])

    def test_03_create_directory_and_rename(self):
        """Test creating directories and renaming items."""
        mk_res = self.fm.create_directory(self.workspace_dir, "new_folder")
        self.assertTrue(mk_res["ok"])
        self.assertTrue(os.path.isdir(mk_res["path"]))

        ren_res = self.fm.rename_item(mk_res["path"], "renamed_folder")
        self.assertTrue(ren_res["ok"])
        self.assertTrue(os.path.isdir(os.path.join(self.workspace_dir, "renamed_folder")))
        self.assertFalse(os.path.exists(mk_res["path"]))

    def test_04_copy_item_with_conflict_modes(self):
        """Test copy with keep_both, skip, and replace conflict modes."""
        dst_dir = os.path.join(self.workspace_dir, "review")
        
        # 1. First copy
        c1 = self.fm.copy_item(self.sample_mri, dst_dir)
        self.assertTrue(c1["ok"])
        target = os.path.join(dst_dir, "test_mri.nii.gz")
        self.assertTrue(os.path.exists(target))

        # 2. Copy with skip
        c_skip = self.fm.copy_item(self.sample_mri, dst_dir, conflict_mode="skip")
        self.assertTrue(c_skip["ok"])
        self.assertTrue(c_skip.get("skipped"))

        # 3. Copy with keep_both
        c_both = self.fm.copy_item(self.sample_mri, dst_dir, conflict_mode="keep_both")
        self.assertTrue(c_both["ok"])
        self.assertIn("test_mri_copy_", c_both["target_path"])
        self.assertTrue(os.path.exists(c_both["target_path"]))

    def test_05_move_and_delete_with_safety_guard(self):
        """Test move and safe deletion with protected file guards."""
        dst_dir = os.path.join(self.workspace_dir, "review")
        mv_res = self.fm.move_item(self.sample_mri, dst_dir)
        self.assertTrue(mv_res["ok"])
        self.assertFalse(os.path.exists(self.sample_mri))
        self.assertTrue(os.path.exists(mv_res["target_path"]))

        # Refusal without explicit confirmation
        del_refuse = self.fm.delete_item(mv_res["target_path"], confirm=False)
        self.assertFalse(del_refuse["ok"])
        self.assertTrue(os.path.exists(mv_res["target_path"]))

        # Refusal to delete critical Pensieve file
        fake_db = os.path.join(self.workspace_dir, "pensieve_core.db")
        open(fake_db, "w").close()
        del_db = self.fm.delete_item(fake_db, confirm=True)
        self.assertFalse(del_db["ok"])
        self.assertIn("Refused", del_db["error"])
        self.assertTrue(os.path.exists(fake_db))

        # Confirmed deletion of regular file
        del_res = self.fm.delete_item(mv_res["target_path"], confirm=True)
        self.assertTrue(del_res["ok"])
        self.assertFalse(os.path.exists(mv_res["target_path"]))

    def test_06_archive_and_restore_with_sha256(self):
        """Test archiving to Data Vault and restoring to local SSD with SHA-256 verification."""
        test_file = os.path.join(self.workspace_dir, "data", "archive_target.txt")
        with open(test_file, "w") as f:
            f.write("RESEARCH_INTEGRITY_DATA_TO_ARCHIVE")

        # Archive to vault
        arch_res = self.fm.archive_entry(test_file, vault_category="studies")
        self.assertTrue(arch_res["ok"])
        self.assertTrue(arch_res.get("verified"))
        vault_file = arch_res["target_path"]
        self.assertTrue(os.path.exists(vault_file))

        # Restore from vault
        restore_dir = os.path.join(self.workspace_dir, "restored")
        rest_res = self.fm.restore_entry(vault_file, restore_dir)
        self.assertTrue(rest_res["ok"])
        self.assertTrue(rest_res.get("verified"))
        self.assertTrue(os.path.exists(os.path.join(restore_dir, "archive_target.txt")))

    def test_07_working_dir_migration_planning(self):
        """Test WorkingDirMigrationEngine planning, discovery, and active job checks."""
        migrator = WorkingDirMigrationEngine(self.workspace_dir)
        target_dir = os.path.join(self.tmp_dir, "new_workspace")

        plan = migrator.plan_migration(target_dir)
        self.assertTrue(plan["ok"])
        self.assertGreater(plan["file_count"], 0)
        self.assertGreater(plan["target_free_gb"], 0)

        # Active job blocking
        pat_file = os.path.join(self.workspace_dir, "app_data", "patients.json")
        with open(pat_file, "w") as f:
            json.dump([{"code": "SUBJ_999", "status": "running", "step": "SynthSeg"}], f)

        blocked_plan = migrator.plan_migration(target_dir)
        self.assertFalse(blocked_plan["ok"])
        self.assertIn("Pipeline jobs are currently running", blocked_plan["error"])

    def test_08_working_dir_migration_execution(self):
        """Test transactional working directory migration with journal and file verification."""
        # Reset patients.json to idle
        pat_file = os.path.join(self.workspace_dir, "app_data", "patients.json")
        with open(pat_file, "w") as f:
            json.dump([{"code": "SUBJ_999", "status": "done"}], f)

        migrator = WorkingDirMigrationEngine(self.workspace_dir)
        target_dir = os.path.join(self.tmp_dir, "migrated_workspace")

        exec_res = migrator.execute_migration(target_dir, verify_checksums=True)
        self.assertTrue(exec_res["ok"])
        self.assertTrue(exec_res["old_dir_preserved"])
        self.assertGreater(exec_res["files_migrated"], 0)

        # Verify destination files
        self.assertTrue(os.path.exists(os.path.join(target_dir, "data", "test_mri.nii.gz")))
        self.assertTrue(os.path.exists(os.path.join(target_dir, "app_data", "patients.json")))

        # Verify old files preserved
        self.assertTrue(os.path.exists(self.sample_mri))

        # Verify migration journal
        journal_path = os.path.join(self.workspace_dir, "app_data", "working_dir_migration_journal.json")
        self.assertTrue(os.path.exists(journal_path))
        with open(journal_path, "r") as f:
            j = json.load(f)
        self.assertEqual(j["status"], "completed")
        self.assertEqual(j["copied_count"], exec_res["files_migrated"])


if __name__ == "__main__":
    unittest.main()
