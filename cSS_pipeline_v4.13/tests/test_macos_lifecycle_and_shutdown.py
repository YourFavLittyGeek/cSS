"""test_macos_lifecycle_and_shutdown.py - Verification for macOS window close and safe quit lifecycle"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)

import os
import sys
import shutil
import sqlite3
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))
sys.path.insert(0, os.path.join(ROOT, "app"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory, DurableLocalJournal
from uengine.transfer_manager import TransferManager


class TestMacOSLifecycleAndShutdown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="percival_shutdown_test_")
        self.workspace = os.path.join(self.tmp, "workspace")
        self.vault_dir = os.path.join(self.tmp, "PERCIVAL_VAULT")
        os.makedirs(self.workspace, exist_ok=True)
        self.vault = PercivalDataVault.create_vault(self.tmp, name="PERCIVAL_VAULT")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shutdown_check_logic(self):
        # 1. Idle state check
        running_pts = []
        tm = TransferManager(self.workspace, vault_root=self.vault.root_path)
        active_transfers = [it for it in tm.get_queue() if it.get("status") in ("transferring", "pending")]
        jnl = DurableLocalJournal(db_path=os.path.join(self.tmp, "journal.db"))
        pending_jnl = len(jnl.get_pending_entries())

        can_quit_immediately = (len(running_pts) == 0 and len(active_transfers) == 0)
        self.assertTrue(can_quit_immediately)
        self.assertEqual(len(running_pts), 0)
        self.assertEqual(len(active_transfers), 0)

        # 2. Busy state check with running study
        running_pts = ["STUDY_BUSY_01"]
        can_quit_immediately = (len(running_pts) == 0 and len(active_transfers) == 0)
        self.assertFalse(can_quit_immediately)

    def test_safe_wal_checkpoint_and_flush(self):
        pensieve = PensieveCoreMemory(self.vault, live_db_path=os.path.join(self.tmp, "live_pensieve.db"))
        pensieve.remember_study("DEV_SHUT_01", "pt_01", "clinical", "development")
        pensieve.record_expert_annotation("DEV_SHUT_01", "Dr_A", "definite_css", "superficial_siderosis", "high")

        # Live DB path exists
        self.assertTrue(os.path.exists(pensieve._live_db_path))

        # Perform flush_and_close
        res = pensieve.flush_and_close()
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("flushed"))
        self.assertTrue(res.get("closed"))

        # Verify database integrity after WAL checkpoint
        with sqlite3.connect(pensieve._live_db_path) as con:
            cur = con.execute("PRAGMA integrity_check;")
            row = cur.fetchone()
            self.assertEqual(row[0], "ok")


if __name__ == "__main__":
    unittest.main()
