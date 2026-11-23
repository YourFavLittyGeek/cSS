# Phase 1d focused safety audit (shutdown, request durability, rollback failures)

Scope requested before Phase 1e. Tests: `tests/test_phase1d_audit.py` (12, isolated). Findings were fixed; every fix is
covered by a mutation test (MA1–MA7).

## Findings and fixes
| # | Finding | Fix |
|---|---|---|
| F1 | Without a window (`--no-window`, Ctrl-C) the app left `serve_forever()` and the interpreter exited with daemon worker threads mid-operation — no pause was attempted. (Data stayed recoverable; the exit was simply not graceful.) | `css_app.py` main: pool shutdown in a `finally` on that path. |
| F2 | `SIGTERM` (logout, `kill`) terminated the process immediately, bypassing the safe shutdown. | `css_app.py` main: `SIGTERM` runs the same `_perform_safe_shutdown` as Quit. |
| F3 | An error *during* rollback (e.g. permission denied while removing a file) escaped `run()`: direct callers got an exception and the job stayed `rolling_back` until the next start-up detection. | `_abort_run` contains per-file undo failures: the file keeps its journaled `rolling_back` intent, nothing unproven is deleted, the job ends `needs_attention`; a 1c discard (or resume) finishes the undo later. A committed file changed by someone else during the failing job is also reported (`needs_attention`, left in place). |
| F4 | A pause request written by a timed-out shutdown stayed in the journal after its owner died, so the next resume paused again immediately. | A pause request never outlives its owner: cleared when `detect_interrupted()` marks the job and when a resume / discard decision is recorded. |

## 1. Shutdown safety
- Every exit path now pauses running transfers first: Quit / window close / `SIGTERM` (`_perform_safe_shutdown`: pool
  shutdown with a 15 s wait, then `os._exit(0)`), Ctrl-C / server stop (`finally`).
- **No worker can outlive the application:** worker threads live inside the app process (no subprocesses in the
  transfer package); `os._exit` / process death ends them, and the kernel releases the job locks (flock).
- A job that has not reached a safe boundary within 15 s is cut off exactly like SIGKILL. Every destructive step is
  journaled before it runs and every publish is atomic, so the job is classifiable at *any* instant: tested by a timed-
  out shutdown inside a commit (tree fingerprint stable after exit, job never `completed`, detected `interrupted`,
  resumed or discarded correctly) and by a seeded **random-instant SIGKILL fuzz** (24 kills across copying / flushing /
  verifying / committing; all recovered; any unrecognized temporary file reported and left untouched).
- Real application test: `app/css_app.py` run as a program on a temporary project, a job created over HTTP, then
  `SIGTERM` and (separately) `SIGINT` → the job is `paused` with its own partial copy kept, and resumes correctly.

## 2. Resume / discard request durability (no second recovery mechanism)
Requests are held in memory by the worker pool; the **decision** is persisted by Phase 1c (`recovering`,
`recovery_decision`) before any change.
| Interrupted when | State after restart | Expected behaviour |
|---|---|---|
| request queued, worker not started | job still `paused` / `interrupted`, no decision | nothing lost or completed; the user requests again (either choice still possible) |
| resume running, process killed | `recovering` → detected `interrupted`, decision `resume` kept | resume again (continues from the journal); discard refused |
| discard running, process killed | `interrupted`, decision `discard` kept | discard again; resume refused |
| graceful shutdown during resume | `paused` at a resume checkpoint, decision `resume` kept | resume again |
| shutdown timed out mid-step | active state → detected `interrupted`; stale pause request dropped | resume / discard as above |
A job is never marked `completed` by a restart, a worker exit or detection; only the final transition of a run / resume
that finished every phase does that (mutation D3 / MA-tests confirm).

## 3. Rollback failure handling
- Disk full / I/O error during commit → rollback follows the 1c protocol: `rolling_back` intent journaled before each
  undo (event order checked), identity + hash checked before any removal, previous versions restored exclusively.
- Failure during rollback itself: permission denied while undoing → `needs_attention`, the committed files untouched and
  still identified; after the permission is restored, 1c discard finishes cleanly.
- Journal failure while recording the undo intent → **nothing is deleted** (no intent, no destructive step); the job is
  `needs_attention`; discard later completes.
- SIGKILL during rollback (after intent / after removal / after restore / second file) → `rolling_back` → detected
  `interrupted` → resume or discard ends correct.
- A file changed by someone else during the failing job is never deleted (left in place, reported).

## Remaining limits
- Requests are not durable by design (re-request after a restart); the durable part is the recovery decision.
- A shutdown cut-off mid-step is equivalent to a crash: correct, but the job needs a user resume / discard.
- `SIGKILL` / power loss cannot be intercepted; covered by the 1c crash guarantees.

## Mutation tests (each reverts one fix or guarantee; all caught)
| # | Mutation | Caught by |
|---|---|---|
| MA1 | rollback failures escape again (no per-file containment) | permission-during-rollback, journal-failure-during-rollback |
| MA2 | failure to journal the undo intent is ignored | *survives by design*: undo reads its authorisation (origin state, target) back from the journal, so a missing intent still deletes nothing |
| MA2b | ...and the authorisation is taken from memory instead of the journal | journal-failure-during-rollback (files deleted without intent) |
| MA3 | rollback removes files without identity / hash check | changed-file-during-failing-job |
| MA4 | shutdown does not request a pause | real-app SIGTERM/SIGINT, timed-out shutdown, graceful shutdown during resume |
| MA5 | stale pause request kept after its owner died | timed-out shutdown (resume paused again) |
| MA6 | no pool shutdown on the Ctrl-C / server-stop path | real-app SIGINT |
| MA7 | no SIGTERM handler | real-app SIGTERM |
