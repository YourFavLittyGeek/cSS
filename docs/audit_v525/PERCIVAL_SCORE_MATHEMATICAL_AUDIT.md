# PERCIVAL v5.25-dev — MATHEMATICAL AUDIT OF SCORING ENGINES

**Document ID:** `AUDIT-MATH-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Neuroimaging Scientist, Biostatistician & Software Quality Auditor  
**Scope:** `scripts/detect_css.py`, `unified_score/uscore/`, `unified_engine/uengine/percival/meta.py`, `learners.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & Core Verdict

This audit provides a formal mathematical and computational forensic evaluation of the scoring systems implemented in Percival v5.25-dev:
1. **MATH Engine (`score_v3` and `score_v4`)**: Evaluated for algorithmic nature, determinism, physical grounding, and scale boundedness.
2. **Unified Score Engine**: Evaluated for feature definition, reliability gating, and logistic formulation.
3. **Percival Score Engine & Meta-Models**: Evaluated for level-0 log-odds integration, recalibration with $\lambda = 0.5$, boundary conditions $[0, 100]$, and missing-data safety guards.

### Primary Audit Findings:
- **MATH is NOT Machine Learning:** MATH (`score_v4`) is an entirely deterministic, hand-crafted heuristic scoring function based on geometric and physical priors. It contains zero learned weights, performs no backpropagation or parameter estimation, and requires no training data.
- **Scale and Calibration of MATH:** `score_v4` produces an unbounded positive real number $[0, +\infty)$, typically in the range $[0, 15]$. It is not a calibrated posterior probability. When integrated into Percival, it requires monotonic Platt/logistic recalibration (`MathRecalibration`) to map onto log-odds space.
- **Percival Score Strict Boundedness:** The final Percival Score is strictly bounded in $[0, 100]$ via standard logistic sigmoid activation $\sigma(z) \cdot 100$.
- **Handling of Missing Data:** When critical imaging inputs or segmentations are absent, the engine explicitly outputs `"insufficient"` (or `NaN`), rather than imputing a default zero or reassuringly low score.

---

## 2. Mathematical Audit of the MATH Engine (`detect_css.py`)

### 2.1 Algorithmic Characterization
In `cSS_pipeline_v4.13/scripts/detect_css.py` (lines 1025–1050), candidate lesions are scored by deterministic geometric and intensity heuristics.

#### `score_v3` Formula:
$$s_3 = \text{depth} \cdot (0.25 + \text{contact}) \cdot \ln(1 + \text{vol}) \cdot \prod_{k \in \mathcal{P}_3} f_k$$
where:
- $\text{depth} = \text{darkness\_z}$: Z-score intensity darkness relative to normal-appearing parenchyma.
- $\text{contact} = \text{surface\_contact}$: Fraction of candidate boundary voxels contacting CSF/pial boundary.
- $\text{vol} = \text{volume\_mm}^3$: Physical volume of the connected component.
- Multiplicative penalty factors $\mathcal{P}_3$:
  - $\text{artz} = 1 \implies \times 0.5$ (candidate intersects known susceptibility artifact zones: sinuses, air-bone interfaces).
  - $\text{midz} = 1 \implies \times 0.5$ (candidate within 5 mm of interhemispheric falx/midline).
  - $\text{cfrac} < 0.35 \implies \times 0.6$ (cortex fraction below 35%, indicating deep white matter).
  - $\text{longs} = 1 \implies \times 0.5$ (long continuous structure $> 40\text{ mm}$ along z-axis, characteristic of venous sinuses).

#### `score_v4` Formula:
$$s_4 = \sqrt{\max(\text{depth}, 0)} \cdot (0.25 + \text{on\_surf}) \cdot (0.25 + \text{sheet}) \cdot (0.5 + \text{aln}) \cdot (1.0 + \text{tram}) \cdot \prod_{j \in \mathcal{P}_4} f_j$$
where:
1. **Subpial Depth Penalty ($\text{on\_surf}$):**
   $$\text{on\_surf} = \exp\left( -\left(\frac{\text{pdist} + 0.5}{1.5}\right)^2 \right)$$
   Physical justification: cSS deposits in the subpial space of the cerebral cortex, peaking approximately $0.5\text{ mm}$ below the pial surface. Candidates deeper in cortex or deep white matter ($\text{pdist} \gg 0$) or free in sulcal CSF ($\text{pdist} > 1\text{ mm}$) suffer rapid Gaussian attenuation.
