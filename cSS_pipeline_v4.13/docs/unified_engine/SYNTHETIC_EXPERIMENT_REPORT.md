<!-- Copied from the isolated workspace ~/cSS_ml_work/SYNTHETIC_EXPERIMENT_REPORT.md (2026-11-20). The experiment ran on the workspace
prototype (src/cssml), which the repository engine reproduces exactly (unified_engine/tests/test_port_fidelity.py: identical synthetic
cohort and predictions to 1e-12). Paths such as src/cssml/... refer to the workspace; the engine equivalents are unified_engine/uengine/...
Section 9 (added here) covers the model shipped with the engine. -->

# SYNTHETIC_EXPERIMENT_REPORT.md

**All data in this report are SYNTHETIC (invented in this workspace). No number is a clinical result, an estimate of performance on
patients, or evidence about cSS.** Sections are marked **[measured]** (numbers produced by a run, copied from the files named) or
**[interpretation]** / **[hypothesis]**.

Source files: `reports/SYNTHETIC_RESULTS.md` + `experiment_*_SYNTHETIC.json` (definitive run, session 1), `reports/ABLATION_RESULTS.md` +
`ablation_SYNTHETIC.json` (ablation), `reports/FOLLOWUP_RESULTS.md` + `followup_SYNTHETIC.json` (permutation tests, uncertainty).

## 1. Experiment design

### 1.1 Synthetic data generation (`src/cssml/synthetic.py`) - assumptions, all invented
- Patients: prevalence of cSS among their candidates p_i ~ Beta(1.2, 2.0); 25 % of patients cSS-negative (p_i = 0).
- Repeat examinations: 1 + Poisson(0.3) per patient; exams share p_i. Registration per exam: ok / marginal (0.6 mm noise on pial distance,
  10 %) / failed (5 %; no candidate list, as detector exit 5).
- Candidates: 6-24 per exam; classes cSS / vein / artifact / normal / microbleed (non-cSS mix 0.4 / 0.2 / 0.3 / 0.1). 17 Gaussian
  latent properties with class-specific means (table `G`), scaled toward the common mean by `signal` (1 = full separation, 0 = none);
  class-specific constructions (struct class, zone shares, flags) use the true class with probability `signal`, else a class drawn
  independently of the truth (fix of a first-session leak; verified by an all-column independence test).
- MATH: score_v4, evidence, review tiers and the E1-E29 fate computed by the VERBATIM detector code on every synthetic row.
- Funnel: rule-excluded objects (fate from the real rules), 0-3 gate-dropped tiny objects per exam (no measurements), a never-generated cSS
  lesion in 30 % of positive exams. Labels: every shown object read (reader flip rate 0 in these runs); excluded objects labelled only by
  the review_web `--audit` design (20 %, E1 ineligible).
- Stress knobs (ablation): weak signal 0.4; pure noise 0.0; difficult mimics (vein means pulled 70 % toward cSS); MCAR missingness 25 %
  of 8 measures (applied after MATH, which stays intact); informative missingness (tram_frac missing in 60 % of cSS); scanner darkness
  offset SD 1.5 (default 0.3); volume scaling log-SD 0.7; truth = MATH only (labels resampled from sigmoid(-1 + 2.2 log(score_v4 + 0.05))).
- Defaults reproduce the definitive run bit-identically (assignment digest and metrics re-checked after the knobs were added).

### 1.2 Seeds and reproducibility [measured]
Definitive run seed 7 (40 patients); ablation baseline seeds 11-15, stress scenarios 21-23; permutation tests: noise 41-50, baseline
11-13, weak 21-23, truth-math 21-23; uncertainty 11-13. Fold assignments are seeded (`seed + repeat`) and stored as digests in the JSON
files; `tests/test_end_to_end`, `test_ablation`, `test_prototype_fusion` re-run and compare.

### 1.3 Dataset sizes and class distribution [measured]
Per cohort (40 patients): 412-622 model rows; cSS share 0.39-0.58 by scenario (baseline mean 0.489; noise 0.295; truth-math 0.582).
Baseline seeds 11-15: rows 577 / 467 / 480 / 584 / 412; cSS 297 / 245 / 212 / 308 / 180; patients 39 / 40 / 40 / 38 / 39.
Population = measurement-complete labelled objects (all shown + audited excluded); gate-dropped / never-generated objects are counted in the
funnel, never modelled (definitive seed 7: shown 397, rule-excluded 463, gate-dropped 79, not generated 14 -> 486 model rows, 219 cSS).

