# PERCIVAL v5.25-dev — ARCHITECTURAL AUDIT OF MACHINE LEARNING SUBSYSTEMS

**Document ID:** `AUDIT-ML-ARCH-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Machine Learning Architect & Senior Software Engineer  
**Scope:** `unified_engine/uengine/percival/`, `learners.py`, `meta.py`, `cnn.py`, `store.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Architectural Overview & System Decomposition

Percival v5.25-dev implements a hierarchical two-level machine-learning architecture for detecting, scoring, and ruling out cerebral superficial siderosis (cSS) on brain SWI MRI scans.

```
                           +------------------------+
                           |  RAW SWI MRI & T1/SEG  |
                           +------------------------+
                                       |
              +------------------------+-----------------------+
              |                                                |
              v                                                v
    +-------------------+                            +-------------------+
    | Candidate Extract |                            | Surface-Aligned   |
    | (3D Morphometry)  |                            | Patch Extraction  |
    +-------------------+                            +-------------------+
              |                                                |
    +---------+---------+---------+                            |
    |                   |         |                            |
    v                   v         v                            v
+--------+         +--------+ +--------+                  +---------+
|  MATH  |         | UNIFIED| |  CHAR  |                  |  IMAGE  |
| Engine |         | Score  | |   ML   |                  |   CNN   |
+--------+         +--------+ +--------+                  +---------+
    |                   |         |                            |
    |                   |         +-------------+--------------+
    |                   |                       |
    |                   |                       v
    |                   |              +-----------------+
    |                   |              |    FUSION ML    |
    |                   |              | (Late/Feat/Hyb) |
    |                   |              +-----------------+
    |                   |                       |
    +-------------------+-----------------------+
                        |
                        v
         +-----------------------------+
         |      META-MODEL SELECTION   |
         |      (1-SE Simplicity Rule) |
         +-----------------------------+
                        |
                        v
         +-----------------------------+
         |    SHRINKAGE RECALIBRATION  |
         |         (lambda = 0.5)      |
         +-----------------------------+
                        |
                        v
         +-----------------------------+
         |     PERCIVAL SCORE [0-100]  |
         |   (High / Equivocal / Neg)  |
         +-----------------------------+
```

---

## 2. Level-0 Component Characterization

The system decomposes candidate appraisal into five foundational Level-0 predictors:

| Predictor | Modality / Input | Mathematical Engine | Learned? | Code Location |
|---|---|---|---|---|
| **MATH** | 3D candidate morphology, pial distance, tram-track, z-darkness | Deterministic geometric/physical heuristic (`score_v4`) | NO (Recalibrated via 1D IRLS) | `scripts/detect_css.py` |
| **UNIFIED** | 5 morphometry features ($x_1 \dots x_5$) with reliability gates | Penalized logistic regression | YES | `unified_score/uscore/features.py` |
| **CHAR** | 9 tabular morphometry features | Logistic, GBT, or Random Forest | YES | `percival/meta.py`, `learners.py` |
| **IMAGE** | $24 \times 12 \times 8\text{ mm}$ physical surface patch ($3 \times 49 \times 25$ maps) | 1,425-parameter pure NumPy CNN | YES | `percival/cnn.py` |
| **FUSION** | Multi-modal combination of Char and Image | Decision-level (Late), Feature-level, or Hybrid logistic | YES | `percival/meta.py` |

### 2.1 The Characteristic ML Subsystem
`CHAR` takes 9 explicit geometric and intensity measurements:
`["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d", "log_volume_mm3", "local_cont_max_mm"]`

Notice that `score_v4` and `score_v3` are **excluded** from `CHAR`. This design choice avoids tautological circularity while allowing the machine learner to discover non-linear interactions among raw physical variables.

### 2.2 The Fusion ML Subsystem
Fusion integrates visual representations from `IMAGE` with tabular features from `CHAR`:
- **Late Fusion:** Logistic regression solely on $[z_{\text{char}}, z_{\text{image}}]$.
- **Feature Fusion:** Logistic regression on tabular features + $z_{\text{image}}$: $[\mathbf{x}_{\text{char}}, z_{\text{image}}]$.
- **Hybrid Fusion:** Logistic regression on $[\mathbf{x}_{\text{char}}, z_{\text{image}}, z_{\text{char}}]$.

