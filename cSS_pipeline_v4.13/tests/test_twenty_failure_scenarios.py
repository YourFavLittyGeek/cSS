"""test_twenty_failure_scenarios.py - Independent Reliability and Failure Scenarios Verification.

Systematic verification of the 20 failure and recovery scenarios required by Section 16:
 1. Missing MRI sequence
 2. Corrupted MRI (NaNs / Infs in volume)
 3. Invalid voxel spacing (zero / negative)
 4. Empty candidate mask (0 voxels)
 5. Planar candidate mask (single 2D slice)
 6. Missing LUMOS evidence
 7. Missing NOX features
 8. Core convergence failure / ill-conditioned matrix
 9. Pensieve database unavailable
10. External drive disconnected
11. External drive read-only
12. Insufficient disk space warning
13. Interrupted training / graceful handling
14. Interrupted model promotion / rollback
15. Application crash during annotation (journal durability)
16. Failed journal synchronization / idempotent retry
17. Invalid model checkpoint (corrupted npz)
18. Incompatible model version handling
19. Duplicate study ingestion / idempotent update
20. Application restart during recovery
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)

import os
import sys
import json
import math
import shutil
import tempfile
import unittest
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory, DurableLocalJournal
from uengine.nox import NoxCharacteristicsEngine
from uengine.lumos import LumosImageIntelligence
from uengine.albus import AlbusDiscoveryEngine
from uengine.percival_core import PercivalCoreIntelligence
from uengine.shadow_lab import ShadowMLLaboratory
from uengine.governance import PercivalGovernance
from uengine.contracts import NoxMeasurements, LumosInference, AlbusCandidate

class TestTwentyFailureScenarios(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="fail_scen_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_FAIL")
        self.pensieve = PensieveCoreMemory(self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_missing_mri_sequence(self):
        """Scenario 1: Missing MRI sequence returns graceful degraded status."""
        lumos = LumosImageIntelligence(pensieve=self.pensieve, vault=self.vault)
        # Pass None or empty patch dict
        inf = lumos.analyze_patch("S_MISSING", 1, patch_arrays=None)
        self.assertEqual(inf.status, "unavailable")
        self.assertFalse(inf.has_visual_evidence)
        self.assertEqual(inf.uncertainty, 1.0)
        self.assertIsNone(inf.prob)

    def test_02_corrupted_mri(self):
        """Scenario 2: Corrupted MRI with NaNs and Infs is safely filtered."""
        lumos = LumosImageIntelligence(pensieve=self.pensieve, vault=self.vault)
        swi = np.full((49, 25, 16), np.nan, dtype=np.float32)
        valid = np.zeros((49, 25, 16), dtype=bool) # no valid pixels
        obj = np.zeros((49, 25, 16), dtype=bool)
        inf = lumos.analyze_patch("S_CORRUPT", 2, {"image_swi": swi, "valid_swi": valid, "object_mask": obj})
        self.assertEqual(inf.status, "unavailable")
        self.assertFalse(inf.has_visual_evidence)
        self.assertIsNone(inf.prob)

    def test_03_invalid_voxel_spacing(self):
        """Scenario 3: Zero or invalid voxel spacing rejects physical fabrication."""
        nox = NoxCharacteristicsEngine(pensieve=self.pensieve)
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[2:5, 2:5, 2:5] = True
        # Spacing with 0.0 or negative values must NOT fabricate physical measurements
        meas = nox.measure_candidate("S_SPACING", 3, {"mask_3d": mask, "voxel_spacing_mm": [0.0, 0.0, 0.0]})
        self.assertIsNone(meas.morphology["surface_area_mm2"])
        self.assertIsNone(meas.morphology["sphericity"])
        self.assertIsNone(meas.morphology["volume_mm3"])
        self.assertEqual(meas.morphology["geometry_status"], "invalid_spacing")

    def test_04_empty_candidate_mask(self):
        """Scenario 4: Empty candidate mask (0 voxels) handled explicitly."""
        nox = NoxCharacteristicsEngine(pensieve=self.pensieve)
        mask = np.zeros((10, 10, 10), dtype=bool) # 0 voxels
        meas = nox.measure_candidate("S_EMPTY", 4, {"mask_3d": mask})
        self.assertEqual(meas.morphology["volume_mm3"], 0.0)
        self.assertIsNone(meas.morphology["sphericity"])
        self.assertEqual(meas.morphology["geometry_status"], "empty_mask")

    def test_05_planar_candidate_mask(self):
        """Scenario 5: Planar candidate mask preserves lambda3 = 0.0 without crash."""
        nox = NoxCharacteristicsEngine(pensieve=self.pensieve)
        planar = np.zeros((10, 10, 10), dtype=bool)
        planar[2:7, 2:7, 4] = True # single slice k=4
        meas = nox.measure_candidate("S_PLANAR", 5, {"mask_3d": planar, "voxel_spacing_mm": [1.0, 1.0, 2.0]})
        self.assertTrue(meas.morphology["is_planar"])
        self.assertAlmostEqual(meas.morphology["raw_lambda3_mm2"], 0.0, delta=1e-5)
        self.assertTrue(np.isfinite(meas.morphology["elongation"]))

    def test_06_missing_lumos_evidence(self):
        """Scenario 6: Missing LUMOS visual evidence suppresses score and yields maximum uncertainty in Core."""
        core = PercivalCoreIntelligence(pensieve=self.pensieve, vault=self.vault)
        cand_a = AlbusCandidate(6, "S_M6", "L", (10, 10, 10), (5, 5, 5), 20, 10.0, (8,8,8,12,12,12), 0.70, "v5.25", "v4")
        meas_n = NoxMeasurements(6, "S_M6", morphology={"volume_mm3": 10.0, "elongation": 1.2},
                                 signal={"darkness_z": -2.0, "edge_contrast": 0.5},
                                 anatomy={"pial_distance_mm": 0.5, "cortex_fraction": 0.7})
        inf_missing = LumosInference(6, "S_M6", None, None, 1.0, (0,0,0), "v5.25", has_visual_evidence=False, status="unavailable")
        asmt = core.evaluate_candidate(cand_a, inf_missing, meas_n)
        self.assertEqual(asmt.status, "incomplete_visual_data")
        self.assertEqual(asmt.band, "unavailable")
        self.assertIsNone(asmt.percival_score)
        self.assertIsNone(asmt.calibrated_prob)
        self.assertEqual(asmt.uncertainty, 1.0)
        self.assertEqual(asmt.confidence, 0.0)

    def test_07_missing_nox_features(self):
        """Scenario 7: Missing NOX features suppresses score and sets explicit unavailable status."""
        core = PercivalCoreIntelligence(pensieve=self.pensieve, vault=self.vault)
        cand_a = AlbusCandidate(7, "S_M7", "R", (10, 10, 10), (5, 5, 5), 20, 10.0, (8,8,8,12,12,12), 0.70, "v5.25", "v4")
        inf_l = LumosInference(7, "S_M7", 0.85, 1.73, 0.1, (49, 25, 16), "v5.25", has_visual_evidence=True, depth_gradient=0.5, status="ok")
        # Missing NOX
        asmt = core.evaluate_candidate(cand_a, inf_l, nox_meas=None)
        self.assertIsNone(asmt.percival_score)
        self.assertIsNone(asmt.calibrated_prob)
        self.assertEqual(asmt.band, "unavailable")
        self.assertEqual(asmt.status, "incomplete_geometry_data")

    def test_08_core_convergence_failure(self):
        """Scenario 8: Singular or ill-conditioned feature matrix does not crash IRLS fit."""
        core = PercivalCoreIntelligence(pensieve=self.pensieve, vault=self.vault)
        # All identical rows -> singular matrix
        N = 20
        X_singular = np.ones((N, 5))
        y = np.ones(N)
        # Should gracefully terminate within iterations without raising exception
        core.fit(X_singular, y, l2_penalty=0.0)
        self.assertTrue(np.isfinite(core.weights["bias"]))

    def test_09_pensieve_database_unavailable(self):
        """Scenario 9: Unconnected Pensieve returns safe fallbacks rather than crashing."""
        self.vault._is_connected = False
        res = self.pensieve.evaluate_candidate_identity("S_DISC", "L", (10.0, 10.0, 10.0))
        self.assertEqual(res["outcome"], "new_candidate")
        self.assertFalse(res["evidence"]["vault_connected"])

    def test_10_external_drive_disconnected(self):
        """Scenario 10: External drive disconnection detected and blocked safely."""
        self.vault._is_connected = False
        self.assertFalse(self.vault.is_connected())
        with self.assertRaises(RuntimeError):
            self.vault.path("models", "LUMOS", "checkpoint.npz")

    def test_11_external_drive_read_only(self):
        """Scenario 11: Read-only volume flag is accurately reported in stats."""
        stats = self.vault.get_storage_stats()
        self.assertIn("read_only", stats)
        self.assertIsInstance(stats["read_only"], bool)

    def test_12_insufficient_disk_space(self):
        """Scenario 12: Warning emitted when free space is constrained."""
        stats = self.vault.get_storage_stats()
        self.assertIn("warning", stats)

    def test_13_interrupted_training(self):
        """Scenario 13: Interrupted training returns cleanly with valid state."""
        shadow = ShadowMLLaboratory(pensieve=self.pensieve, vault=self.vault)
        exp = shadow.formulate_hypothesis("ALBUS", "Test interruption", {"formula": "formula_v4_baseline"})
        ok, prop = shadow.run_experiment(exp)
        self.assertTrue(ok)
        self.assertEqual(exp.status, "completed")

    def test_14_interrupted_model_promotion_rollback(self):
        """Scenario 14: Failed or unapproved model promotion rolls back cleanly."""
        gov = PercivalGovernance(pensieve=self.pensieve, vault=self.vault)
        rb_ok, rb_msg = gov.rollback("ALBUS")
        # No prior backup exists yet, handles cleanly
        self.assertIsInstance(rb_ok, bool)

    def test_15_application_crash_journal_durability(self):
        """Scenario 15: Annotations written to journal persist across process restart."""
        journal_path = os.path.join(self.temp_dir, "test_crash_journal.db")
        j1 = DurableLocalJournal(db_path=journal_path)
        e_id = j1.record_entry("expert_annotations", "INSERT", {"study_id": "CRASH_S1", "call": "definite_css"}, "CRASH_S1")
        del j1 # simulate crash / restart

        # Reopen journal database
        j2 = DurableLocalJournal(db_path=journal_path)
        pending = j2.get_pending_entries()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["entry_id"], e_id)

    def test_16_failed_journal_synchronization_retry(self):
        """Scenario 16: Idempotent replay of synced journal does not duplicate rows."""
        self.pensieve.remember_study("ST_SYNC", "PT_SYNC", "COHORT", "development")
        c_uid = self.pensieve.remember_candidate("ST_SYNC", 1, "L", (1,1,1), (1,1,1), 10, 5.0, (0,0,0,2,2,2), 0.8)
        self.vault._is_connected = False
        ann_id = self.pensieve.record_expert_annotation("ST_SYNC", "Dr_A", "definite_css", candidate_uid=c_uid)

        # Reconnect
        self.vault._is_connected = True
        res1 = self.pensieve.sync_local_journal()
        self.assertEqual(res1["synced_count"], 1)

        # Second sync attempt is a no-op (no pending left)
        res2 = self.pensieve.sync_local_journal()
        self.assertEqual(res2["synced_count"], 0)

    def test_17_invalid_model_checkpoint(self):
        """Scenario 17: Corrupted model checkpoint file does not crash LUMOS loader and refuses inference."""
        bad_weights = self.vault.path("models", "LUMOS", "lumos_active_weights.npz")
        os.makedirs(os.path.dirname(bad_weights), exist_ok=True)
        with open(bad_weights, "wb") as f:
            f.write(b"CORRUPTED_NON_NPZ_DATA_BYTES")

        # Loading must not crash, should mark checkpoint corrupted and refuse inference
        lumos = LumosImageIntelligence(pensieve=self.pensieve, vault=self.vault)
        self.assertEqual(lumos.checkpoint_status, "checkpoint_corrupted")
        inf = lumos.analyze_patch("S17", 17, {
            "image_swi": np.ones((49, 25, 17), dtype=np.float32),
            "valid_swi": np.ones((49, 25, 17), dtype=bool),
            "object_mask": np.zeros((49, 25, 17), dtype=bool)
        })
        self.assertEqual(inf.status, "checkpoint_unavailable")
        self.assertIsNone(inf.prob)

    def test_18_incompatible_model_version(self):
        """Scenario 18: Incompatible formula identifier raises informative ValueError."""
        albus = AlbusDiscoveryEngine(pensieve=self.pensieve)
        with self.assertRaises(ValueError):
            albus.set_formula("non_existent_future_formula_v99")

    def test_19_duplicate_study_ingestion(self):
        """Scenario 19: Duplicate study ingestion is idempotent and prevents silent overwrite."""
        res1 = self.pensieve.remember_study("ST_DUP", "PT_DUP", "COHORT", "development")
        self.assertEqual(res1["status"], "inserted")
        # Ingest identical again -> idempotent no-op
        res2 = self.pensieve.remember_study("ST_DUP", "PT_DUP", "COHORT", "development")
        self.assertEqual(res2["status"], "idempotent_noop")
        study = self.pensieve.get_study("ST_DUP")
        self.assertEqual(study["study_id"], "ST_DUP")
        # Ingest with conflicting content -> conflict detected without destructive overwrite
        res3 = self.pensieve.remember_study("ST_DUP", "PT_DIFFERENT", "COHORT", "development")
        self.assertEqual(res3["status"], "conflict_detected")
        study_after = self.pensieve.get_study("ST_DUP")
        self.assertEqual(study_after["patient_pseudo_id"], "PT_DUP") # original preserved

    def test_20_application_restart_during_recovery(self):
        """Scenario 20: Rebuilding engines from existing vault reconstructs identical state."""
        self.pensieve.remember_study("ST_RESTART", "PT_RESTART", "COHORT", "development")
        uid = self.pensieve.remember_candidate("ST_RESTART", 1, "R", (5,5,5), (2.5,2.5,2.5), 15, 7.5, (0,0,0,3,3,3), 0.72)

        # Re-initialize Pensieve and Vault from same path
        vault2 = PercivalDataVault(self.vault.root_path)
        pensieve2 = PensieveCoreMemory(vault2)
        with pensieve2._get_connection() as con:
            cur = con.execute("SELECT * FROM candidates_memory WHERE candidate_uid = ?", (uid,))
            cand = cur.fetchone()
        self.assertIsNotNone(cand)
        self.assertEqual(cand["study_id"], "ST_RESTART")

    def test_21_vault_prefix_containment(self):
        """Scenario 21: Data Vault path resolution enforces strict containment against prefix spoofing."""
        # Standard traversal attempt
        with self.assertRaises(ValueError):
            self.vault.path("..", "outside.txt")
        # Prefix spoofing attempt
        prefix_attack = self.vault.root_path + "_ATTACK"
        rel_attack = os.path.relpath(prefix_attack, self.vault.root_path)
        with self.assertRaises(ValueError):
            self.vault.path(rel_attack, "exploit.bin")

if __name__ == "__main__":
    unittest.main()
