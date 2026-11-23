# PERCIVAL v5.25-dev — AUDIT OF NESTED VALIDATION & ABLATION ARCHITECTURE

**Document ID:** `AUDIT-NESTED-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Neuroimaging Scientist & Biostatistician  
**Scope:** `unified_engine/uengine/percival/nested.py`, `tests/test_ablation.py`, `tests/test_patient_split.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & Core Verdict

In neuroimaging biomarker research, cross-validation that fails to encapsulate model selection, hyperparameter tuning, feature transformations, and calibration produces heavily biased performance estimates. Percival v5.25-dev introduces `nested.py`, a dedicated engine executing patient-grouped nested cross-fitting across the entire machine-learning procedure.

### Primary Audit Verdict:
1. **Full Outer-Fold Encapsulation:** Every data-dependent transformation (median imputation, feature standardization, regularizer $\lambda$ selection, tree splitting, Platt calibration, and decision cutpoints) is fitted strictly on outer-training patients ($tr$). Outer-held-out patients ($te$) are evaluated exactly once on the frozen pipeline.
2. **Comprehensive 12-Model Ablation Suite:** The architecture systematically contrasts the full ensemble against 12 component subsets (e.g., MATH alone, Image alone, Characteristic alone, Stack without Image, etc.).
3. **Paired Patient-Bootstrap Inference:** Differences in discrimination ($\Delta \text{AUC}$) are assessed via 500 paired cluster-bootstrap resamples clustered at the patient level ($u \in \text{unique patients}$), producing valid non-parametric $95\%$ confidence intervals.
4. **Critical Scientific Interpretation of AUC Metrics:** In synthetic cohort runs (`check_percival.py`), meta-models achieve $\text{AUC} \approx 1.000$, whereas MATH achieves $\text{AUC} \approx 0.35-0.70$. As audited herein, this is an artifact of synthetic distribution separation, NOT proof of clinical perfection.

---

## 2. Mathematical Structure of Nested Cross-Fitting

### 2.1 The Two-Level Partition Scheme
- Outer loop: $K_{\text{outer}} = 5$ patient folds.
  - Development cohort $\mathcal{D}_{\text{dev}} = \bigcup_{k=1}^5 \mathcal{F}_k$, where $\mathcal{F}_j \cap \mathcal{F}_k = \emptyset$ at the patient ID level.
- Inner loop: $K_{\text{inner}} = 3$ patient folds.
  - For outer fold $k$, the outer training set is $\mathcal{T}_k = \mathcal{D}_{\text{dev}} \setminus \mathcal{F}_k$.
  - The inner loop partitions $\mathcal{T}_k = \bigcup_{m=1}^3 \mathcal{I}_{k, m}$.

```
+-----------------------------------------------------------------------------+
| OUTER LOOP: K_outer = 5 Patient Folds                                       |
|                                                                             |
| +-------------------------------------------------------+ +---------------+ |
| | OUTER TRAINING PATIENTS (T_k = D_dev \ F_k)           | | HELD-OUT (F_k)| |
| |                                                       | | (Unseen)      | |
| |   INNER LOOP: K_inner = 3 Folds                       | |               | |
| |   +-------------+ +-------------+ +-------------+     | |               | |
| |   | Inner CV 1  | | Inner CV 2  | | Inner CV 3  |     | |               | |
| |   +-------------+ +-------------+ +-------------+     | |               | |
| |   - Component Family Discovery (1-SE Rule)            | |               | |
| |   - Inner OOF Predictions generated                   | |               | |
| |   - Fusion Model fitted on Inner OOF                  | |               | |
| |   - Meta-Model fitted & Platt calibrated              | |               | |
| |   - Decision thresholds established                   | |               | |
| |                                                       | |               | |
| |   Refit full pipeline on T_k                          | |               | |
| +-------------------------------------------------------+ +---------------+ |
|                            |                                      ^         |
|                            +--- Evaluated ONCE on F_k ------------+         |
+-----------------------------------------------------------------------------+
```

### 2.2 Proof of Leakage Prevention
Let $\Theta(\mathcal{T}_k)$ denote the complete set of pipeline parameters (medians, scaling, feature selection, network weights, meta-weights, calibration parameters, thresholds).
Because:
$$\mathcal{T}_k \cap \mathcal{F}_k = \emptyset \quad \text{and} \quad \Theta \text{ is computed strictly from } \mathcal{T}_k$$
$$\mathbb{E}[\text{Loss}(\mathcal{F}_k; \Theta(\mathcal{T}_k))]$$
is an unbiased estimate of the generalization error of the learning algorithm on unseen subjects drawn from the same population.