### 1.4 Training and validation [measured design]
Patient-grouped 5-fold CV, stratified by patient positivity, 2 repeats (ablation) / 3 repeats (definitive) / 1 repeat (permutation);
identical folds for every model. Inside each training part: math recalibration, characteristic training ranges, median imputation /
standardisation, penalty chosen by patient-grouped inner CV (mean per-fold log loss). Threshold for sensitivity / specificity = the
training-part point with sensitivity 0.9. Primary metric = within-patient AUC; CIs by patient-cluster bootstrap (300 draws, repeat 0).

## 2. Models compared (all through the prototype, `prototype.fusion.UnifiedScorer`)
| name | definition |
|---|---|
| math_only | MATH alone: sigmoid(a + b log(score_v4 + 0.05)) - monotone, same order as score_v4 |
| learned_only | PAST EXPERIENCE on the 10 CHARACTERISTICS inputs, no MATH |
| offset (proposed) | MATH logit + learned increment fitted with the math logit as offset |
| offset_nonoverlap | offset model on the 5 inputs score_v4 does not use (edge_contrast, cortex_frac, elongation_3d, log_volume, local_cont_max) |
| naive | MATH logit + independently fitted learned-only logit ("add the scores") |
| joint | characteristics + math logit as a penalised free column |
| legacy_confidence | v5.10 confidence procedure, verbatim, refitted per fold (baseline only) |
| lofo:x | offset model without input x (baseline only) |

## 3. Results - baseline (signal 1; 5 seeds; mean (min to max)) [measured, reports/ABLATION_RESULTS.md]

| model | within-patient AUC | delta vs MATH | pooled AUC | log loss | Brier | cal. slope | CITL | ECE | sens / spec |
|---|---|---|---|---|---|---|---|---|---|
| math_only | 0.949 (0.940-0.957) | 0 | 0.938 | 0.317 | 0.098 | 0.96 | 0.01 | 0.030 | 0.90 / 0.81 |
| learned_only | 0.950 (0.935-0.974) | +0.000 (-0.010 to +0.019) | 0.937 | 0.315 | 0.098 | 1.03 | -0.01 | 0.035 | 0.89 / 0.82 |
| **offset** | **0.978 (0.971-0.985)** | **+0.029 (+0.017 to +0.035)** | 0.972 | **0.213** | **0.062** | 1.04 | 0.00 | 0.023 | 0.89 / **0.94** |
| offset_nonoverlap | 0.969 (0.959-0.979) | +0.020 (+0.007 to +0.029) | 0.963 | 0.244 | 0.073 | 1.03 | -0.00 | 0.030 | 0.89 / 0.91 |
| naive | 0.969 (0.956-0.983) | +0.020 (+0.013 to +0.029) | 0.962 | 0.270 | 0.077 | **0.66** | 0.17 | 0.045 | 0.90 / 0.91 |
| joint | 0.977 (0.970-0.985) | +0.029 (+0.018 to +0.032) | 0.971 | 0.217 | 0.063 | 1.01 | 0.00 | 0.025 | 0.89 / 0.94 |
| legacy_confidence | 0.998 (0.995-1.000) | +0.049 | 0.998 | 0.071 | 0.016 | 1.95 | -0.08 | 0.034 | 0.89 / 1.00 |

Per-seed paired delta (offset vs MATH) with patient-bootstrap CI: +0.033 [0.013, 0.047], +0.031 [0.010, 0.046], +0.017 [0.003, 0.032],
+0.035 [0.019, 0.056], +0.028 [0.004, 0.055]. Fold-wise AUC (offset) 0.974 (0.969-0.981).

