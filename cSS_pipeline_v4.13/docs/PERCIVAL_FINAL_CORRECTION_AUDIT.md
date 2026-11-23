# PERCIVAL v5.25-dev — FINAL SAFETY, DATA-INTEGRITY, SCIENTIFIC-CORRECTION & RELEASE FREEZE AUDIT

**Mission ID**: `PERCIVAL-FINAL-ACCEPTANCE-CORRECTIONS-2026`  
**Date**: November 22, 2026  
**Target Release**: `Percival v5.25-dev`  
**Base Commit**: `ff401f289bf4bcfbdc77ccc350dc11291fb2b17a`  
**Previous Baseline Archive**: `dist/Percival_v5.25-dev_wte4a20b4.zip` (SHA-256: `b1a099ae19f71ada0a5feb2821c12d77f4fe15b3e5180e2579be800dff0ab34d`)  
**Mission Classification**: Autonomous Forensic Engineering, Safety Correction, Release Reconciliation & Release Freeze  

---

## 1. Executive Summary & Verification Decision

Following an independent forensic investigation into the candidate release `Percival v5.25-dev (wte4a20b4)`, targeted architectural, mathematical, and data integrity corrections were applied to resolve remaining safety vulnerabilities. All ten mission priorities have been fully implemented, rigorously verified across automated failure scenarios, and reconciled into a unified, reproducible build.

### Canonical Acceptance Decision
* **Gate 1 — Software, Numerical & Architectural Engineering**:  
  $$\mathbf{VERIFIED\ PASS}$$  
  All 294 executable verifications (57 unit/integration tests, 205 deep engine tests, and 32 pipeline invariant checks) execute with 100% success. Zero regressions, zero memory leaks, zero data leakage, and complete offline socket isolation.

* **Gate 2 — Clinical Diagnostic Validation**:  
  $$\mathbf{NOT\ CLINICALLY\ VALIDATED}$$  
  All empirical performance evaluations have been conducted exclusively on synthetic physical phantoms, mathematical simulations, and synthetic Gaussian distributions. The system has NOT undergone prospective multi-center clinical trials on patient populations. Clinical diagnostic use remains strictly prohibited.

---

## 2. Itemized Verification of the Ten Mission Priorities

### Priority 1: Scoring Safety on Missing & Degraded Evidence
* **Pre-Correction Defect**: When 3D MRI patch data was missing or corrupted, LUMOS passed `prob = 0.5` with `has_visual_evidence = False`. Downstream in `PercivalCoreIntelligence`, the logistic integration formula combined `albus_term` and `nox_logit` to produce an arbitrary calibrated probability ($\approx 0.31$), yielding a misleading numerical Percival Score.
* **Correction Implemented**:
  1. Updated `LumosInference` contract: `prob`, `logit`, and `depth_gradient` are now `Optional[float] = None`.
  2. In `uengine/lumos.py`: When patch data is missing, non-finite, or lacks valid SWI voxels, LUMOS returns `prob = None`, `logit = None`, `depth_gradient = None`, and `status = "unavailable"`.
  3. In `uengine/percival_core.py`: If visual appearance evidence (`has_lumos`) or quantitative geometry (`has_nox`) is missing or invalid, Core suppresses numerical scoring:
     $$\text{percival\_score} = \text{None}, \quad \text{calibrated\_prob} = \text{None}, \quad \text{band} = \text{"unavailable"}, \quad \text{confidence} = 0.0, \quad \text{uncertainty} = 1.0$$
  4. In `app/percival_gui.py`: When `asmt.percival_score is None`, the GUI explicitly assigns `s["percival_score"] = None`, displaying as an em-dash (`—`) in `percival_view.js`.

