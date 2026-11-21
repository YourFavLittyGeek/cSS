# Percival v5.23 - implementation and test report (handover continuation, 2026-11-21)

Synthetic data only. Nothing was committed, pushed or merged; no clinical data or identifier was opened.
Recovery state: `RECOVERY_REPORT_2026-11-21.md`. Architecture: `PERCIVAL_ARCHITECTURE.md`. Local-only: `LOCAL_AI_ARCHITECTURE.md`.

## 1. Already completed before this session (verified, kept)
Import / identification / study administration, processing pipeline and QC, candidate detection with lineage, MATH (score_v4),
Unified Score engine, Image ML prototype, setup wizard, Training screen, reviewer with calls ledger, and the v5.22 Percival Score engine
(components, meta-model discovery, calibration, thresholds, locked test, acceptance, registry, ledger, Intelligence screen).
The ten "known GUI issues" of the brief were fixed in Phases B-G and are covered by the app suite (RECOVERY_REPORT §3).

## 2. Implemented in v5.23
| Area | What | Files |
|---|---|---|
| Characteristic ML | logistic / gradient-boosted trees / random forest (numpy) compared by patient-grouped CV, 1-SE choice, importances, per-feature AUC | `uengine/percival/learners.py`, `meta.py` |
| Image ML | pixel-logistic baseline vs CNN on the same candidates (CNN must earn its place); test-time-augmentation stability per candidate | `learners.py`, `cnn.py`, `meta.py` |
| Fusion | late / feature-level / hybrid compared; paired bootstrap test of fusion vs the better single model | `meta.py` |
| Percival Intelligence | input provenance + overlap, component ablation with CIs, disagreement patterns from expert labels (per candidate at scoring), out-of-distribution distance, study QC status as reliability input, calibration tables | `uengine/percival/intelligence.py`, `meta.py` |
| Percival Score | ridge-penalised Platt calibration; bootstrap-stable red / yellow / green; status `review`; reasons per candidate; in-sample flag | `meta.py`, `percival_gui.py` |
| Expert review / learning | immutable review snapshots (labels + outputs shown at review time + visibility of the score + coordinates, measurements, patch hashes, versions); watcher hook; `/api/percival/reviews` | `percival_gui.py`, `css_app.py` |
| GUI | reviewer "Why this score" panel; one primary score (old Unified card removed when Percival exists); Intelligence "Evidence & reliability" tab; explorer reasons; `#intel?tab=` deep links | `scripts/review_web.html`, `app/percival_view.js` |
| Local-only | static scan extended to `unified_engine/`; Percival engine + app tests under the runtime network guard | `tests/check_local_only.py` |
| Test runner | every check runs; unavailable checks reported SKIPPED (never passed); Percival tests added | `tests/run_uscore_tests.sh` |
| Docs | architecture / data flow / training & evaluation / MATH + Unified audit / limitations; local-AI architecture; user-guide section | `docs/percival_app/*.md` |

## 3. Repaired (defects found and fixed)
1. **Reviewer could not open any study** (v5.20, uncommitted): `review_web.py` redefined `LABELS` (study label map), shadowing the
   fine-label table -> `/api/meta` HTTP 500 `KeyError: 'C'`. Renamed `STUDY_LABELS`.
2. **Reviewer page stopped loading** (v5.20, uncommitted): global helper `LB()` clashed with `loadStudy`'s local `LB` label buffer
   (temporal dead zone: "Cannot access 'LB' before initialization"). Renamed `studyLabel()`.
3. **Rollback broken after re-promotion**: promoting the already-active version recorded itself as `previous`. Fixed in `promote`.
4. **Calibration saturated** (scores 0 / 100, test calibration slope ~8): unpenalised Platt on separable data. Ridge 1.0 on the slope.
5. **Thresholds collapsed** (red == green, no yellow band). Bootstrap-stable cut-points; an empty yellow band is reported explicitly.
6. **State race**: `/api/percival/state` read versions before the job status, so a finishing cycle could look finished with stale
   versions. Job read first; model JSON cached by mtime.
7. **Cache race**: snapshots and training could write the same study's feature cache concurrently. `gather` serialised; atomic `.npz`.
8. **Viewer note overwritten** by the legacy gauge ("rule-based evidence"). Call order fixed; in-sample warning shown under the score.
9. **Suite hid failures**: `set -e` stopped at `check_ui_poll` (no Node), so later checks never ran. Runner rewritten.
10. Test fixes: wrong second-cycle expectation; random-UUID locked-test partition made more robust (test fraction 0.35 in the app test);
    the app test now stops its own reviewer process (it outlived the app) and prints browser / server errors.

## 4. Tests (executed 2026-11-21 on this Mac, conda env `css`, Python 3.11.17; synthetic data only)
| Suite | Result |
|---|---|
| `bash tests/run_uscore_tests.sh` (app + Percival) | **30 checks passed, 0 failed, 1 skipped** (851 PASS lines). Skipped: `check_ui_poll` - needs Node / npm, not installed |
| `bash unified_engine/run_tests.sh` (engine incl. Image ML app + browser) | **0 failing stages** |
| `bash tests/run_tests.sh` (pipeline on phantoms, incl. browser reviewer server) | **ALL TESTS PASSED** |
| `tests/check_percival.py` (engine, 37 checks incl. 15 new v5.23) | ALL PASS |
| `tests/check_app_percival.py` (real app + headless Chrome, 21 checks incl. 6 new) | ALL PASS (confirmed on a separate run) |
| `tests/check_local_only.py` | static scan incl. `unified_engine/` PASS; Percival engine + app tests pass with the network blocked; no connection attempted |

Flakiness found and handled: `check_app_percival` failed intermittently because of three real races / test assumptions (state race,
cache race, random-UUID locked test, all fixed in §3) and once from CPU contention while the pipeline suite ran in parallel (first
render exceeded Chrome's 12 s virtual budget; that check now retries once with 30 s). Synthetic results of note (not clinical):
the CNN lost to the pixel baseline (AUC 0.57-0.65 vs 0.83-0.96) and was not chosen; fusion was worse than Characteristic ML alone
(paired CI above 0) in one run and "no demonstrated improvement" in another; Image ML was redundant given the other sources.
Side effect of the suites: they regenerate three tracked files under `unified_score/output/` (synthetic test reports).

## 5. Not done / requires clinical data
- No training or evaluation on real clinical data (by rule); every performance figure is synthetic.
- Clinical validation of the Percival Score, its thresholds and calibration: requires expert-reviewed clinical cohorts with the locked
  test cohort, ideally an external site.
- `check_ui_poll` not run (Node / npm not installed).
- No click-through test of reviewer keyboard shortcuts (unchanged from Phase G).