**Ablation, leave one feature out** (change of the offset model's within-patient AUC; mean (min to max) over 5 seeds): edge_contrast
-0.011 (-0.015 to -0.008); log_volume_mm3 -0.003 (-0.005 to -0.002); tram_frac -0.003 (-0.005 to 0.000); elongation_3d -0.002;
darkness_z, pial_dist_mm, tube_ratio, local_cont_max_mm -0.001; cortex_frac 0.000; tram_frac_missing 0.000 (-0.005 to +0.005).

## 4. Results - stress scenarios (3 seeds each; within-patient AUC, delta vs MATH, calibration slope) [measured]

| scenario | math_only | learned_only | offset | offset_nonoverlap | naive (slope) | joint |
|---|---|---|---|---|---|---|
| weak signal | 0.732 | 0.718 (-0.014) | 0.751 (+0.019; slope 0.88) | 0.746 (+0.013) | 0.749 (slope 0.58) | 0.751 (+0.019) |
| pure noise | 0.485 | 0.518 (+0.049) | 0.510 (+0.032) | 0.489 (+0.014) | 0.507 (slope -1.54) | 0.514 (+0.049) |
| difficult mimics | 0.845 | 0.828 (-0.017) | 0.873 (+0.029) | 0.851 (+0.006) | 0.861 (slope 0.60) | 0.873 (+0.030) |
| MCAR missing 25 % | 0.932 | 0.888 (-0.047) | 0.961 (+0.030) | 0.955 (+0.022) | 0.953 (slope 0.74) | 0.961 (+0.029) |
| informative missing (tram) | 0.937 | 0.930 (-0.007) | 0.986 (+0.049; slope 1.17) | 0.971 (+0.035) | 0.977 (slope 0.79) | 0.986 (+0.050) |
| scanner darkness SD 1.5 | 0.890 (slope **0.36**, ECE 0.185) | 0.946 (+0.057) | 0.958 (+0.065; slope 0.76, CITL 0.12) | 0.889 (-0.000) | 0.957 (slope 0.63) | 0.955 (+0.063) |
| volume scaling SD 0.7 | 0.953 | 0.944 (-0.009) | 0.980 (+0.026) | 0.976 (+0.022) | 0.972 (slope 0.63) | 0.980 (+0.027) |
| **truth = MATH only** | 0.790 | 0.713 (**-0.077**) | 0.792 (**+0.002**, slope 0.97) | 0.789 (-0.002) | 0.777 (-0.015; slope **0.57**) | 0.780 (-0.013) |

Truth = MATH, per seed (offset delta, CI): +0.004 [-0.003, 0.010], +0.002 [-0.003, 0.007], +0.000 [-0.001, 0.002] - no CI excludes 0.
Pure noise, per seed (offset delta, CI): +0.017 [0.000, 0.031] (lower bound exactly 0), +0.018 [-0.081, 0.113], +0.060 [0.007, 0.127] -
**1 of 3 CIs excludes 0** (seed 23), a false positive on noise (see sections 6-7).

## 5. Leakage and patient-separation checks [measured]
- Every fold: no patient on both sides (asserted in `patient_split.fold_indices`); repeat examinations kept together (tested, 3 repeats).
- Forbidden learned inputs (ids, labels, scores, model outputs, rule flags) refused at construction; protected patients refused at fit.
- Predictions unchanged when the input carries flipped labels, a patient-level positivity column or a fake confidence column; one-row and
  batch predictions identical (no row sees another).
- Label copy and model-output copy detected; test-label invariance and preprocessing isolation for the new and the legacy model.
- Exam-level vs patient-level CV with a memorising scorer on noise: AUC > 0.9 vs ~0.5 (shows why patient grouping is mandatory).
- No fold failure in any run (all JSON `failures` empty).

## 6. Assessment of the incremental-value decision rule [measured + interpretation]
The paired patient-bootstrap CI of the within-patient AUC difference resamples FIXED cross-validated predictions; it ignores the
variability of fitting. **[measured]** On pure noise it excluded 0 in 1 of 3 ablation seeds (seed 23; seed 21 touched 0), and the permutation null of
the offset model's delta is not centred at 0 (null means between -0.027 and +0.020 on noise). A within-patient permutation test (characteristic
columns permuted jointly among a patient's candidates, MATH and labels fixed, whole CV refitted) was therefore added; results in section 7.
**[interpretation]** The bootstrap CI alone is not a valid Gate D criterion; the permutation test (or a fresh independent test set) is.

## 7. Follow-up: incremental-value decision rules and uncertainty categories [measured, reports/FOLLOWUP_RESULTS.md,
reports/noise_bootstrap_fp_permutation_SYNTHETIC.json]

### 7.1 Paired bootstrap CI vs within-patient permutation test (39 permutations, one CV repeat, 40 patients)

