# Unified score: definitive feature dictionary (cycle-2 audit, branch `experimental/unified-gui`)

Source of truth: `unified_score/uscore/features.py` (definitions), `uscore/common.py:9` (`PREDICTORS`), and `uscore/model.py` (how they enter the model). Line numbers refer to the current working tree.

## How features enter the model (all five)
- **Status per value:** each value is `reliable`, `unreliable` or `unavailable`.
- **Only reliable values enter the model** (`model.design`, model.py:22). Unreliable and unavailable values are set to the training mean after standardisation, so they contribute exactly 0. They are never negative evidence (tested in `check_uscore_pipeline` 3 and `check_uscore_features`).
- **Standardisation** uses the training patients' reliable values only (`standardise_fit`). The ridge penalty excludes the intercept.
- **Primary model:** z = b0 + Σ b_j·x_j over these five keys, in this order.
- **Predeclared fallback** (common.py:10): if events ÷ slopes < 10, drop x4, then x5.
- **Fitted directions** are reported per outer fold, with sign agreement, on the Train & validate screen. They are not yet known for real data; the "expected direction" below is the design hypothesis, not a constraint.

| # | Key (`PREDICTORS`) | Name | Implementation | Unit / range | Exact definition | Expected direction (hypothesis) | Reliable when | Unreliable / unavailable | In primary model |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `x1_vessel_continuity_mm` | Vessel continuity | `features.x1_vessel` (l. 80) | mm, 0 … 2× crop margin (crop margin 20 mm) | Z = voxels within max(1.5 mm, 1 voxel) of the candidate. V = vessel-map components touching Z. The centreline of V (distance-transform ridge) outside Z splits into pieces; reach = max distance of a piece from the candidate. TRAVERSE = two pieces whose contact centroids are ≥ 2 mm apart. **x1 = sum of the two largest reaches if TRAVERSE, else 0** (contact without traverse = 0) | higher → less cSS-like (a vessel passes through) | vessel map present and registration ok / marginal (the map is restricted by labels). Censoring at the crop edge is a note (lower bound) | unavailable: no vessel map. Unreliable: registration unreliable / unverified / SWI-only | **yes** |
| 2 | `x2_core_contrast_nu` | Dark-core contrast | `features.x2_core` (l. 113), core from `core_decompose.decompose_experimental` | noise units (robust SD of the 2–5 mm background shell), 0 … ~40 | c = (μ_b − I) / σ_b, where μ_b, σ_b are the median and MAD-SD of the shell after one 2-MAD clip (masked voxels filled beforehand). Core = c ≥ 3 at the local peak and c ≥ 0.5 × local peak. **x2 = median c over the core** | higher → more cSS-like (to be learned; vessels are also dark) | a core exists and ≤ 50 % of core voxels are unstable | unavailable: shell has < 20 valid voxels. Unreliable: no core (value = median over the candidate) or core unstable | **yes** |
| 3 | `x3_pial_distance_mm` | Distance to the brain surface | `features.x3_pial` (l. 127) | mm, about −10 … +10 (− in tissue, + in CSF) | **median of the signed pial distance map** (`work/ID_pial_sd`) over the core (or the candidate if the core has < 3 voxels) | more negative (subpial / cortical) → more cSS-like | T1 anatomy and label shift ≤ 1.0 mm | unavailable: no pial distance map. Unreliable: registration unreliable / unverified, SWI-only anatomy | **yes** |
| 4 | `x4_sulcal_alignment` | **Surface conformity** (approved name, decision of 2026-11-19): the relationship of the candidate geometry to the brain surface. **Not equivalent to alignment along a sulcus.** The internal key keeps its old name for file compatibility | `features.x4_sulcal` (l. 134) | 0 … 1 | n = mean unit gradient of the pial distance over the core (the surface normal). PCA axes of the core in mm, λ1 ≥ λ2 ≥ λ3. **Line** (λ1/λ2 ≥ 2.25): x4 = 1 − \|e1·n\|. **Sheet** (λ2/λ3 ≥ 2.25): x4 = \|e3·n\|. Otherwise undefined | higher → more cSS-like (lies in / along the surface) | T1 anatomy, label shift ≤ 0.5 mm, a line or sheet shape, normal coherence (resultant length) ≥ 0.5 | unavailable: no anatomy or < 3 voxels. Unreliable: shift > 0.5 mm, SWI-only, shape undefined (blob-like), incoherent normals | **yes** (first to be dropped by the fallback) |
| 5 | `x5_extracranial_mm` | Extracranial continuation | `features.x5_extracranial` (l. 172) | mm, 0 … crop margin | On the **unmasked** SWI, c_raw = (μ_b − raw) / σ_b. R = connected component (26-connectivity) of {c_raw ≥ 3 and raw ≥ 0.15 μ_b} ∪ candidate that contains the candidate. **x5 = maximum distance from the brain mask over R outside the brain mask** | higher → less cSS-like (artefact / scalp continuation) | unmasked SWI on the same grid; registration ok / marginal (the mask comes from labels) | unavailable: no unmasked SWI or no brain mask. Unreliable: registration. Known bias: blooming adds ~1–1.5 mm. Continuation across a bone signal void is not followed | **yes** (second to be dropped) |

## Finding: x4 is not alignment along the sulcus
- **What the design intended:** "alignment along the sulcus", meaning whether the candidate runs along the local sulcal axis (fundus / bank direction).
- **What x4 computes:**
  - **Sheet mode:** whether the sheet lies in the surface or sulcal wall (\|e3·n\|, the plane normal against the surface normal). For a cSS band on a sulcal bank this captures the intended meaning, so sheet mode is consistent with "lies along the sulcal wall".
  - **Line mode:** 1 − \|e1·n\| asks only whether the line is **tangent to the surface**. A line running along a sulcus and a line crossing it over a gyral crown are both tangent and both score ≈ 1. So in line mode **x4 is a surface-tangency / conformity descriptor, not sulcal-axis alignment.**
