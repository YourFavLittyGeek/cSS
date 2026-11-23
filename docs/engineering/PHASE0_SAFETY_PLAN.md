# PERCIVAL Phase 0 — safety plan and record

Scope approved by the user on 2026-11-23: scientific integrity, destructive-operation protection,
test isolation, safety regression tests. **Not in scope**: Phase 1 (transfer-engine job model, queue,
resume, journal-driven eject states), File Manager / Sync / Transfer Center / Settings redesign,
anything touching the physical Vault.

## 1. Repository state before Phase 0

- Branch `feature/v5.25-final-master-delivery`, HEAD `65b0e49dd20a9eb0c2a1ea892c5d8fdbcd10426b`.
- Working tree: only untracked `docs/handover_claude/` (5 files). No stash. Backup refs
  `refs/backup/handover-2026-11-21`, `refs/backup/v523-engine`, `refs/backup/v523-final` preserved.
- `claude/css-detection-audit-2esnbb` is checked out in another worktree (`~/Projects/cSS`) and was not
  touched; no branch was merged, reset, rebased or force-pushed.
- Phase 0 branch: `claude/phase0-safety`, created from `65b0e49` with `git switch -c` (non-destructive).
- **Shared worktree admin (found at commit review):** this checkout is a linked worktree of `~/Projects/cSS/.git`
  whose admin entry `worktrees/cSS-unified-score-ml` is registered to a *different* directory,
  `~/Projects/cSS-unified-score-ml`; both directories' `.git` files point at that one entry, so they share one HEAD
  and one index. The `git switch -c` above therefore also moved the HEAD seen from `~/Projects/cSS-unified-score-ml`
  (from `feature/v5.25-final-master-delivery` to `claude/phase0-safety`, same commit `65b0e49`; no file in that
  directory changed). That directory was already far from HEAD before Phase 0 (read-only status: 99 deleted,
  29 modified, 8 untracked - a stale 2026-11-22 checkout); any git write run inside it would record that state on the
  shared branch. Not changed in Phase 0; needs a user decision.
- The handover documents stay untracked and are not committed as a specification
  (see `HANDOVER_VERIFICATION_RECORD.md`).

## 2. Live-settings preservation report

Backup (read-only copies, `cp -p`, SHA-256 verified):
`~/PERCIVAL_SAFETY_BACKUPS/phase0_live_state_20261123T124450/` (settings.json, setup_state.json,
setup_done.json, setup_report.json, wizard_state.json, patients.json, `~/.percival_vault_config.json`,
`~/.percival_local_journal.db`, Application Support `project_path` and `setup.log`, plus `SHA256SUMS`).

What the 12:33 test run wrote (established from mtimes + the code paths the tests execute):

| File | Written at | What changed | Prior value |
|---|---|---|---|
| `app_data/settings.json` | 12:33:09 | `setup_post("save_config")` set `candidate_redetection=True`, `candidate_calling=True` and **forced `rerun_mode="auto"`** | candidate_* were already `True` (identical in `previous_config`) → no-op. `rerun_mode` prior value cannot be proven (no earlier backup); every wizard/setup save forces `auto`, the code default is `choose` |
| `app_data/setup_state.json` | 12:33:09 | `validated_config` re-saved, `last_validation_time` / `updated_at` | values otherwise identical to `previous_config` |
| `~/Library/Application Support/Percival Dev/project_path` | 12:33:11 | **points at a deleted temp dir** `/var/folders/…/percival_fm_test_dn92d4hn/migrated_workspace` (written by `working_dir_migration` under `test_storage_and_file_manager`) | unknown; current effective base is `~/Percival_project` because `_resolve_project_base` ignores a non-existent path |
| `~/.percival_vault_config.json` | 12:33:14 | **points at a deleted temp vault** `/var/folders/…/pvault_test_32d6xqfk/external_ssd/VAULT_ALPHA` (written by `test_vault`) | unknown; `vault.py` ignores a non-existent saved path |
| `~/.percival_local_journal.db` | 12:33:13 | written by `test_twenty_failure_scenarios` | unknown |
| `patients.json`, `pensieve.db`, studies, MRI | — | **not modified** | — |

