# Phase 2 — final safety audit before commit (2026-11-18)

## 1. The seven audit checks (Task 1 items), re-verified
| # | Check | Result |
|---|---|---|
| 1 | Inspect the complete real-validation results | all report tables, logs (98 runs, rc 0), environment, sha256 before/after read |
| 2 | Verify reported numbers against the original tables | recomputed; corrections in PHASE2_SCIENTIFIC_AUDIT.md (shown-only AUCs 0.67 / 0.53 / 0.46, unmatched calls 140 not 115) |
| 3 | Reconcile counts, labels, denominators | 954 = 154 shown + 800 excluded; dev negatives = 47 shown + 129 unblinded excluded-audit objects; held-out negatives shown only; gate drops never evaluated |
| 4 | Patient-level CV methodology | `css_model.lopo`: one patient out, imputation + scaling fitted in the training fold, fixed L2, no selection; pooled LOPO AUC (10 models) noted |
| 5 | Information leakage | none in the module evaluation; production's dev performance optimistic (rules tuned on the same patients/readers, meter-visible reads); inherited calls not independent |
| 6 | Held-out not used for selection | analysis code fits on `cohort == dev` only; no threshold derived from M12-M15 in the run; M12-M15 were examined once before (not pristine) |
| 7 | Object-level AUC vs patient-level vs threshold-based kept apart | yes; no patient-level AUC exists; hemisphere-level binary only; production patient-level specificity 0 by construction |

## 2. Inter-reader agreement confidence intervals (added)
Every Cohen kappa, Fleiss kappa, quadratic-weighted kappa (confidence 1-5, multifocality 0-2) and the lesion detection overlap now carries
a 95 % patient-cluster bootstrap CI (2,000 resamples, items of a patient resampled together, seed fixed). Tested: columns present.

## 3. Statistical validity of sampling and miss-rate estimates
| Issue found | Fix |
|---|---|
| `--max-per-study` cap made inclusion probabilities unequal within strata | removed (refused if given) |
| Later batches recorded a shrinking stratum N (remainder), so pooling batches with their own N was wrong | estimator pools batches per stratum with N_h from the inventory; batches must share the strata (checked) |
| Normal-approximation CI collapses to 0-0 when no cSS is found and under-covers at low rates (simulation: 60-65 % coverage at 1-3 %) | primary interval = N-weighted sum of exact Clopper-Pearson stratum limits (100 % coverage in simulation; conservative); normal interval kept, labelled unreliable |
| "3 / n" upper bound approximate | exact 1 - 0.05^(1/n) (30 -> 9.5 %) in the plan and the report |
| Indeterminate / unresolved objects | reported and bounded both ways, not silently counted as negatives |
| Unsampled strata | listed, never extrapolated |
Simulation (`tests/sim_estimator.py`, real stratum sizes, 4,000 draws per rate): bias <= 0.0005 at true rates 0-10 %.
Scope: design-based inference about the rejected objects of these 14 scans.

## 4. Deliverables present and reproducible
| Deliverable | File | Reproduced by |
|---|---|---|
| 1 | PHASE2_SCIENTIFIC_AUDIT.md | numbers from the run tables (recomputation code in this session; tables not committed: they hold reader calls) |
| 2 | EXPERT_ANNOTATION_PROTOCOL.md | - |
| 3 | REVIEWER_AUDIT_MODE_SPECIFICATION.md | `tests/check_reference_audit.sh` |
| 4 | EXCLUDED_OBJECT_SAMPLING.csv | `tools/make_sampling_plan.py <all_objects_full_table.csv>` (counts only, no ids) - rebuilt, identical |
| 5 | EXPERT_ANNOTATION_TEMPLATE.csv (+ _objects, _patient, _dictionary) | generated from `annotation_schema.py` |
| 6 | INTER_READER_AGREEMENT_PLAN.md | `agreement.py` |
| 7 | PRODUCTION_FALSE_NEGATIVE_ANALYSIS.md | `evaluate.py`, `tests/sim_estimator.py` |
| 8 | PHASE2_EXECUTION_GUIDE_MAC.md | - |

## 5. Production unchanged
- Branch `experimental/phase2-reference-audit` starts from `115721f` (v5.11.0-phase1, the production state); the commit adds only
  `reference_audit/` - `git diff 115721f --stat -- scripts tests` is empty.
- No file under `reference_audit/` imports anything from `scripts/`; it writes only to `$CSS_BASE/reference_audit/`.
- End-to-end test: sha256 of every file in review/, work/, data/ identical before and after the full Phase 2 chain (phantoms).
- Production test suite `tests/run_tests.sh` (v5.11.0-phase1 code): ALL TESTS PASSED (29 min, 2026-11-18).
- Reference-audit end-to-end test `reference_audit/tests/check_reference_audit.sh`: ALL REFERENCE-AUDIT CHECKS PASSED.

## 6. Data protection
Committed: code, documentation, templates, a counts-only sampling plan. Not committed: MRI images, masks, reader calls, the validation
tables (`all_objects_full_table.csv` contains reader calls), any CONCEALED key. Study codes (M02-M15) only; no names, MRNs or dates of birth. Reader initials and reader-specific kappas were removed from all documents
(agreement reported as aggregate median / interquartile range only); tool examples use generic reader codes (R1, R2, READER1).
