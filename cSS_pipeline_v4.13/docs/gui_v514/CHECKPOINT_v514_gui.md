# v5.14.1-gui implementation checkpoint (branch `experimental/unified-gui`)

- **Branch:** `experimental/unified-gui`, created from `3bbfa14` in a separate worktree (`/home/user/unified-gui`).
- **Not done:** no commit, push or merge; no archive built.
- **Production:** `css/main` is still `3bbfa14`.

## 1. What was built
| Area | Files | Summary |
|---|---|---|
| Screen A: Unified workflow | `app/unified_gui.py`, `app/unified_view.js`, `app/css_app.py` (routes), `app/css_app.html` (tab) | 8 steps: cohort audit, features, reliability, train & nested validation, model & freeze, candidates, robustness, export. Every step is a background job with progress, Stop, Log and error display |
| Screen B: reviewer | `scripts/review_web.py` (`/api/uscore`, core / support in `/api/morph3d`), `scripts/review_web.html` (card, layers, jump to candidate), `scripts/morph3d_view.js` (layers) | unified card (category, reasons, five predictors with reliability and contributions, three detectors, stability, protective flags); 3-D layers "Dark core (experimental)" and "Blooming / support"; card and layers hidden in a validation read |
| Screen C: test protocol | `app/gui_protocol.py`, Test protocol tab | T1–T15; 13 automatic checks (T1–T4, T5a, T6–T13) and 3 manual items (T5, T14, T15); saved as an xlsx / json test record |
| Fail-safe execution | `app/css_app.py` | unified step OPT-IN (off by default); runs after "done" and the results save, in a background thread and subprocess, 15-minute limit; status pending / running / completed / failed / interrupted (after a restart) |
| Statistical safeguards | `uscore/pipeline.py`, `report.py`, GUI | training never freezes (separate freeze needs the typed word FREEZE); estimate labelled CROSS-VALIDATION; v5.10 only in a separate "not comparable" box; held-out section "Not run"; held-out evaluation has no GUI route and the CLI needs a written authorization file |
| Test harness | `tests/run_tests.sh` | `set -o pipefail`; `head` → `first` and piped `grep -q` → `grep … >/dev/null` (both avoid false SIGPIPE failures). A failing piped check now fails the suite |
| Build stamp | `scripts/BUILD`, `scripts/VERSION`, `install.sh` | BUILD = `$Format:%H %cs$` (was a stale literal); a source-checkout install stamps commit, date, branch and "+uncommitted changes"; VERSION installed and set to v5.14.1-gui |
| Install gap (pre-existing since 115721f) | `install.sh` | `review_web.html` and `morph3d_view.js` were never installed: the reviewer failed on a fresh install. Now installed |
| Cylinder investigation | `docs/INVESTIGATION_morph3d_cylinder.md` | real defect in the v5.12 local-shape classifier (no "below resolution" outcome). Test left FAILING; fix proposed, not applied |
| Tests | `tests/check_app_unified.py` (new, 25 checks through the app's HTTP API), `uscore_synthbase.py` (complete candidate columns, dark map, segmentation) | added to `run_uscore_tests.sh` |

## 2. Test results (outputs in this folder)
| Suite | Result |
|---|---|
| `run_uscore_tests.sh` (dark core, features, 17 adversarial scenes, 5-seed sweep, pipeline, **app GUI end to end**) | **all passed** (`TEST_uscore.txt`) |
| `test_shell.sh` | **passed** (`TEST_shell.txt`) |
| `run_tests.sh` (corrected harness) | **FAILS at the morph3d cylinder check** (`TEST_run_tests.txt`). This is the real defect above, now no longer hidden. The suite stops at its first failure |
| `run_tests.sh` continued past that one check (scratch copy, only that line made non-fatal; not part of the branch) | **every other section passed** ("ALL TESTS PASSED"; the only FAIL is the cylinder check) — `TEST_run_tests_continue_past_morph3d.txt` |

During the harness fix a false failure appeared ("agreement on identical sessions"). Cause: under `pipefail`, `grep -q` stops reading and the writer exits 141. The tool itself exits 0. Fixed by not using `grep -q` in pipes.

## 3. Original processing workflow preserved
- **Detector and scorer unchanged:** `detect_css.py`, `score_css.py`, `css_common.py`, `css_qc.py`, `run_css.sh`, `align_seg.py`, `cohort.py`, `css_confidence.py` and `prep_anat.sh` are identical to 3bbfa14 (git diff). Only the reviewer / viewer files in `scripts/` changed.
- **App order:** detection → QC → AI score → results copy → "done" → results workbook. Only after that does the unified step queue, and only when it is switched on.
- **Fail-safe tested:** T9 injects a unified failure; the patient stays "done" and the results workbook is still written.
- **Integrity tested:**
  - T11 and `check_app_unified` hash review/, data/, work/ and raw/ around unified runs: nothing changes. The one exception is the existing v5.14 AI-score backfill (`*_score_ai.json`), which runs at app start and is unrelated to the unified score.
  - Reader files (`*_calls*.csv`, score files, viewer settings) are never written by the unified code.

## 4. Held-out data protected
- The GUI has no held-out route (`/api/u/heldout` → refused; T13).
- `LabelAccess` refuses held-out labels in development mode and logs every access.
- **The CLI requires all of:**
  - a frozen model;
  - its hash;
  - `uscore/heldout_authorization.json` with your name, the date, that hash and the exact statement.

  A hash alone is refused, and so is an altered statement (tested in `check_uscore_pipeline`).
- In every run here, held-out label reads = 0.

## 5. Demonstration
Screenshots in this folder, from the real app running a SYNTHETIC demo cohort (SYN studies; red banner; never a result):
- A1–A8: the eight workflow steps;
- B1 (+ overview): the reviewer with the unified card;
- B2: the 3-D view with the dark-core (red) and support (blue) layers;
- C: the test protocol.

The whole workflow was driven through the app's own endpoints (the same calls the buttons make). `check_app_unified.py` repeats it automatically.

## 6. Known limitations
- No real patient data in this container. The Mac run is the real validation: process M patients, run steps 1–8, tick T5, T14 and T15.
- Synthetic demo numbers (AUC 1.00, saturated probabilities) are meaningless: the synthetic data separate trivially.
- The cylinder defect (above) affects the 3-D viewer's local-shape display on thick-slice scans.
- Synthetic fixtures needed the full production candidate columns, a dark map and a segmentation before the reviewer could open them. This is a test-fixture matter, not an app change.

## 7. Diff against 3bbfa14
`DIFF_vs_3bbfa14.patch`:
- **Tracked files:** 23 changed, +379 / −92. This includes 2 regenerated synthetic test outputs under `unified_score/output/`.
- **New files:** `app/unified_gui.py`, `app/gui_protocol.py`, `app/unified_view.js`, `app/production_reference.json` (and their bundle copies), `tests/check_app_unified.py`, `tests/uscore_synth_columns.json`, the docs, and this folder.
