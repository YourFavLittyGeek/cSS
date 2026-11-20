# TEST_REPORT.md - Unified Score engine and its GUI integration

All tests use SYNTHETIC data and temporary bases. Results below are copied from executed runs on 2026-11-20 (macOS 26.7.1, conda env
`css`: Python 3.11.17, numpy 2.4.6, scipy 1.17.1, pandas 3.1.0; Google Chrome for the headless-browser checks).

## 1. Commands
```zsh
cd /Users/tarabeah.selim/Projects/cSS-unified-score-ml/cSS_pipeline_v4.13 && conda activate css
bash unified_engine/run_tests.sh /tmp/uengine_tests.log      # all engine stages (~5 min)
python tests/check_app_shadow_engine.py --shots /tmp/shots     # app + browser integration only (~25 s)
bash tests/run_uscore_tests.sh                                 # EXISTING suite of the experimental app (regression, ~15-20 min)
```

## 2. Engine runner `unified_engine/run_tests.sh` - result: **0 failing stages**
| stage | result |
|---|---|
| 1 pinned production sources (`run_engine.py verify`) | ok, 0 problems (detect_css.py, css_tiers.py, css_common.py, css_features.py, css_confidence.py, css_model.py, train_ranker.py, uscore/model.py, uscore/common.py byte-identical to the pinned sha256) |
| 2 static check (compile, unused imports, unbound names, imports with warnings as errors) | 51 files, 0 findings |
| 3 engine tests (unittest, ResourceWarning = error) | **Ran 119 tests, OK** (0 failures, 0 errors, 0 skipped) |
| 4 app + browser integration (`tests/check_app_shadow_engine.py`) | **35 / 35 PASS** (with `--shots`: 36, incl. "screenshots written") |

### Test files (19) and what they establish
| file | n | coverage requested by the mission |
|---|---|---|
| test_engine_provenance | 4 | MATH regression: engine executes the repo's own production code (pinned sha256, pinned verbatim blocks, rule constants, 157-column contract) |
| test_math_preservation | 8 | MATH regression: verbatim == independent replica on 5000 rows incl. NaN branches; 24 rules fire; first-match order; switches; E30 never from MATH; recorded values authoritative |
| test_schema | 8 | feature schema: every column classified; rule-decision columns parsed from source; legacy inputs classified |
| test_characteristics | 5 | feature validation: refusal of scores / flags / ids; 6 statuses; not_measured; indicator; transforms |
| test_prototype_components | 7 | components: recorded vs verbatim MATH, inconsistent / not scorable, extrapolation clipping, corrupt inputs, offset increment, input validation |
| test_prototype_fusion | 8 | fusion: all 5 modes, trace arithmetic (to 1e-9), category rules, reproducibility + persistence + tamper refusal, component swap, leakage / separation, patient level separate |
| test_prototype_scenarios | 8 | synthetic positive / negative / borderline / difficult mimic; missing data; corrupted inputs; extreme values; unscorable; unexpected inputs |
| test_registry_shadow | 11 | model loading / versioning / health (ok, missing, corrupt, edited, relabelled card, schema, engine major version), never overwrite, apply policy, user model dir; shadow: applied + separated + nothing else written, deterministic equality, real study withheld, corrupt model and crash fallback, corrupted rows, patient keys, registration, reproducible, demo base refuses a real folder and carries no labels |
| test_port_fidelity | 1 | repository engine == tested workspace prototype (identical cohort, predictions to 1e-12) |
| test_patient_split, test_leakage, test_funnel | 5 + 7 + 5 | patient grouping, repeat exams, protected set; feature / label / model-output leakage, repeat-exam leakage demonstration; funnel and audit sampling design |
| test_ml, test_evaluation, test_fusion | 8 + 7 + 5 | IRLS correctness, offset, preprocessing isolation, legacy adapters; metrics + decomposition identity; gate lock, double counting |
| test_auc_investigation, test_synthetic, test_end_to_end, test_ablation | 6 + 4 + 7 + 5 | low pooled AUC reproduced with the ORIGINAL uscore code; pure noise uninformative in every column; full synthetic path; negative control, permutation null |

### App + browser integration checks (`tests/check_app_shadow_engine.py`, all PASS)
synthetic base written · app starts (write guard on, real folders protected) · Shadow ML screen in the GUI · shadow_mode / experimental /
synthetic flags · shadow switch OFF by default · healthy synthetic model active · existing unified switch untouched · POST without app header
refused (403) · unknown study refused · run starts / completes · ML applied on SYN study · engine-verified inputs unchanged · four blocks per
candidate · model hash / version / formula on every prediction · deterministic score_v4 == detector list · intervals present · **review/
byte-identical after runs** · **study records unchanged** · clean shutdown · restart · results survive restart · **non-synthetic study: ML
withheld, deterministic fallback** · enable switch · broken model listed as unusable · **configured corrupt model -> withheld with reason** ·
**engine crash -> job failed, deterministic rows served, rows = detector rows, app keeps serving** · review/ byte-identical and study records
unchanged after all runs incl. the crash · no write into the real project folders · browser: shadow banner, synthetic banner + model
version, the three outputs shown separately.

