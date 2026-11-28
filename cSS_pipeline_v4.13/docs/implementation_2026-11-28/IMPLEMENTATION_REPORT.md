# Implementation report — post-audit corrections (2026-11-28)

Baseline: branch `claude/phase0-safety`, HEAD `f4c5ca6` (code `773e08b`), clean working tree; latest release
`Percival_v5.25-dev_773e08b.zip`. Audit: `~/PERCIVAL_audit_2026-11-27/` (documents 00–07).
No real-data training was run, no label was created or changed, no model was promoted, no original MRI was touched. The user's
running app and reviewer windows were not stopped. All tests ran isolated (`tests/run_isolated_suite.py`, temporary HOME / project).

Classification: **D** confirmed defect · **L** confirmed scientific limitation · **S** suspected, needs verification · **F** future enhancement.
Status: **FIXED** · **VERIFIED-OK** (already correct) · **OPEN**.

## 1. Tracking table

| # | Finding (audit ref) | Cls | Sev | Component / files | Correction | Acceptance criterion → evidence | Status |
|---|---|---|---|---|---|---|---|
| 1 | Pooled-OOF artefact: meta level re-split the table into new random folds and pooled fold-specific models (v001: per-fold slopes all > 0, pooled AUC 0.508) (03 S1) | D | Critical | `uengine/percival/meta.py` (folds, discover, train_cycle), `nested.py`, new `validation.py` | one stratified patient-fold assignment shared by components and meta level; discrimination measured WITHIN held-out folds (`fold_auc`); nested reports within-outer-fold AUC | re-run on the cached ds001 scores: fold-AUC 0.69 for ALBUS vs pooled 0.51; a fixed random score has fold-AUC 0.50 ± 0.03 (`test_validation_m1.TestWithinFold`); fold offsets cannot hide a within-fold ranking (test) | FIXED |
| 2 | Calibration fitted on the pooled table (slope −0.41 reversed the model; 773e08b only clamped it) (03 S1) | D | Critical | `validation.calibrate`, meta.py, nested.py | Platt with one intercept per held-out fold and a common slope (between-fold offsets cannot bias it), intercept refitted to the base rate; slope ≥ 1e-3 enforced (order never reversed), per-fold slopes + sign agreement reported | on ds001-like data the within-fold slope is +0.30 (was −0.41); inverse data → clamped, never reversed (`test_training_progress`, `test_validation_m1`) | FIXED |
| 3 | 1-SE rule on the unpaired SE of the best model, no null baseline → simplest model always chosen (03 S2) | D | Critical | `validation.select_kind`, meta `_select` + `discover` | fold-stratified AUC; paired patient bootstrap on the same resamples; simplest model only within one PAIRED SE of the best; `informative` only when the chosen model's lower 95 % bound > 0.5; log loss + prevalence baseline reported | strong model beats a simpler null; indistinguishable → simpler kept; noise → not informative (tests); `check_percival` "chosen beats ALBUS alone" passes | FIXED |
| 4 | Class weighting differs between families compared on log loss (03 S6) | D | High | meta `_select` | family choice now by discrimination (fold AUC, paired) — weighting cannot bias it; log loss shown for reference | `_select` uses `V.select_kind` | FIXED |
| 5 | Acceptance compared PERCIVAL (abstentions removed) with ALBUS (all candidates) (03 S3) | D | High | meta `evaluate_test`, `acceptance` | `math_same` = ALBUS on exactly the candidates PERCIVAL scored; coverage reported; acceptance uses `math_same` | `TestAcceptance` | FIXED |
| 6 | Candidate-level metrics only; 4 positive test patients (03 S4) | L | High | `validation.patient_level`, `lesion_level`; Model Center card | patient-level AUC (highest candidate per patient, missed-mark patients positive) with CI + reliability note (< 10 per class); lesion sensitivity at 0.5/1/2/4 FP per study with missed lesions in the denominator; acceptance requires ≥ 5 patients with a cSS CANDIDATE | `TestLevels`, `TestAcceptance`; card `pvLevels` | FIXED (sample size remains a limitation) |
| 7 | Not-informative models presented as scores (mission 3.1) | D | High | meta acceptance, Model Center | acceptance reason "not informative"; red banner in the meta-model screen | `TestAcceptance` | FIXED |
| 8 | Test reuse: a failing model did not use the milestone (03 S5) | D | High | `percival_gui.test_reuse_gate` | every consultation uses the milestone (`consumed=True`), pass or fail | `TestApp.test_failed_consultation_uses_the_milestone` | FIXED |
| 9 | Readiness checklist was display-only; training could start without its prerequisites (mission 3.4) | D | High | `percival_gui.readiness`, `train_async`, `percival_view.js` | staged gate (data imported → review completed → ground truth → training dataset eligible → validation eligible (not blocking) → training permitted); `train_async` refuses with the reasons; the test override works only when EVERY study is synthetic | `TestApp.test_gate_blocks_training`; `check_app_percival` (synthetic) still trains | FIXED |
| 10 | Engine code hash missed `ml_component.py`, imaging, detector; no library versions (03 S18) | D | Medium | `percival_gui._code_version` | hashes `uengine/percival/*`, `ml_component.py`, `imaging/*`, `detect_css.py`, `call_ledger.py`, `surface_aligned_patch.py`; records Python / numpy / scipy | code read | FIXED |
| 11 | SHADOW governed lab got 0 rows on real data (`status` key absent) (01 / 03 S15) | D | Medium | `percival_gui._shadow_rows` | eligibility from `components.shadow` of the manifest | `TestApp.test_shadow_reads_the_real_manifest_shape` (real manifest shape) | FIXED |
| 12 | `jload` turned any read error into `[]`/`{}`; next save overwrote `patients.json` / `settings.json`; shared `.tmp` (00 #5) | D | Critical | new `app/safe_json.py`; `css_app.jload/jsave`; banner in `css_app.html` | retries; last good `.bak`; unreadable original preserved in `app_data/corrupt/`; no backup → file BLOCKED (saves refused) until explicitly unblocked; unique tmp + fsync + dir fsync + lock; problems shown on screen | `tests/test_safe_json.py` (12: truncated, empty, whitespace, invalid, permission, transient, interrupted write, vanished file, backup recovery, blocked, concurrent writers, wiring) | FIXED |
| 13 | Identity vault plaintext by default; an unreadable vault was replaced by an EMPTY one (00 #6) | D | Critical | `app/identity.py`, new `app/keystore.py`, `identity_gui.py`, `uengine/health.py` | AES-256-GCM (cryptography library) with a random 256-bit device key in the macOS login Keychain; plaintext migrated only after a decrypt round-trip, then moved to the Trash; unreadable vault never replaced; recovery key (typed confirmation); health check reports plaintext as a warning; tests never touch the real Keychain | `tests/test_identity_encryption.py` (7); `check_identity` ALL PASS | FIXED (migration runs at the next app start on the user's Mac) |
| 14 | Pen-mark fate judged from the drawn line, frozen at drawing time (00 #8, 02 B2) | D | High | `scripts/review_web.py` (`_pen_filled`), `uengine/imaging/patches.mark_fate_now`, `percival_gui` (`_lumos_marks`, `confirmed_mark_rows`), `albus_redetect.fate_report` | enclosed area on the drawn slice; current fate recomputed from the current detector outputs at gathering (`fate_now`); strokes stored unchanged | `tests/test_marks_m2.py` (loop with a 5-voxel margin: old "not generated", new "overlaps shown candidate #3") | FIXED |
| 15 | Missed lesions cut to 3 slices (02 B4) | D | High | `patches.mark_prism`, `mark_object(prism_native=)`, `extract_marks`, `albus_redetect.build_objects` | growth through the slices inside the drawn footprint (±12 mm), never sideways beyond the outline; gather cache v7 and ALBUS re-detection 1.1 re-extract automatically | `test_marks_m2` (12-slice lesion → 12 slices, neighbour vein excluded; old code 3 slices) | FIXED |
| 16 | Outline = ridge core; full extent never shown (00 #9, 04) | L | Med-High | new `uengine/imaging/refine.py`; reviewer `/api/labels?kind=extent`, dashed cyan outline + menu toggle | ALBUS outline refinement = score_css's grading rule applied to every candidate (dark map, ≤ 5 mm, nearest core), measures + leak warning, derived & hashed outputs, stale → remade | `tests/test_segmentation_m3.py` | FIXED (first version) |
| 17 | Segmentation metrics vs expert masks | F→done | — | new `uengine/imaging/seg_metrics.py` | Dice, IoU, sens/precision, ASSD, HD95, boundary F1 (mm), slice recall, lesion matching, by size; "no reference" when no expert mask | `test_segmentation_m3.TestMetrics` (hand-computed) | FIXED (no expert masks exist yet) |
| 18 | Extent measures to NOX | F | — | `_shadow_rows` | offered to SHADOW as candidate variables (`extent_*`); NOX adopts them only through a confirmed + approved SHADOW hypothesis | code | FIXED (governed path) |
| 19 | File Manager buttons without handlers (01 G2) | D | High | `file_manager_view.js`, `uengine/file_manager.delete_item` | + Folder, Copy, Move, Archive, Restore, Delete, row Rename / Verify / Delete wired to the guarded backend; delete moves to the Trash with typed confirmation | `tests/test_app_screens_m5.py` | FIXED |
| 20 | Settings: fake "Operational" + 0/0/0, placeholders, dead pre-flight toggle, mislabelled backup (01 G3-G6) | D | High | `settings_view.js` | PENSIEVE index (counts, separation check, rebuild), archive counts, training gate, model registry, event log — or "unavailable"; toggle removed; backup relabelled to what it does | `test_app_screens_m5` | FIXED |
| 21 | uScore prototype notices asked to retrain a hidden model; "Unified" wording (01 C3, G10) | D | Medium | `css_app.py`, `css_app.html` | shown only with prototypes switched on; relabelled "uScore prototype" | `test_app_screens_m5` | FIXED |
| 22 | `/api/percival/identity` calls a missing function (01 G1) | D | Low | css_app.py | — (no caller; not changed) | — | OPEN |
| 23 | Activity screen lacks PERCIVAL cycles; quit "Wait for finish" no-op; GET /api/health mutates; JS error overlay (01 G7-G9, C4) | D | Medium | css_app | not in this mission's scope list | — | OPEN |
| 24 | Detector: voxel-count neighbourhoods, SWI-only rule set, `del _dil` crash, mm call matching, axial-only QC (02 B1, B6, B7) | D | Medium-High | detect_css.py, css_common.py | NOT changed: the detector is pinned; each is an ALBUS version change that needs a recorded non-inferiority comparison | — | OPEN (next ALBUS version) |
| 25 | ALBUS forced re-measurement maps (BAND/LAB1/TUBE) from original objects (02 B3) | D | Medium | scripts/albus_measure.py | not changed (detector-side) | — | OPEN |
| 26 | ALBUS tuning cases (M02–M15) possibly among project patients (03 S7) | S | High | — | needs an internal identity check (never logged) | — | OPEN (verification) |
| 27 | LUMOS footprint channel = ALBUS mask; scanner confounding (03 S8, S11) | S | Medium | cnn.py | not changed; ablation planned | — | OPEN |
| 28 | Single expert reader; no κ (03 S14) | L | Medium | — | needs a second expert | — | OPEN (requires expert) |
| 29 | Patient-level separation, blinding, unreviewed ≠ negative, missing indicators, immutable ledgers | — | — | split.py, review_blind, eligibility | re-verified in code | VERIFIED-OK |
| 30 | Expert-mask annotation tool (brush) | F | — | reviewer | not built | — | OPEN (future) |
| 31 | Other fixed-`.tmp` writers (store `_js`, identity registry, notify centre …) | D | Low | various | not changed in this mission (patients/settings fixed) | — | OPEN |
| 32 | Storage migration to OneDrive/SharePoint, Windows port | F | — | — | out of scope by the mission | — | OPEN (future) |

## 2. Files changed / added
Engine: `unified_engine/uengine/percival/validation.py` (new), `meta.py`, `nested.py`; `uengine/imaging/patches.py`, `refine.py` (new),
`seg_metrics.py` (new); `uengine/file_manager.py`; `uengine/health.py`.
App: `app/safe_json.py` (new), `app/keystore.py` (new), `app/css_app.py`, `app/css_app.html`, `app/identity.py`, `app/identity_gui.py`,
`app/percival_gui.py`, `app/percival_view.js`, `app/albus_redetect.py`, `app/file_manager_view.js`, `app/settings_view.js`.
Reviewer: `scripts/review_web.py`, `scripts/review_web.html`.
Tests (new): `test_validation_m1.py` (15), `test_safe_json.py` (12), `test_identity_encryption.py` (7), `test_marks_m2.py` (8),
`test_segmentation_m3.py` (7), `test_app_screens_m5.py` (4). Updated to the new definitions (same invariants): `test_lumos_missed_marks.py`,
`test_albus_redetect.py`, `test_training_progress.py`, `test_lumos_second_look.py`, `check_percival.py`, `check_adversarial_leakage.py`,
`check_app_percival.py`.

## 3. What changes for the user at the next start of the new build
1. The identity vault is encrypted automatically (the old plaintext file goes to the Trash after a verified round-trip; empty the Trash).
   Show and keep the recovery key OFFLINE: needed to open the vault on another Mac.
2. Feature caches (v7) and ALBUS re-detections (1.1) are rebuilt once at the next training / re-detection (longer first run).
3. The training button refuses while a readiness stage fails and says which one.
4. The M1 milestone was already consulted by v001: declare the next milestone before the next cycle (every consultation now uses it).

## 4. Remaining limitations
See the OPEN rows. Most important: the cohort size (16 + ~5 positive patients) makes every estimate unstable; the detector-side fixes wait
for a new ALBUS version with a non-inferiority comparison; segmentation accuracy cannot be reported until expert masks exist.

## 5. Verification evidence (2026-11-28, isolated: temporary HOME / project / volumes root)
- New tests: test_validation_m1 15/15, test_safe_json 12/12, test_identity_encryption 7/7, test_marks_m2 8/8, test_segmentation_m3 7/7,
  test_app_screens_m5 4/4 - all OK.
- Existing checks, all pass: check_percival, check_percival_learning, check_image_ml_integration, check_adversarial_leakage,
  trace_candidate (0 broken steps), check_identity, check_app_percival (app-level training on synthetic studies).
- Isolated unittest suite: every file that could run completed OK, except the items below.
- **Environment problem during the run (not caused by the code):** the external drive's /Volumes/Percival/PERCIVAL_VAULT stopped answering -
  a plain `lstat` of it hangs in the kernel (uninterruptible), so did `lsof` and an `ls` of the folder started ~2 h earlier; the user's
  running app (port 8830) was also in that wait. Files that touch the real drive path or `lsof` could not finish and are NOT verified in
  this run: test_drive_mount, test_phase0_isolation, test_setup_autofix, test_storage_center_rebuild, test_setup_center_redesign (skipped),
  test_phase1c_recovery, test_phase1d_workers, test_phase1e_eject_vault, test_progress_and_setup_finish, test_storage_ux_rebuild (hung),
  test_phase1d_audit (1 error: the app subprocess did not exit within 60 s of SIGINT - its shutdown path calls the transfer/eject checks).
  They must be re-run after the drive is reconnected / the Mac restarted (`tests/run_isolated_suite.py`).