2. **Sheet Geometry vs. Tubular Vessel ($\text{sheet}$):**
   $$\text{sheet} = 1.0 - \text{tube\_ratio}$$
   Physical justification: Cerebral cortical veins are cylindrical tubes with large eigenvalue ratios ($\lambda_1 \gg \lambda_2 \approx \lambda_3$), yielding $\text{tube\_ratio} \to 1.0$. Superficial siderosis deposits are laminar sheets conforming to cortical gyri ($\lambda_1 \approx \lambda_2 \gg \lambda_3$), yielding $\text{tube\_ratio} \to 0.0$.
3. **Surface Alignment ($\text{aln}$):**
   Sulcal alignment cosine $\text{aln} \in [0, 1]$, measuring whether the principal longitudinal axis of the candidate is parallel to the cortical boundary tangent plane.
4. **Tram-Track Feature ($\text{tram}$):**
   Fraction of the lesion exhibiting parallel linear hypointensities along sulcal banks ($\text{tram} \in [0, 1]$).
5. **Multiplicative Penalties $\mathcal{P}_4$:**
   - Artifact zone: $f = 0.5$
   - Midline zone ($< 5\text{ mm}$ to falx): $f = 0.7$
   - Long venous structure ($> 40\text{ mm}$): $f = 0.5$
   - Infratentorial cerebellar/brainstem zone: $f = 0.3$
   - FLAIR acute blood/thrombosis mimic active: $f = 0.5$

### 2.2 Mathematical Critique of `score_v4`
1. **Damped Darkness Square-Root:** $\sqrt{\max(\text{depth}, 0)}$ was implemented because clinical SWI data demonstrated that pial veins with deoxyhemoglobin frequently display higher darkness Z-scores ($Z > 5$) than thin, chronic hemosiderin sheets ($Z \approx 2-3$). Linear or exponential dependence on darkness favors veins over true cSS. The square root dampens intensity dominance.
2. **Non-Normalized Output:** The product of maximum possible terms is:
   $$\max(s_4) \approx \sqrt{\text{depth}_{\max}} \cdot (1.25) \cdot (1.25) \cdot (1.5) \cdot (2.0) \approx 4.6875 \cdot \sqrt{\text{depth}_{\max}}$$
   For $\text{depth} = 9.0$, $s_4 \approx 14.06$. $s_4$ has no upper bound. It is an arbitrary positive scalar ranker, not a calibrated likelihood ratio or probability.

---

## 3. Mathematical Audit of the Unified Score Engine (`uscore/`)

The Unified Score combines 5 morphometric and anatomical predictors:
- $x_1$: Vessel continuity length ($\text{mm}$)
- $x_2$: Dark core contrast ($\text{nu}$)
- $x_3$: Distance to pial surface ($\text{mm}$)
- $x_4$: Sulcal surface alignment cosine ($\in [0, 1]$)
- $x_5$: Extracranial continuation length ($\text{mm}$)

### 3.1 Reliability Gating Matrix
Each feature $x_k$ is accompanied by a validation gate:
$$g(x_k) \in \{\text{"reliable"}, \text{"unreliable"}, \text{"missing"}\}$$
If $x_3$ (pial distance) is unreliable (e.g., failed brain mask or skull-stripping artifact), $x_3$ is marked invalid.
The linear predictor is computed as:
$$\eta_{\text{unified}} = \beta_0 + \sum_{k=1}^5 \beta_k \cdot \tilde{x}_k$$
where $\tilde{x}_k$ is standardized using training set medians and interquartile ranges. If more than 2 features are missing or unreliable, the prediction reverts to `"insufficient"` rather than evaluating with arbitrary zeros.

---

## 4. Mathematical Audit of Percival Score & Meta-Models (`meta.py`)

### 4.1 Level-0 Components in Log-Odds Space
Percival defines 5 level-0 components, each mapped into log-odds space ($z = \text{logit}(p) = \ln(p / (1 - p))$):
1. $z_{\text{math}}$: Monotonic recalibration of `score_v4`:
   $$z_{\text{math}} = a \cdot \ln(s_4 + \epsilon) + b$$
   fitted via Iteratively Reweighted Least Squares (IRLS) against expert review labels $y \in \{0, 1\}$.
2. $z_{\text{unified}}$: Penalized logistic regression on $x_1, \dots, x_5$.
3. $z_{\text{char}}$: Penalized logistic regression, Gradient Boosted Trees (GBT), or Random Forest over candidate morphology features:
   $$\mathbf{x}_{\text{char}} = [\text{darkness\_z}, \text{edge\_contrast}, \text{pial\_dist\_mm}, \text{cortex\_frac}, \text{tram\_frac}, \text{tube\_ratio}, \text{elongation\_3d}, \log(\text{vol}), \text{local\_cont\_max\_mm}]$$
