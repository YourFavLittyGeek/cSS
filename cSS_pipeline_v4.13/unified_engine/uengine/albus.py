"""uengine/albus.py - ALBUS: Mathematical Candidate Discovery Engine

The initial analytical component in the Percival pipeline:
  MRI -> ALBUS -> LUMOS + NOX -> PERCIVAL CORE -> PERCIVAL SCORE

Responsibilities:
  1. Mathematical discovery of potential cSS lesions from MRI data.
  2. Extensible formula registry (versioned mathematical candidate scoring).
  3. Adaptive thresholds and sensitivity-preserving candidate filtering.
  4. Active learning loop connected to PENSIEVE (recovering missed lesions,
     penalizing recurrent false positive patterns).
  5. Generating standardized AlbusCandidate objects with spatial fingerprints.
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from uengine.contracts import AlbusCandidate
from uengine.pensieve import get_pensieve, PensieveCoreMemory

class AlbusFormulaRegistry:
    """Registry of mathematical discovery formulas with physical-unit scaling."""
    
    @staticmethod
    def formula_v4_baseline(features: Dict[str, float]) -> float:
        """Baseline production physical heuristic formula (score_v4)."""
        pdist = float(features.get("pial_distance", features.get("pdist", 1.0)))
        darkness = float(features.get("darkness_z", -1.5))
        tube = float(features.get("tube_ratio", 1.5))
        tram = float(features.get("tram_frac", 0.0))
        cortex = float(features.get("cortex_frac", 0.5))

        # Pial surface proximity window (Gaussian decay with 1.5 mm spread)
        on_surf = float(np.exp(-((pdist + 0.5) / 1.5) ** 2))
        dark_factor = float(np.clip(-darkness / 2.0, 0.1, 3.0))
        tube_penalty = float(np.exp(-max(0.0, tube - 1.5) / 1.2))
        tram_boost = 1.0 + 0.5 * max(0.0, tram)
        score = on_surf * dark_factor * tube_penalty * tram_boost * (0.8 + 0.4 * cortex)
        return float(max(0.0, score))

    @staticmethod
    def formula_adaptive_subpial(features: Dict[str, float]) -> float:
        """Adaptive subpial formula adjusting for cortical distance and surface curvature."""
        pdist = float(features.get("pial_distance", features.get("pdist", 1.0)))
        darkness = float(features.get("darkness_z", -1.5))
        tube = float(features.get("tube_ratio", 1.5))
        cortex = float(features.get("cortex_frac", 0.5))
        edge = float(features.get("edge_contrast", 0.4))

        # Sharper subpial localization (1.2 mm window)
        on_surf = float(np.exp(-((pdist + 0.2) / 1.2) ** 2))
        dark_factor = float(np.clip(-darkness / 1.8, 0.1, 3.5))
        # Stronger penalization of cylindrical vessels
        tube_penalty = float(np.exp(-max(0.0, tube - 1.2) / 1.0))
        edge_boost = 1.0 + 0.4 * float(np.clip(edge, 0.0, 1.0))
        score = on_surf * dark_factor * tube_penalty * edge_boost * (0.7 + 0.5 * cortex)
        return float(max(0.0, score))

    @staticmethod
    def formula_curvilinear_enhanced(features: Dict[str, float]) -> float:
        """Enhanced curvilinear continuous sheet formula for subtle low-burden cSS."""
        base = AlbusFormulaRegistry.formula_adaptive_subpial(features)
        continuity = float(features.get("skeleton_length", features.get("continuity_mm", 4.0)))
        continuity_boost = float(np.clip(1.0 + (continuity - 3.0) / 10.0, 0.8, 1.6))
        return float(base * continuity_boost)

FORMULAS = {
    "formula_v4_baseline": AlbusFormulaRegistry.formula_v4_baseline,
    "formula_adaptive_subpial": AlbusFormulaRegistry.formula_adaptive_subpial,
    "formula_curvilinear_enhanced": AlbusFormulaRegistry.formula_curvilinear_enhanced
}

class AlbusDiscoveryEngine:
    def __init__(self, formula_id: str = "formula_v4_baseline",
                 threshold: float = 0.5, pensieve: Optional[PensieveCoreMemory] = None):
        self.formula_id = formula_id
        self.base_threshold = float(threshold)
        self.threshold = float(threshold)
        self.pensieve = pensieve if pensieve is not None else __import__('uengine.legacy_guard', fromlist=['NullPensieve']).NullPensieve()   # Stage 1: never the global legacy memory by default
        self.version = "albus-5.25.0"
        self.adaptive_multiplier = 1.0
        self.active_learning_history: List[Dict[str, Any]] = []

    def set_formula(self, formula_id: str) -> None:
        if formula_id not in FORMULAS:
            raise ValueError(f"Unknown ALBUS formula: {formula_id}")
        self.formula_id = formula_id

    def calculate_score(self, features: Dict[str, float]) -> float:
        fn = FORMULAS.get(self.formula_id, AlbusFormulaRegistry.formula_v4_baseline)
        return fn(features)

    def update_adaptive_threshold(self) -> float:
        """Dynamically adapt detection threshold based on PENSIEVE learning history.
        
        cSS detection principle: Missing a true cSS lesion is clinically catastrophic.
        When missed lesions are flagged by clinicians, sensitivity multiplier s_adapt increases,
        lowering the threshold. Recurrent false positives gently increase the threshold,
        normalized by patient review count to prevent a single scan from distorting global sensitivity.
        """
        albus_mem = self.pensieve.ask_albus_memory(limit=100)
        n_missed = albus_mem.get("missed_lesions_count", 0)
        missed_list = albus_mem.get("missed_lesions", [])
        fp_corrections = albus_mem.get("false_positive_corrections", [])
        n_fp = len(fp_corrections)

        # Patient-level normalization for both missed lesions and false positives
        missed_studies = set(m.get("study_id") for m in missed_list if m.get("study_id"))
        n_missed_patients = max(1, len(missed_studies))
        missed_per_patient = n_missed / n_missed_patients

        fp_studies = set(c.get("study_id") for c in fp_corrections if c.get("study_id"))
        n_fp_patients = max(1, len(fp_studies))
        fp_per_patient = n_fp / n_fp_patients

        # Sensitivity multiplier: bounded in [0.5, 2.0]
        s_adapt = float(np.clip(1.0 + 0.12 * missed_per_patient - 0.05 * fp_per_patient, 0.5, 2.0))
        self.adaptive_multiplier = s_adapt

        # Exponential smoothing (alpha = 0.35) to prevent threshold oscillation
        target_thresh = float(np.clip(self.base_threshold / s_adapt, 0.15, 0.85))
        alpha = 0.35
        self.threshold = float(np.clip((1.0 - alpha) * self.threshold + alpha * target_thresh, 0.15, 0.85))
        return self.threshold

    def learn_from_missed_lesion(self, study_id: str,
                                 centroid_vox: Tuple[float, float, float],
                                 centroid_mm: Tuple[float, float, float],
                                 local_features: Dict[str, float],
                                 reviewer_notes: str = "") -> Dict[str, Any]:
        """Diagnose and learn from a lesion that ALBUS failed to detect.
        
        Performs multi-causal failure analysis across seven distinct mechanisms:
        1. Outside candidate search region
        2. Below intensity threshold
        3. Rejected by tubularity penalty
        4. Subpial margin window miss
        5. Segmentation failure / partial volume
        6. Image-quality limitation
        7. Mathematical threshold margin gap
        
        Enforces partition isolation: Locked test cohort studies are prohibited
        from triggering adaptive updates to prevent evaluation leakage.
        """
        # Strict partition isolation guard
        study_info = self.pensieve.get_study(study_id)
        if study_info and study_info.get("partition") == "test":
            raise PermissionError(f"Cannot adapt ALBUS from locked test cohort study {study_id} (data leakage protection).")

        score = self.calculate_score(local_features)
        reasons = []
        contributing_factors = []
        
        pdist = float(local_features.get("pial_distance", local_features.get("pdist", 1.0)))
        darkness = float(local_features.get("darkness_z", -1.5))
        tube = float(local_features.get("tube_ratio", 1.5))
        vol_vox = float(local_features.get("volume_vox", 10.0))
        snr = float(local_features.get("snr", 20.0))
        contrast = float(local_features.get("edge_contrast", 0.4))
        in_mask = local_features.get("in_brain_mask", True)

        # Multi-causal independent factor evaluation
        if not in_mask or pdist > 6.0:
            contributing_factors.append("outside_search_region")
            reasons.append(f"Outside candidate search region: pdist={pdist:.2f}mm exceeded cortex boundary")
        if vol_vox < 5:
            contributing_factors.append("segmentation_failure")
            reasons.append(f"Segmentation failure: fragmented volume={vol_vox} voxels below minimum lesion size")
        if snr < 8.0 or contrast < 0.15:
            contributing_factors.append("image_quality_limitation")
            reasons.append(f"Image quality limitation: snr={snr:.1f}, contrast={contrast:.2f} degraded detection")
        if tube > 2.2:
            contributing_factors.append("tubularity_vessel_rejection")
            reasons.append(f"Excessive tubularity penalty: tube_ratio={tube:.2f} caused vessel mimic rejection")
        if darkness > -0.9:
            contributing_factors.append("below_intensity_threshold")
            reasons.append(f"Subtle hypointensity: darkness_z={darkness:.2f} was faint")
        if 1.8 < pdist <= 6.0:
            contributing_factors.append("subpial_margin_miss")
            reasons.append(f"Subpial margin window miss: pdist={pdist:.2f}mm exceeded surface window")
        if not contributing_factors:
            contributing_factors.append("threshold_margin_gap")
            reasons.append(f"Threshold margin gap: score={score:.3f} marginally below active threshold={self.threshold:.3f}")

        primary_failure = contributing_factors[0]
        diagnosis = "; ".join(reasons)
        
        # Record correction in PENSIEVE with detailed causal category
        cid = self.pensieve.record_correction(
            study_id=study_id,
            event_type="missed_lesion_flagged",
            component="ALBUS",
            initial_ai=f"unproposed_score_{score:.3f}",
            ground_truth="definite_css",
            evidence={**local_features, "failure_category": primary_failure, "contributing_factors": contributing_factors},
            pattern=f"{primary_failure}: {diagnosis}"
        )
        
        # Trigger adaptive threshold update
        new_thresh = self.update_adaptive_threshold()
        
        event = {
            "correction_id": cid,
            "study_id": study_id,
            "calculated_score": score,
            "threshold_before": self.threshold,
            "threshold_after": new_thresh,
            "failure_category": primary_failure,
            "contributing_factors": contributing_factors,
            "diagnosis": diagnosis,
            "reviewer_notes": reviewer_notes
        }
        self.active_learning_history.append(event)
        return event

    def discover_candidate(self, study_id: str, cand_id: int, hemi: str,
                           centroid_vox: Tuple[float, float, float],
                           centroid_mm: Tuple[float, float, float],
                           volume_vox: int, volume_mm3: float,
                           bbox: Tuple[int, int, int, int, int, int],
                           raw_features: Dict[str, float]) -> Optional[AlbusCandidate]:
        """Evaluate a candidate region and generate an AlbusCandidate if above threshold."""
        score = self.calculate_score(raw_features)
        if score < self.threshold:
            return None

        # Build candidate object
        cand = AlbusCandidate(
            cand_id=cand_id,
            study_id=study_id,
            hemi=hemi,
            centroid_vox=centroid_vox,
            centroid_mm=centroid_mm,
            volume_vox=volume_vox,
            volume_mm3=volume_mm3,
            bbox=bbox,
            math_score=score,
            detection_version=self.version,
            formula_id=self.formula_id,
            quality={"contrast": raw_features.get("edge_contrast", 0.0), "snr": raw_features.get("snr", 15.0)},
            evidence=raw_features,
            fingerprint=PensieveCoreMemory.compute_candidate_uid(study_id, hemi, centroid_vox)
        )

        # Register candidate in PENSIEVE persistent memory
        try:
            self.pensieve.remember_candidate(
                study_id=study_id,
                cand_id=cand_id,
                hemi=hemi,
                centroid_vox=centroid_vox,
                centroid_mm=centroid_mm,
                volume_vox=volume_vox,
                volume_mm3=volume_mm3,
                bbox=bbox,
                albus_score=score,
                albus_formula=self.formula_id,
                detection_version=self.version
            )
        except Exception:
            pass

        return cand

    def learn_from_pensieve(self) -> Dict[str, Any]:
        """Consult PENSIEVE long-term memory, update adaptive threshold, and return state."""
        new_thresh = self.update_adaptive_threshold()
        albus_mem = self.pensieve.ask_albus_memory(limit=50)
        missed_count = albus_mem.get("missed_lesions_count", 0)
        fp_corrections = albus_mem.get("false_positive_corrections", [])

        actionable_recommendations = []
        if missed_count > 0:
            actionable_recommendations.append(
                f"Adapted threshold to {new_thresh:.2f} (multiplier {self.adaptive_multiplier:.2f}) to recover {missed_count} missed lesions."
            )
        if len(fp_corrections) > 5:
            actionable_recommendations.append(
                f"Increased tubularity penalty advised for {len(fp_corrections)} recurrent vessel false positives."
            )

        return {
            "status": "active_learning_applied",
            "missed_lesions_to_recover": missed_count,
            "false_positives_recorded": len(fp_corrections),
            "current_formula": self.formula_id,
            "base_threshold": self.base_threshold,
            "active_threshold": self.threshold,
            "adaptive_multiplier": self.adaptive_multiplier,
            "recommendations": actionable_recommendations
        }
