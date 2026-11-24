# Phase 3A.1 — Cross-process safe writes, append-only reviewer event journals, crash recovery

Scope (as approved): safe writes and locking, append-only reviewer event journals, crash recovery and corruption handling.
NOT in this milestone: blinded read / blinded candidate ids, roles and consensus policy, adjudication, missed-lesion
per-reviewer storage, whole-study review, matcher decision, migration. Not installed or activated: the live app runs
`~/Percival_project/scripts`, which is unchanged (byte-identical to the previous commit for every file touched here).

## What changed

New `scripts/review_io.py` (stdlib + pandas, installed alongside the other scripts by the existing installer later):
- `atomic_write_bytes/text/json`: unique temp file in the same folder → fsync → `os.replace` → fsync(folder); file mode kept.
- `append_line`: `O_APPEND` + fsync; closes a torn last line first.
- `study_lock(base, sid)` / `project_lock(base, name)`: `fcntl.flock` on `review/.<sid>.lock` (between processes) +
  per-process re-entrant lock (between threads, nesting allowed); 60 s timeout → clear "try again" error; study key validated.
- Journal `review/<sid>_events_<reviewer>.jsonl`: one fsynced canonical JSON line per change, schema `review-events/1.0`,
  sequence number, SHA-256 of the previous line (hash chain), SHA-256 of the file written. Written **before** the file
  (write-ahead). Per-reviewer tables (calls, excluded-object audit calls) are journaled as record-level changes (exact CSV
  record text, quote-aware, so the file is rebuilt byte-for-byte); the shared missed-cSS file as full snapshots (small).
- Recovery (`ensure_table`, `ensure_missed`) runs under the study lock before every read-for-change and every write:

  | Situation | Outcome |
  |---|---|
  | file = journal head | nothing |
  | file missing | rebuilt from the journal, `recovered` event |
  | file = the state just before the head (crash between journal line and file) | rolled forward, `recovered` |
  | file unreadable, or a truncated prefix of the head | copy to `review/quarantine/` (never deleted), rebuilt, `recovered` |
  | file readable but unknown, or equal to an older state (another tool, a restore, a person) | **kept**, full content journaled as `external_change` |
  | file unreadable and no journal | `RecoveryError`; nothing overwritten, nothing started empty |
  | historical file, no journal, only read | nothing written; the first change journals its exact content as `baseline` |
- `verify_study`: read-only report (chains valid, every journaled file equals its journal head).

Wired in (no change to file names, columns or formats read by any consumer):
- `review_web.py`: calls, comments, undo/clear/revote, import, finish, excluded-object audit calls, missed-cSS add /
  delete / comment, final record, primary-reviewer file, reviewers list, viewer settings; `/api/call`, `/api/import`,
  `/api/finish` hold the study lock across the whole read-modify-write; review log via `append_line`; orphan temp files
  of this module cleaned at start.
- `call_ledger.py`: `materialize` (shared `ID_calls.csv` + `ID_effective.json` atomic, under the study lock — the shared
  file stays a derived representation), `set_policy` (project lock), `decide_carry` (confirm journaled as
  `carry_confirm`, reject as `carry_reject`), `consolidate` (each rewrite journaled as `consolidate` — the removed calls
  remain in the journal history), `restore` (restored reviewer files become the journal head, `restore` event).
- `inherit_calls.py`: reviewer file write journaled as `inherit`, under the study lock.

## Tests

`tests/test_phase3a1_review_io.py` — 25 tests, synthetic projects only, real reviewer server processes, real SIGKILL via
the existing test-only crash points (`PERCIVAL_TEST_CRASH_AT`, `PERCIVAL_TEST_SLOW_AT`; no-ops outside isolation):
atomic write crash before / after replace; fsync of file + folder and mode kept; torn log line; cross-process lock
exclusion, re-entrancy, thread serialisation, bad study keys; journal hash chain and tamper detection; torn journal line;
byte-for-byte rebuild after 4 changes incl. quotes / commas / newline in a comment, removal, correction, reorder; crash
between journal and file → roll forward; truncated and garbage files → quarantine + rebuild; external change kept;
deliberate restore of an older state not undone; unreadable file without journal refused and untouched; historical file
read creates nothing and first write records it exactly; two reviewer processes (same reviewer, two windows) + missed
marks in parallel with a widened race window → no lost call / mark / log line, unique missed ids, chains verify; reviewer
SIGKILLed mid-save recovers on restart; server quarantines + rebuilds a corrupt file; unrecoverable file refused, not
overwritten; missed deletions kept in history and rebuild; consolidate keeps removed calls in history and restore
becomes the head; 4 processes × 5 policy changes all kept; inherit_calls journaled.