Approved change (only this one): `settings.json` `rerun_mode`: `"auto"` → `"choose"`. Applied after the
backup was verified, with the app not running (only a `review_web.py` session for `~/Percival_demo` on
port 8765, left untouched). No other live setting is modified.

**Needs a user decision (not changed):** `project_path` and `~/.percival_vault_config.json` contain test
paths. They are currently harmless (both readers skip missing paths), but if a directory with that name
ever existed again the app would open it. Proposed restore: `project_path` →
`~/Percival_project`; vault config → `/Volumes/Percival/PERCIVAL_VAULT` (or remove).

## 3. Implementation plan (by file and function)

### A. Scientific integrity
- `app/percival_gui.py::score_study` — the ALBUS/LUMOS/NOX/CORE block runs only when
  `SET["features"]["experimental_core"]` is true (default **false**). Its output goes **only** to
  `s["experimental_core"] = {score, band, status, uncertainty, label: "EXPERIMENTAL – not validated"}`;
  `percival_score / band / status` from the trained model are never written by it.
- Same function — study score: if no candidate has a valid trained score, the study is
  `status="unassessable"` with `total/L/R = None` and a reason; `score_css.py --accept-ids none` is **not**
  run (that records 0). Scored studies get `status="scored"`. Ledger/record schema otherwise unchanged.
- `app/percival_gui.py::score_study_unified` — refuses unless `experimental_core` is on; output labelled
  experimental.
- Training labels (`label_summary`) already map only explicit expert calls to y∈{0,1} and errors to "no
  labels"; locked in by regression tests, not changed.

### B. Destructive-operation protection
- **New** `unified_engine/uengine/safety.py` — one policy for every server-side file operation:
  `validate_study_code` (`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`), `canon` (realpath), `volumes_root()`
  (`PERCIVAL_VOLUMES_ROOT` override, default `/Volumes`), `PathPolicy(base, vault_root)` with
  `check_source / check_write_target / check_delete`: everything must resolve (symlinks followed) inside
  the project base or the configured Vault; **protected** (never deleted, moved, renamed, overwritten or
  written into): `raw/`, `data/`, `app_data/import_src/`, `review/` (reader calls, missed lesions, finals,
  review logs, call ledger, call policy), `labels/`, `historical/`, `percival/` (trained model store),
  `private/`, `subjects/`-level and `app_data/` top-level files (settings, pensieve.db, identity),
  Vault `original_mri/`, `Dicom/`, `Pensieve|PENSIEVE/`, `manifest/` and the sibling `Dicom/` of the
  Vault mount; roots and first-level directories (`work/`, `studies/`, …) can never be deleted whole.
- `uengine/file_manager.py` — `delete_item`, `copy_item`, `move_item`, `rename_item`,
  `create_directory`, `archive_entry`, `restore_entry`, `clean_staging`, `delete_study`, `stage_study`,
  `archive_study` go through the policy and the study-code validator. `delete_study` no longer removes
  anything under `review/` (reader records preserved; derived files are left for the pipeline to
  regenerate). Study-file matching uses a code boundary (`M1` no longer matches `M10`).
  `conflict_mode="replace"` copies to a staging name, verifies, then swaps; the old target is removed only
  after the new copy is verified.
- `uengine/cleaning_manager.py` — `delete_by_study` validates the code; `purge_quarantine` requires an
  explicit `purge_all=True` (no implicit "all" on a missing id) and a contained `quarantine_id`;
  `restore_quarantine` refuses traversal ids, protected / outside targets and existing targets.
- `uengine/study_workspace_manager.py::clean_eligible_workspace` — the API can no longer pass `force`
  (server ignores it); the workspace path from the ledger must pass the policy.
- `uengine/unified_transfer_engine.py` — streaming copy and APFS-clone path verify the `.part` file
  **before** `os.replace`; on mismatch only the `.part` is removed and an existing destination is kept.
  Move deletes only source files verified in this run (never `rmtree` of the source tree).
- `uengine/storage/sync_manager.py` — `execute_sync` treats the client list only as a selection: it
  recomputes the preview server-side, refuses unknown items, `can_proceed=False`, conflicts, or paths
  outside `work/<id>` → `studies/<id>`; reports failures (`ok=False`). `study_ids` accepts a comma string.