## 3. Regression: the EXISTING test suite of the experimental app (`tests/run_uscore_tests.sh`) on this branch
Final run 2026-11-20 17:20-17:32 EST (after the two test-harness fixes below). `run_uscore_tests.sh` stops at the first failing script
(`set -e`); it ran 14 scripts with **357 PASS, 0 FAIL** and stopped at `check_ui_poll` (npm missing); the two scripts after it were run
separately with the same interpreter.

| existing test | result on this branch | classification |
|---|---|---|
| check_core_decompose, check_uscore_features, check_uscore_adversarial, check_uscore_seeds (5), check_uscore_pipeline, check_heldout_protection, check_processing_manager, check_link_study, check_production_models, check_pm_full_pipeline, check_audit_local, check_local_only | **pass** | - |
| check_write_guard | **pass, 28 / 28** (was: aborted by a timeout) | **test-harness problem.** The test runs the real launcher head; on refusal it calls `/usr/bin/osascript display dialog`, a modal dialog that waits for a click in a logged-in macOS session -> 60 s timeout. Fix (test only): that one notification call is replaced by `echo DIALOG >&2`; the launcher's refusal logic and exit codes are unchanged, and the check is now STRICTER (it also requires the refusal notice). |
| check_export_safety | **pass, all** (was: 2 FAIL, also on the unmodified base 6f0ca44) | **test-harness problem, not a safety defect.** Diagnostic run: the app returned `/private/var/folders/.../lab_exports/cSS_share_....zip` while the test's HOME was `/var/folders/...` (macOS `/var` is a symlink to `/private/var`). The app correctly reports the canonical real path (the guard resolves symlinks by design); the test compared against the non-canonical spelling. Fix (test only): HOME and base are canonicalised with `os.path.realpath`; the assertion `path.startswith(HOME + "/lab_exports/")` is unchanged. |
| check_ui_poll | **not run** | **environment.** Needs Node / npm + Playwright (FileNotFoundError: npm). Not installed on this Mac. |
| check_selection_notifications | **pass, 24 / 24** | - |
| check_app_unified | **pass, 31 / 31** | the existing Unified tab, through the API of the modified app |

No genuine application defect was found in the existing suite. Total: 412 PASS, 0 FAIL, 1 script not runnable (environment).

Side effect of the existing suite: it rewrites 3 tracked files in `unified_score/output/` (COHORT_REPORT_SYNTHETIC_TEST.md, adversarial_seeds.json,
example_candidate_reports_SYNTHETIC.json); they were restored with `git checkout --` and are not part of any commit.

## 4. Failures found and fixed during this integration (none skipped, no assertion weakened)
| # | failure | cause | fix |
|---|---|---|---|
| 1 | app refused to start in the first smoke test | the write guard protects `$HOME/css_project`; with HOME redirected my demo base sat exactly there | demo base named `syn_base` (the guard worked as designed) |
| 2 | `test_corrupted_rows_and_missing_lists` TypeError | pandas 3 refuses a string in a float column (test code) | column cast to object before injecting the corrupt value |
| 3 | `test_ml_failure_falls_back` | my crash simulation patched `load`, which the health check also calls, so the ML path was never entered | patch `predict` (crash inside ML scoring) |
| 4 | ResourceWarnings | unclosed files in `demo_base.py` and a test | context managers |
| 5 | integration: "existing files byte-identical" FAIL on `app_data/patients.json` | **not the engine**: the unchanged app re-serialises patients.json (indentation) at start-up; control runs without any shadow action show the same byte change and no field change | review/ compared by bytes, patients.json by every field of every study record (both pass); documented |
| 6 | static check: 3 unused imports; runner ran each stage twice | my code | removed; runner rewritten (each stage once) |
| 7 | label "Main evidence" misleading (showed the learned correction, not total evidence) | UI wording | "Largest learned corrections to MATH (log-odds)" + tooltip |
| 8 | existing suite: `check_write_guard` hang, `check_export_safety` 2 FAIL | test-harness problems (section 3) | fixed in the two tests only; app, guard and launcher unchanged; no assertion weakened (write-guard check made stricter) |
| 9 | existing suite: `check_ui_poll` not runnable | environment (no Node / npm) | not changed |
