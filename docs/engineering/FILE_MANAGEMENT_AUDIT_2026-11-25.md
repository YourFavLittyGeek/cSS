# File management / transfer audit - 2026-11-25

Question from the user: the reviewer is slow to open - is it transferring from the drive, and why would it transfer
studies that were not reviewed? Answer: NO transfer happened (Pensieve `studies/` empty, no marker, transfer journal
empty). The wait was the reviewer's own computation (fixed in 8273d1c: 27 s -> 4.6 s, next patient preloaded 0.06 s).

## Fixed now (8273d1c)
| Problem | Fix |
|---|---|
| Reviewer open 17-27 s: candidate centres by whole-volume scans; side check recomputed on every /api/meta (3-4 s, up to 3x per open) | bounding-box centres (identical), side check cached + reuses loaded labels, next study preloaded |
| Pensieve move deleted Mac files before writing the record -> crash mid-delete = files only on the drive, no record | marker "deleting" with every file + SHA-256 written first; treated as in Pensieve; restorable |
| A study could move while processing (Processing Manager / unified score) or while still being read | skipped; also waits until its review files are unchanged for the grace time |
| Quit did not wait for a running move | it waits; the quit check counts it |

## Plan - DONE 2026-11-25 (user: "go ahead"): items 1-4 in 4da2b2c, 5-8 in the next commit; 9-10 still open
Single owner: app/pensieve_move.py, view: Transfer Center
### High
1. **Protect `<Pensieve>/studies/`** (`safety.py` PROTECTED_VAULT_DIRS lacks it): after a move it holds the ONLY copy of
   raw/ + data/, yet `/api/files/delete|move` could remove it. Make it write-once: only new version folders through
   pensieve_move's policy; never delete / move / rename.
2. **One `ensure_local(code)` helper** used by every reader of images: Anatomy QC, unified score, image ML / CNN index,
   Percival "MRI available", export, same-patient check (`study_split.py:101` hashes data/<ID>_swi.nii - use the marker's
   SHA-256 when moved), Processing Manager `pm_execute` / `set_active`, pathway advice. Either bring the study back or show
   "in Pensieve" instead of "missing".
### Medium
3. **Temporary DICOM cleanup vs move**: clean the temp copies before moving, exclude raw/*/_dicom from the move,
   `source_cleanup.verified()` accepts the marker's raw/SWI entry.
4. **Remove / Purge** (`study_admin.py`) ignore the Pensieve copy: show it and ask (keep on drive / delete there too);
   carry the marker on Remove.
5. **Retire the overlapping systems** (each half-does the same job, several with wrong folder layouts): Sync screen
   (expects work/<ID>/ folders that never exist - always 0 files), File Manager Stage/Archive/Clean (StudyWorkspaceManager),
   Storage Archive/Stage/Verify (FileManager: copies only review files, cannot see version folders, shows moved studies as
   "Local only"), "Process transfer" + its policies (TransferManager queue nothing fills), older transfer engine endpoints.
   Replace by one Pensieve panel per study: state, version list, Move now / Bring back / Verify against the marker.
6. **"Free up Mac space" / Prune**: delete staging/logs without checking running studies; sizes follow symlinks (reports
   the DICOM targets, not freed space); wording claims "verified Vault copies". Skip running studies, lstat sizes, honest text.
### Low
7. Settings that do nothing (sync auto-triggers, 13 transfer policies, cleaning mode / min free space / 13 of 15 categories,
   folder settings originals/processed/albus/lumos/nox/pensieve_backups/scratch): remove or label "not active".
8. Dead buttons: "Change working directory" (always refused), "Clean Orphan Staging" (calls a missing operation, error
   hidden), workspace "Clean" (can never pass). Remove or wire.
9. Unverified own copies (Vault backup, import copy into import_src): route through the journaled engine.
10. Proposed earlier, still open: when the Mac drops below ~50 GB, offer to move reviewed studies.

## Status of items 5-8 (implemented)
5. Retired (answer `retired`, pointing to Pensieve): storage archive / stage / clean / verify / sync_execute, workspace stage /
   archive / clean / enqueue / process_next, transfer enqueue / process_next. Sync Center hidden from the menu. Storage and
   File Manager study rows show ONE Pensieve panel (state, Move to Pensieve, Bring back, Check = read back + compare SHA-256).
6. Free up Mac space and staging prune skip studies being processed; sizes with lstat (links, not their targets).
7. Labelled "not active" / disabled: archival policies, cleaning mode, 13 of 15 cleaning categories, folder settings that
   are never read (now "fixed").
8. "Change working directory" -> "use Setup"; "Clean Orphan Staging Buffers" wired to the staging prune.