| scenario | seed | observed delta (within AUC) | paired bootstrap 95 % CI | CI excludes 0 | permutation p (39 perms) | null mean | null 95th pct |
|---|---|---|---|---|---|---|---|
| pure_noise | 41 | -0.0163 | [-0.0408, 0.0062] | False | 0.650 | -0.0035 | +0.0354 |
| pure_noise | 42 | -0.0172 | [-0.0463, 0.0198] | False | 0.925 | -0.0031 | +0.0241 |
| pure_noise | 43 | -0.0212 | [-0.0457, 0.0029] | False | 0.600 | -0.0018 | +0.0964 |
| pure_noise | 44 | +0.0009 | [-0.0716, 0.0544] | False | 0.150 | -0.0273 | +0.0454 |
| pure_noise | 45 | -0.0022 | [-0.0491, 0.0545] | False | 0.650 | +0.0139 | +0.0958 |
| pure_noise | 46 | -0.0316 | [-0.0608, -0.0109] | False | 0.825 | -0.0153 | +0.0134 |
| pure_noise | 47 | -0.0292 | [-0.0838, 0.0164] | False | 0.900 | -0.0033 | +0.0447 |
| pure_noise | 48 | +0.0226 | [-0.0496, 0.0885] | False | 0.325 | +0.0015 | +0.0456 |
| pure_noise | 49 | +0.0417 | [-0.0134, 0.092] | False | 0.050 | +0.0019 | +0.0313 |
| pure_noise | 50 | +0.0060 | [-0.0495, 0.062] | False | 0.300 | -0.0026 | +0.0929 |
| baseline | 11 | +0.0328 | [0.0134, 0.047] | True | 0.025 | -0.0030 | -0.0002 |
| baseline | 12 | +0.0308 | [0.0103, 0.0457] | True | 0.025 | -0.0034 | +0.0020 |
| baseline | 13 | +0.0170 | [0.0027, 0.0325] | True | 0.025 | -0.0017 | +0.0034 |
| weak_signal | 21 | +0.0095 | [-0.0169, 0.03] | False | 0.025 | -0.0099 | -0.0021 |
| weak_signal | 22 | +0.0109 | [-0.0072, 0.0263] | False | 0.075 | -0.0017 | +0.0074 |
| weak_signal | 23 | +0.0378 | [0.0051, 0.0701] | True | 0.025 | -0.0036 | +0.0087 |
| truth_math_only | 21 | +0.0038 | [-0.0025, 0.0096] | False | 0.225 | +0.0012 | +0.0071 |
| truth_math_only | 22 | +0.0018 | [-0.0026, 0.0068] | False | 0.325 | +0.0002 | +0.0034 |
| truth_math_only | 23 | +0.0003 | [-0.0014, 0.0021] | False | 0.325 | -0.0013 | +0.0072 |

pure_noise: bootstrap CI excludes 0 in 0 / 10; permutation p < 0.05 in 0 / 10

baseline: bootstrap CI excludes 0 in 3 / 3; permutation p < 0.05 in 3 / 3

weak_signal: bootstrap CI excludes 0 in 1 / 3; permutation p < 0.05 in 2 / 3

truth_math_only: bootstrap CI excludes 0 in 0 / 3; permutation p < 0.05 in 0 / 3

### 7.2 Uncertainty categories (offset model, 30 bootstrap refits; recomputed after the missing-count fix)

| seed | category | n | observed cSS rate | mean p |
|---|---|---|---|---|
| 11 | likely_cSS | 221 | 0.95 | 0.96 |
| 11 | uncertain | 157 | 0.48 | 0.48 |
| 11 | unlikely_cSS | 199 | 0.06 | 0.05 |
| 11 | not_scorable | 0 | - | - |
| 12 | likely_cSS | 192 | 0.96 | 0.95 |
| 12 | uncertain | 123 | 0.43 | 0.44 |
| 12 | unlikely_cSS | 152 | 0.05 | 0.05 |
| 12 | not_scorable | 0 | - | - |
| 13 | likely_cSS | 161 | 0.94 | 0.93 |
| 13 | uncertain | 133 | 0.39 | 0.38 |
| 13 | unlikely_cSS | 186 | 0.04 | 0.06 |
| 13 | not_scorable | 0 | - | - |

runtime 1142 s

### 7.3 The two ablation noise seeds re-tested with the permutation test

| seed | observed delta | bootstrap CI | CI excludes 0 | permutation p | null mean |
|---|---|---|---|---|---|
| 21 | +0.0174 | [0.000, 0.031] | False | 0.175 | +0.0017 |
| 23 | +0.0602 | [0.007, 0.127] | **True** | 0.125 | **+0.0202** |

**Summary [measured]:** pure noise, 13 cohorts: paired bootstrap CI excluded 0 in **1 / 13**; permutation p < 0.05 in **0 / 12** (seed 49 at p = 0.050). Baseline: both rules 3 / 3. Weak signal: bootstrap 1 / 3, permutation 2 / 3. Truth = MATH: both 0 / 3.
**[interpretation]** With so few cohorts neither false-positive rate is estimated precisely; the permutation test has the right null by
construction (the observed null mean reached +0.020 on noise, so a zero-centred CI is the wrong reference) and was at least as powerful
here. Gate D should use it (or an independent test set), not the bootstrap CI.

