# HANDOVER.md - Unified Score ML engine, shadow-mode integration (2026-11-20)

Start with INTEGRATION_REPORT.md, then TEST_REPORT.md and KNOWN_LIMITATIONS.md.

## 1. Location
- Worktree `/Users/tarabeah.selim/Projects/cSS-unified-score-ml`, branch `feature/unified-score-ml-integration`.
- Base: `origin/experimental/unified-gui` @ `6f0ca44` (Percival v5.14.2-rc5). No upstream; nothing pushed, merged, tagged or deployed.
- Commits: `faea197` engine + Shadow ML screen; `bac5db9` tests (counts in its message predate counting: see TEST_REPORT);
  `812bbee` docs, runner, static check, port fidelity, screenshots; plus the handover commit (two test-harness fixes + this document).
- Diff vs `6f0ca44`: app changes are `app/css_app.py` (+33 lines) and `app/css_app.html` (small); new `app/shadow_engine_gui.py`,
  `app/shadow_view.js`, `unified_engine/`, `tests/check_app_shadow_engine.py`, `docs/unified_engine/`; two existing tests changed
  (`tests/check_export_safety.py`, `tests/check_write_guard.py`, test-harness only). `scripts/` and `unified_score/` unchanged.

## 2. Test results (executed)
| suite | result |
|---|---|
| `unified_engine/run_tests.sh` | 0 failing stages: pinned sources ok, static check 51 files / 0 findings, 119 / 119 unit tests, 35 / 35 integration |
| `tests/check_app_shadow_engine.py --shots` | 36 / 36 |
| existing suite `tests/run_uscore_tests.sh` + the 2 scripts after the stop | 412 PASS, 0 FAIL; `check_ui_poll` not runnable (no Node / npm) |

## 3. The three existing-suite issues
1. **check_export_safety (2 FAIL) - test-harness problem.** The app returned the canonical path `/private/var/...`; the test
   compared it to `/var/...` (a symlink on macOS). The app behaviour is correct (real-path checking is a safety feature). Fix: the test
   canonicalises its temporary HOME / base. The assertion is unchanged. Fails identically on the unmodified base, so not a regression.
2. **check_write_guard (timeout) - test-harness problem.** The launcher's refusal notice is a modal osascript dialog; it blocks the test
   in a logged-in session. Fix: only that notification is replaced with a stderr echo inside the test; the test now also asserts the
   notice was triggered (stricter). Launcher and guard code unchanged.
3. **check_ui_poll - environment.** Requires Node / npm + Playwright; not installed. Not run; not changed.

## 4. Protection evidence (checked 2026-11-20 17:21 EST)
- Original checkout `~/Projects/cSS`: `claude/css-detection-audit-2esnbb` @ `7936c16`, only the untracked `.DS_Store` (pre-existing).
  Changes there since the session start: `.git/` (shared object store of the worktree - expected), `.claude/settings.local.json`
  (Claude Code permissions), `.DS_Store` (Finder).
- `origin/experimental/unified-gui` still `6f0ca44`.
- Installed apps `/Applications/cSS Experimental.app` (v5.14.2-rc3), `Percival.app` (rc4), `Percival-1.app` (rc5), `cSS Pipeline.app`:
  0 files changed since the session start.
- `~/css_project`: one entry changed since the session start, a Finder `.DS_Store`.
- `~/cSS_experimental`: many changes in `app_data/staging`, `raw/`, `runs/` - written by the user's own Percival app
  (pid 5889, `CSS_BASE=~/cSS_experimental`, port 8810), which was processing studies. Not touched by this work.
- RC3 = the installed rc3 app above; no separate Signal Laboratory or engineered-app location was identified on disk beyond the
  installed apps and checkouts listed here.

## 5. Data access - exact account
- No MRI image, mask, label value, candidate table, feature table, prediction or per-study metric was opened at any time.
- No training on clinical data. Nothing was sent to any service other than this assistant session.
- Read-only, early in the session (missions 1-2, repository inspection): directory listings of `~/css_project` and
  `~/cSS_experimental` (folder names, including study folder codes), existence checks of label / grade files (not opened), version
  files, `START_HERE.txt`, source code, and `tools/m0_metadata_check.py` (prints only file existence, JSON key names and per-role
  study COUNTS from the split manifest). During this handover: modification times and per-folder change counts (folder names such as
  study codes appeared in that output).
- The existing app suite (`check_uscore_pipeline`) reads the repository-tracked `unified_score/cohort_manifest_RECONCILED.csv`
  (study codes and split roles) and prints counts only. That is pre-existing behaviour of the repository; the new engine never reads it.

## 6. Commands
```zsh
cd /Users/tarabeah.selim/Projects/cSS-unified-score-ml/cSS_pipeline_v4.13 && conda activate css
# launch (synthetic base only)
python unified_engine/run_engine.py demo-base /tmp/uengine_demo_base --n 6
CSS_BASE=/tmp/uengine_demo_base CSS_EXPERIMENTAL=1 PYTHONPATH=app/guard python app/css_app.py --port 8820   # open http://127.0.0.1:8820/#shadow
# tests
bash unified_engine/run_tests.sh /tmp/uengine_tests.log
python tests/check_app_shadow_engine.py --shots /tmp/shots
bash tests/run_uscore_tests.sh            # stops at check_ui_poll without npm; then:
python3 tests/check_selection_notifications.py && python3 tests/check_app_unified.py
git checkout -- unified_score/output/      # the existing suite rewrites 3 tracked files there
```

## 7. Recommendation
Ready for human code review; no blocking defect known. Review focus: the `css_app.py` routes / after-done hook, the registry apply
policy (synthetic marker + SYN prefix), and the two test-harness fixes. Not ready for clinical use: no clinically trained model exists.

## 8. Percival application build (Phases A-G, after the Stage 1 handover)
Commits on this branch: `1f981ba` Phase B + v5.16 identification · `2a9706e` Phase C lineage · `787e99d` reviewer Quick Add / labels ·
`d301a61` Training screen · `6804f23` batch Add layout · `3640081` setup wizard · Phase G commit (setup readiness fix, guide, audit).
Documents: `docs/percival_app/` - PHASE_A_AUDIT, PHASE_B_REPORT, IDENTITY_SCHEMA_AND_MIGRATION, IMPORT_WORKFLOW, INSTALL_AND_USER_GUIDE,
PHASE_G_GUI_AUDIT (screen-by-screen test coverage, remaining defects), screenshots/.
Not done without approval: push / merge / release; migrating a clinical project; replacing model weights; clinical training.
