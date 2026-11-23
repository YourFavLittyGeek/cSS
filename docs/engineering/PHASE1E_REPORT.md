# Phase 1e — Transfer Center GUI, eject protection, migration blocking, Vault verification

Not installed or activated: the live application runs the installed copy in `~/Percival_project/app`, which is unchanged.

## 1e.1 Eject protection from real activity + Vault verification (`c6d492d`)
- `uengine/storage/activity.py`: per volume, (1) transfer jobs from the durable journal, opened read-only (never
  created) — *active* jobs block, *parked* (paused / interrupted / needs-attention) jobs are reported as needing the
  drive; (2) every process with files open on the filesystem (`lsof +f -- <mount>`); if that cannot be determined the
  result is UNKNOWN and normal eject is refused.
- `EjectManager`: READY only with no active transfer and no open files. Active transfers block normal, emergency AND
  forced eject (a force token does not override protected operations); an emergency eject first asks those jobs to
  pause at a safe boundary (≤30 s) and only then asks macOS; BUSY by other programs → macOS is asked, a refusal leads
  to the existing confirmed force flow.
- `uengine/storage/vault_check.py`, `GET /api/transfer/vault_check`: read-only verdict `archive_ok` / `not_external` /
  `read_only` (exFAT, read-only mount, unknown filesystem) / `not_a_vault` / `unavailable`, with filesystem, mount
  point, read-only flag, manifest, free / total space. Read-only destination volumes are refused before any write.
- Tests: `test_phase1e_eject_vault.py` (10) on real APFS / HFS+ / FAT32 / exFAT and read-only images mounted in the
  test volumes root, real lsof, real unmount via hdiutil; mutations E1–E6 caught.

## 1e.2 Migration and conflicting-maintenance blocking (`3924604`)
- `storage/migrate_execute` and `migration/execute` are refused until a separately approved migration workflow exists
  (`migrate_plan` / discovery remain); `project_path` and `workspace_dir` are never rewritten by them.
- Refused while any transfer job is unfinished: prune, free-space, clean execute, purge quarantine.
- Refused when an unfinished job touches the path / study: file delete / move / rename, study delete, staging clean,
  delete-by-study, workspace clean. An unreadable journal refuses rather than allows.
- Tests: `test_phase1e_guards.py` (4); mutations G1–G3 caught.

## 1e.3 Transfer Center GUI (`this commit`)
- `app/transfer_view.js` rewritten: tabs *Needs your decision* (paused / interrupted / needs attention / failed),
  *Running*, *Queued*, *History* (searchable); per job: state, worker, files / bytes committed and staged, current file,
  recovery decision, error; detail: 7-step timeline, files with states and errors, skipped items, last journal events,
  read-only recovery check (resumable / discardable / ambiguous items); Vault verdict and eject state from the backend.
- The view keeps no job state: each 2-second refresh replaces all data with the endpoint payloads; the only client
  state is tab / selection / search. Controls are a pure function of the journaled state (pause; resume / discard /
  check for paused & interrupted; cancel only before start; discard with an explicit confirmation; a recorded recovery
  decision is not offered to be switched); every action is a backend request that is re-validated there.
- Sidebar: the transfer meter counts running jobs from the journal; the Eject button follows the backend's `can_eject`.
- Crash fixes: the undefined `round()` helper (Transfer Center, Sync Center "Sync Now", Settings storage breakdown);
  the poll uses the shell's `V` (was `window.V`).
- Tests: `test_phase1e_gui.py` (10) feeding payloads of real backend states (completed, needs_attention, failed,
  paused, SIGKILL-interrupted, queued) to the view in Node (`tests/gui_transfer_harness.js`); mutations U1–U6 caught.
  No browser automation is installed on this Mac; layout / visual behaviour is not machine-tested.