- **Is it a coordinate-PCA morphology descriptor?** Partly. It combines the object's own PCA axes (morphology) with the surface normal from the pial distance gradient (anatomy). It is not pure PCA morphology: it does use anatomy, but only the surface normal, not the sulcal axis.
- **Demonstrated** in `tests/check_uscore_features.py`, x4-audit section, on a synthetic sulcus:

  | Synthetic line | x4 (current) | x4b (exploratory sulcal axis) |
  |---|---|---|
  | on the bank, along the sulcus | 1.00 | 1.0 |
  | on the crown, across the sulcus | 1.00 | 0.0 |
  | on a flat convexity | 1.00 | unavailable (no sulcal axis exists) |

**Proposed correction** (for your decision; nothing substituted silently):
- **Option A, rename (no model change):** call x4 "surface conformity" everywhere and keep its definition. This is the honest description of what it measures; the GUI already labels it "x4 surface conformity*" with an explanatory note.
- **Option B, replace in line mode (model change):**
  - define x4 = \|e1·s\| for lines and keep \|e3·n\| for sheets;
  - s = the sulcal axis, the smallest-eigenvalue eigenvector of the structure tensor of surface normals within 6 mm;
  - on a flat convexity (no folding) a line's x4 would be "unavailable" (no evidence either way).

  This is implemented as the **exploratory, non-model** descriptor `x4b_sulcal_axis_exploratory` (features.py l. 151) so it can be evaluated first. Adopting it means re-defining predictor 4 and re-training, which needs your approval.
- **Recommendation:** Option A now (no ambiguity). Option B only if, after a development-set comparison, it adds information, decided before any held-out evaluation.

## Calculated but NOT primary-model predictors
**Unified engine (stored in the feature files and reports; not in `PREDICTORS`):**
- **`x4b_sulcal_axis_exploratory`:** exploratory sulcal-axis alignment for lines (above).
- **Candidate-level meta** (`F["_meta"]`): candidate_voxels, core_voxels, core_pieces, core_unstable_frac, decomposition status and label (experimental), shape_resolvable, registration state.
- **Feature extras:**
  - x1: contact, traverse, overlap_frac, reaches, censored, notes;
  - x2: core_voxels, core_unstable_frac;
  - x3: iqr, on (core / candidate);
  - x4: mode (line / sheet), axis_ratio_12, axis_ratio_23, normal_coherence;
  - x5: ext_voxels, pieces, censored.
- **Detector-only measures** (detectors.py), used by the alternative-explanation detectors, never by the model:
  - vein: centreline_overlap_frac, tubular_cross_section (λ2/λ3 ≤ 2 and √(λ1/λ2) ≥ 2), resolved_cross_section, sheet_components (λ2/λ3 ≥ 3, ≥ 3 mm);
  - extracranial: continuous, connected_to_core;
  - skull interface: void_distance_mm, parallel_cos, outside_cortex, band_shaped, vessel_overlap.
- **Perturbation summaries** (perturb.py): per-feature unstable fraction and range, traverse_kept_frac, x5_min_mm, core_jaccard_median, core_kept_frac, score_range. They feed protective flags and detector "unresolved" conditions only.
- **Inputs used only by the decision engine:** detector CSV columns infra_frac, infratentorial and near_ich_suggest (out-of-scope protective flags).
- **Comparator only:** v5.10 `confidence_pct`, shown separately as "not comparable".

**3-D viewer (`scripts/css_morph3d.py`, display only; the unified score does not use any of these):**
- volume, mesh surface area, sphericity, surface / volume;
- PCA eigenvalues / sd / axes / ratios, extents;
- local thickness (median, min, max, p10, p90);
- local-shape shares, including the new resolution classes;
- resolution samples_median;
- skeleton length / ends / branches, cross-section profile and CV;
- image-Hessian shares;
- pial-surface relation, cortical footprint, vessel contact;
- reliability level and notes.

**Detector (`detect_css.py`):** 128 candidate columns. None is a unified predictor; only the four decision inputs above are read.

## Decision (2026-11-19): x4 kept as "surface conformity"; x4b exploratory
- **x4** stays in the primary model unchanged (definition, training and coefficients untouched). Everywhere it is shown it is named **surface conformity** and explained as the relationship of the candidate geometry to the brain surface, explicitly *not* alignment along a sulcus.
- **x4b sulcal axis** (`x4b_sulcal_axis_exploratory`) is a separate exploratory descriptor, never in `PREDICTORS`, never used for training, calibration or the decision.
  - Method: surface normals n = unit gradient of the pial distance at near-surface voxels (|pial distance| ≤ 2 mm) within 6 mm of the object; structure tensor J = mean(n nᵀ), eigenvalues l0 ≤ l1 ≤ l2; sulcal axis s = e0. x4b = |t · s|, t = the object's first principal axis (1 along the sulcus, 0 across).
  - **Unavailable:** no pial distance map (no anatomy); fewer than 3 voxels; not line-like (λ1/λ2 < 2.25; sheets are covered by x4 sheet mode); fewer than 20 surface voxels nearby; surface not folded (l1 < 0.1, e.g. flat convexity: no sulcal axis exists).
  - **Unreliable:** any registration reason under the strict rule (label shift > 0.5 mm, unverified / SWI-only registration).
  - Reliability limits: validated only on synthetic geometry (1.0 along, 0.0 across); never validated on the cohort.