- `uengine/storage/eject_manager.py` — normal eject runs `check_ejection_safety` first; force eject
  needs a server-issued single-use token (120 s, bound to the mount point, only after a refused normal
  unmount) **and** the volume name typed by the user; mount point must be a real mount under
  `volumes_root()`; `diskutil` runner injectable; refused outright under test isolation.
- `app/css_app.py` — dispatchers validate study codes; `force` removed from `workspace/clean`; eject
  passes token/confirmation; `storage/prune` days ≥ 1; `/api/log` code validated (traversal); static
  `.js` handler confined to `app/`; `files/verify` path checked by the policy.
- `app/css_app.html` (sidebar emergency eject) and `app/settings_view.js` (quarantine purge-all) — the
  minimum JS change needed for the server-side confirmation. No other UI change.

### C. Test isolation
- **New** `tests/_isolation.py::activate()` — before any application import: temporary `HOME`,
  `CSS_BASE`, `PERCIVAL_VOLUMES_ROOT` (empty temp dir), `PERCIVAL_TEST_ISOLATION=1`, no bytecode writes;
  installs an audit hook that **refuses** any write-type operation (open-for-write, rename/replace,
  remove, rmdir, mkdir, rmtree, chmod, utime, symlink…) inside the real home (looked up with `pwd`,
  not `$HOME`) except the code checkout, anything under `/Volumes`, and refuses to start `diskutil` or
  any program pointed at the live project / `/Volumes`.
- **New** `tests/test_00_isolation_bootstrap.py` — sorts first in discovery so the plain documented
  command is isolated too; every `tests/test_*.py` also calls `activate()` (idempotent) so single-file
  runs are safe.
- **New** `tests/run_isolated_suite.py` — fingerprints the live files (SHA-256 + mtime) before and after
  the run and fails if anything changed; prints the evidence.
- `app/css_app.py` — import-time side effects (`_ensure_pipeline_installed`, `PM.recover_all`,
  `PM.recover_imports`, `reconcile_studies_on_disk`) run only when started as a program (`__main__`), so
  production start-up order is unchanged; importing the module (tests, tools) has no side effects.
  When imported under a test (or `PERCIVAL_TEST_ISOLATION=1`), it refuses to bind to a base inside the
  real home or under `/Volumes`.
- Hard-coded `/Volumes` discovery in vault resolution (`storage_paths`, `vault`, `file_manager`,
  `setup_state_manager`, `study_workspace_manager`) uses `volumes_root()`.

### D. Regression-test matrix (`tests/test_phase0_safety.py`, `tests/test_phase0_isolation.py`)

| # | Case | Expected |
|---|---|---|
| S1 | empty study code (delete_study, clean_staging, delete_by_study, stage/archive, API) | refused, nothing removed |
| S2 | invalid codes (`..`, `M01/../x`, `*`, `M0?`, spaces, 65 chars) | refused |
| S3 | path traversal (`delete_item`, copy dst, `/api/log`, quarantine id, static `.js`) | refused |
| S4 | delete raw MRI (`raw/`, `data/`, `import_src/`, Vault `original_mri/`, `Dicom/`) | refused, files intact |
| S5 | delete reader calls / missed / final / call ledger / call policy | refused, files intact; delete_study keeps review/ |
| S6 | Vault-wide deletion (vault root, `studies/`, `archive/`, `processed_mri/`) | refused |
| S7 | sync with client-forged source/destination | refused, nothing copied |
| S8 | client-supplied force (workspace clean, eject) | ignored / refused without token + typed name |
| S9 | checksum failure during copy, replace and clone | existing destination byte-identical, `.part` removed |
| S10 | move of a tree containing an uncopied dotfile | dotfile still at source |
| S11 | CORE returns nothing while a trained score exists | trained `percival_score` unchanged |
| S12 | no valid trained score in a study | `status="unassessable"`, total `None`, `score_css` not run |
| S13 | unreviewed / unsure / errored labels | never `y=0` |
| S14 | experimental layer default | off; when on, output only under `experimental_core` |
| I1 | `HOME`, `CSS_BASE`, `expanduser("~")` | temp, not the real home |
| I2 | `css_app.B` after import | inside the temp tree |
| I3 | write into the real home / `/Volumes` | `PermissionError` from the guard (probe path has a non-existent parent, so a broken guard still cannot create anything) |
| I4 | starting `diskutil` | refused |
| I5 | live-file fingerprints before/after the full suite | identical |

