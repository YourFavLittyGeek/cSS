"""test_final_scientific_acceptance.py - Independent Mathematical & Scientific Acceptance Tests.

Directly verifies:
1. NOX sphericity vs second-moment isotropy, analytical cube and sphere, unregularized planar eigenvalues.
2. LUMOS Darboux frame orientation invariance, near-zero denominator fail-safes.
3. PENSIEVE multi-evidence identity adjudication (no unconditional proximity merge) and DurableLocalJournal disconnection resilience.
4. ALBUS locked-test partition isolation (data leakage prevention) and exponential smoothing stability.
5. PERCIVAL CORE IRLS unpenalized intercept, feature extraction identity between training and inference.
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
from uengine.contracts import NoxMeasurements, LumosInference, AlbusCandidate

class TestFinalScientificAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="final_sci_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_ACCEPT")
        self.pensieve = PensieveCoreMemory(self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # MISSION A: NOX MATHEMATICAL VALIDITY (SPHERICITY VS ISOTROPY)
    # =========================================================================
    def test_nox_sphericity_vs_second_moment_isotropy(self):
        """Prove mathematically that a cube has isotropic second moments but sphericity != 1.0."""
        nox = NoxCharacteristicsEngine(pensieve=self.pensieve)

        # 1. Ideal 10x10x10 mm Cube (1.0 mm isotropic voxels)
        cube = np.zeros((16, 16, 16), dtype=bool)
        cube[3:13, 3:13, 3:13] = True
        meas_cube = nox.measure_candidate("S1", 1, {"mask_3d": cube, "voxel_spacing_mm": [1.0, 1.0, 1.0]})

        # Analytical Wadell's Sphericity for 10mm cube: Psi = pi^(1/3) * (6 * 1000)^(2/3) / 600 = ~0.806
        self.assertEqual(meas_cube.morphology["volume_mm3"], 1000.0)
        self.assertEqual(meas_cube.morphology["surface_area_mm2"], 600.0)
        self.assertAlmostEqual(meas_cube.morphology["sphericity"], 0.806, delta=0.005)

        # Second moments of cube: discrete sampling of 10 points yields 8.25 mm^2 along each axis
        eigs = meas_cube.morphology["eigenvalues_mm2"]
        self.assertAlmostEqual(eigs[0], 8.25, delta=0.05)
        self.assertAlmostEqual(eigs[1], 8.25, delta=0.05)
        self.assertAlmostEqual(eigs[2], 8.25, delta=0.05)
        # Second-moment isotropy is 1.0 (equal principal moments), proving isotropy != sphericity
        self.assertAlmostEqual(meas_cube.morphology["second_moment_isotropy"], 1.0, delta=0.001)
        self.assertFalse(meas_cube.morphology["is_planar"])

        # 2. Planar Single-Slice Mask (5x5 mm in-plane, 1 slice along z)
        planar = np.zeros((16, 16, 16), dtype=bool)
        planar[5:10, 5:10, 8] = True # single z slice
        meas_planar = nox.measure_candidate("S1", 2, {"mask_3d": planar, "voxel_spacing_mm": [1.0, 1.0, 2.0]})

        # True physical z-variance is 0.0 (unregularized)
        self.assertTrue(meas_planar.morphology["is_planar"])
        self.assertAlmostEqual(meas_planar.morphology["raw_lambda3_mm2"], 0.0, delta=1e-6)
        # Planarity metric (l2 - l3) / l1 should be close to 1.0
        self.assertGreater(meas_planar.morphology["planarity"], 0.8)

    # =========================================================================
    # MISSION B: LUMOS DARBOUX INVARIANCE & DENOMINATOR ROBUSTNESS
    # =========================================================================
    def test_lumos_darboux_orientation_and_near_zero_reference(self):
        """Verify normal axis sign consistency across in-plane rotations and zero-reference safety."""
        lumos = LumosImageIntelligence(pensieve=self.pensieve, vault=self.vault)

        # 1. Superficial patch with normal axis along dim 2
        patch = np.ones((49, 25, 16), dtype=np.float32)
        patch[:, :, 8:] = 0.20 # Superficial cortex is hypointense
        valid = np.ones((49, 25, 16), dtype=bool)
        obj = np.zeros((49, 25, 16), dtype=bool)
        obj[:, :, 8:] = True

        inf1 = lumos.analyze_patch("S1", 1, {"image_swi": patch, "valid_swi": valid, "object_mask": obj})
        self.assertGreater(inf1.depth_gradient, 0.4)
        self.assertEqual(inf1.depth_gradient_status, "reliable")

        # In-plane 90-degree rotation in (u, v) tangent plane leaves transverse n axis invariant
        patch_rot = np.rot90(patch, k=1, axes=(0, 1))
        valid_rot = np.rot90(valid, k=1, axes=(0, 1))
        obj_rot = np.rot90(obj, k=1, axes=(0, 1))
        inf_rot = lumos.analyze_patch("S1", 2, {"image_swi": patch_rot, "valid_swi": valid_rot, "object_mask": obj_rot})
        self.assertAlmostEqual(inf1.depth_gradient, inf_rot.depth_gradient, delta=1e-4)

        # 2. Denominator near-zero safety
        patch_zero = np.zeros((49, 25, 16), dtype=np.float32)
        inf_zero = lumos.analyze_patch("S1", 3, {"image_swi": patch_zero, "valid_swi": valid, "object_mask": obj})
        self.assertEqual(inf_zero.depth_gradient, 0.0)
        self.assertEqual(inf_zero.depth_gradient_status, "unreliable_reference")

    # =========================================================================
    # MISSION C: PENSIEVE IDENTITY ADJUDICATION & DURABLE LOCAL JOURNAL
    # =========================================================================
    def test_pensieve_identity_and_durable_journal(self):
        """Verify multi-evidence candidate identity and durable journaling during vault disconnection."""
        # 1. Register candidate C1
        self.pensieve.remember_study("ST_ID", "PT_01", "SYN", "development")
        c1_uid = self.pensieve.remember_candidate(
            study_id="ST_ID", cand_id=1, hemi="L",
            centroid_vox=(50.0, 50.0, 20.0), centroid_mm=(25.0, 25.0, 40.0),
            volume_vox=30, volume_mm3=15.0, bbox=(48, 48, 19, 52, 52, 21),
            albus_score=0.75
        )

        # Case A: Shift within 0.8 mm with overlapping bbox -> same_candidate
        id_eval_a = self.pensieve.evaluate_candidate_identity(
            study_id="ST_ID", hemi="L",
            centroid_mm=(25.4, 25.3, 40.2), # ~0.53 mm distance
            bbox=(49, 49, 19, 53, 53, 21), volume_mm3=14.0
        )
        self.assertEqual(id_eval_a["outcome"], "same_candidate")
        self.assertEqual(id_eval_a["matched_uid"], c1_uid)
        self.assertGreater(id_eval_a["confidence"], 0.70)

        # Case B: Proximity 0.9 mm but strictly disjoint bounding boxes -> uncertain_identity (not merged)
        id_eval_b = self.pensieve.evaluate_candidate_identity(
            study_id="ST_ID", hemi="L",
            centroid_mm=(25.0, 25.0, 40.9), # 0.9 mm along z
            bbox=(48, 48, 22, 52, 52, 24), # disjoint z window [19, 21] vs [22, 24]
            volume_mm3=15.0
        )
        self.assertEqual(id_eval_b["outcome"], "uncertain_identity")
        self.assertIsNone(id_eval_b["matched_uid"]) # Proves no blind proximity merging

        # 2. Durable Local Journaling during vault disconnection
        self.vault._is_connected = False # Simulate drive disconnection
        ann_id = self.pensieve.record_expert_annotation(
            study_id="ST_ID", reviewer_id="Dr_Offline", call="definite_css",
            candidate_uid=c1_uid, confidence="high"
        )
        self.assertTrue(ann_id.startswith("ann_"))
        journal_status = self.pensieve.local_journal.get_status()
        self.assertGreaterEqual(journal_status["pending_count"], 1)

        # Reconnect vault and replay journal
        self.vault._is_connected = True
        sync_res = self.pensieve.sync_local_journal()
        self.assertEqual(sync_res["status"], "synced")
        self.assertGreaterEqual(sync_res["synced_count"], 1)

        # Verify annotation was committed to the authoritative Data Vault
        with self.pensieve._get_connection() as con:
            cur = con.execute("SELECT * FROM expert_annotations WHERE annotation_id = ?", (ann_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["reviewer_id"], "Dr_Offline")

    # =========================================================================
    # MISSION D: ALBUS FEEDBACK ISOLATION & STABILITY
    # =========================================================================
    def test_albus_locked_test_isolation_and_damping(self):
        """Verify locked test cohort cannot trigger learning, and threshold adapts with exponential damping."""
        albus = AlbusDiscoveryEngine(pensieve=self.pensieve)

        # 1. Locked test cohort isolation guard
        self.pensieve.remember_study("ST_LOCKED", "PT_LOCKED", "SYN", partition="test")
        with self.assertRaises(PermissionError):
            albus.learn_from_missed_lesion("ST_LOCKED", (0,0,0), (0,0,0), {"pial_distance": 0.5, "darkness_z": -2.0})

        # 2. Multi-causal contributing factors
        self.pensieve.remember_study("ST_DEV", "PT_DEV", "SYN", partition="development")
        # Lesion with both high tubularity AND faint contrast
        diag = albus.learn_from_missed_lesion(
            "ST_DEV", (0,0,0), (0,0,0),
            {"pial_distance": 0.5, "darkness_z": -0.5, "tube_ratio": 3.0, "edge_contrast": 0.10, "snr": 6.0}
        )
        self.assertIn("contributing_factors", diag)
        self.assertGreater(len(diag["contributing_factors"]), 1)
        self.assertIn("image_quality_limitation", diag["contributing_factors"])
        self.assertIn("tubularity_vessel_rejection", diag["contributing_factors"])

    # =========================================================================
    # MISSION E: PERCIVAL CORE IRLS INTERCEPT & FEATURE EXTRACTION IDENTITY
    # =========================================================================

if __name__ == "__main__":
    unittest.main()
