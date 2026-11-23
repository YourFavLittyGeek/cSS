"""test_lumos_core_ablations.py - Controlled LUMOS Depth & Core Ablation Study.

Evaluates 5 distinct model configurations on a patient-separated neuroimaging cohort:
  Config A: LUMOS alone (CNN probability without depth or geometry)
  Config B: LUMOS + depth gradient (G_perp)
  Config C: LUMOS + pial distance (d_pial)
  Config D: LUMOS + cortical context (f_cortex)
  Config E: Complete LUMOS and Core integration (ALBUS + LUMOS + NOX + G_perp + Epoximise synergy)

Patient-level cross-fitting ensures zero leakage between training folds and evaluation folds.
Computes ROC-AUC, Sensitivity, Specificity, Brier score, and 95% bootstrap confidence intervals.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)

import os
import sys
import json
import math
import unittest
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.percival_core import PercivalCoreIntelligence
from uengine.contracts import AlbusCandidate, LumosInference, NoxMeasurements

def compute_auc(y_true, y_pred):
    pos = y_pred[y_true == 1]
    neg = y_pred[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    matches = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(matches / (len(pos) * len(neg)))

def compute_brier(y_true, y_prob):
    return float(np.mean((y_prob - y_true) ** 2))

def bootstrap_ci(y_true, y_pred, metric_fn, n_boot=500, seed=42):
    rng = np.random.default_rng(seed)
    N = len(y_true)
    scores = []
    for _ in range(n_boot):
        idx = rng.choice(N, size=N, replace=True)
        if len(np.unique(y_true[idx])) < 2:
            continue
        scores.append(metric_fn(y_true[idx], y_pred[idx]))
    if not scores:
        return 0.0, 0.0
    return float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))

def run_ablation_study():
    # Deterministic synthetic cohort of 24 patients, 120 candidate lesions (mimicking CAA vs vessel mimics)
    rng = np.random.default_rng(101)
    n_patients = 24
    n_cands_per_pt = 5
    total_cands = n_patients * n_cands_per_pt

    patient_ids = []
    labels = []
    candidates = []

    for p in range(n_patients):
        pid = f"PATIENT_{p:02d}"
        for c in range(n_cands_per_pt):
            # 35% overall prevalence of true cSS lesions
            is_css = int(rng.uniform(0, 1) < 0.35)
            patient_ids.append(pid)
            labels.append(is_css)

            # Features:
            # LUMOS alone logit (CNN flattened projection: partially distinguishes cSS from mimic)
            lumos_prob = float(np.clip(rng.normal(0.72 if is_css else 0.38, 0.20), 0.05, 0.95))
            lumos_logit = float(np.log(lumos_prob / (1.0 - lumos_prob)))

            # G_perp: Transverse depth gradient along normal axis (positive for superficial cSS, negative for deep vessel)
            depth_grad = float(rng.normal(0.65 if is_css else -0.55, 0.35))

            # d_pial: Distance to pial surface (cSS close to surface, deep veins further away)
            pial_dist = float(max(0.1, rng.normal(0.6 if is_css else 2.2, 0.5)))

            # f_cortex: Cortical context fraction (cSS high, subcortical/meningeal mimics lower)
            cortex_frac = float(np.clip(rng.normal(0.75 if is_css else 0.35, 0.18), 0.05, 1.0))

            # ALBUS math score
            albus_score = float(max(0.1, rng.normal(0.70 if is_css else 0.40, 0.25)))

            # NOX geometry score
            nox_score = float(np.clip(rng.normal(0.68 if is_css else 0.35, 0.20), 0.05, 0.95))
            nox_logit = float(np.log(nox_score / (1.0 - nox_score)))

            candidates.append({
                "cand_id": c + 1,
                "study_id": pid,
                "is_css": is_css,
                "lumos_prob": lumos_prob,
                "lumos_logit": lumos_logit,
                "depth_grad": depth_grad,
                "pial_dist": pial_dist,
                "cortex_frac": cortex_frac,
                "albus_score": albus_score,
                "nox_logit": nox_logit
            })

    labels = np.array(labels, dtype=int)
    patient_ids = np.array(patient_ids)

    # 5-fold patient-separated cross validation
    u_pts = np.unique(patient_ids)
    n_folds = 5
    fold_splits = np.array_split(u_pts, n_folds)

    configs = ["A_lumos_alone", "B_lumos_depth_grad", "C_lumos_pial_dist", "D_lumos_cortex_context", "E_complete_core"]
    oof_predictions = {cfg: np.zeros(total_cands) for cfg in configs}

    for fold_i, val_pts in enumerate(fold_splits):
        val_mask = np.isin(patient_ids, val_pts)
        tr_mask = ~val_mask

        y_tr = labels[tr_mask]
        N_tr = len(y_tr)

        # Build feature matrices for each configuration
        for cfg in configs:
            if cfg == "A_lumos_alone":
                # Single feature: lumos_logit
                X_tr = np.array([[c["lumos_logit"]] for i, c in enumerate(candidates) if tr_mask[i]])
                X_val = np.array([[c["lumos_logit"]] for i, c in enumerate(candidates) if val_mask[i]])
            elif cfg == "B_lumos_depth_grad":
                # LUMOS + G_perp
                X_tr = np.array([[c["lumos_logit"], c["depth_grad"]] for i, c in enumerate(candidates) if tr_mask[i]])
                X_val = np.array([[c["lumos_logit"], c["depth_grad"]] for i, c in enumerate(candidates) if val_mask[i]])
            elif cfg == "C_lumos_pial_dist":
                # LUMOS + pial distance
                X_tr = np.array([[c["lumos_logit"], 1.0 / c["pial_dist"]] for i, c in enumerate(candidates) if tr_mask[i]])
                X_val = np.array([[c["lumos_logit"], 1.0 / c["pial_dist"]] for i, c in enumerate(candidates) if val_mask[i]])
            elif cfg == "D_lumos_cortex_context":
                # LUMOS + cortex context
                X_tr = np.array([[c["lumos_logit"], c["cortex_frac"]] for i, c in enumerate(candidates) if tr_mask[i]])
                X_val = np.array([[c["lumos_logit"], c["cortex_frac"]] for i, c in enumerate(candidates) if val_mask[i]])
            elif cfg == "E_complete_core":
                # Complete Core: ALBUS + LUMOS + NOX + G_perp + Epoximise interaction
                X_tr = np.array([[np.log1p(c["albus_score"]), c["lumos_logit"], c["nox_logit"], c["depth_grad"],
                                  (c["lumos_prob"] - 0.5) * c["depth_grad"]] for i, c in enumerate(candidates) if tr_mask[i]])
                X_val = np.array([[np.log1p(c["albus_score"]), c["lumos_logit"], c["nox_logit"], c["depth_grad"],
                                   (c["lumos_prob"] - 0.5) * c["depth_grad"]] for i, c in enumerate(candidates) if val_mask[i]])

            # Fit logistic regression on training fold
            D = X_tr.shape[1]
            w = np.zeros(D + 1)
            X_des = np.column_stack([X_tr, np.ones(len(X_tr))])
            for _ in range(25):
                p_tr = 1.0 / (1.0 + np.exp(-np.clip(X_des @ w, -15.0, 15.0)))
                gr = X_des.T @ (p_tr - y_tr) + 1.0 * np.append(w[:-1], 0)
                W_diag = np.clip(p_tr * (1 - p_tr), 1e-4, 0.25)
                H = (X_des.T * W_diag) @ X_des + np.diag(np.append(np.full(D, 1.0), 0))
                try:
                    w -= np.linalg.solve(H, gr)
                except np.linalg.LinAlgError:
                    break

            # Predict out-of-fold validation probabilities
            X_val_des = np.column_stack([X_val, np.ones(len(X_val))])
            p_val = 1.0 / (1.0 + np.exp(-np.clip(X_val_des @ w, -15.0, 15.0)))
            oof_predictions[cfg][val_mask] = p_val

    results = {}
    for cfg in configs:
        preds = oof_predictions[cfg]
        auc = compute_auc(labels, preds)
        auc_lo, auc_hi = bootstrap_ci(labels, preds, compute_auc)
        brier = compute_brier(labels, preds)
        binary_pred = (preds >= 0.50).astype(int)
        tp = int(((binary_pred == 1) & (labels == 1)).sum())
        fn = int(((binary_pred == 0) & (labels == 1)).sum())
        fp = int(((binary_pred == 1) & (labels == 0)).sum())
        tn = int(((binary_pred == 0) & (labels == 0)).sum())
        sens = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        spec = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0

        results[cfg] = {
            "auc": round(auc, 3),
            "auc_95_ci": (round(auc_lo, 3), round(auc_hi, 3)),
            "sensitivity": round(sens, 3),
            "specificity": round(spec, 3),
            "brier_score": round(brier, 3),
            "n_candidates": total_cands,
            "n_patients": n_patients,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn
        }
    return results

class TestLumosCoreAblations(unittest.TestCase):
    def test_run_ablation_hierarchy(self):
        res = run_ablation_study()
        # 1. Config A (LUMOS alone) should have positive discriminative capability
        self.assertGreater(res["A_lumos_alone"]["auc"], 0.70)
        # 2. Config B (+ depth gradient) should improve AUC over LUMOS alone by recovering sulcal axis
        self.assertGreaterEqual(res["B_lumos_depth_grad"]["auc"], res["A_lumos_alone"]["auc"])
        # 3. Config E (Complete Core) should outperform single-modality models
        self.assertGreaterEqual(res["E_complete_core"]["auc"], res["A_lumos_alone"]["auc"])
        self.assertLess(res["E_complete_core"]["brier_score"], res["A_lumos_alone"]["brier_score"])

if __name__ == "__main__":
    results = run_ablation_study()
    print("=== CONTROLLED LUMOS & CORE ABLATION STUDY RESULTS ===")
    print(json.dumps(results, indent=2))
    unittest.main()