Results:
- `tests/run_isolated_suite.py test_phase3a1_review_io.py`: 25/25, 0 skipped, live fingerprints changed 0, writes refused 0.
- `tests/run_isolated_suite.py` (all `test_*.py`): 312 run, 0 failures, 0 errors, 0 skipped; isolation PASS.
- Official `tests/run_tests.sh` (temporary HOME, temp CSS_BASE): unmodified HEAD `ALL TESTS PASSED`; this change
  `ALL TESTS PASSED` (51 sections each, the same 1 pre-existing SKIP: `object_ledger.py not implemented yet`).
  Includes check_review_web, check_call_ledger (31 PASS), check_lineage (24 PASS), check_inherit, check_labels,
  check_consensus.

Mutation tests (each applied to a copy in the scratchpad; all 16 caught):

| # | Mutation | Caught by |
|---|---|---|
| R1 | write straight to the target | crash-before-replace test |
| R2 | no fsync of the file | fsync test |
| R3 | in-process lock only (no flock) | cross-process lock, concurrent windows, parallel policy |
| R4 | file written before the journal | crash-between-journal-and-file, reviewer killed mid-save |
| R5 | unreadable file without journal → start empty | refused-and-untouched (unit + server) |
| R6 | roll forward from any earlier state | deliberate restore not undone |
| R7 | overwrite damaged file without quarantine copy | truncated / garbage / server-corrupt tests |
| R8 | hash chain not verified | tamper test |
| R9 | append without closing a torn line | torn log line, torn journal line |
| R10 | reviewer call without the cross-process lock | concurrent windows |
| R11 | missed marks without the cross-process lock | concurrent windows |
| R12 | reviewer save bypasses the journal | corrupt-file rebuild, killed mid-save |
| R13 | consolidate rewrites without the journal | consolidate/restore test |
| R14 | policy update without the project lock | parallel policy changes |
| R15 | inherit_calls writes directly | inherit test |
| R16 | restore without becoming the journal head | consolidate/restore test |

## Integrity report
- Live project `~/Percival_project`: unchanged (isolation fingerprints; `review/` empty, no journal files).
- Installed app: `review_web.py`, `call_ledger.py`, `inherit_calls.py` byte-identical to the previous commit; `review_io.py`
  not installed. (Their mtime 2026-11-23 10:38 is an earlier install of build 236ad5f, already recorded in Phase 2.)
- Vault: not mounted (`/Volumes` = Macintosh HD only); nothing accessed.
- Historical calls: none on this Mac; journaling never rewrites existing files on read; first change records the exact
  prior bytes. No models touched. No push / merge / rebase.
- FreeSurfer installation unchanged (see finding 1).

## Findings (pre-existing, not fixed here)
1. `tests/phantom_v4.py` appends labels to `$FREESURFER_HOME/FreeSurferColorLUT.txt`; with `FREESURFER_HOME` pointing at
   the real installation it tries to modify it (refused by permissions on this Mac; LUT verified unchanged).
   `run_tests.sh` sets a stub; running the check scripts on their own does not.
2. `tests/check_review_web.py` can leave a reviewer server running (it held the runner's output pipe open) and uses fixed
   ports 8931-8933, so two runs cannot be made at the same time (a parallel run produced a false failure).

## Limitations / residual risks
- Locks are advisory: tools that do not use `review_io` are not excluded — `review_css.py` (writes the shared, derived
  `ID_calls.csv`), the app op `percival/missed_lesion` (appends to `ID_missed.csv`; its rows are detected as an external
  change; the op is removed in milestone 3A-3), `expert_import.py` / `label_missed.py` (write `labels/`, not `review/`).
- `call_ledger.sources()` (read-only path used by the app) does not run recovery; a damaged reviewer file is still
  skipped there until the reviewer window repairs it (unchanged behaviour).
- `flock` semantics on exFAT / network volumes are untested (the project folder is local APFS).
- Journals grow with every change and are read in full on each append (fine at review scale; no compaction).
- Journal times come from the local clock; ordering of the shared missed file across reviewers uses time + sequence.
- `consolidate` still rewrites reviewer files (now with full history kept); its replacement by adjudication is 3A-4.
