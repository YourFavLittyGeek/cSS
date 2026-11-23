"""test_final_master_delivery.py - Comprehensive Verification Suite for PERCIVAL Final Master Delivery.

Tests:
1. SetupWizard (Steps 1-6, persistence, resumption)
2. StartupHealthCheck (19 points, auto-repair, status tiers)
3. StagingManager (space estimate, SHA-256 verification, cleanup, safe pruning)
4. StorageAdvisor (capacity tiers, retention rules, reclamation recommendations)
5. PercivalDataVault & Disconnection Management (UUID, degraded mode, transfer queue, emergency quota)
6. JobRecoveryManager (8 pipeline stages, atomic progression, crash recovery)
7. PensieveBackupEngine (sqlite3.Connection.backup, WAL, integrity checks, rotation, restore)
8. LegacyMigrationEngine (discovery, structured options, non-destructive migration)
9. Identity & Password-Free Architecture (default unlocked, optional app lock toggle)
10. FileManager (dual-storage topology, status classification)
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unified_engine"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from uengine.wizard import SetupWizard
from uengine.health import StartupHealthCheck, HEALTHY, HEALTHY_WITH_WARNINGS, DEGRADED_MODE, BLOCKED
from uengine.staging import StagingManager
from uengine.storage_advisor import StorageAdvisor, TIER_HEALTHY, TIER_EMERGENCY
from uengine.vault import PercivalDataVault, TransferQueueManager
from uengine.recovery import JobRecoveryManager, PIPELINE_STAGES
from uengine.pensieve_backup import PensieveBackupEngine
from uengine.legacy_migration import LegacyMigrationEngine
from uengine.file_manager import FileManager, STATUS_LOCAL_ONLY, STATUS_SYNCHRONIZED, STATUS_DRIVE_REQUIRED
from identity import Identity, IdentityError, VaultLocked


class TestFinalMasterDelivery(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="percival_final_delivery_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_1_setup_wizard_six_steps(self):
        wiz = SetupWizard(self.test_dir)
        self.assertFalse(wiz.is_completed())

        # Step 1
        s1 = wiz.step1_inspect_system()
        self.assertIn("os_name", s1)
        self.assertIn("ram_total_gb", s1)
        self.assertIn("recommended_concurrency", s1)

        # Step 2
        s2 = wiz.step2_configure_storage(local_workspace=self.test_dir)
        self.assertTrue(s2["valid"])

        # Step 3
        s3 = wiz.step3_detect_volumes()
        self.assertIn("volumes", s3)

        # Step 4
        s4 = wiz.step4_scan_legacy_data([self.test_dir])
        self.assertIn("total_items", s4)

        # Step 5
        s5 = wiz.step5_generate_migration_plan()
        self.assertIn("estimated_space_reclaimed_gb", s5)

        # Step 6
        s6 = wiz.step6_finalize()
        self.assertEqual(s6["status"], "completed")
        self.assertTrue(wiz.is_completed())

        # Verify resumption
        wiz_reloaded = SetupWizard(self.test_dir)
        self.assertTrue(wiz_reloaded.is_completed())

    def test_2_startup_health_check_nineteen_checks(self):
        hc = StartupHealthCheck(self.test_dir)
        res = hc.run_all(auto_repair=True)
        self.assertEqual(res["total_checks"], 19)
        self.assertIn(res["status"], [HEALTHY, HEALTHY_WITH_WARNINGS])
        self.assertGreaterEqual(res["passed"], 14)
        self.assertIsInstance(res["repairs_applied"], list)

        # Verify shutdown sentinel
        hc.mark_clean_shutdown()
        self.assertTrue(os.path.exists(hc.sentinel_file))

    def test_3_staging_and_archival(self):
        sm = StagingManager(self.test_dir)
        test_file = os.path.join(self.test_dir, "brain_swi.nii")
        with open(test_file, "wb") as f:
            f.write(b"SYNTHETIC_BRAIN_IMAGE_BYTES" * 100)

        # Estimate space
        est = sm.estimate_staging_space([test_file])
        self.assertTrue(est["is_sufficient"])

        # Stage
        stg_res = sm.stage_study("STU001", [test_file], verify=True)
        self.assertEqual(len(stg_res["files"]), 1)
        staged_path = stg_res["files"][0]["staged"]
        self.assertTrue(os.path.exists(staged_path))

        # Archive
        vault_dest = os.path.join(self.test_dir, "mock_vault", "processed_mri")
        arch_res = sm.archive_results("STU001", [staged_path], vault_dest, verify=True)
        self.assertEqual(arch_res["archived_count"], 1)
        self.assertTrue(os.path.exists(arch_res["files"][0]["vault"]))

        # Cleanup staging
        cln = sm.cleanup_staging("STU001")
        self.assertTrue(cln["cleaned"])
        self.assertFalse(os.path.exists(os.path.dirname(staged_path)))

        # Retention policy: removal of local originals when disabled vs enabled
        ret_policy_off = sm.prune_local_originals("STU001", [test_file], [arch_res["files"][0]["vault"]], policy_allowed=False)
        self.assertFalse(ret_policy_off["pruned"])
        self.assertTrue(os.path.exists(test_file))

        ret_policy_on = sm.prune_local_originals("STU001", [test_file], [arch_res["files"][0]["vault"]], policy_allowed=True)
        self.assertTrue(ret_policy_on["pruned"])
        self.assertFalse(os.path.exists(test_file))

    def test_4_storage_advisor_and_reclamation(self):
        sa = StorageAdvisor(self.test_dir)
        cap = sa.evaluate_capacity()
        self.assertIn("tier", cap)
        self.assertIn("free_percent", cap)

        # Generate fake expired scratch file
        os.makedirs(sa.scratch_dir, exist_ok=True)
        old_scratch = os.path.join(sa.scratch_dir, "old_tmp.dat")
        with open(old_scratch, "wb") as f:
            f.write(b"SCRATCH_DATA" * 50)
        # Set mtime back 10 days
        past_time = time.time() - (10 * 86400)
        os.utime(old_scratch, (past_time, past_time))

        recs = sa.generate_recommendations(scratch_days=7)
        self.assertGreaterEqual(recs["total_reclaimable_bytes"], 0)
        
        prune_res = sa.execute_prune("prune_scratch", days_threshold=7)
        self.assertGreaterEqual(prune_res["items_removed"], 1)
        self.assertFalse(os.path.exists(old_scratch))

    def test_5_vault_disconnection_and_transfers(self):
        vault_root = os.path.join(self.test_dir, "VOLUMES", "PERCIVAL_VAULT")
        v = PercivalDataVault.create_vault(os.path.dirname(vault_root), name="PERCIVAL_VAULT")
        self.assertTrue(v.is_connected())
        self.assertIsNotNone(v.volume_uuid)

        st = v.get_connection_status()
        self.assertTrue(st["connected"])
        self.assertFalse(st["degraded_mode"])
        self.assertEqual(st["archived_badge"], "ARCHIVED — ACCESSIBLE")

        # Disconnection & degraded mode
        v_disc = PercivalDataVault("/nonexistent/drive")
        st_disc = v_disc.get_connection_status()
        self.assertFalse(st_disc["connected"])
        self.assertTrue(st_disc["degraded_mode"])
        self.assertEqual(st_disc["archived_badge"], "ARCHIVED — DRIVE REQUIRED")
        self.assertIn("DEGRADED MODE", st_disc["banner_message"])

        # Emergency scratch quota
        eq = PercivalDataVault.get_emergency_scratch_quota(self.test_dir)
        self.assertIn("emergency_quota_gb", eq)

        # TransferQueueManager
        tqm = TransferQueueManager(self.test_dir)
        src = os.path.join(self.test_dir, "output.nii")
        with open(src, "wb") as f:
            f.write(b"RESULT_NIFTI" * 20)
        dst = os.path.join(v.root_path, "processed_mri", "output.nii")

        tx = tqm.enqueue("job_99", src, dst)
        self.assertEqual(tx["status"], "pending")

        paused_n = tqm.pause_for_disconnection()
        resumed = tqm.resume_transfers(v)
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0]["status"], "completed")
        self.assertTrue(os.path.exists(dst))

    def test_6_job_recovery_lifecycle(self):
        jrm = JobRecoveryManager(self.test_dir)
        jid = jrm.start_job("STUDY_REC", "PAT_REC")

        # Run stages 1 and 2
        jrm.start_stage(jid, PIPELINE_STAGES[0])
        jrm.complete_stage(jid, PIPELINE_STAGES[0])
        jrm.start_stage(jid, PIPELINE_STAGES[1])
        jrm.complete_stage(jid, PIPELINE_STAGES[1])

        # Stage 3 in progress when crash occurs
        jrm.start_stage(jid, PIPELINE_STAGES[2])

        # Recovery query
        resumable = jrm.get_resumable_jobs()
        self.assertEqual(len(resumable), 1)
        self.assertEqual(resumable[0]["completed_stages"], [PIPELINE_STAGES[0], PIPELINE_STAGES[1]])
        self.assertEqual(resumable[0]["resume_from_stage"], PIPELINE_STAGES[2])

        # Rollback partial stage
        jrm.rollback_incomplete_stage(jid, PIPELINE_STAGES[2])

        # Resume and complete all
        for s in PIPELINE_STAGES[2:]:
            jrm.start_stage(jid, s)
            jrm.complete_stage(jid, s)

        summary = jrm.get_recovery_summary()
        self.assertEqual(summary["completed_jobs"], 1)

    def test_7_pensieve_backup_and_restoration(self):
        db_path = os.path.join(self.test_dir, "pensieve.db")
        vault_dest = os.path.join(self.test_dir, "vault_backup")
        sec_dest = os.path.join(self.test_dir, "sec_backup")

        # Init SQLite DB in WAL mode
        con = sqlite3.connect(db_path)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("CREATE TABLE candidates (id INT PRIMARY KEY, score REAL);")
        con.execute("INSERT INTO candidates VALUES (1, 0.98);")
        con.commit()
        con.close()

        pbe = PensieveBackupEngine(db_path, vault_dir=vault_dest, secondary_backup_dir=sec_dest)
        ok, msg = pbe.check_source_integrity()
        self.assertTrue(ok)

        # Snapshot
        snap_res = pbe.create_snapshot(label="test_snap")
        self.assertTrue(snap_res["success"])
        self.assertEqual(len(snap_res["destinations"]), 2)

        # Verification
        v_res = pbe.verify_backup(snap_res["destinations"][0])
        self.assertTrue(v_res["valid"])
        self.assertIn("candidates", v_res["tables"])

        # Restoration
        rest_res = pbe.restore_backup(snap_res["destinations"][0])
        self.assertTrue(rest_res["success"])
        self.assertTrue(os.path.exists(rest_res["safety_backup"]))

    def test_8_legacy_migration_engine(self):
        lme = LegacyMigrationEngine(self.test_dir)
        # Create mock legacy directory
        leg_dir = os.path.join(self.test_dir, "legacy_study")
        os.makedirs(leg_dir)
        with open(os.path.join(leg_dir, "LEGACY01_candidates.csv"), "w") as f:
            f.write("cand_id,score\n1,0.85\n")

        disc = lme.discover_legacy_data([self.test_dir])
        self.assertGreaterEqual(disc["total_studies"], 1)

        plan = lme.create_migration_plan(disc["studies"], default_strategy="import_pensieve_only")
        self.assertIn("import_pensieve_only", plan["strategy_breakdown"])

        mig_res = lme.execute_migration(plan, dry_run=False)
        self.assertEqual(mig_res["migrated"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "review", "LEGACY01_candidates.csv")))

    def test_9_password_free_launch_and_optional_lock(self):
        # 1. Default launch: No password required
        idm = Identity(self.test_dir, app_lock_enabled=False)
        self.assertTrue(idm.unlocked())
        self.assertFalse(idm.app_lock_enabled)

        # Can store and view identities without unlocking
        pid = idm.add_patient(mrn="MRN_DEFAULT", name="Free Person")
        sid = idm.add_study(pid, "KEY01", "CODE01", accession="ACC01")
        view_std = idm.view(sid, "standard")
        self.assertEqual(view_std["patient_name"], "Free Person")
        self.assertEqual(view_std["accession"], "ACC01")

        # 2. Optional opt-in to app lock
        idm.enable_app_lock("securepassphrase123")
        self.assertTrue(idm.app_lock_enabled)
        self.assertTrue(idm.vault_exists())

        # When locked, identifiers are guarded
        idm.lock()
        self.assertFalse(idm.unlocked())
        v_locked = idm.view(sid, "standard")
        self.assertTrue(v_locked.get("locked"))
        self.assertNotIn("patient_name", v_locked)

        # Unlocking returns identifiers
        idm.unlock("securepassphrase123")
        self.assertTrue(idm.unlocked())
        v_unlocked = idm.view(sid, "standard")
        self.assertEqual(v_unlocked["patient_name"], "Free Person")

        # 3. Disabling app lock returns to password-free
        idm.disable_app_lock("securepassphrase123")
        self.assertFalse(idm.app_lock_enabled)
        self.assertTrue(idm.unlocked())

    def test_10_file_manager_dual_storage(self):
        vault_path = os.path.join(self.test_dir, "TEST_VAULT")
        v = PercivalDataVault.create_vault(self.test_dir, name="TEST_VAULT")
        fm = FileManager(self.test_dir, vault_root=v.root_path)

        # Create local study
        with open(os.path.join(fm.review_dir, "FM01_candidates.csv"), "w") as f:
            f.write("cand_id\n1\n")

        studies = fm.list_studies()
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0]["study_code"], "FM01")
        self.assertEqual(studies[0]["status"], STATUS_LOCAL_ONLY)

        # Archive to vault
        arch = fm.archive_study("FM01")
        self.assertGreaterEqual(arch["files_archived"], 1)

        # Now synchronized
        studies_sync = fm.list_studies()
        self.assertEqual(studies_sync[0]["status"], STATUS_SYNCHRONIZED)

        # Verify checksums
        vc = fm.verify_study_checksums("FM01")
        self.assertTrue(vc["all_match"])


if __name__ == "__main__":
    unittest.main()
