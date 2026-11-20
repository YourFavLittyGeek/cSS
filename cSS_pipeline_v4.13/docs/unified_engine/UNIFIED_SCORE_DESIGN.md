# UNIFIED_SCORE_DESIGN.md - Unified = f(MATH, CHARACTERISTICS, PAST EXPERIENCE)

## 1. The fusion rule and why

**logit p = [a + b log(score_v4 + 0.05)] + [b0 + Σ_j w_j z_j]**  (MATH logit, fixed form, 2 learned parameters) + (learned increment)

The increment is fitted with the MATH logit as an **offset**: its weights estimate only what the characteristics add *beyond* MATH.
Alternatives were tested on synthetic data (docs/unified_engine/SYNTHETIC_EXPERIMENT_REPORT.md):

| alternative | finding (synthetic) | decision |
|---|---|---|
| averaging / adding component scores ("naive") | double counts: calibration slope 0.57-0.79 in every scenario; worse than MATH when MATH is the truth (-0.015) | rejected |
| characteristics alone (learned-only) | equals MATH when signals coincide, loses -0.047 with 25 % missing inputs and -0.077 when MATH is the truth | rejected as the fusion |
| joint (math logit as a penalised free column) | as good as offset with signal; worse than MATH when MATH is the truth (-0.013) because the penalty shrinks the MATH coefficient | rejected |
| **offset** | +0.029 within-patient AUC at baseline, never below MATH on average across 9 scenarios, calibrated (slope 0.97-1.04 except under scanner darkness shifts) | **adopted** |

## 2. Overlap, correlated evidence, double counting

- score_v4 consumes darkness_z, pial_dist_mm, tube_ratio, surface_alignment, tram_frac (+ 4 flags); 5 of the 9 measured inputs overlap.
  With the offset, their weights are corrections to MATH's fixed form (e.g. a different slope), not independent evidence.
- The confidence model (24 of 30 inputs shared with MATH) and its output `confidence_pct` are never inputs (schema role `model_output`).
- Leave-one-feature-out (synthetic): removing any single score_v4 input changes the offset model by <= 0.003 within-patient AUC -
  strongly redundant, as expected; the increment came mostly from edge_contrast, which score_v4 does not use.

## 3. Missingness

Per-value status (ok / missing_structural / missing_input / missing_unexpected / corrupt / out_of_range / extrapolation_clipped /
not_measured). Structural tram_frac missingness is carried by `tram_frac_missing`; other missing values are imputed with the training
median and **counted**; more than 2 of the 9 measured inputs missing / invalid -> category `uncertain`. Informative missingness is a hazard:
in the synthetic MNAR scenario the indicator inflated the gain (+0.049) by learning the missingness mechanism.

## 4. Patient-level variation and calibration

Evaluation uses within-patient AUC (pooled AUCs mix in between-patient prevalence / intercept effects - the LOPO artefact reproduced on
pure noise). Patient bootstrap intervals. Calibration reported (slope, calibration-in-the-large, ECE). MATH's absolute darkness term is
sensitive to scanner darkness offsets (synthetic slope 0.36); the offset model inherits part of it (slope 0.76) - to be checked on real data.

## 5. Uncertainty and categories (reading aids; nothing is excluded)

30 patient-bootstrap refits -> 5-95 % interval. likely_cSS: p >= 0.7 and interval above 0.5; unlikely_cSS: p <= 0.3 and interval below 0.5;
otherwise **uncertain**, and always uncertain when an interval straddles 0.5, inputs are missing / corrupt / out of the training range,
MATH is inconsistent with its recomputation, or registration is not ok. not_scorable when MATH has no score or the object is outside the
candidate model. Synthetic check: observed cSS rate 0.94-0.96 (likely), 0.39-0.48 (uncertain), 0.04-0.06 (unlikely).

## 6. When the fusion refuses to answer (safe fallback = existing deterministic MATH)

no healthy model · model incompatible (schema / detector / engine version / mode / data_kind) · model corrupt (hash) · model trained on
synthetic data and study not synthetic · any exception in the ML path · engine subprocess crash / timeout. In every case the existing
deterministic output (score_v4, evidence, rule fate, tiers, recorded 0-4) is shown, labelled as such.

## 7. Gate for any future clinical use (not met)

Clinically labelled, patient-keyed development data (Gate B), explicit authorization to train (Gate C), and for fusion (Gate D): a
within-patient **permutation test** (or an independent test set) showing information beyond MATH, acceptable calibration on independent
patients, a frozen model evaluated once on a protected test set, documented rationale. The paired bootstrap CI is not sufficient
(1 / 13 false positives on pure noise in synthetic tests; its null is not centred at 0).