## 4. Risks and dependencies
- The eject safety check still reads an empty job table (Phase 1 fix); Phase 0 makes force eject
  impossible without explicit confirmation but cannot make "READY" truthful.
- Transfer-engine resume (size-only skip) stays unreachable; documented for Phase 1.
- Protecting `review/` and `data/` blocks generic File Manager edits there by design; the pipeline and
  reviewer still write them through their own code paths (not through FileManager).
- Older `tests/check_*.py` scripts are not part of the unittest suite; those that import `css_app`
  already use a temp HOME. They are not run in Phase 0.
- No real-data or hardware test is possible in Phase 0 (by instruction); all tests use synthetic files.

## 5. Status (2026-11-23, end of Phase 0)

### Completed and verified
- A (scientific integrity), B (destructive-operation protection), C (test isolation), D (regression matrix S1-S14,
  I1-I5) implemented as planned in §3, on branch `claude/phase0-safety` (uncommitted, awaiting the user's review).
- Live change: `settings.json` `rerun_mode` `auto` → `choose` (diff: exactly that one line).
- `python3 tests/run_isolated_suite.py`: 147 tests OK (114 existing + 33 new), live fingerprints changed 0, writes
  refused by the guard 0 → ISOLATION RESULT: PASS.
- Plain documented command `python3 -m unittest discover -s tests -p "test_*.py"`: 147 OK; 21 live fingerprints taken
  independently from the shell before/after are identical.
- `tests/check_gui_js_syntax.py`: ALL PASS (37).
- Production start-up smoke test (`app/css_app.py --no-window` on a temporary HOME / CSS_BASE): `/`, `/api/state`,
  static JS 200; `/api/log?code=../../x` 400; empty-code delete and `/etc/hosts` delete refused over HTTP; start-up
  side effects still run when started as a program; live fingerprints unchanged afterwards.
- The new safety tests run against the untouched `65b0e49` code (extracted with `git archive`): 47 failures +
  29 errors (S1-S12, S14 detect the original defects; S13 passes there too - it locks in label behaviour that was
  already correct).
- Deliberate changes to existing tests: every `tests/test_*.py` calls `_isolation.activate()` first;
  `test_storage_and_file_manager` 04/05 now copy/move inside `work/` (copying into `review/` and moving out of
  `data/` is refused by design) and test 05 additionally asserts that moving an original is refused.

### Implementation notes (differences from the plan)
- Test guard: read-only `diskutil info|list` are allowed (vault.py volume-UUID lookups); every other verb is refused.
- Test guard resolves `dir_fd`-relative names (`shutil.rmtree` passes names relative to an open folder) via
  `F_GETPATH`; unresolvable → refused (fail closed).
- Clean execute: `review/*.incomplete` files are no longer cleaned (review/ is protected); they are reported as refused.

### Not done / remaining risks (proposed, not implemented)
- `project_path` and `~/.percival_vault_config.json` still point at deleted test paths (needs user decision, §2).
- Eject safety still reads an empty job table: READY is not trustworthy until Phase 1 writes the journal.
- Transfer engine: singleton reset per request, no worker/queue, size-only resume, no directory fsync (Phase 1).
- `working_dir_migration` (`/api/storage/migrate_execute`, reachable from Settings) copies with `copy2`, checksums
  only < 50 MB and writes `project_path`; not changed in Phase 0 (migration is a separately approved operation).
- `transfer_manager.execute_free_up_mac_space` / `storage_advisor.execute_prune` delete staging/scratch content by age
  without Vault verification (app-managed temporary areas; days now ≥ 1).
- `/api/settings` accepts arbitrary keys; no Host-header check (DNS rebinding); `validate_python` executes the given
  path; `/api/open` opens any path - local-server hardening for a later phase.
- Pensieve defects (FK failures, ID mismatch, duplicates, replay) untouched - Phase 4.
- Older `tests/check_*.py` scripts were not run (not part of the unittest suite).
