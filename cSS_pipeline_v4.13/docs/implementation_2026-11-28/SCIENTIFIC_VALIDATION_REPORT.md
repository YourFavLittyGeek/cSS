# Scientific validation report — PERCIVAL validation methodology 2.0 (2026-11-28)

PERCIVAL is an experimental research decision-support system. Nothing in this report is a clinical validation.

## 1. Root cause of the v001 failure (reproduced, read-only, on the cached development scores)
| Quantity (development cohort ds001: 559 candidates, 38 patients, 33 cSS in 16 patients) | Value |
|---|---|
| ALBUS level-0 out-of-fold AUC (pooled) | 0.64 |
| ALBUS level-0 AUC **within** the held-out folds (fold-stratified) | **0.69** |
| v001 meta level: per-fold slopes of the 5 re-split folds | 0.34, 0.39, 0.32, 0.99, 0.04 (all positive) |
| v001 meta level: pooled out-of-fold AUC (math_only) | 0.508 |
| random predictor through the v001 procedure (200 runs) | 0.42 mean (0.33–0.52) |
| v001 calibration slope (pooled) | −0.41 → reversed a correctly ordered model (test 0.92 → 0.09) |
| within-fold common calibration slope of the ALBUS score (new method) | **+0.30** (per-fold 0.80, −0.17, 0.77, −0.01, 0.18) |

Mechanism: the meta level split the out-of-fold table into NEW random folds, so a held-out meta fold mixed component predictions made by
five different fold models with different intercepts; held-out prevalence differed between folds (0.023–0.098, unstratified); the
between-fold offsets dominated a weak within-fold ranking; a calibration fitted on that pooled table then got a negative slope.
The 773e08b clamp stopped the reversal but left flat, uninformative scores.

## 2. Methodology now (code: `uengine/percival/validation.py`, used by `meta.py`, `nested.py`)
1. **Patient separation**: every fold is patient-grouped (unchanged, asserted); the locked test cohort and the sealed fresh cohort are never
   used for fitting, selection, calibration or thresholds (unchanged; `check_adversarial_leakage` passes).
2. **Stratified folds**: patients with ≥ 1 cSS candidate are dealt first (largest first) to the fold with the fewest positive candidates;
   patients without cSS to the fold with the fewest patients. Deterministic.
3. **One fold assignment for both levels**: component out-of-fold predictions and the meta-model comparison use the same folds.
4. **Discrimination within folds** (`fold_auc`): pair-weighted mean of the AUC inside each held-out fold. A fixed random score has expectation
   0.50 (test: 0.50 ± 0.03 over 120 cohorts). Remaining known bias: when a model LEARNS a direction from pure noise, small-sample
   cross-validation is pessimistic (≈ 0.45 on this cohort size) — conservative; it can never inflate.
5. **Model choice** (`select_kind`): paired patient bootstrap (300 resamples, the same for every candidate model); the simplest model is
   chosen only when its gap to the best is ≤ one PAIRED standard error; the model is **informative** only when the chosen model's lower 95 %
   bound is above 0.5. Log loss, Brier and a prevalence-only baseline are reported for transparency. Families (NOX logistic / trees,
   LUMOS pixel-logistic / CNN) are chosen the same way — by discrimination, so class weighting cannot bias the comparison.
6. **Calibration** (`calibrate`): Platt with one intercept per held-out fold and one common slope (ridge on the slope only), intercept
   refitted to the development base rate; slope ≥ 1e-3 (order never reversed); a clamped slope blocks acceptance; per-fold slopes with a
   different sign are a warning. Discrimination and calibration are reported separately.
7. **Nested cross-fitting**: unchanged structure (whole procedure inside each outer fold), now with stratified outer folds, the shared-fold
   discovery and within-fold calibration inside, and AUC reported within outer folds; acceptance compares PERCIVAL with ALBUS on that basis.
8. **Locked test evaluation**: candidate-level AUC/PR-AUC/Brier/calibration (as before) PLUS
   - ALBUS on exactly the candidates PERCIVAL scored (`math_same`) and the coverage (abstention is reported, not hidden);
   - patient level: highest candidate score per patient; a patient with only an expert-marked missed cSS is positive; AUC with patient
     bootstrap CI, flagged "not reliable" with < 10 patients per class; sensitivity / specificity at the red and green cuts;
   - lesion level: sensitivity at 0.5 / 1 / 2 / 4 false positives per study; lesions ALBUS never proposed count as missed.
9. **Acceptance** additionally requires: informative on the development folds; ≥ 5 test patients with a cSS CANDIDATE (not only marks);
   ALBUS comparison on the same candidates. Every test consultation uses the milestone (pass or fail).
10. **Readiness gate**: training is refused until data, completed blind expert review, eligible ground truth and verified identities exist.

## 3. Leakage checks
| Check | Result |
|---|---|
| patient in two folds (component, meta, nested, CNN early stopping) | asserted; `test_validation_m1.TestFolds`, `check_percival`, `check_adversarial_leakage` ALL PASS |
| expert labels as predictors | label-like variables refused (SHADOW); labels joined after the gather cache (unchanged) |
| marks of held-out / test patients in training | refused (`test_lumos_missed_marks`, `test_albus_redetect`) |
| sealed fresh cohort in training or SHADOW | refused (`test_split_mix`) |
| test performance influencing selection | selection and calibration use development folds only; every test consultation uses the milestone |
| synthetic data counted as real | training gate override works only for all-synthetic projects; SHADOW refuses synthetic approval |

## 4. Segmentation evaluation
No expert reference masks exist in the project, so **no segmentation accuracy is reported**. The metric code
(`uengine/imaging/seg_metrics.py`: Dice, IoU, sensitivity/precision = under/over-segmentation, ASSD, HD95, maximum Hausdorff, boundary F1 at a
mm tolerance, slice recall, one-to-one lesion matching, by lesion size) is verified on hand-computed masks only.
The extent outline (`refine.py`) is verified on synthetic volumes (full band recovered from a centre-line core, no growth beyond 5 mm or outside
the dark map, no overlap between neighbouring candidates, leak warning when growth is stopped only by the limit).

## 5. Explicit limitations
- 16 development and 4–5 test patients with cSS: any AUC has a wide interval; patient-level CIs are flagged unreliable below 10 per class.
- The current project's locked test group (15 patients after the balance) was consulted once (v001, milestone M1).
- Single expert reader, who is also the developer; no inter-reader agreement yet.
- Labels exist only for ALBUS detections + expert marks (verification bias).
- Possible scanner / field-strength confounding is reported (subgroup calibration) but not corrected.
- The detector's own thresholds may have been tuned on some project patients (to be verified internally).
- Within-fold calibration uses few positives per fold: calibrated values are approximate; ranking is the more reliable output.
