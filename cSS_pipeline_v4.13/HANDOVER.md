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
  `Percival_v5.25-dev_<sha>.zip` + `_BUILD_INFO.txt`. Current: `Percival_v5.25-dev_0cb269d.zip`
  (sha256 d3ba09edbb66fd10520bd809c779832c5044bd06cb060696b910290348236e6c).
  NEWER: `Percival_v5.25-dev_a722e87.zip` (sha256 a7a11d95ac43a448b61031918d10ee37f3136efb3e6772687711cb78151bc812) -
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

## 6. Open items / next steps (ask the user before starting)
1. User reported the app WINDOW froze after "Use Percival_project" (server answered, page idle, no JS error in
   Chrome or JavaScriptCore). Not reproduced; ask what the screen shows on the 0cb269d build. Idea: a page
   heartbeat + "not responding - reload" overlay; log requests per minute server-side.
2. Proposed, not built: when the Mac drops below ~50 GB, offer (or automatically, user to decide) to archive
   completed + reviewed studies to the Data Vault with transparent restore on open.
3. Known baseline test failures in tests/run_uscore_tests.sh: check_app_identity / check_app_import_v518 (headless
   Chrome timeouts), check_app_setup (FileExistsError in its own temp setup), + processing_manager, write_guard,
   local_only, ui_poll, app_review_qc, app_identity, app_training, app_add_layout, study_admin (pre-existing).
4. Setup wizard keys dcm2niix_path / threads are not saved by setup_post save (fallbacks work).
5. Import "same_exam" rows are excluded silently (only a note) - could be surfaced more clearly.
6. Image-model training on the user's 70 studies: follow docs (Training Configuration), never automatic.