---

## 3. The 12-Model Ablation Suite

`nested.py` executes 12 controlled ablations (`ABLATIONS`) on identical patient folds:
1. `Characteristic ML alone` ($[\text{char}]$)
2. `Image ML alone` ($[\text{image}]$)
3. `Unified Score alone` ($[\text{unified}]$)
4. `MATH alone` ($[\text{math}]$)
5. `Characteristic + Image` ($[\text{char}, \text{image}]$)
6. `Characteristic + Unified` ($[\text{char}, \text{unified}]$)
7. `Image + Unified` ($[\text{image}, \text{unified}]$)
8. `Fusion alone` ($[\text{fusion}]$)
9. `All components (stack)` ($[\text{math}, \text{unified}, \text{char}, \text{image}]$)
10. `Without Unified Score` ($[\text{math}, \text{char}, \text{image}]$)
11. `Without Image ML` ($[\text{math}, \text{unified}, \text{char}]$)
12. `Without Characteristic ML` ($[\text{math}, \text{unified}, \text{image}]$)

### 3.1 Handling Missing Inputs in Subsets
In `SubsetStack`:
When an input component is missing for a candidate (e.g., Image ML failed due to corrupted FOV), the value is imputed with the training fold median, and an explicit binary missingness indicator column (`col_missing`) is fed to the penalized logistic model. If all component inputs for a candidate are missing, the output evaluates to `NaN` (`"insufficient"`), strictly preventing false negative scores.

---

## 4. Paired Patient-Bootstrap Statistical Inference

To compare model $A$ against model $B$:
1. Candidates evaluated by both models are filtered: $\mathcal{C}_{\text{eval}} = \{i : \text{finite}(s_A(i)) \land \text{finite}(s_B(i))\}$.
2. Unique patient clusters $\mathcal{U} = \text{unique}(\{p(i) : i \in \mathcal{C}_{\text{eval}}\})$ are identified.
3. For $b = 1, \dots, 500$:
   - Sample $|\mathcal{U}|$ patients with replacement: $\mathcal{U}^{*(b)}$.
   - Extract all candidates associated with $\mathcal{U}^{*(b)}$.
   - Compute $\Delta \text{AUC}^{*(b)} = \text{AUC}_A^{*(b)} - \text{AUC}_B^{*(b)}$.
4. The $95\%$ empirical confidence interval is extracted as the 2.5th and 97.5th percentiles: $[\Delta_{2.5\%}, \Delta_{97.5\%}]$.
If $0.0 \in [\Delta_{2.5\%}, \Delta_{97.5\%}]$, the incremental improvement is statistically indistinguishable from zero at $\alpha = 0.05$.

---

## 5. Critical Scientific Warning: Synthetic vs. Clinical AUC

### 5.1 The Synthetic AUC=1.000 Phenomenon
In test executions on synthetic phantoms (`check_percival.py`), test metrics report:
- `math_only`: $\text{AUC} = 0.357 - 0.705$
- `equal_mean`: $\text{AUC} = 0.998 - 1.000$
- `stack_fusion`: $\text{AUC} = 1.000$

**Scientific Causation:**
In `phantom.py` and `make_synthetic.py`, synthetic cSS lesions are generated with distinct, independent Gaussian shifts across darkness ($Z \sim \mathcal{N}(-2, 0.8)$), edge contrast ($+0.3$), cortex fraction ($+0.2$), and tube ratio ($-0.8$).
When combining 5 independently perturbed features into a multi-feature logistic or ensemble classifier, the joint signal-to-noise ratio ($d' = \sqrt{\sum d_k^2}$) scales with the square root of the number of features, driving receiver operating characteristic curves to near-perfection.
In contrast, MATH applies a rigid, hand-crafted multiplicative formula tuned for real human cortical morphology; because synthetic lesion geometry deviates from human cortical sulcal geometry, MATH is severely penalized.

**Mandatory Audit Stance:**
AUC values derived from synthetic phantoms verify software execution correctness, pipeline connectivity, and absence of code crashes. They do **NOT** constitute proof of clinical superiority or diagnostic efficacy in human cerebral superficial siderosis. Clinical performance must be validated solely on multi-center human cohorts.

---

## 6. Audit Verdict

**Nested Validation Architecture: PASS**  
The nested cross-fitting implementation in `nested.py` meets the highest contemporary standards of biostatistical rigor, featuring strict patient cluster isolation, paired non-parametric bootstrapping, and comprehensive ablation reporting.
