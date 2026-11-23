# Phase 1c — crash recovery design (proposal, then implemented in the 1c commit)

## Gaps in the committed 1b journal (5b9b566)
1. No **identities** recorded (source, `.part`, published file): after a crash recovery could not prove a file is the
   one Percival wrote.
2. Destructive steps are not **write-ahead logged**: `preserved_path` is written only *after* the commit; moving the
   old version aside, publishing, rolling back, removing a move source and removing a preserved version have no
   recorded intent - a crash between intent and record would leave unclassifiable files.
3. Folders created by a job are kept only in memory.
4. No reliable **liveness**: `owner_pid` can be reused by another process.

## Schema v2 (additive migration; v1 journals are upgraded in place, never rewritten)
`job_files` + `attempt` (restage counter → part name `<dst>.part-<job>` / `<dst>.part-<job>-r<N>`), `src_identity`,
`part_identity`, `old_identity` (destination that existed before the job), `dst_identity`, `preserved_state`
(`none|planned|moved|removing|removed|restored`), `intent` (JSON of the destructive step about to happen).
`jobs` + `recovery_decision` (`resume|discard`, fixed once chosen), `recovery_attempts`, `created_dirs` (JSON).
Identity = `[size, mtime_ns, inode]` (a rename keeps it; any write changes it).

New file states: `committing` (intent to publish), `rolling_back` (intent to undo), `removing_source` (intent).
New job states: `rolling_back`, `recovering`.

## Write-ahead protocol (normal run and recovery share it)
| Destructive step | Recorded BEFORE the step | Classifiable after a crash by |
|---|---|---|
| create `.part` | — (then immediately `part_identity` from `fstat`, before any data) | inode match; an unrecorded `.part` is *unrecognized* |
| move old destination aside | file `committing` + `preserved_path`, `old_identity`, `preserved_state=planned` | preserved file has `old_identity` |
| publish | (same `committing` intent, `part_identity`) | destination has `part_identity` and its hash = source hash |
| undo publish / restore old | file `rolling_back` + expected identities | destination / preserved identities |
| remove move source | file `removing_source` (destination verified by hash first) | source missing, or unchanged |
| remove preserved version | `preserved_state=removing` | preserved missing, or `old_identity` |
| remove our `.part` | `intent=discard_part` + identity | `.part` missing, or identity |
| create folder | appended to `jobs.created_dirs` before `mkdir` | folder exists and is empty |

## Liveness
A running job (normal run or recovery) holds an exclusive `flock` on `app_data/locks/job-<id>` for its whole
lifetime; the kernel releases it when the process dies (including SIGKILL). `detect_interrupted()` marks a job in an
active state `interrupted` only if it can take that lock (owner provably dead). It changes nothing on disk. QUEUED jobs
are not interrupted.

## Recovery is never automatic
`detect_interrupted()` (safe at start-up) → `assess(job)` (read-only, hashes everything) → the user chooses
`resume(job)` or `discard(job)`. The decision is persisted (`recovering`, `recovery_decision`) **before** any change and
cannot be switched later. An ambiguous assessment blocks resume; discard never touches anything that is not provably
the job's own.

## Assessment: per-file classification (deterministic, every claim verified by identity AND hash)
| Class | Evidence | resume | discard |
|---|---|---|---|
| `published_ok` | committed/committing; destination identity = recorded part/dst identity; hash = source hash | keep (record committed) | remove it, restore preserved |
| `staged_ok` | our `.part` (identity) hashes to source hash; source unchanged | commit | remove `.part` |
| `needs_copy` | pending / copying / rolled back / failed; source unchanged | (discard our partial `.part`) restage → commit | remove our partial `.part` |
| `preserved_aside` | old version at `preserved_path` with `old_identity`, destination free | publish (or restore) | restore old version |
| `source_removed` | move: source gone after verified commit | keep destination (only copy) | **keep destination** (only copy) |
| `skipped` | skipped identical | — | — |
| **ambiguous** → blocks resume, reported: `source_missing`, `source_changed`, `destination_missing`, `destination_changed` (foreign / modified), `preserved_changed`, `part_changed`, `unknown_state` | | refuse | leave the item untouched, report |
| **unavailable**: a source root or destination folder / volume is missing | | refuse (no change) | refuse (no change) |
Unrecognized temporary files (an artifact of this job without a recorded identity, or of an unknown job) are reported
and **never deleted**; a restage uses a new attempt name next to them.

## Outcomes
- resume → `completed` / `completed_with_retained_sources`; a non-ambiguous failure while resuming (disk full,
  permission) → back to `interrupted` with the error (everything done so far is recorded; safe to retry).
- discard → `cancelled`; if an old version could not be restored safely → `needs_attention`.
- Running `resume` / `discard` again is a no-op on a terminal job and continues an interrupted recovery from the
  journal (every step re-checks its precondition, so a repeated step is harmless).

## Tests (isolated; real disk images for filesystems)
SIGKILL at every write-ahead boundary of normal run, resume and discard (env `PERCIVAL_TEST_CRASH_AT`, honoured only
under `PERCIVAL_TEST_ISOLATION=1`), repeated crashes during recovery, then recovery to the correct end state, twice
(idempotent); disk full, permission denied, missing / changed source, missing / changed destination, changed
preserved version, unrecognized temp files, unavailable volume (APFS disk image detached and re-attached); recovery on
APFS / HFS+ / FAT32 images; exFAT refusal unchanged. Mutation tests for each guarantee.

## Implementation status (1c commit)
Implemented as designed in `uengine/transfer/{models,journal,copier,service,locks,crashpoints}.py`. Notes:
- One extra file edge `committing → verified` ("intent recorded, no rename happened") lets resume re-commit a verified
  part; one undo routine (`_undo_file`) serves both normal-run rollback and discard; its intent keeps the publish
  target and the state it came from.
- A preserved version marked `removing` that still has its recorded identity can still be restored; once actually
  removed (`removed`, or `removing` and gone), discard keeps the committed file and ends `needs_attention`.
- Rows without identities (written by the 1b code) are never trusted: such a job is not resumable and discard leaves
  every unproven file in place.
- Tests (`tests/test_phase1c_recovery.py`, 20): 64 real SIGKILL crashes across all 15 normal-run boundaries x
  archive / stage / move x resume / discard, each recovered and then repeated (no-op); crashes during resume (3
  boundaries) and discard (up to 4); disk full; permission denied; missing / changed source; missing / changed
  destination (incl. rewritten in place with the timestamp reset); changed preserved version; unrecognized temp file;
  own partial part; v1→v2 migration; unavailable volume (APFS image detached / re-attached); recovery on APFS, HFS+,
  FAT32 images; exFAT refusal unchanged. 8 mutation tests (R1–R8), all caught.