Uncertainty categories **[measured]**: likely_cSS observed cSS rate 0.94-0.96, uncertain 0.39-0.48, unlikely_cSS 0.04-0.06; the
'uncertain' band holds the genuinely mixed cases and no candidate was forced into a positive / negative category.

## 8. Scientific and architectural assessment [interpretation, based on sections 3-7; synthetic only]

| question | answer on this synthetic evidence | basis |
|---|---|---|
| Do MATH and CHARACTERISTICS overlap? | **Yes, strongly.** The characteristics alone (learned_only 0.950) reproduce MATH (0.949): score_v4 is a fixed function of 5 of the 9 inputs. Removing any single score_v4 input from the offset model changes it by <= 0.003. | baseline table; LOFO |
| Does PAST EXPERIENCE add new information? | **Here yes, but only what the generator put outside score_v4's form**: +0.029 within AUC, log loss 0.317 -> 0.213, specificity 0.81 -> 0.94 at matched sensitivity. Most of the gain comes from edge_contrast (LOFO -0.011), which score_v4 does not use but the generator made class-dependent. With truth = MATH only, the gain is +0.002 (CIs include 0). Whether real SWI has information outside score_v4 is **unknown** and is exactly what Gate C must measure. | sections 3, 4, LOFO |
| Does the model double-count? | **The offset design does not** (truth = MATH: slope 0.97, no gain). **Naive addition does** in every scenario (calibration slope 0.57-0.79, CITL up to +0.4, worse log loss), and in truth = MATH it is worse than MATH (-0.015). Joint fitting is slightly worse than MATH when MATH is the truth (-0.013) because the penalty shrinks the math coefficient. | section 4 |
| Is fusion better than MATH alone? | Better in 7 of 9 scenarios on within AUC (+0.019 to +0.065); equal when MATH is the truth; on pure noise the apparent +0.032 is not evidence (section 6/7). | sections 3, 4, 7 |
| Does any component make things worse? | **learned_only** loses to MATH when data are missing (-0.047) or MATH is the truth (-0.077); **naive** loses calibration everywhere; **joint** loses when MATH is the truth. The offset model never fell below MATH beyond -0.000 on average. | section 4 |
| Do missing data, patient variation or scaling distort results? | MCAR missingness hurts learned_only, not offset (MATH intact by design of the scenario - in reality missing inputs could also break MATH). **Informative missingness inflates the gain** (+0.049; the indicator learns the missingness mechanism - not transferable, a hazard). **Scanner darkness shifts break MATH's calibration** (slope 0.36) and the offset model inherits part of it (slope 0.76, CITL 0.12) - MATH's absolute darkness term is the weak point. Volume scaling: no material effect. Patient prevalence variation: handled by within-patient metrics (pooled AUC artefact, first session). | section 4 |
| Interpretable and reproducible? | Yes: every prediction decomposes exactly into math logit + intercept + per-feature contributions (tested to 1e-9); identical hashes and metrics on re-runs. Interpretability limit: the increment's per-feature weights are correlated with score_v4's inputs and must be read as corrections, not as stand-alone effects. | tests |
| Does a higher synthetic AUC mean a better model? | **No.** legacy_confidence reaches 0.998 because the invented struct / location columns separate classes almost perfectly, and it is badly calibrated (slope 1.95). Informative missingness raises AUC through an artefact. The generator's choices decide every gain. | sections 3, 4 |

**Conclusion [interpretation]:** the results support the ARCHITECTURE (three separate components; MATH as an offset; learned increment;
quality gating; within-patient evaluation; permutation-based incremental-value test) as a *safe way to ask* whether past experience adds to
MATH. They say nothing about whether it does on real data. Two design consequences were adopted: (1) Gate D requires the permutation test
(or an independent test set), not the bootstrap CI; (2) informative-missingness indicators need a scientific justification before use, and
MATH's sensitivity to darkness calibration should be examined on real scans (score_v4 uses darkness z directly).

## 9. The model shipped with the engine [measured, unified_engine/models/synthetic_demo_offset_v1.0.0.json card]

Trained by `run_engine.py train-synthetic` (seed 500, 60 synthetic patients, 699 candidates, 353 cSS; generator seeds distinct from the
demo-base seed 900 and from every experiment above). 5-fold patient-grouped CV of the same procedure on its training cohort: MATH only
within-patient AUC 0.945 (0.912-0.965), offset 0.980 (0.967-0.991), delta +0.035 (bootstrap 0.017-0.059), calibration slope 1.09,
specificity 0.96 vs 0.82 at sensitivity 0.90. Synthetic; MODEL_CARD.md.