### Priority 2: NOX Geometry Integrity & Rejection of Fabricated Metrics
* **Pre-Correction Defect**: Zero or negative spacing clamped surface area to `max(0.5, ...)`, fabricating a finite Wadell sphericity ($\approx 0.806$). Empty candidate masks substituted a default 10.0-voxel volume. Single-voxel masks substituted arbitrary unit eigenvalues `[1.0, 1.0, 1.0]`.
* **Correction Implemented**:
  1. Spacing Validation: In `uengine/nox.py`, if any spacing dimension is $\le 0.0$ or non-finite, NOX marks `morphology["geometry_status"] = "invalid_spacing"`, `stability["geometry"] = "invalid_spacing"`, and sets all physical metrics (`volume_mm3`, `surface_area_mm2`, `sphericity`, `eigenvalues_mm2`, `elongation`) to `None`. No clamping or synthetic substitution occurs.
  2. Empty Mask Handling: Masks with 0 voxels set `volume_mm3 = 0.0`, `surface_area_mm2 = 0.0`, `sphericity = None`, `eigenvalues_mm2 = None`, and `geometry_status = "empty_mask"`.
  3. Single-Voxel Masks: 1-voxel masks set `sphericity = None` and `eigenvalues_mm2 = None`, reflecting that sample covariance and continuous sphericity are undefined for a single grid point.
  4. Planar Mask Truth: Planar masks preserve exact physical $\lambda_3 = 0.0$, `is_planar = True`, and compute stable in-plane elongation $\sqrt{\lambda_1 / \lambda_2}$.

### Priority 3: Checkpoint Safety & Refusal of Un-Trained Model Inference
* **Pre-Correction Defect**: `LumosImageIntelligence._load_active_checkpoint()` used a bare `try ... except Exception: pass` block. If `lumos_active_weights.npz` was corrupt, truncated, or incompatible, it silently fell through, leaving `SmallCNN` initialized with random uncalibrated weights (`seed=0`), allowing uncalibrated inference to proceed without warning.
* **Correction Implemented**:
  1. Checkpoint Integrity Verification: Validates all required weight tensors (`W1`, `b1`, `W2`, `b2`, `W3`, `b3`) and array integrity upon loading.
  2. Backup Redundancy: If the active checkpoint is corrupt, LUMOS automatically attempts recovery from `models/LUMOS/lumos_backup_weights.npz`.
  3. Refusal of Inference: If both active and backup checkpoints are corrupt or missing, LUMOS flags `checkpoint_status = "checkpoint_corrupted"`. When `analyze_patch()` is invoked, it refuses inference, returning `status = "checkpoint_unavailable"`, `prob = None`, and an explicit diagnostic error message.
  4. Checksum Identity: All checkpoints compute and store their SHA-256 hash upon loading or saving.

### Priority 4: Pensieve Ingestion Integrity & Conflict Adjudication
* **Pre-Correction Defect**: `remember_study()` used SQLite `ON CONFLICT(study_id) DO UPDATE SET`, silently overwriting existing study records and patient linkages.
* **Correction Implemented**:
  1. Content Fingerprinting: Computes a deterministic SHA-256 fingerprint over study payload attributes (`patient_pseudo_id`, `cohort`, `partition`, `voxel_spacing_mm`).
  2. Idempotent Ingestion: If an incoming study matches the existing study's content fingerprint, it executes an idempotent no-op (`status = "idempotent_noop"`).
  3. Conflict Detection: If an incoming study has the same `study_id` but a different content fingerprint, overwrite is refused (`status = "conflict_detected"`), and the discrepancy is permanently logged in `corrections_memory`.
  4. Expert Ground Truth Immutability: In `remember_candidate()`, candidates with existing expert annotations (`expert_annotations`) are permanently locked against structural overwrite by detector re-runs.

### Priority 5: Data Vault Directory Containment & Security
* **Pre-Correction Defect**: `PercivalDataVault.path(*parts)` used string prefix checking: `if not resolved.startswith(self.root_path): raise ValueError(...)`. An attacker could bypass containment using a sibling directory sharing the same prefix (e.g. `/path/to/VAULT_ATTACK` against root `/path/to/VAULT`).
* **Correction Implemented**:
  1. Substituted string prefix matching with strict path containment semantics using `pathlib.Path(resolved).resolve().is_relative_to(pathlib.Path(root).resolve())` and `os.path.commonpath([resolved, root]) == root`.
  2. Verified across `test_21_vault_prefix_containment` that both `..` directory traversal and prefix-spoofing sibling paths raise `ValueError`.

