# HANDOVER - resume here (Percival / cSS pipeline)

Last updated: 2026-11-25 afternoon (5 commits after `0cb269d`: a882c10, dc2e9b6, 829126b, 06ad66d + this note).
Read this first, then CLAUDE.md (project science + history). Do not trust older handover notes over the code
(docs/handover_claude/ and the Gemini handover overstate features - verify in code).

## 1. Where the work lives
- Working folder: `~/percival_code_only` (git worktree; package root `cSS_pipeline_v4.13/`). Work and commit HERE.
- Branches: main/default on GitHub = `claude/css-detection-audit-2esnbb`; working branch here = `claude/phase0-safety`.
  Both point to the same commit after the 2026-11-25 fast-forward. After every commit push BOTH:
  `git push origin claude/phase0-safety && git push origin HEAD:refs/heads/claude/css-detection-audit-2esnbb`
  (fast-forward only - if main moved, stop and ask; never force-push).
- Remote: github.com/YourFavLittyGeek/cSS. Release tag: `percival-v5.25-dev-20261125`.
- `~/Projects/cSS` = another worktree with main checked out at an OLD commit (7936c16) - not touched, the user may
  ask to update it (`git -C ~/Projects/cSS merge --ff-only`). `~/Projects/cSS-unified-score-ml` shares the worktree
  metadata with this folder - NEVER modify that folder.

## 2. Hard rules (from the user, still in force)
- Never kill the user's reviewer sessions (ports 8765-8773) or the app (8800 production, 8830 dev, 8831 demo).
- Tests ONLY isolated: `~/miniforge3/envs/css/bin/python tests/run_isolated_suite.py` (temp HOME / CSS_BASE /
  volumes root, write-refusing guard). Never run app tests against the live project. If the live app is running
  while the suite runs, "live fingerprints changed" can appear from the APP's own writes - rerun with the app closed.
- Stage files by explicit name; never `git add -A`. Never commit `.claude/`, `docs/handover_claude/`,
  `docs/engineering/PHASE1_TRANSFER_ENGINE_PLAN.md`, `docs/engineering/PHASE3A_GROUND_TRUTH_PLAN.md`.
- No reset / clean / rebase / force-push. No real-data training, no manufactured labels, no model promotion.
- Privacy: study codes only, never MRN / names / accession in commits, logs or external requests.
- Confirm before destructive actions; prefer move-to-Trash over delete; check `pgrep -fl "ditto|rsync|css_app"`
  before moving the user's folders (a folder was once moved mid-backup).
- The user writes quickly with typos; answer in plain language, short, with numbered steps; they want permanent
  fixes inside the app (no Terminal steps for them).

## 3. User's machine / data (as of 2026-11-25)
- Mac M3 Pro 36 GB, FreeSurfer 8.2.0 at /Applications/freesurfer/8.2.0, licence ~/Downloads/license.txt,
  conda env `css` (~/miniforge3/envs/css), dcm2niix /opt/homebrew/bin/dcm2niix. ~66 GB free on the Mac.
- External drive `/Volumes/Percival` (exFAT): `PERCIVAL_VAULT` (empty vault, created by the app), source data
  folders `AI Training cSS`, `AI Training CAA`, `Dicom` (never touch), `Percival_Import_Template.xlsx`.
- Dev app project: `~/Percival_project` (fresh, no studies; its setup state is reverted to first launch by the
  0cb269d fix on next start). Demo: `~/Percival_demo` (synthetic SYN001-006, reviewer may run on 8765).
