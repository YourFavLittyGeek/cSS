# PHASE_B_REPORT.md - Process Manager duplicates, review status / reviewer calls, Anatomy QC (2026-11-20)

Synthetic data only; no clinical file opened. Test results: section 5 (filled in from executed runs).

## 1. Duplicate detection (root cause: PHASE_A_AUDIT section 2)
| before | after |
|---|---|
| NIfTI identity = sha1 of the first 64 KB (header + empty corner): DIFFERENT studies with the same protocol header collided | `series_detect.content_fingerprint`: sha256 of the COMPLETE uncompressed image (header + every voxel); same for .nii / .nii.gz; independent of folder name and location |
| DICOM identity = SeriesInstanceUID truncated to 40 characters (shared scanner prefix) | full SeriesInstanceUID (`uid:`), or sha256 of every file when there is none |
| one wording "duplicate code" for a code clash with the project, a repeat inside the batch and the image check | three messages: exact duplicate (with what matched), "code already used by another study (a different image)", "code appears more than once in this batch" |
| warning only | an exact duplicate is left out (Include unticked) with the reason; it can still be ticked deliberately |
| old studies: weak fingerprint only | a weak match is settled from the study's own raw copy (`raw/ID/SWI`): its full fingerprint is computed and stored (additive: `fingerprint_v1` keeps the old value; `app_data/backups/patients.before_fingerprint_v2.json` written once before the first change); only when no raw copy exists is the match shown as "possible", never as certain |

## 2. Reviewer calls and review status (user decision 2026-11-20)
- **Every reviewer's calls are kept** (`review/ID_calls_<reviewer>.csv`, one file per reviewer, never edited by any policy step). The
  Excel export (`/api/export.xlsx`, export to the verified folder) has a `candidate_calls` sheet: one row per candidate, for EVERY
  reviewer a call, date-time and comment column, then the effective call, its source reviewer and time, the rule; plus a `call_policy`
  sheet.
- **Effective call** = by default the NEWEST call of any reviewer (`scripts/call_ledger.py`). A rule can choose one reviewer instead
  ("where this reviewer did not call: use the newest call" or "only"), for one study, a cohort or all studies (study > cohort > all).
  Changing it is possible from the Studies (results) screen and the Model (training) screen ("Reviewer calls" panel); every change is
  logged in `review/call_policy.json`.
- The shared `review/ID_calls.csv` / `ID_score.json` now hold the EFFECTIVE calls and their score (same file format), so the reader
  score, results, exports, study selection and Unified Score training all follow the rule without code changes in `unified_score/`.
  Before each rewrite the previous files are copied to `review/call_history/ID/`.
- The reviewer (`scripts/review_web.py`): each save writes the reviewer's own file and refreshes the effective calls; each finish writes
  the reviewer's OWN score (`ID_score_rev_<name>.json`) and re-scores the effective calls. The v5.7 "primary reviewer" rule (first saver
  owns the shared file) is replaced; "set primary reviewer" now means "use this reviewer's calls for this study".
  **Behaviour change**: `tests/check_review_web.py` asserted the v5.7 rule; it now asserts the new rule (newest call effective, Reader A's
  own file untouched, earlier shared files archived, choosing Reader A restores A's calls and score).
- **"Rewrite old calls - keep only the newest"**: the only destructive step; plan shown first; refused unless the exact phrase
  `REWRITE OLD CALLS` is typed (checked on the server, plus a final browser confirmation); every affected file archived to
  `review/call_history/ID/consolidate_<time>/`; `restore` puts them back byte-identical.
- **Review states** (derived from the files, read only): Not started / In progress / Reviewed / Needs re-review. Reviewed = every current
  candidate has an effective call AND a reviewer finished (finish or final save) - ANY reviewer, named in the status. Needs re-review =
  a finished review whose candidates changed afterwards (re-detection: calls that no longer match a candidate, new candidates). The
  Studies screen shows the label and the reason; status is independent of AI processing status.

## 3. Anatomy QC restored
New screen **Anatomy QC** in the main navigation (`app/qc_gui.py`, `app/qc_view.js`, `/api/fsqc/*`), plus an "Anatomy QC" button in every
study panel: FreeSurfer installation (folder, version, tools, licence readable - contents never shown), per-study anatomy route, the
expected FreeSurfer / SynthSeg / registration outputs (present / missing / older than the SWI), the Process Manager's reuse verdicts,
the detector's QC record and the QC image (now creatable for imported studies), Freeview (labels on the SWI, or the FreeSurfer recon with
surfaces). A study shows "QC ok" only when the required outputs exist and the recorded status is ok. The old QC window (`/qc?code=`) and
the study-panel "QC image" button are unchanged.

## 4. Files
New: `scripts/call_ledger.py`, `app/review_calls_gui.py`, `app/calls_view.js`, `app/qc_gui.py`, `app/qc_view.js`,
`tests/check_call_ledger.py`, `tests/check_duplicate_detection.py`, `tests/check_app_review_qc.py`, docs.
Changed: `app/series_detect.py` (content fingerprint), `app/css_app.py` (duplicate check + messages + fingerprint upgrade, review state in
results, Excel sheets, `/api/calls/*`, `/api/fsqc/*`, routes), `app/css_app.html` (status labels incl. Needs re-review, validation
messages, exact duplicates unticked, Reviewer calls button, Anatomy QC nav / route / study-panel button, scripts), `app/unified_view.js`
(Reviewer calls button on the Model screen), `scripts/review_web.py` (ledger), `tests/check_review_web.py` (new rule),
`tests/run_uscore_tests.sh` (new checks).

## 5. Tests (executed 2026-11-20, final code incl. v5.16 identification)
| suite | result |
|---|---|
| main pipeline suite `tests/run_tests.sh` (phantoms, real detector, reviewer server) | ALL TESTS PASSED (27:41 min) |
| app suite `tests/run_uscore_tests.sh` (+ new checks) | 598 PASS, 0 FAIL; `check_ui_poll` not runnable (no Node / npm) |
| engine runner `unified_engine/run_tests.sh` | 7 stages, 0 failing (119 + 78 unit tests, Shadow ML and Image ML app checks) |
New checks: check_call_ledger (30), check_duplicate_detection (17), check_app_review_qc (30 / 31 with screenshots), check_identity,
check_app_identity, check_gui_js_syntax.
Test-harness fix: `tests/check_morph3d_api.py` failed whenever FreeSurfer's `mri_vol2vol` is on the PATH (the reviewer writes ONE display cache,
`work/<ID>_t1_swispace.nii.gz`, by design). Proven on a copy of the phantom data (passes without FreeSurfer on the PATH, fails with it); the
check now requires every pre-existing file to be byte-identical and allows only that cache as a new file (negative controls: a modified
file and an unexpected new file both still fail).
Defects found and fixed on the way: unclosed files in `series_detect.scan`; `write_grades_file` KeyError for study records without grade
fields (e.g. linked studies); a JavaScript syntax break during the Studies-toolbar edit, caught by the new syntax check.
