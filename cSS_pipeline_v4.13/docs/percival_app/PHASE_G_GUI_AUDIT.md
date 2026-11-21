# Percival Phase G - GUI audit, test coverage and remaining defects

Branch `feature/unified-score-ml-integration` (worktree `cSS-unified-score-ml`). Everything here uses synthetic data. No clinical MRI was
opened, nothing was pushed, merged or deployed, and the model weights were not replaced (Image ML `8d223b29…` is unchanged).

## 1. Screens and how each is tested

"Functional" means an automated test drives the real app server over HTTP (and, where marked, headless Chrome reads the rendered DOM).
"Screenshot only" means the screen was rendered and inspected, but no automated test clicks through it.

| Screen | Test(s) | Coverage | Screenshot |
|---|---|---|---|
| Studies (list, Standard / Incognito, review status, Edit identifiers) | check_app_identity, check_identity, check_app_review_qc | functional + DOM | studies_standard, studies_incognito, studies_review_status, studies_standard_after_restart, screen_studies |
| Add studies - guided import (7 steps) | check_app_identity (template, preview, commit, rollback, re-import) | functional | import_wizard_steps |
| Add studies - batch table | check_app_batch_layout, check_duplicate_detection | functional + DOM layout at 1280 / 1500 px | batch_add_1280px, batch_add_1500px |
| Review (reviewer window, Quick Add, human vs AI labels) | check_review_web, check_gui_js_syntax | functional (API) + JS syntax; keyboard shortcuts **not** driven | reviewer_quick_add |
| Reviewer calls panel (policy, consolidation, restore) | check_call_ledger, check_app_review_qc | functional | - |
| Compare runs (lineage, confirm / reject) | check_lineage | functional | - |
| Anatomy QC | check_app_review_qc | functional | anatomy_qc, anatomy_qc_missing |
| Training A-D | check_app_training | functional + DOM | training_A..D |
| Model (Unified Score) / Shadow ML | check_app_unified, check_uscore_* | functional | screen_uni, screen_shadow |
| Image ML | check_app_image_ml, unified_engine test_image_ml | functional + offline (netguard) | screen_imageml |
| Setup wizard | check_app_setup | functional + DOM (first run, restart) | setup_wizard |
| Activity (queue) | check_processing_manager, check_pm_full_pipeline, check_ui_poll | functional (API); **check_ui_poll needs Node - not run** | screen_act |
| Settings | check_app_setup (Setup card), check_export_safety (folders) | partial: the Features toggles have no dedicated test | screen_set |

## 2. Remaining defects and limits (known, not hidden)

1. **check_ui_poll cannot run on this Mac** (it needs Node/npm, which is not installed). It is the only check in the app suite
   that was not executed. Because the stock runner uses `set -e`, it stops there; the Phase G run used a copy without `set -e`, so every
   later check was run and reported.
2. **Intermittent check_app_identity failure** ("Excel file format cannot be determined" on the downloaded template): seen once,
   not reproduced in 4 reruns or in the Phase G run (see §3). A diagnostic print records the response size and type if it happens
   again. Root cause not yet proven; the likeliest is reading the file before the download finished writing.
3. **No click-through test** for the reviewer's keyboard shortcuts, the Settings Features toggles, or the Activity screen's live
   updates in a browser. These were checked by hand on synthetic data only.
4. **Old "From image folders" Add flow** still records the source folder path it was given; the guided import stores neutral copies
   (`app_data/import_src/<file_key>/`). Projects that used the old flow before v5.16 may have patient-named source paths in
   existing logs; v5.16 redacts new log lines but does not rewrite old logs (rewriting history needs your approval).
5. **Legacy logs / names.csv** are kept unchanged (additive migration, as approved).
6. **Image ML is synthetic only.** Its outputs are blocked on non-synthetic studies and labelled "SYNTHETIC". It is not clinically
   validated, and neither is the Unified Score.
7. **Lineage**: anything other than a clean one-to-one IoU ≥ 0.5 match waits for a human. On a large re-run this can mean many
   confirmations; there is no bulk-confirm button (on purpose for now).

8. **Fixed in Phase G - setup wizard overstated readiness.** It marked "Pipeline installed" as ready by falling back to the repository's
   `scripts/run_css.sh`, while the app runs `<project>/scripts/run_css.sh` (the Studies banner correctly said "Setup needs attention:
   Pipeline"). Found by launching the final build on a fresh synthetic project. The fallback is removed, and check_app_setup now asserts
   both the missing and the present case.

## 3. Phase G regression run (executed 2026-11-20, commit 63470ff)
- App suite (`tests/run_uscore_tests.sh`, run without `set -e`): 675 PASS / 0 FAIL. Only `check_ui_poll` was not run (no Node / npm).
  `check_app_identity` passed (the intermittent failure did not recur).
- Engine suite (`unified_engine/run_tests.sh`): 0 failing stages.
- Pipeline suite (`tests/run_tests.sh`): ALL TESTS PASSED (28 min).

## 4. v5.18 (after Phase G, on your request): one import pathway, study library, export with files
- **Add studies** = From folders + From another project. The guided import and the batch table are merged, and "Store names" is gone.
- **Folder names:** patient name / MRN / accession number / code / irrelevant, plus optional sub-folder meaning (accession / code).
  Bug fixed: code folder names were replaced by generated PCV codes; they are now the study codes.
- **Rules:**
  - Standard: MRN and accession are required from the user; the name is optional; a blank code is generated; grouped by MRN.
  - Incognito: the key is required and stored in the vault (the passphrase is asked, the screens stay de-identified, the vault is
    relocked afterwards); the code is required; no grouping.
  - Irrelevant folder names: every Excel row needs `folder`.
  - The DICOM header only cross-checks.
- **Series:** automatic SWI / T1 with reasons; **Series…** dialog with thumbnails for a manual choice ("chosen by you").
- **Study library:** a verified copy (sha256) at `<MRN>/<accession>/` or `<code>/`; never overwrites; originals untouched.
- **Export:** "Studies with files…" to a chosen local folder; results always, plus processed / FreeSurfer / MRI / logs as chosen.
  Incognito exports use code folders, contain no DICOM, and hide paths in the logs.
- **Patient column** in Studies: name · MRN (Standard) or an incognito icon (Incognito).
- **Tests:** `check_app_import_v518.py` (new). `check_app_add_layout.py` replaces `check_app_batch_layout.py`. `check_app_identity.py`
  was updated: its old expectations encoded the code-folder bug and the key-less Incognito import.