- In the Trash (user may empty): previous session project, `~/Percival_project_old_20261124`, the three drive
  backups (old identifiers purged at the user's request). `~/css_project`, `~/Percival_V1_unused_setup` remain.
- User has 70 unique-patient MRIs to import; plan: test fraction 0.25, finalized studies only, auto-cycles OFF.

## 4. Build / release
- App zip: `bash tools/build_percival_dev_app.sh ~/PERCIVAL_releases` (committed files only) ->
  `Percival_v5.25-dev_<sha>.zip` + `_BUILD_INFO.txt`. Current: `Percival_v5.25-dev_9e0ae13.zip` (audit fixes: grade-0 repair, bands, one AI opinion; sha256 79b90a138d25d6f81206537cd1b942501271762450cbfffa1fa9c5c44ea9e53b). Before: `Percival_v5.25-dev_b543b6a.zip` (missed-cSS loop steps 1-4 + second look + Save fix; sha256 96a3c829c110e67eeb64774ef05c6101e8457abe4dfbf7eed68b653fb5b36671). Before: `Percival_v5.25-dev_6dda504.zip` (LUMOS learns from missed marks; sha256 8bd20cfe7706871085b7add4b28cfc50827150913ee10ba8f58fe5b1c284d803). Before: `Percival_v5.25-dev_01e95bc.zip`
  (sha256 d3ba09edbb66fd10520bd809c779832c5044bd06cb060696b910290348236e6c).
  NEWER: `Percival_v5.25-dev_1a0bbcc.zip` (sha256 4418b70780927a230cafb0242f87efcb753ba3deb8bffd3f88ede0e58e24f13a; incl. audit items 1-8) -
  not yet installed by the user at the time of writing.
- Install for the user: quit app, unzip, drag "Percival Dev.app" to Applications (Replace), open, "Use Percival_project".
- Launcher: app/mac_percival/launcher.sh (project path in ~/Library/Application Support/Percival Dev/project_path,
  exports CSS_BASE and PERCIVAL_APP_BUNDLE). Server: app/css_app.py (ThreadingHTTPServer, pywebview window).

## 5. What the last sessions changed (commits on top of the Stage 1-9 mission)
- ace3bfc: Data Vault (<drive>/PERCIVAL_VAULT) created automatically (setup save/finish, start-up, every 30 s);
  FreeSurfer found automatically (setup_gui.find_freesurfer, PERCIVAL_FS_SEARCH in tests).
- 88effaf: setup Finish + Import run as background jobs (app/progress_jobs.py, GET /api/job?id=, app/progress_view.js
  window: bar, step k/N, label, elapsed, remaining, "Continue in background" pill, notification centre). Root cause
  of the "frozen after Finish": nav gate used window.SETUP_LIFECYCLE that was never refreshed. Step 6 readiness runs
  missing checks live (_setup_fill_checks); BLOCKED -> 🔒 LOCKED with "Why locked". Failed import removes its copies.
  New project folder chosen in setup -> automatic restart (/api/setup/restart).
- 57c4a58: app/source_cleanup.py - temporary DICOM copies (app_data/import_src/<key>, raw/<key>/<MOD>/_dicom,
  staging) deleted after VERIFIED completion (Settings > Mac storage: after_processing default / keep_days / keep);
  re-runs reuse raw/*.nii.gz. Import space check (15 GB reserve), no new run below 20 GB free (CUR["disk_wait"]).
  "Delete files" for failed/stopped studies (opens Remove/Purge dialog).
- 0cb269d: setup wizard skipped on new projects because the empty vault skeleton / empty pensieve.db counted as an
  existing installation - now only real content counts; wrongly auto-completed empty projects revert once.
- Tests: tests/test_progress_and_setup_finish.py (19), tests/test_setup_autofix.py (9). Isolated suite 461 / 0 fail.

## 5b. Session 2026-11-25 afternoon (user's requests: Transfer Center, Pensieve, viewer timer, retry / methods)
- a882c10 Transfer Center: worker pool kept the Vault path of its start (empty) -> "not connected"; set_vault() now follows
  SET. exFAT (user's drive) archived with a GUARDED commit (locked check-then-rename, never overwrites; CSS_EXFAT_STRICT=1 =
  old refusal). Live copy progress + "On this Mac" card. Sidebar / Transfer Center label "Pensieve" (LABELS ONLY - the user
  asked not to rename internals: the existing PENSIEVE memory index keeps its name).
- dc2e9b6 Reviewer: after the final save -> next patient immediately / after N typed seconds / manual (keys autopt/autosec).
- 829126b app/pensieve_move.py: after the final review (+5 min) the study's processed files (raw/<code>/, data/, synthseg/,
  work/, logs/ <code>_*, subjects/<code>/) go to <Pensieve>/studies/<code>/<version>/ (journaled job, SHA-256 read-back,
  only verified files deleted on the Mac); review/ copied AND kept; marker review/<code>_pensieve.json. Restore on open in
  the reviewer and before a re-run (missing files only, verified). User-approved narrow exception to the Phase 0 raw/data
  protection (RestorePolicy). Settings card "Pensieve · after the review" (move default / copy / off, wait N min).
  Studies reviewed BEFORE the first start of this build never move by themselves (SET pensieve_since; button in Settings).
  Anything that reads images of a moved study other than the reviewer / a re-run (training feature extraction, exports
  of images) needs the study brought back first - not yet automatic.
- 06ad66d app/pathway_rules.py (requirements, ✓/✗/○/🚫 in every method list, Retry with method choice for every failure,
  T1-mismatch rule -> SWI-only), prep_anat.sh honours a chosen method over an old recon, cohort.py skips 1-slice localizers.
  Study-026 was processed on a 1-slice localizer (512x512x1) - its results are invalid: re-import / re-run it after install.
- docs/engineering/PATHWAY_REQUIREMENTS.md (sources). Isolated suite 499 / 0.

- Evening: reviewer 6x faster + next study preloaded; Pensieve move crash-safe (marker 'deleting' before deletes), never
  moves a study in use; drive auto-mount + Mount button (drive_mount.py). Full audit + plan of the remaining file-management
  problems: docs/engineering/FILE_MANAGEMENT_AUDIT_2026-11-25.md (items 1-8 DONE on the user's go; 9-10 open). Since ~12:06 the live app has moved
  Study-039..046 to Pensieve after their final reviews (verified, as designed).

- Late evening: ca4bcc2 role change rebuilds the effective calls (review/ID_calls.csv was empty for every study read before
  the user became expert at 14:04; their own calls files were always complete - audit of 35 studies: calls file = events =
  review log). Audit items 9-10 done (checked_copy.py for import copy + Vault backup; low-space offer + "Free Mac space").
  Reviewer shows name · MRN / accession bottom right under the reviewer name (Standard, vault readable; asked live from the
  app via /api/viewer_ident, CSS_APP_PORT); Incognito / locked = study code; snapshots never carry identifiers (top-left
  uses the code too). Training state for the user: expert role set; local learning switch still off; test group (split v001,
  20 %, 9 patients) can reach at most 4 cSS-positive with the current patients - more import needed (user's decision on a
  25 % split version).
- The user ran an OLD reviewer (port 8767, started 11:04) next to the current one: never kill it; ask them to close the tab.

- Night 2026-11-25 (user decisions): 7291abc Review menu (all not yet reviewed / choose cohorts checklist), viewer identity line
  never shows the previous patient + red bar in reviewer windows started before an update (the user's "MRN does not change" was
  most likely such an old window - 3 were open; app answers were verified correct per study, hashed). 3afe20e ARCHITECTURE:
  ALBUS -> NOX + LUMOS -> PERCIVAL (only combiner); Unified + Fusion components REMOVED; NOX = 30 measurements
  (docs/percival_app/NOX_FEATURES.md); model["modules"] = per-module loop (NOX / LUMOS adopted only when improved);
  learning gather brings Pensieve studies back (ensure_local hook) and caches inputs (percival/cache v5). Hidden prototype
  screens (Training, uScore scorer, Stage-1, Image ML prototype) still use old names - hidden, not part of the architecture.
  Isolated checks: run old check_*.py through a wrapper that calls tests/_isolation.activate() first (they do not isolate
  themselves); check_percival / _learning / image_ml_integration / adversarial_leakage / trace_candidate pass.

- 01e95bc missed-cSS marks: NONE of the user's marks was ever saved (page sent the plane index, server wants the name; plus drafts
  dropped silently). Fixed + regression test. The user must re-mark missed cSS in the studies where they drew them (they are lost).
- LUMOS learns from the missed-cSS marks (user decision): uengine/imaging/patches.extract_marks (same surface-aligned extractor;
  object = dark voxels INSIDE the drawing - detector dark map work/ID_dark.nii.gz first, else < -3 robust SD of the local brain;
  growing beyond the drawing leaked into veins on the phantom); percival_gui _mark_maps / gather_marks / _lumos_marks (eligible
  expert, development partition, not on a shown candidate), cache v6 (missed csv in the key); meta.component_oof compares LUMOS
  with / without the marks on the same folds and uses them only when the candidate log loss is not worse (decision in
  model.data.lumos_missed_marks + modules.LUMOS); training folds only, never held-out / test patients; nested gets the decision.
  docs/percival_app/LUMOS_MISSED_MARKS.md, tests/test_lumos_missed_marks.py.
- LUMOS second look (built, INACTIVE until >= 50 marks / 10 patients / 70 % held-out marks recognised): second_look.py, app
  PG.second_look (background scan, percival/second_look/ID.json+npz), css_app /api/second_look (blind-gated), reviewer card +
  /api/lumos_reject (expert rejects = LUMOS 'not cSS' examples), Model Center line. Also fixed: marks with a plane NAME did not
  draw / 'go to' in the viewer. tests/test_lumos_second_look.py. User started re-marking (026: 2, 027: 1 saved OK).
- Steps 1-4 (2026-11-26): ALBUS re-detection of marks (app/albus_redetect.py + scripts/albus_measure.py: PINNED detector executed with
  forced objects in memory on a disposable APFS-clone copy; detect_css.py NOT changed), reviewer confirms ALBUS's orange outline
  (/api/albus_marks, /api/albus_confirm, review/ID_missed_confirm_by_*.csv), NOX learns from confirmed objects (origin AUC <= 0.75 +
  paired no-harm rule meta.no_harm, also for LUMOS), PERCIVAL scores marks without ALBUS (meta.NoAlbus; test.missed_lesions separate), Model
  Center "Where ALBUS loses cSS" (fate_report). Viewer: Save button fixed (onclick took the event), pen clipped to the image.
  tests/test_albus_redetect.py (phantom end-to-end: project untouched). NOTE: detect_css.py fails on uengine synthetic_images studies
  (NameError _dil at line 647) - pre-existing, not touched; phantom_v4 studies run.
- 2026-11-26 audit (docs/AUDIT_pipeline_2026-11-26.md, from branch claude/pensive-brahmagupta-09dlhu) VERIFIED first
  (docs/AUDIT_pipeline_2026-11-26_VERIFICATION.md). Found + fixed a bigger bug: final save rebuilt the effective calls before the review
  counted as complete -> 13 patients showed grade 0 in Results / cSS_results.xlsx (startup repair rebuilds + re-scores, Pensieve studies
  brought back). Also: grade from the model's bands (total / total_upper, needs_review), one AI opinion (PERCIVAL, rule meter fallback),
  legacy albus.py bugs. vault.py / pensieve.py are LIVE - do not delete (audit A4 was wrong there).
- Balanced locked test group (PERCIVAL > System > Locked test group; split.balance, new split version, hash order, never trained-on
  patients, >= 8 dev per class) + test patients with expert missed marks count 'with cSS' (train_cycle test_css_patients). User's
  project: 9 test = 5 with cSS (incl. 040 via marks) + 4 without -> balance adds 1 without cSS. User trains in batches of 50.

## 6. Open items / next steps (ask the user before starting)
1. User reported the app WINDOW froze after "Use Percival_project" (server answered, page idle, no JS error in
   Chrome or JavaScriptCore). Not reproduced; ask what the screen shows on the 0cb269d build. Idea: a page
   heartbeat + "not responding - reload" overlay; log requests per minute server-side.
2. (done late evening 2026-11-25: low-space offer, Settings › Pensieve.)
3. Known baseline test failures in tests/run_uscore_tests.sh: check_app_identity / check_app_import_v518 (headless
   Chrome timeouts), check_app_setup (FileExistsError in its own temp setup), + processing_manager, write_guard,
   local_only, ui_poll, app_review_qc, app_identity, app_training, app_add_layout, study_admin (pre-existing).
4. Setup wizard keys dcm2niix_path / threads are not saved by setup_post save (fallbacks work).
5. Import "same_exam" rows are excluded silently (only a note) - could be surfaced more clearly.
6. Image-model training on the user's 70 studies: follow docs (Training Configuration), never automatic.
