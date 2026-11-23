# Phase 1d — Transfer Center endpoints, background workers, cooperative pause

Backend only (the GUI is Phase 1e). Builds on the 1a–1c journal, verified copier and recovery; no second recovery path.

## Endpoints (`app/css_app.py` → `uengine/transfer/api.py`, under `/api/transfer/`; legacy ops unchanged)
| Method | Path | Body / query | Result |
|---|---|---|---|
| GET | `jobs` | `state=a,b` `limit≤500` | `{ok, jobs:[summary]}` newest first |
| GET | `job` | `id` | `{ok, job:summary, files:[{seq, rel_path, size, state, error, attempt, dst}], skipped, events (last 50)}` |
| GET | `assess` | `id` | `{ok, assessment}` (Phase 1c read-only, hashes files) |
| GET | `workers` | — | `{ok, workers:{alive, stopping, running, pending_requests, workers_per_device, detected_interrupted_at_start}}` |
| POST | `jobs/create` | `{operation: archive\|stage\|move, items:[{src, dst}] (1–1000), study_id?, keep_previous?, request_id?}` | `{ok, job_id, duplicate, state}` |
| POST | `jobs/pause` | `{job_id}` | queued → `paused`; running → `pause_requested` (stops at the next safe boundary); paused → `noop` |
| POST | `jobs/resume` | `{job_id}` | `{requested: "resume"}` → background Phase 1c `resume` |
| POST | `jobs/discard` | `{job_id}` | `{requested: "discard"}` → background Phase 1c `discard` |
| POST | `jobs/cancel` | `{job_id}` | only a job that has not started (`queued` → `cancelled`, nothing written); otherwise refused |

Summary: `job_id, operation, study_id, commit_mode, state, terminal, created_at, updated_at, progress{files_done,
files_total, bytes_committed, bytes_staged, bytes_total, percent_committed, current_file}, control, recovery_decision,
running, heartbeat_age_s, error{code, message}|null`. Refusals: `{ok:false, error:{code: bad_request|not_found|refused|
internal, message}}`. All paths pass the Phase 0 policy in `TransferService.submit` (exFAT destinations refused).
POSTs still require the `X-CSS-App: 1` header.

## Workers (`uengine/transfer/workers.py`)
- The journal is the queue (QUEUED jobs, creation order). Explicit resume / discard requests are held in memory; the
  job itself stays durably PAUSED / INTERRUPTED, so a lost request is simply re-requested.
- One worker slot per destination device (`st_dev`): an HDD is written strictly sequentially; different devices run in
  parallel. Per-study / per-destination locks still give file-level exclusivity.
- Duplicate execution is impossible: `run` takes the per-job liveness lock first (also across processes) and moves
  QUEUED → PREPARING with an `expected` check. Any pool in any process may run a queued job; exactly one does.
- A worker never reports an outcome: status is read from the journal; after an abnormal exit the job (lock free again)
  is marked INTERRUPTED by 1c detection — never "completed".
- Start-up runs `detect_interrupted()` (no disk change). Shutdown stops dispatching, requests a pause of every running
  job and waits (app shutdown: 15 s); a job that does not reach a safe boundary in time stays active and is detected as
  interrupted on the next start.
- Duplicate requests: `request_id` is stored in a UNIQUE-indexed journal column (schema v3); a second create with the same
  id returns the existing job atomically.

## Pause / resume
- `pause` writes `jobs.control = 'pause'` (schema v3); the owner checks it only at safe boundaries: between copy chunks
  (the partial `.part` is kept, its identity already journaled), before each file, before the commit phase, between
  commits, before removing move sources, before finalizing previous versions, and the corresponding points of a
  resume. A pause never rolls back; the job becomes PAUSED with every file in a classifiable state.
- PAUSED leaves only through Phase 1c `resume` / `discard` (`PAUSED → RECOVERING`); the partially copied file is
  re-copied from its start (its own partial `.part` is recognised and removed); verified files are reused.
- A volume that disappears mid-job → INTERRUPTED (no rollback attempted); recovered after re-mount. Disk full /
  permission failures → normal rollback of the job's own data → FAILED with a structured error.

## Schema v3 (additive): `jobs.control`, `jobs.request_id` (+ unique index created after migration).