Selection among Fusion families is performed automatically on out-of-fold log-loss using the 1-SE rule (`Late < Feature < Hybrid`).

---

## 3. The 7 Candidate Meta-Models & Model Discovery

Percival evaluates seven candidate meta-models on patient-grouped cross-validation folds:

1. `math_only`: Baseline control relying strictly on the recalibrated physics heuristic.
2. `equal_mean`: Simple unweighted average of available level-0 log-odds: $\bar{z} = \frac{1}{|\mathcal{S}|} \sum_{c \in \mathcal{S}} z_c$.
3. `logreg_unweighted`: Standard unregularized logistic regression over component log-odds.
4. `ridge_calibrated`: L2-regularized logistic regression with cross-validated penalty parameter $\lambda \in [10^{-3}, 10^3]$.
5. `rf_light`: Lightweight Random Forest (20 estimators, maximum tree depth 3, minimum samples per leaf 5).
6. `gbm_light`: Lightweight Gradient Boosted Trees (learning rate 0.05, 30 iterations, maximum depth 2).
7. `stack_fusion`: Stacking logistic model combining $[z_{\text{math}}, z_{\text{unified}}, z_{\text{fusion}}]$.

### 3.1 The 1-SE Simplicity Selection Rule
In `meta.py` (`_select`):
```python
best = min(ok, key=lambda k: ok[k]["logloss"])
lim = ok[best]["logloss"] + (ok[best].get("logloss_se") or 0)
return next(k for k in order if k in ok and ok[k]["logloss"] <= lim)
```
Where `order` defines the a priori complexity hierarchy:
$$\text{math\_only} \prec \text{equal\_mean} \prec \text{logreg\_unweighted} \prec \text{ridge\_calibrated} \prec \text{rf\_light} \prec \text{gbm\_light} \prec \text{stack\_fusion}$$

*Scientific Appraisal:* A complex ensemble (e.g., `gbm_light` or `stack_fusion`) will **never** be selected over a simpler linear or averaging model unless its cross-validated log-loss improves by more than one full bootstrap standard error. This provides robust defense against overfitting on small medical datasets.

### 3.2 Small-Cohort Tree/Boosting Guard
When candidate count is low ($N < 60$), gradient boosted trees and random forests are automatically skipped with an explicit documented justification in the training report (`"skipped: cohort size < 60"`), falling back to regularized linear or averaging models.

---

## 4. Model Registry, Promotion & Immutability

### 4.1 Schema and Storage (`store.py`)
Model artifacts are serialized into JSON dictionaries adhering to Schema 4:
- `engine`: Engine identifier and version tag (`percival-engine/5.24`).
- `timestamp`: UTC ISO 8601 string.
- `fingerprint`: SHA-256 hash of training study codes and reviewer annotations.
- `components`: Serialized weights for MATH, UNIFIED, CHAR, IMAGE, FUSION.
- `meta_model`: Selected meta-model architecture and coefficients.
- `thresholds`: Validated high-confidence and review-required cutpoints.
- `component_metrics`: Out-of-fold AUC, PR-AUC, Brier score, and calibration parameters.

### 4.2 Promotion and Rollback Lifecycle
1. **Candidate State:** Newly trained models are initially stored in `models/candidate_vX.json`.
2. **Promotion:** User must explicitly promote the model via UI or API (`/api/percival/promote`). The active production link is updated atomically via symbolic symlink `models/active.json`.
3. **Rollback:** Any previous model version remains permanently archived in `models/history/`. Rollback to an earlier model is guaranteed to restore exact identical inference outputs.
4. **Prediction Ledger Immutability:** Historical candidate calls and study assessments are recorded in an append-only JSON ledger (`records/ledger.jsonl`). A model promotion or detector rerun never overwrites past clinical decisions.

---

## 5. Architectural Verdict

**ML Architecture: PASS — EXCELLENT SCIENTIFIC DESIGN**  
The separation of level-0 specialized domain models from higher-level meta-learners, combined with the 1-SE simplicity rule, small-cohort guards, and immutable registry versioning, represents an exceptionally well-engineered medical AI architecture.
