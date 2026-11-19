# Unified cSS score: cohort report — SYNTHETIC TEST (not a result)

Model `uscore-model/1.0` hash `eca8f132ad94d871`; predictors x1_vessel_continuity_mm, x2_core_contrast_nu, x3_pial_distance_mm; ridge lambda 0.01; effective df 3.13. Probability output: **yes**. EXPERIMENTAL research output; not a diagnosis.

## 1. Development estimates (nested leave-one-patient-out, out-of-fold; SYN01, SYN02, SYN03, SYN04, SYN05, SYN06)

- **WARNING: the chosen penalty is at the edge of the search grid in some folds** (near-separable data: probabilities saturate)
- candidates 24 (10 cSS) from 6 patients; fallback: ['fallback: 10 events / 5 slopes < 10 -> dropped x4_sulcal_alignment', 'fallback: 10 events / 4 slopes < 10 -> dropped x5_extracranial_mm']
- discrimination: AUC 1.00 (patient-bootstrap 95 % CI [1.0, 1.0]); raw-score AUC 1.00
- calibration: slope 0.97, intercept -0.19; Brier 0.000 (CI [2.4669119607478186e-21, 3.893679134296391e-19])
- reliability bins (mean predicted vs observed): 0.00→0.00 (n 11); 0.00→0.00 (n 11); 0.00→0.00 (n 14); 1.00→1.00 (n 10); 1.00→1.00 (n 8)
- at the ordering cut 1.00 (prioritisation only): candidate sensitivity 1.00, specificity 1.00, FP per patient 0.00, patient sensitivity 1.00 (6 cSS-positive patients)
- v5.10 confidence_pct on the same candidates: AUC – — v5.10 was fitted on these same M02-M11 calls: its AUC here is IN-SAMPLE (optimistic), the unified score's is out-of-fold

### Coefficient stability across outer folds (standardised)

| predictor | mean | SD | sign agreement |
|---|---|---|---|
| x1_vessel_continuity_mm | -1.37 | 0.29 | 1.00 |
| x2_core_contrast_nu | 6.01 | 0.44 | 1.00 |
| x3_pial_distance_mm | -11.19 | 0.71 | 1.00 |

Penalty per fold: [0.01, 0.01, 0.01, 0.01, 0.01, 0.01]; effective df per fold: [3.07, 3.05, 3.11, 3.09, 3.11, 3.11]

### Feature missingness (development candidates)

| predictor | reliable | unreliable | unavailable |
|---|---|---|---|
| x1_vessel_continuity_mm | 1.00 | 0.00 | 0.00 |
| x2_core_contrast_nu | 0.50 | 0.50 | 0.00 |
| x3_pial_distance_mm | 1.00 | 0.00 | 0.00 |
| x4_sulcal_alignment | 0.83 | 0.17 | 0.00 |
| x5_extracranial_mm | 1.00 | 0.00 | 0.00 |

### False positives / false negatives at the ordering cut (out-of-fold; * = not reliable)


## 2. Candidate categories (all included studies scored by the frozen model)

- development: {'uncertain': 22, 'alternative_high_confidence': 2}
- held-out: {'uncertain': 10, 'alternative_high_confidence': 2}
- protective conditions: unstable under perturbation (22); dark-core decomposition unstable (16)
- perturbation-unstable candidates: 22 / 36
- categories by registration state: ok: {'uncertain': 32, 'alternative_high_confidence': 4}

## 3. Independent held-out results (frozen model)

- INDEPENDENT HELD-OUT (frozen model): n 12 (8 cSS, 3 patients); AUC 1.00 (CI [1.0, 1.0]); Brier 0.000; calibration slope 1.06
- at the frozen ordering cut: sensitivity 0.50, specificity 1.00, patient sensitivity 1.00