### Priority 6: Test Matrix Mathematical Reconciliation
* **Mathematical Resolution**:
  The previous forensic reports cited counts of 277 and 293. The complete reconciliation is documented in `PERCIVAL_TEST_INVENTORY.json`:
  - `tests/test_*.py`: **57** discoverable unittest test methods (formerly 56 before adding `test_21_vault_prefix_containment`).
  - `unified_engine/tests/test_*.py`: **205** deep engine test methods.
  - Subtotal Discoverable Unittests: **262** unique tests.
  - `tests/check_percival.py`: **32** sequential pipeline verification checks.
  - **Grand Total Executable Verifications**: $262 + 32 = \mathbf{294}$.
  - The historical 277 count arose from an early baseline ($205 \text{ engine} + 40 \text{ unit} + 32 \text{ pipeline} = 277$). The 293 count was ($205 + 56 + 32 = 293$). The canonical baseline is **294**.

### Priority 7: Forensic Audit of the LUMOS Ablation Study
* **Detailed Findings**: Documented in `cSS_pipeline_v4.13/docs/PERCIVAL_LUMOS_ABLATION_REAUDIT.md`.
  - The apparent jump in ROC-AUC to $0.992$ in Configuration B is the direct analytical result of sampling synthetic depth gradients from Gaussian distributions conditioned on the ground truth: $G_{\perp} \mid (y=1) \sim \mathcal{N}(0.65, 0.35^2)$ vs $G_{\perp} \mid (y=0) \sim \mathcal{N}(-0.55, 0.35^2)$.
  - Analytical Cohen's $d' = 1.20 / 0.35 \approx 3.4286 \implies \text{AUC}_{\text{theory}} = \Phi(d' / \sqrt{2}) \approx 0.9923$.
  - The test establishes the mathematical validity and leak-free convergence of the Percival Core logistic regression solver, but does NOT establish clinical efficacy on real-world MRI scans.

### Priority 8: Terminology Reconciliation & Mathematical Definitions
To eliminate ambiguity, Percival components strictly adhere to standard mathematical definitions:
1. **Raw Logit / Math Score** ($z \in \mathbb{R}$): The unbounded linear combination of evidence features or raw detector heuristic.
2. **Calibrated Probability** ($P \in [0.0, 1.0]$): Posterior probability produced by regularized Platt recalibration: $\sigma(a \cdot z + b)$.
3. **Percival Score** ($S \in [0, 100] \cup \{\text{None}\}$): Scaled integer representation $\text{round}(100 \times P)$ for clinical display, suppressed to `None` (em-dash) when evidence is incomplete.
4. **Epistemic Uncertainty** ($U \in [0.0, 1.0]$): Quantifies evidence completeness and inter-component cross-modal disagreement: $0.5 \cdot \text{TTA\_variance} + 0.5 \cdot |P_{\text{LUMOS}} - P_{\text{NOX}}|$.
5. **Assessment Confidence** ($C = 1.0 - U$): Degree of reliability of the computed assessment.

### Priority 9: Governance Safety Threshold Formalization
* **Non-Inferiority Classification**:
  The criterion $\Delta \text{Sensitivity} \ge -0.005$ ($\le 0.5\%$ allowable degradation) in `PercivalGovernance` is formalized as an **internal engineering screening threshold** for automated hypothesis pruning in Shadow ML. It is **NOT** a clinical non-inferiority margin, which requires pre-specified statistical hypothesis testing ($\Delta < -\delta_0$) with patient-powered clinical outcome bounds.

### Priority 10: Canonical Build & Release Freeze
* **Build Artifact**: Packaged via `build_percival_dev_app.sh --worktree dist`.
* **Reproducibility Verification**: Verified by clean-slate extraction and smoke testing in an isolated directory.
