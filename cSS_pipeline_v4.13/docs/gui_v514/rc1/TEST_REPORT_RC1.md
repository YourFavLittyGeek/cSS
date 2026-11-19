# RC1 test report (v5.14.2-rc1, branch experimental/unified-gui, uncommitted, on 3bbfa14)

**Where:**
- Linux container (x86_64), synthetic data only;
- headless Chromium for the GUI;
- no macOS, no FreeSurfer installation, no real MRI.

## Commands and results (logs in this folder)
| Command | Result | Log |
|---|---|---|
| `bash tests/run_tests.sh` (phantoms end to end, detector, scoring, QC, morphology incl. the 100-case resolution matrix, viewer) | **ALL TESTS PASSED**, exit 0 | `TEST_run_tests.txt` |
| `bash tests/run_uscore_tests.sh` (unified score, held-out protection, Processing Manager, linking, full-pipeline history, export safety, audit script, local-only, app GUI) | **first attempt FAILED**: protocol check T4 detected the changed `score_css.py` (see below) | `TEST_uscore_and_app_attempt1_FAILED_T4.txt` |
| same, after recording the change in `app/production_reference.json` | **all passed**: 322 PASS lines, 0 FAIL, exit 0 | `TEST_uscore_and_app.txt` |
| `bash tests/test_shell.sh` (run_css / prep_anat / run_all flow with stubbed FreeSurfer) | **SHELL TESTS PASSED**, exit 0 | `TEST_shell.txt` |
| `python3 tests/e2e_rc1.py docs/gui_v514/rc1` (built bundle, real launcher, real detector, GUI walkthrough, restart, integrity, network) | **35 PASS, 0 FAIL**, exit 0 | `TEST_e2e_rc1.txt`, `E2E_RC1_RESULT.txt`, screenshots `R01`–`R14` |

**The one failure, and what was done:**
- **What T4 checks:** the app's own integrity check compares installed detector / scorer files with reference fingerprints.
- **Why it failed:** it correctly flagged `score_css.py`, changed in RC1 by a one-line display fix. The summary print crashed on numeric region labels; this is reproduced in the E2E run without the FreeSurfer colour table.
- **What was done:** the check was **not weakened**. The reference now records `score_css.py` as changed, with the reason, and the check reports it.

## Acceptance evidence
| Requirement | Automated evidence | Seen in the GUI (screenshot) | Needs you (Mac / clinical) |
|---|---|---|---|
| Launch and navigation | E2E: bundle built, unzipped, own launcher starts the app on 8810 and installs its pipeline; refuses `~/css_project` | R01 | first open on macOS, window, dialogs |
| MRI import (existing processed studies) | check_link_study 11/11; E2E: 4 studies brought in, source unchanged (every file's content and modification time) | R02 | your folder layout, disk use |
| Recognition and reuse of FreeSurfer | check_processing_manager (six categories, version, incomplete / incompatible / corrupted); E2E: linked recon recognised, version shown, never written | R03, R04 | real FreeSurfer `build-stamp`, real recon-all |
| New cSS detection run | E2E: real `detect_css.py` on synthetic SWI (SWI-only and 2.4 mm-slice studies), AI score written without error, unified report regenerated | R05–R08 | run time and candidates on your studies |
| Candidate generation and scoring | E2E; run_tests phantoms | R09, R12 | clinical judgement |
| Morphology incl. unresolved cases | 100-case matrix; E2E: thick-slice study shows acquisition-limited with the explanation | R13, R14 | 1.5 T 3 mm studies |
| 3-D rendering | E2E: panel renders with measures (software WebGL) | R13, R14 | Mac GPU |
| Processing history, old results preserved | archive / restore / make-active / resume tests; E2E: both candidate lists archived; restart mid-run → interrupted, previous outputs restored | R08 | one quit-while-running test |
| Export and backup safety | check_export_safety 16/16; E2E: warning first, Desktop refused | R10, R11 | iCloud on your Mac |
| No external network attempts | check_local_only; E2E with every outside connection blocked and logged: **none attempted** | — | Wi-Fi-off run |

## Not tested here
- macOS-specific behaviour: Gatekeeper, pywebview window, osascript pickers, notifications, caffeinate.
- Real FreeSurfer, real pial surfaces → surface_features in a new run.
- Real-data run time.
- Patients → Re-run with the real pipeline (only the history hooks are unit-tested).