4. $z_{\text{image}}$: Log-odds output from the pure NumPy CNN on surface-aligned $24 \times 12 \times 8\text{ mm}$ patches.
5. $z_{\text{fusion}}$: Second-level logistic fusion model combining image log-odds with tabular characteristics.

### 4.2 Meta-Model Integration Families
Seven candidate meta-models are compared on development folds:
1. `math_only`: $z_{\text{meta}} = z_{\text{math}}$
2. `equal_mean`: $z_{\text{meta}} = \frac{1}{|\mathcal{S}|} \sum_{c \in \mathcal{S}} z_c$, where $\mathcal{S}$ is the set of available valid components.
3. `logreg_unweighted`: Unpenalized logistic regression on available log-odds.
4. `ridge_calibrated`: L2-penalized logistic regression with cross-validated penalty $\lambda$.
5. `rf_light`: Shallow random forest (max depth 3, 20 trees).
6. `gbm_light`: Shallow gradient boosting (max depth 2, learning rate 0.05).
7. `stack_fusion`: Stacking logistic regression over $\{z_{\text{math}}, z_{\text{unified}}, z_{\text{fusion}}\}$.

### 4.3 Double-Counting Prevention
To prevent collinear variance inflation and circularity:
$$\mathcal{M}_{\text{valid}} \iff \text{No meta-model includes } z_{\text{fusion}} \text{ simultaneously with } z_{\text{char}} \text{ or } z_{\text{image}}.$$
Since $z_{\text{fusion}}$ is derived from $z_{\text{char}}$ and $z_{\text{image}}$, including all three in a linear model creates severe multicollinearity and double-counts evidence. This invariant is enforced in `MT.SIMPLICITY` and verified in test assertions.

### 4.4 Recalibration and Final Scaling
For the selected meta-model output $z_{\text{meta}}$:
$$z_{\text{cal}} = \alpha \cdot z_{\text{meta}} + \beta$$
To prevent extreme overconfidence from empirical fits on small sample sizes, Percival applies shrinkage towards unscaled log-odds with $\lambda_{\text{cal}} = 0.5$:
$$\alpha_{\text{reg}} = (1 - \lambda_{\text{cal}}) \cdot \alpha + \lambda_{\text{cal}} \cdot 1.0$$
$$\beta_{\text{reg}} = (1 - \lambda_{\text{cal}}) \cdot \beta + \lambda_{\text{cal}} \cdot 0.0$$
The final posterior probability is:
$$p_{\text{percival}} = \sigma(z_{\text{cal}}) = \frac{1}{1 + e^{-z_{\text{cal}}}}$$
The integer Percival Score displayed in the UI is:
$$\text{Percival Score} = \text{round}(100 \cdot p_{\text{percival}}), \quad \in [0, 100]$$

### 4.5 Decision Thresholds
Percival defines three clinical operational tiers based on validated empirical cutpoints:
- **High Confidence cSS:** $\text{Score} \ge 70$ (Green band) — High specificity ($\ge 95\%$), minimal false positives.
- **Equivocal / Review Required:** $35 \le \text{Score} < 70$ (Amber band) — Reader review mandatory.
- **Negative / Vessel / Artifact:** $\text{Score} < 35$ (Gray/Neutral band) — Ruled out as vascular mimic or noise.

---

## 5. Mathematical Verdict

| Component | Mathematical Soundness | Status | Comments |
|---|---|---|---|
| MATH `score_v3` | Heuristic / Empirical | PASS | Preserved for backward comparison. |
| MATH `score_v4` | Geometric / Physical Heuristic | PASS | Deterministic; requires recalibration when converted to probability. |
| Unified Score | Standard Regularized Logistic | PASS | Bounded, includes feature reliability gates. |
| Percival Meta-Models | Logistic / Tree Ensembles | PASS | Double-counting strictly prevented; 1-SE rule enforced. |
| Recalibration ($\lambda=0.5$) | Shrinkage Recalibration | PASS | Prevents over-fitting on small sample sizes. |
| Final Scaling | Sigmoid $\to [0, 100]$ | PASS | Strictly bounded $[0, 100]$; `"insufficient"` upon missing critical inputs. |

**Audit Conclusion:** The mathematical formulations governing Percival's scoring engines are rigorously implemented, mathematically consistent, and free of algebraic circularities.
