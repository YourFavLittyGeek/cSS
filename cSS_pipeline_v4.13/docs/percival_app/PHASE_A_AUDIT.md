# PHASE_A_AUDIT.md - Percival complete application build: architecture and bug audit (2026-11-20)

Read-only audit of branch `feature/unified-score-ml-integration` @ `e2b9a87` (worktree
`/Users/tarabeah.selim/Projects/cSS-unified-score-ml`). No code was changed. Only synthetic files (scratch folder) were used to
reproduce defects; no clinical image, table or label was opened.

## 0. Repository state at the start
- Branch `feature/unified-score-ml-integration`, HEAD `e2b9a87`, working tree clean (only Finder `.DS_Store`), no stash, not on any remote.
- The brief mentions "uncommitted P3 work": there is none. P3 and the Image ML prototype were committed in `e2b9a87`.

## 1. Architecture (as found)
| layer | files | notes |
|---|---|---|
| desktop shell | `app/css_app.py` (1495 lines, stdlib `http.server`, 127.0.0.1, POST needs `X-CSS-App: 1`), optional pywebview window, Mac launcher `app/mac*`, write guard `app/guard` | state in `$CSS_BASE/app_data/` (`patients.json`, `settings.json`, `qc/`, `logs/`) |
| single-page GUI | `app/css_app.html` (795 lines; router `render()` / `VMAP`), `unified_view.js` (Model), `shadow_view.js`, `image_ml_view.js` | rc5 redesign 6f0ca44 rebuilt Studies / study panel / Activity / Settings |
| import | `series_detect.py` (scan + series fingerprint), `css_app.scan_patient` / `add_to_queue` | Add studies (single / batch) |
| Process Manager | `app/processing_manager.py` (620 lines) | earlier-processing detection per stage, run archive, import from another project |
| pipeline | `scripts/run_css.sh`, `prep_anat.sh`, `detect_css.py`, `score_css.py`, `css_qc.py` | run as subprocesses per study |
| reviewer | `scripts/review_web.py` + `review_web.html` (separate server, port 8765) | calls, primary reviewer, finish / final save |
| Unified Score (Stage 1) | `unified_score/uscore` (Model screen) + `unified_engine/` (Shadow ML) | unchanged |
| Image ML (Stage 2 prototype) | `unified_engine/uengine/imaging/`, `app/image_ml_gui.py` | synthetic only |

## 2. Bug 1 - Process Manager / Add studies reports a duplicate for a first-time study
What triggers a duplicate message (three independent mechanisms, two with the same wording):
1. **SWI fingerprint** (`css_app.scan_patient`, feature `duplicate_check`, default on): the chosen SWI's `fingerprint` is compared with
   the stored fingerprint of every study in `patients.json` -> warning "this SWI is already in the project as X".
   `series_detect.scan` computes it as: NIfTI = **sha1 of the first 64 KB of the file**, truncated to 16 hex characters; DICOM =
   SeriesInstanceUID, else sha1 of the first 64 KB of the first file.
   **Root cause (reproduced with synthetic files):** the first 64 KB of an uncompressed `.nii` is the 352-byte header plus the first
   ~32 000 voxels, which lie in the empty corner of the field of view. Two DIFFERENT studies with the same protocol header and an empty
   corner get the SAME fingerprint. Synthetic reproduction: two studies with different brain voxels, identical header -> identical
   `.nii` fingerprint (`90ff7e542d28c35c`), different full-file sha256. (`.nii.gz` happened to differ in the test because the compressed
   stream diverges earlier, but it is equally weak in principle.) Whether real exports collide depends on how identical their headers
   are (affine, description); this was NOT checked on clinical data.
2. **Code collision, browser** (`css_app.html validate()`): the `seen` set is initialised with EVERY code already in the project, and
   the message is the same "duplicate code" as for a repeated code inside the batch. A folder whose naming rule (`before_underscore`,
   `digits`) yields an existing code is reported as a duplicate although the study is new.
3. **Code collision, server** (`add_to_queue`): same rule and same wording; the whole batch is refused.
4. Process Manager import (`processing_manager.import_study`): refuses when `runs/ID/import.json|link.json` or `data/ID_*` exists -
   correct protection, but the message does not say what matched.
What is NOT compared today: full-content hash, voxel-data hash, study / series UID for NIfTI (dcm2niix JSON), acquisition date/time,
source path. Renamed / moved folders are not distinguished from new ones because the folder path is deliberately not stored (only
its sha1 prefix `source_folder_hash`, never used for matching).

## 3. Bug 4 - study never shows "Reviewed" after the review is finished
The Studies status is derived in the browser from `results()` (`css_app.py`): **Reviewed = `review/ID_score.json` exists with a
total score**; "Review in progress" = `ID_calls.csv` has calls. Root causes:
1. **Primary-reviewer rule** (`review_web.py`, v5.7): the FIRST name that saves a call becomes the study's permanent primary reviewer
   (`primary(..., if_missing=True)`). Only the primary reviewer's finish writes the shared `ID_score.json`; every other reviewer's
   finish writes `ID_score_rev_<name>.json` and `ID_final_<name>.json`, which the Studies screen never reads. Any earlier save under
   another name (a test name, a different spelling, a colleague) makes the user's own completed review invisible - permanently.
