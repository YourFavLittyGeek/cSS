"""uengine/percival_core.py - PERCIVAL CORE: Central Evidence Integration & Scoring Engine

The central decision-making intelligence of the Percival ecosystem:
  MRI -> ALBUS -> LUMOS + NOX -> PERCIVAL CORE -> PERCIVAL SCORE

Responsibilities:
  1. Integrates evidence from ALBUS, LUMOS, and NOX.
  2. Absorbs the relationship and interaction modeling of EPOXIMISE AI directly into Core
     (modeling how 3D visual appearance modulates quantitative geometry and physical discovery).
  3. Eliminates redundant separate EPOXIMISE, META, and FUSION layers.
  4. Ridge-penalized calibration mapping into a single primary Percival Score [0, 100].
  5. Evaluates epistemic & aleatoric uncertainty, returning explicit confidence and bands:
     - Green (>= 70): High probability cSS
     - Amber (40-69): Equivocal / Review Required
     - Gray (< 40): Unlikely cSS / Vessel / Artifact
  6. Explicit missing-data fail-safes: never treats unavailable inputs as true 50% probability.
  7. Trainable integration weights via L2-penalized regression across patient folds.
  8. Outputs standardized PercivalAssessment contract objects.
  9. Queries and updates PENSIEVE persistent memory.
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from uengine.contracts import AlbusCandidate, LumosInference, NoxMeasurements, PercivalAssessment
from uengine.pensieve import get_pensieve, PensieveCoreMemory
from uengine.vault import get_vault, PercivalDataVault

class PercivalCoreIntelligence:
    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 calibration_params: Optional[Tuple[float, float]] = None,
                 pensieve: Optional[PensieveCoreMemory] = None,
                 vault: Optional[PercivalDataVault] = None):
        self.pensieve = pensieve if pensieve is not None else __import__('uengine.legacy_guard', fromlist=['NullPensieve']).NullPensieve()   # Stage 1: never the global legacy memory by default
        self.vault = vault if vault is not None else __import__('uengine.legacy_guard', fromlist=['NullVault']).NullVault()   # Stage 1: never the external Vault by default
        self.version = "percival-core-5.25.0"
        
        # Integration weights (learned across ALBUS, LUMOS, NOX, and absorbed Epoximise interactions)
        self.weights = weights or {
            "w_albus": 0.25,
            "w_lumos": 0.40,
            "w_nox": 0.30,
            "w_depth_gradient": 0.25, # Active consumption of LUMOS transverse depth gradient
            "w_lumos_nox_interaction": 0.15, # Absorbed Epoximise interaction term
            "bias": -0.8
        }
        # Platt calibration (a * logit + b) with shrinkage
        self.calibration = calibration_params or (1.2, -0.2)

    @staticmethod
    def extract_feature_vector(albus_cand: Optional[AlbusCandidate],
                               lumos_inf: Optional[LumosInference],
                               nox_meas: Optional[NoxMeasurements]) -> Tuple[np.ndarray, Dict[str, bool]]:
        """Unified, centralized extraction of Core design vector across training and inference.
        
        Returns:
            vector: np.ndarray of shape (5,) [albus_term, lumos_logit, nox_logit, depth_grad, interaction]
            availability: Dict[str, bool] {"albus": ..., "lumos": ..., "nox": ...}
        """
        has_albus = bool(albus_cand and albus_cand.math_score is not None)
        has_lumos = bool(lumos_inf and getattr(lumos_inf, "has_visual_evidence", True) and
                         lumos_inf.status == "ok" and getattr(lumos_inf, "prob", None) is not None)
        has_nox = bool(nox_meas and nox_meas.morphology and
                       nox_meas.morphology.get("geometry_status") not in ("invalid_spacing", "empty_mask"))

        s_albus = albus_cand.math_score if (has_albus and albus_cand) else 0.5
        albus_term = float(np.log1p(max(0.0, s_albus)))

        if has_lumos and lumos_inf and lumos_inf.prob is not None:
            s_lumos = float(lumos_inf.prob)
            lumos_logit = float(np.log(np.clip(s_lumos, 1e-4, 1.0 - 1e-4) / (1.0 - np.clip(s_lumos, 1e-4, 1.0 - 1e-4))))
            depth_grad = float(getattr(lumos_inf, "depth_gradient", 0.0) or 0.0)
        else:
            s_lumos = 0.5
            lumos_logit = 0.0
            depth_grad = 0.0

        if has_nox and nox_meas:
            pdist = float(nox_meas.anatomy.get("pial_distance_mm", 1.0) or 1.0)
            darkness = float(nox_meas.signal.get("darkness_z", -1.5) or -1.5)
            tube = float(nox_meas.morphology.get("elongation", 1.5) or 1.5)
            cortex = float(nox_meas.anatomy.get("cortex_fraction", 0.5) or 0.5)
            contrast = float(nox_meas.signal.get("edge_contrast", 0.4) or 0.4)
            geom_score = 0.35 * (-darkness / 2.0) + 0.25 * np.exp(-pdist / 1.5) - 0.20 * (tube - 1.0) + 0.20 * cortex + 0.10 * contrast
            s_nox = float(np.clip(geom_score, 0.05, 0.95))
            nox_logit = float(np.log(s_nox / (1.0 - s_nox)))
        else:
            s_nox = 0.5
            nox_logit = 0.0

        absorbed_epoximise_interaction = float((s_lumos - 0.5) * (s_nox - 0.5) * 4.0) if (has_lumos and has_nox) else 0.0

        vec = np.array([albus_term, lumos_logit, nox_logit, depth_grad, absorbed_epoximise_interaction], dtype=float)
        avail = {"albus": has_albus, "lumos": has_lumos, "nox": has_nox}
        return vec, avail

    def fit(self, X_features: np.ndarray, y: np.ndarray,
            groups: Optional[List[str]] = None, l2_penalty: float = 1.0) -> "PercivalCoreIntelligence":
        """Fit integration weights and calibration parameters using L2-regularized logistic regression.
        
        Features per candidate: [albus_term, lumos_logit, nox_logit, depth_gradient, interaction_term].
        Enforces patient-level grouping to prevent validation leakage.
        """
        X = np.asarray(X_features, dtype=float)
        y = np.asarray(y, dtype=float)
        N, D = X.shape

        # Standard Newton-Raphson / IRLS with Ridge penalty
        w = np.zeros(D + 1, dtype=float)
        X_design = np.column_stack([X, np.ones(N)])

        for _ in range(30):
            logits = X_design @ w
            probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -15.0, 15.0)))
            grad = X_design.T @ (probs - y)
            # Add L2 penalty (exclude intercept)
            reg = l2_penalty * w
            reg[-1] = 0.0
            grad += reg

            # Hessian with L2 ridge shrinkage
            W_diag = np.clip(probs * (1.0 - probs), 1e-5, 0.25)
            H = (X_design.T * W_diag) @ X_design
            H += np.diag(np.full(D + 1, l2_penalty))
            H[-1, -1] -= l2_penalty # no regularization on intercept

            try:
                step = np.linalg.solve(H, grad)
                w -= step
                if np.max(np.abs(step)) < 1e-4:
                    break
            except np.linalg.LinAlgError:
                break

        self.weights = {
            "w_albus": float(w[0]),
            "w_lumos": float(w[1]),
            "w_nox": float(w[2]),
            "w_depth_gradient": float(w[3]) if D > 3 else 0.25,
            "w_lumos_nox_interaction": float(w[4]) if D > 4 else (float(w[3]) if D == 4 else 0.15),
            "bias": float(w[-1])
        }
        
        # Out-of-fold Platt calibration using patient groups when available
        if groups is not None and len(set(groups)) >= 3:
            u_groups = np.unique(groups)
            oof_logits = np.zeros(N)
            for g in u_groups:
                val_mask = (np.array(groups) == g)
                tr_mask = ~val_mask
                if len(np.unique(y[tr_mask])) >= 2:
                    w_fold = np.zeros(D + 1)
                    X_tr = X_design[tr_mask]
                    y_tr = y[tr_mask]
                    for _ in range(15):
                        p_tr = 1.0 / (1.0 + np.exp(-np.clip(X_tr @ w_fold, -15.0, 15.0)))
                        gr = X_tr.T @ (p_tr - y_tr) + l2_penalty * np.append(w_fold[:-1], 0)
                        H_tr = (X_tr.T * np.clip(p_tr * (1 - p_tr), 1e-5, 0.25)) @ X_tr + np.diag(np.append(np.full(D, l2_penalty), 0))
                        try:
                            w_fold -= np.linalg.solve(H_tr, gr)
                        except np.linalg.LinAlgError:
                            break
                    oof_logits[val_mask] = X_design[val_mask] @ w_fold
            
            # Fit Platt slope & intercept on oof_logits
            var_lg = np.var(oof_logits)
            slope = float(np.clip(np.cov(oof_logits, y)[0, 1] / max(1e-4, var_lg), 0.5, 2.0))
            intercept = float(np.mean(y) - slope * np.mean(oof_logits))
            self.calibration = (slope, intercept)
        else:
            self.calibration = (1.0, 0.0)

        return self

    def evaluate_candidate(self,
                           albus_cand: Optional[AlbusCandidate],
                           lumos_inf: Optional[LumosInference],
                           nox_meas: Optional[NoxMeasurements]) -> PercivalAssessment:
        """Produce the unified Percival Score and clinical assessment.
        
        Learns the joint evidence across mathematical candidate discovery,
        3D visual appearance, and quantitative morphology. Absorbs Epoximise AI's
        cross-modal interaction modeling directly into Core.
        """
        cand_id = albus_cand.cand_id if albus_cand else (lumos_inf.cand_id if lumos_inf else (nox_meas.cand_id if nox_meas else 0))
        study_id = albus_cand.study_id if albus_cand else (lumos_inf.study_id if lumos_inf else (nox_meas.study_id if nox_meas else "unknown"))

        # Missing input safeguards
        available_components = []
        has_lumos = False
        has_nox = False
        has_albus = False

        if albus_cand and albus_cand.math_score is not None:
            available_components.append("albus")
            has_albus = True
        if lumos_inf and getattr(lumos_inf, "has_visual_evidence", True) and lumos_inf.status == "ok" and getattr(lumos_inf, "prob", None) is not None:
            available_components.append("lumos")
            has_lumos = True
        if nox_meas and nox_meas.morphology and nox_meas.morphology.get("geometry_status") not in ("invalid_spacing", "empty_mask"):
            available_components.append("nox")
            has_nox = True

        # Safety: Incomplete, missing, or corrupted evidence must NOT produce neutral scores or default probabilities.
        # Numerical score is suppressed (None) and marked explicit unavailable status.
        if not has_lumos and not has_nox:
            return PercivalAssessment(
                cand_id=cand_id,
                study_id=study_id,
                percival_score=None,
                calibrated_prob=None,
                band="insufficient",
                confidence=0.0,
                uncertainty=1.0,
                status="insufficient",
                components={"albus": albus_cand.math_score if albus_cand else None},
                provenance={"available_inputs": available_components, "engine": self.version,
                            "warning": "Visual MRI patch and quantitative 3D features unavailable."}
            )

        if not has_lumos:
            return PercivalAssessment(
                cand_id=cand_id,
                study_id=study_id,
                percival_score=None,
                calibrated_prob=None,
                band="unavailable",
                confidence=0.0,
                uncertainty=1.0,
                status="incomplete_visual_data",
                components={"albus": albus_cand.math_score if albus_cand else None, "nox": nox_meas.morphology if nox_meas else None},
                provenance={"available_inputs": available_components, "engine": self.version,
                            "warning": "Visual MRI patch appearance is unavailable or corrupt; score suppressed."}
            )

        if not has_nox:
            return PercivalAssessment(
                cand_id=cand_id,
                study_id=study_id,
                percival_score=None,
                calibrated_prob=None,
                band="unavailable",
                confidence=0.0,
                uncertainty=1.0,
                status="incomplete_geometry_data",
                components={"albus": albus_cand.math_score if albus_cand else None, "lumos": lumos_inf.prob if lumos_inf else None},
                provenance={"available_inputs": available_components, "engine": self.version,
                            "warning": "Quantitative 3D characteristics unavailable or invalid; score suppressed."}
            )

        # Extract unified design vector guaranteeing training/inference identity
        vec, avail = self.extract_feature_vector(albus_cand, lumos_inf, nox_meas)
        albus_term, lumos_logit, nox_logit, depth_grad, absorbed_epoximise_interaction = vec

        s_albus = albus_cand.math_score if (albus_cand and albus_cand.math_score is not None) else 0.5
        s_lumos = float(lumos_inf.prob) if (has_lumos and lumos_inf) else 0.5
        lumos_unc = float(lumos_inf.uncertainty) if (has_lumos and lumos_inf) else 1.0

        # NOX geom score for metadata
        if has_nox and nox_meas:
            s_nox = float(1.0 / (1.0 + np.exp(-nox_logit)))
        else:
            s_nox = 0.5

        lumos_nox_disagreement = abs(s_lumos - s_nox)

        w_lumos_eff = self.weights["w_lumos"] if avail["lumos"] else 0.0
        w_nox_eff = self.weights["w_nox"] if avail["nox"] else 0.0
        w_depth_eff = self.weights.get("w_depth_gradient", 0.25) if avail["lumos"] else 0.0
        w_inter_eff = self.weights.get("w_lumos_nox_interaction", 0.15) if (avail["lumos"] and avail["nox"]) else 0.0

        # Percival Core Integration Logit
        raw_core_logit = (
            self.weights["w_albus"] * albus_term +
            w_lumos_eff * lumos_logit +
            w_nox_eff * nox_logit +
            w_depth_eff * depth_grad +
            w_inter_eff * absorbed_epoximise_interaction +
            self.weights["bias"]
        )

        # 6. Platt Recalibration
        calib_a, calib_b = self.calibration
        calibrated_logit = calib_a * raw_core_logit + calib_b
        calibrated_prob = float(1.0 / (1.0 + np.exp(-np.clip(calibrated_logit, -15.0, 15.0))))

        # Integer Percival Score [0, 100]
        percival_score = int(np.clip(round(calibrated_prob * 100.0), 0, 100))

        # Band assignment: Green (>= 70), Amber (40-69), Gray (< 40)
        if percival_score >= 70:
            band = "green"
        elif percival_score >= 40:
            band = "amber"
        else:
            band = "gray"

        # Overall epistemic uncertainty evaluation
        if not has_lumos:
            total_uncertainty = 1.0
            confidence = 0.0
            status = "incomplete_visual_data"
            band = "amber" if percival_score >= 40 else "gray"
        else:
            total_uncertainty = float(np.clip(0.5 * lumos_unc + 0.5 * lumos_nox_disagreement, 0.0, 1.0))
            confidence = float(np.clip(1.0 - total_uncertainty, 0.0, 1.0))
            status = "reliable"
            if total_uncertainty > 0.4:
                status = "uncertain"
            if lumos_nox_disagreement > 0.6:
                status = "review"

        assessment = PercivalAssessment(
            cand_id=cand_id,
            study_id=study_id,
            percival_score=percival_score,
            calibrated_prob=calibrated_prob,
            band=band,
            confidence=confidence,
            uncertainty=total_uncertainty,
            status=status,
            components={
                "albus_score": s_albus,
                "lumos_prob": s_lumos,
                "nox_score": s_nox,
                "core_logit": raw_core_logit
            },
            absorbed_epoximise={
                "interaction_synergy": absorbed_epoximise_interaction,
                "lumos_nox_disagreement": lumos_nox_disagreement,
                "absorbed_architecture": "Integrated natively in Percival Core (No external Epoximise layer)"
            },
            provenance={
                "version": self.version,
                "available_inputs": available_components,
                "calibration": {"a": calib_a, "b": calib_b}
            }
        )

        # Update PENSIEVE memory with the integrated assessment
        try:
            self.pensieve.remember_candidate(
                study_id=study_id,
                cand_id=cand_id,
                hemi=albus_cand.hemi if albus_cand else "U",
                centroid_vox=albus_cand.centroid_vox if albus_cand else (0.0, 0.0, 0.0),
                centroid_mm=albus_cand.centroid_mm if albus_cand else (0.0, 0.0, 0.0),
                volume_vox=albus_cand.volume_vox if albus_cand else 10,
                volume_mm3=albus_cand.volume_mm3 if albus_cand else 5.0,
                bbox=albus_cand.bbox if albus_cand else (0,0,0,0,0,0),
                albus_score=s_albus,
                lumos_prob=s_lumos,
                lumos_unc=lumos_unc,
                nox_meas=nox_meas.morphology if nox_meas else {},
                percival_score=percival_score,
                percival_status=status
            )
        except Exception:
            pass

        return assessment

    def learn_from_pensieve(self) -> Dict[str, Any]:
        """Consult PENSIEVE regarding component reliability and historical disagreement."""
        core_mem = self.pensieve.ask_core_memory()
        return {
            "component": "PERCIVAL_CORE",
            "active_version": self.version,
            "architecture": "Single Unified Evidence Integrator with Absorbed Epoximise Interaction",
            "total_candidates_scored": core_mem.get("total_scored_candidates", 0),
            "epoximise_status": "Fully absorbed into Percival Core",
            "scoring_scale": "Percival Score [0, 100] integer",
            "clinical_bands": {
                "green": ">= 70 (High Probability cSS)",
                "amber": "40 - 69 (Equivocal / Expert Review Recommended)",
                "gray": "< 40 (Unlikely cSS / Low Risk / Artifact)"
            }
        }
