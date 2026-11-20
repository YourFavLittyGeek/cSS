# MODEL_EVALUATION_PLAN.md - Stage 2 evaluation protocol (design; prespecified before any data is seen)

## 1. Units and splits
- Unit of independence: `patient_key`. Every split, fold, bootstrap, calibration fit, early-stopping set and
  augmentation statistic is grouped by patient. Repeat exams always on one side.
- Held-out test set: frozen BEFORE any image model is fitted; never used for selection; opened once per model version.
- Development: K = 5 patient-grouped outer folds (or leave-one-patient-out when < 30 patients), nested inner
  patient-grouped CV for hyperparameters and penalty.
- Stratify folds by patient cSS status and acquisition group (sequence x field) when counts allow.

## 2. Population and endpoints
- Rows: shown + excluded objects with consensus `definite_css` (1) or `definite_mimic` (0); indeterminate,
  insufficient_quality and out_of_scope excluded and reported by count.
- Primary endpoint: **within-patient** AUC (Stage 1 finding: pooled / LOPO AUC is distorted by prevalence; pooled =
  weighted within + between). Report pooled and between-patient AUC alongside.
- Secondary: average precision; sensitivity at 1 and 3 false positives per scan; log loss; Brier; calibration
  intercept and slope (patient-grouped); per-subtype false-positive rates (surface vein, sulcal vein, artifact,
  iron cortex, microbleed); patient-level 0-4 agreement when used as a ranking aid (Stage 3, not Stage 2).

## 3. Comparisons (same folds, same rows)
1. MATH only (recalibrated score_v4) - reference.
2. MATH + C (Stage 1 offset).
3. MATH + I (image increment only).
4. MATH + C + I (proposed).
5. I alone and C alone (diagnostic, not candidates for deployment).
6. Naive sum (double-counting control).

## 4. Incremental value and redundancy
- Decision test: **within-patient permutation test** (Stage 1: the paired bootstrap CI gave a false gain on 1 / 13
  pure-noise data sets; the permutation test 0 / 12). Permute the image stream jointly among a patient's candidates,
  refit the whole CV, 200 permutations; I is retained only if p < 0.05 AND the within-patient AUC gain >= 0.02
  (prespecified, for approval).
- Redundancy: correlation of I's increment with the MATH logit and C's increment (out-of-fold); calibration slope
  of 4 vs 2 (slope < 0.8 = double counting); ablation removing `overlap_with_math` features.
- Negative controls (synthetic): pure-noise images (I must add nothing), image carrying only MATH information
  (I must add nothing beyond M), label-shuffled images.

## 5. Fusion fitting (cross-fitting, no leakage)
Stage-wise: (i) MATH recalibration a, b on outer-training patients; (ii) C increment with MATH offset; (iii) I
increment trained on outer-training patients, its OUT-OF-FOLD predictions (inner patient-grouped cross-fitting)
fed to (iv) the fusion weights g_C, g_I with the MATH offset. No stage ever sees an out-of-fold patient's labels.
Calibration: the fusion is itself a logistic model; recalibration only on development out-of-fold predictions.
Uncertainty: patient bootstrap of the full pipeline (option A: 30-100 refits) or 5-seed ensemble x bootstrap
(option B); intervals evaluated by coverage on synthetic truth.

## 6. Robustness and subgroups
- Leave-one-acquisition-group-out (sequence / vendor / field) when >= 2 groups have >= 5 patients.
- Slice thickness strata (<= 1.2 mm vs > 1.2 mm); anatomy source (recon-all vs SynthSeg); qc_status.
- Missing-channel analysis: performance with FLAIR / phase removed at test time.
- Label noise: results against consensus vs single reader; inter-reader kappa reported as the ceiling.

## 7. Gates (extends Stage 1 gates A-D)
| gate | condition | consequence |
|---|---|---|
| S2-A synthetic | all synthetic tests pass, negative controls show no gain, geometry invariance holds | may request clinical-data approval |
| S2-B data | blockers 1-7 resolved (ARCHITECTURE_DESIGN section 6), held-out frozen | may train on development data |
| S2-C development | permutation test + minimum gain on development, calibration slope 0.8-1.2 | may run once on held-out |
| S2-D held-out | within-patient AUC gain CI excludes 0, no subgroup worse than MATH by > 0.05 | may be shown in shadow mode on real studies |
Even after S2-D the output stays shadow / research; no clinical decision uses it.

## 8. Sample-size realism
With ~30 patients and ~100-400 positive candidates, the 95 % CI half-width of a within-patient AUC near 0.9 is roughly
0.03-0.05 and an AUC gain of 0.02 may not be detectable; the plan reports power by simulation (synthetic generator
calibrated only to counts, not to clinical values) before training, and states "not detectable" rather than
claiming equivalence.
