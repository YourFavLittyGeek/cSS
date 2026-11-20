# MODEL_CARD.md - synthetic_demo_offset v1.0.0

**SYNTHETIC-TRAINED DEMONSTRATION MODEL. Not trained on, validated on, or applicable to any patient. The engine refuses to apply it to a
non-synthetic study.**

| field | value |
|---|---|
| file | `unified_engine/models/synthetic_demo_offset_v1.0.0.json` |
| model hash | `55f5b640dfcd14449600396c0bf9ec21c40fb5a2995c8ccb12e52cbdb7c547cc` (sha256 of all parameters; verified on every load) |
| created | 2026-11-20 14:58 by `run_engine.py train-synthetic` (`uengine/train_demo.py`) |
| engine / fusion | uengine/1.0 · uengine-fusion/1.0 · mode `offset`: p = sigmoid(MATH logit + learned increment) |
| data_kind | synthetic (in the card AND in the hash-protected training record) |
| training data | `uengine.synthetic.make_cohort` seed 500, 60 synthetic patients, 699 candidates (353 cSS), population = measurement-complete labelled objects (shown + audited excluded) |
| inputs | darkness_z, edge_contrast, pial_dist_mm, cortex_frac, tram_frac, tube_ratio, elongation_3d, log_volume_mm3, local_cont_max_mm, tram_frac_missing (prespecified; FEATURE_SCHEMA.md) |
| MATH recalibration | a = -4.438, b = 6.276 (logit = a + b log(score_v4 + 0.05)) |
| learned part | L2 penalty 1.0 (nested patient-grouped inner CV, mean per-fold log loss); intercept and 10 weights in the file |
| uncertainty | 30 patient-bootstrap refits (5-95 % interval) |
| intended use | software testing and GUI demonstration on SYN studies only |
| out of scope | any real study, any clinical decision, any performance claim |

## Synthetic cross-validation of the same procedure (5-fold patient-grouped, training cohort, seed 500)

| model | within-patient AUC (95 % CI) | fold-wise AUC | log loss | Brier | cal. slope | sens / spec |
|---|---|---|---|---|---|---|
| MATH only | 0.945 (0.912-0.965) | 0.957 | 0.284 | 0.092 | 0.96 | 0.90 / 0.82 |
| **offset (this model)** | **0.980 (0.967-0.991)** | 0.986 | 0.165 | 0.051 | 1.09 | 0.90 / 0.96 |
| naive sum | 0.969 (0.948-0.984) | 0.978 | 0.216 | 0.067 | 0.71 | 0.90 / 0.92 |
| learned only | 0.948 (0.927-0.967) | 0.953 | 0.289 | 0.090 | 1.02 | 0.89 / 0.86 |

Delta vs MATH (offset): +0.035, paired bootstrap CI 0.017-0.059. These numbers describe the synthetic generator, not cSS.

## Caveats
- every number is decided by invented class distributions; no clinical meaning;
- incremental value over MATH must be judged by the within-patient permutation test, not the bootstrap CI;
- categories are reading aids; nothing is excluded or suppressed.
