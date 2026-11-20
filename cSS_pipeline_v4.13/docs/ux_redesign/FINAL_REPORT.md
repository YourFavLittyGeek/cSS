# UX redesign — final report (Percival experimental app)

Branch: `experimental/unified-gui`, local and **uncommitted** (nothing committed, pushed, tagged or released).
Protected and untouched: production `css/main` / commit 3bbfa14, the RC3 release and its artifacts, Signal Laboratory, clinical datasets and historical outputs.

## What changed
Only the GUI changed:
- `app/css_app.html`: new shell, design system and views.
- `app/css_app.py`: `state()` also returns the project name and path (read-only).
- The GUI tests were moved to the new UI.

Nothing else changed: no detection algorithm, threshold, confidence calculation, ranking model, model weight, feature definition, processing default, scientific output, file format or schema. Every action still calls the same `/api/...` endpoint with the same body.

| Before (8 top tabs) | After (sidebar) |
|---|---|
| Home, Patients (list), Results, Processing (list) | **Studies**: overview tiles (filters) + one table with a plain-language status; click a row → study panel (Summary / Processing / Technical / Log) |
| Add patients + Processing "bring in" | **Add studies**: tabs "From image folders" / "From another project" |
| Patients queue, Processing runs, Unified job boxes | **Activity** (Process Manager): Needs attention · Running · Waiting · Finished in 24 h; capacity collapsed (opens itself in the memory danger zone) |
| Review / Blind read | **Review** (unchanged content) |
| Unified (experimental) | **Model** (unchanged content) |
| Settings + Home setup / version | **Settings**: General · Processing (advanced) · Notifications · System (setup check with fix buttons, version, install / rollback) |

## How the redesign keeps its rules
- **Progress bars only where real:**
  - a pipeline bar is the step fraction (k−1)/5;
  - a model-job bar is the job's own reported progress.
- **Time left** is shown only when the existing timing model gives one, labelled "≈ … (estimate)".
- **No new process states:** each label maps one-to-one to an existing state (vocabulary in REDESIGN_PLAN.md).
- **Confirmations kept:** Stop, Remove, recon-all (2–3 h), new detection run, clinical-data export warning, the training gate. The pathway, retry and re-run dialogs are the same as before.
- **Feature coverage:** all 27 capabilities are kept, with their new locations in FEATURE_PRESERVATION_MATRIX.md.

## Tests (synthetic data only)

| Suite | Result |
|---|---|
| Smoke test: every section and every study-panel tab opened | no page errors |
| `tests/e2e_rc1.py` (rewritten GUI walk-through: bring-in, confirm earlier outputs, compatibility, new detection run with the real pipeline, Activity shows it running, history, Studies, export warning, Desktop refused, reviewer + 3-D) | ALL PASS |
| `tests/run_uscore_tests.sh` (incl. check_ui_poll, check_selection_notifications with the new navigation, screenshots at 1024 / 1280 / 1440 px with no horizontal overflow) | all passed |
| `tests/run_tests.sh`, `tests/test_shell.sh` | see the end of this file |

**Changed test expectations** (documented in the test files):
- the Processing / Results tabs → the Studies table + study panel;
- `#pmd` → the study panel's Technical tab (`#shb`);
- the option radio + `#pmgo` → `[data-c="fresh"]`;
- `#shareb` → `#sexp`;
- the start screen is Studies ("No studies yet").

## Screenshots
- `before/`: 8 old views × dark / light.
- `after/`: 6 sections × dark / light.

**Known cosmetic point:** in full-page screenshots the sticky sidebar ends at the viewport height. In the app window it stays in place while the page scrolls.

## Not done / follow-ups
- The old view functions `homeView`, `ptsView`, `resView` and `procView` are still in the file but are no longer reachable. Their features are covered by the new views. They can be deleted after you have tried the app on the Mac.
- A few labels inside the Add flow still say "patient" (single patient / batch); renaming them was left for your review.
- Not tested on the Mac app bundle or with real MRI data; this was a synthetic demo project only.

## Full-suite results (after the redesign)
- `tests/run_tests.sh`: exit 0
- `tests/test_shell.sh`: exit 0
- `tests/run_uscore_tests.sh`: exit 0 ("unified-score tests: all passed")
- `tests/e2e_rc1.py`: ALL PASS