2. **Completion = a score file, not a review decision**: `/api/finish` without "final" also writes the score, so a study can show
   "Reviewed" before the reviewer has finished; the explicit final save (`ID_final_<name>.json`) is ignored by the Studies screen.
3. **No "Needs re-review"**: after a re-detection the old score file stays, so the study keeps "Reviewed" for a candidate list the
   reviewer has never seen; nothing compares the reviewed candidate list with the current one.
4. **Failure is silent**: if `mark_css.py` / `score_css.py` fails, the error is only in the reviewer's response text; the Studies screen
   shows the old state.
5. Review completion and AI-processing completion share one status column without a defined state machine.

## 4. Bug 5 - FreeSurfer QC no longer visible
- No branch ever had a screen named "FreeSurfer QC". The QC the user used is the **QC window** (`/qc?code=ID`, `/api/qc`): the
  anatomy labels (FreeSurfer / SynthSeg cortex, cyan) and the brain mask (yellow) on three SWI slices, previous / next navigation,
  label-shift value from `review/ID_qc.json`; produced by `css_app.qc_snapshot()` after processing.
- **Root cause:** in rc4 the QC buttons ("QC ↗" per study) and the inline QC image panel (`#qcimg`) lived in `ptsView`. The rc5 redesign
  (6f0ca44) routes the old `pts` view to Activity (`VMAP pts -> act`), so **`ptsView` is never called** (dead code). What remains is a
  small "QC image" button in the study panel, shown only when `app_data/qc/ID.png` exists.
- Secondary: the snapshot is made only by this app's own processing; studies imported / linked through the Process Manager or processed
  by an older app never get one and there is no way to create it; `qc_snapshot` failures are written only to the study log; recon-all
  outputs (surfaces, aparc+aseg, Destrieux) are checked by the Process Manager but not shown as QC; the QC image is PNG-only (no viewer).

## 5. Other findings relevant to the later phases
- **Quick Add**: no screen of that name exists. The candidate label control is the reviewer's call bar (`review_web.html #dec`): 7 coarse
  calls with single keys (Y cSS, V Vessel, N Normal, A Artifact, B Microbleed, U Unsure, H Near ICH). The expert sheet / label table
  have 19 fine codes (`css_common.LABELS`, css-labels/1.0) that the GUI reviewer cannot record - mimic subtypes are lost in GUI reviews.
  ASSUMPTION for Phase E: "Quick Add" = this call bar (please correct if you meant another control).
- **Reviewer identity**: free-text reviewer name per session (`reviewers.json`); the "AI" in the reviewer is the rule-based detector
  meter / AI score (score_css `--tag ai`), labelled "AI vs reviewer" - it is not a learned model and has no version shown.
- **Batch add table**: one row per study with up to 10 columns of selects (folder, code, name, 4 series, radiologist, R, L, notes,
  include); series options show full relative names and descriptions -> wide rows, horizontal scrolling.
- **Setup**: a pre-flight check exists (`/api/preflight`: FreeSurfer, licence, dcm2niix, pywebview with fix buttons) and Settings has
  FreeSurfer home / licence fields, but there is no first-run wizard, no FreeSurfer version / licence validation test, no readiness report.
- **Training interface**: the "Model" screen (`unified_view.js`) mixes study selection, training gate and validation; Image ML and Shadow ML
  are separate screens.
- **Existing tests**: engine runner 7 stages (Stage 1 + imaging + 2 app/browser checks) and the app suite `tests/run_uscore_tests.sh`
  (412 checks) pass; `check_ui_poll` needs Node (not installed).

## 6. Phase dependencies and risks
| phase | depends on | main risks |
|---|---|---|
| B Process Manager, review status, QC | none | changing the "Reviewed" definition and primary-reviewer rule affects existing review files -> must be read-only migration (derive state, never rewrite reviewer files) |
| C reprocessing + lineage | B (state machine for Needs re-review); the Process Manager run archive | candidate matching thresholds decide whether a human call carries over -> transfer only confident matches, everything else flagged; never touch historical calls |
| D Image ML / Unified integration | C (current run as the input) | no detector run on synthetic phantoms today: a synthetic end-to-end fixture must produce real detector tables (phantom + detect_css) for MATH / Characteristic ML |
| E training / Quick Add / batch / identity UI | B, C, D | fine-code labels in the reviewer = new label recording, not a meaning change; needs the css-labels/2.0 mapping (P4) documented |
| F setup wizard | none (can run in parallel) | must never read or display licence contents; FreeSurfer location never assumed |
| G regression, screenshots, docs | all | Node / Playwright absent: click-through tests use the HTTP API + headless Chrome DOM like the existing checks |
Approval points (will stop and ask): any rewrite of existing reviewer files or labels; replacing the bundled model; migrations of
`patients.json` beyond additive fields.
