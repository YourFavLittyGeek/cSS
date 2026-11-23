"""test_vault.py - Verification of PERCIVAL DATA VAULT Architecture"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault, VAULT_DIRS

class TestPercivalDataVault(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="pvault_test_")
        self.dest_dir = os.path.join(self.temp_dir, "external_ssd")
        os.makedirs(self.dest_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vault_creation_and_dirs(self):
        vault = PercivalDataVault.create_vault(self.dest_dir, name="VAULT_ALPHA")
        self.assertTrue(vault.is_connected())
        self.assertTrue(os.path.exists(vault.root_path))
        self.assertTrue(os.path.exists(vault.path("manifest", "vault_manifest.json")))
        for d in VAULT_DIRS:
            self.assertTrue(os.path.isdir(os.path.join(vault.root_path, d)), f"Missing dir: {d}")

    def test_integrity_and_stats(self):
        vault = PercivalDataVault.create_vault(self.dest_dir, name="VAULT_BETA")
        check = vault.verify_integrity()
        self.assertTrue(check["ok"])
        self.assertEqual(len(check["missing_dirs"]), 0)

        stats = vault.get_storage_stats()
        self.assertTrue(stats["connected"])
        self.assertGreater(stats["free_bytes"], 0)
        self.assertIn("categories", stats)

    def test_reconnection_and_eject(self):
        vault = PercivalDataVault.create_vault(self.dest_dir, name="VAULT_GAMMA")
        vpath = vault.root_path
        
        # Test safe eject
        ok, msg = vault.safe_eject()
        self.assertTrue(ok)
        self.assertFalse(vault.is_connected())

        # Test reconnect
        vault2 = PercivalDataVault(vpath)
        self.assertTrue(vault2.is_connected())
        self.assertEqual(vault2.root_path, vpath)

    def test_migration_and_backup(self):
        vault = PercivalDataVault.create_vault(self.dest_dir, name="VAULT_DELTA")
        
        # Write dummy model artifact
        test_model_file = vault.path("models", "ALBUS", "model_v1.json")
        with open(test_model_file, "w") as f:
            f.write('{"version": "albus-1"}')

        # Test backup
        backup_dir = os.path.join(self.temp_dir, "secondary_backup_drive")
        ok_b, msg_b = vault.create_backup(backup_dir)
        self.assertTrue(ok_b)
        self.assertTrue(os.path.exists(backup_dir))

        # Test migration
        new_parent = os.path.join(self.temp_dir, "faster_nvme")
        os.makedirs(new_parent, exist_ok=True)
        ok_m, msg_m = vault.migrate_data(new_parent)
        self.assertTrue(ok_m)
        self.assertTrue(vault.is_connected())
        self.assertTrue(os.path.exists(vault.path("models", "ALBUS", "model_v1.json")))

if __name__ == "__main__":
    unittest.main()
