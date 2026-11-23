# PERCIVAL — Storage Architecture, File Manager & System Implementation Forensic Audit

**Mission ID:** `PERCIVAL-STORAGE-IMPLEMENTATION-AUDIT-2026`  
**Target:** PERCIVAL v5.25 Implementation Baseline  
**Auditor:** Principal Neuroimaging Systems Architect, Clinical Quality Auditor & Senior macOS Systems Engineer  
**Date:** November 22, 2026  
**Execution Standard:** Inspect → Audit → Plan → Implement → Test → Verify → Release  

---

## 1. Executive Summary & Audit Mandate

This forensic audit investigates the concrete user-facing and backend implementation of PERCIVAL's storage management, file management, installation wizard, working-directory migration, and external Data Vault resilience.

### Core Rule of Audit:
> A capability is considered implemented **only** when its complete user-facing workflow actually works from GUI invocation to filesystem execution and cryptographic verification. Documentation, mockups, or non-functional buttons do not constitute implementation.

---

## 2. Requirement-by-Requirement Implementation Matrix

| Requirement | Requested Capability | Actual Implementation Status | Current Code / Files Involved | Verified Behavior vs Implementation Gap | Safety Risk & Required Action |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **REQ-01: Dedicated File Manager Screen** | Primary navigation item named "File Manager" with full file/folder browsing and operations | **Partial (Needs Expansion)** | `uengine/file_manager.py`, `percival_view.js` (vault tab) | Currently placed inside a sub-tab under Percival Intelligence. Needs a dedicated top-level primary navigation view (`app/file_manager_view.js`) with category sidebar, multi-selection, file operations (copy, move, delete, rename, archive, restore). | Low risk; UI restructuring and dedicated endpoint integration required. |
| **REQ-02: Manual File Operations** | Real file/folder Copy, Move, Rename, New Directory, Delete, Archive, Restore with conflict handling | **Backend Partial / GUI Incomplete** | `uengine/file_manager.py` (study-level only) | Current backend only handles study-level staging/archiving. Does not yet expose granular file/folder copy, move, rename, delete, or conflict resolution (Skip, Keep Both, Replace). | **High Risk:** Must prevent accidental deletion of raw MRI or ground truth. Implement transactional confirmation dialogs and conflict handlers. |
| **REQ-03: Working Directory Configuration** | Explicit user selection of working directory during first-launch and in Settings | **Implemented** | `app/css_app.py`, `app/setup_view.js`, `uengine/wizard.py` | Working directory can now be selected during setup and changed in Settings. Need to expand independent destination selection for individual categories. | Low risk; ensure path validation and permission checks are strictly enforced. |
| **REQ-04: Independent Category Destinations** | Independent destination selection for Original MRI, Processed MRI, ALBUS, LUMOS, NOX, Pensieve, Models, Reports | **Partial (Config level only)** | `app_data/settings.json`, `app/css_app.py` | Settings has single paths. Must provide independent path table in Settings and multi-category destination selector in the Installation Wizard. | Moderate; ensure path resolution falls back gracefully if specific category is unconfigured. |
| **REQ-05: Working Directory Migration** | Automatic safe migration when working directory changes with journal, rollback, and validation | **Missing / Backend Only** | `uengine/legacy_migration.py` (legacy study discovery only) | Legacy scanner exists, but changing the working directory does not yet trigger automated file migration, conflict detection, or migration journal rollback. | **Critical Risk:** Changing working directory without migrating leaves studies orphaned. Implement `WorkingDirMigrator` with journaling. |
| **REQ-06: Storage Intelligence** | Real-time monitoring of Mac SSD & Data Vault across 4 capacity tiers (Healthy >25%, Warning 20-25%, Critical 10-20%, Emergency <10%) | **Implemented** | `uengine/storage_advisor.py`, `uengine/vault.py` | Calculates disk capacity, headroom, and categorizes status into tiers. Need to wire active capacity forecast to File Manager header. | Low risk; operational. |
| **REQ-07: Automatic Archiving & Retention** | Smart/Assisted/Manual archiving with 7-day scratch, 14-day failed runs, 30-day logs, zero raw MRI deletion default | **Implemented** | `uengine/staging.py`, `uengine/storage_advisor.py` | Staging space calculation, atomic SHA-256 sync, retention policy enforcement. Original MRI deletion is disabled by default (`keep_local_originals = False` applies only to scratch). | Low risk; verified. |
| **REQ-08: External HDD Disconnection & Degraded Mode** | Hardware Volume UUID binding, graceful Degraded Mode, local emergency scratch fallback, transfer queue | **Implemented & Tested** | `uengine/vault.py` | Volume UUID resolution via `diskutil`, TransferQueueManager, degraded mode handling without crashing. | Low risk; verified in unit tests. |
| **REQ-09: First-Installation Wizard** | Runs on first install or when setup is incomplete; does NOT run repeatedly once finished | **Implemented & Enhanced** | `app/setup_view.js`, `app/setup_gui.py`, `app/css_app.py` | 4-step wizard with Working Directory, External Vault, FreeSurfer, Candidate Re-detection & Calling, and readiness report. | Low risk; verified. |
| **REQ-10: Startup Health Check Every Launch** | Silent 19-point startup check running on every application start (separate from wizard) | **Implemented & Tested** | `uengine/health.py`, `app/css_app.py` | 19-point check, crash sentinel (`.clean_shutdown`), append-only `health_history.jsonl` audit log. | Low risk; verified. |
| **REQ-11: Persistent Recovery Ledger** | 8-stage transactional ledger tracking job stages with crash resumption | **Implemented & Tested** | `uengine/recovery.py`, `app/css_app.py` | Tracks stage progression, partial rollbacks, and recovery summary API. | Low risk; verified. |
| **REQ-12: Zero-Corruption Pensieve Backup** | SQLite backup API, WAL checkpointing (`PRAGMA wal_checkpoint(TRUNCATE)`), dual-destination snapshot rotation | **Implemented & Tested** | `uengine/pensieve_backup.py` | Uses `sqlite3.Connection.backup()`, verifies `PRAGMA integrity_check`, pre-restore safety copy. | Low risk; verified. |
| **REQ-13: Candidate Re-detection & Calling** | Re-detects candidates from original MRI on processing; matches calls via 3D spatial fingerprinting | **Implemented** | `app/percival_gui.py`, `app/css_app.py`, `app/setup_view.js` | Configured `"candidate_redetection": true` and `"candidate_calling": true` by default in `settings.json`. Fingerprint re-attaches expert calls. | Low risk; verified. |
| **REQ-14: Mac Filesystem Forensic Inventory** | Standalone read-only audit of host Mac storage without modifying host files | **Implemented** | `docs/MACOS_HOST_CLEANUP_RECOMMENDATION_REPORT.md` | Comprehensive inventory of 410 GB used / 14 GB free, 38.2 GB legacy research workspaces, and safe migration options. | Zero risk; strictly read-only. |

---

## 3. Implementation Action Plan

To transition from the current state to complete, fully integrated user-facing functionality:

### Priority 1: Dedicated File Manager Screen & Navigation
1. Create `cSS_pipeline_v4.13/app/file_manager_view.js`:
   - Primary navigation item in sidebar: `<button data-v="files">File Manager</button>`.
   - Category tree navigation (Working Directory, External Data Vault, MRI Originals, Imported MRI, Processed MRI, ALBUS, LUMOS, NOX, Pensieve, Models, Reports, Temporary Scratch, Backups, Recovery).
   - File/directory browser table with sorting, search, filtering, and multi-selection checkboxes.
   - Comprehensive operation controls: Copy, Move, Rename, New Directory, Delete with confirmation, Archive, Restore, Verify SHA-256.
2. Extend `cSS_pipeline_v4.13/unified_engine/uengine/file_manager.py`:
   - Implement `browse_category_path()`, `copy_entry()`, `move_entry()`, `rename_entry()`, `create_dir()`, `delete_entry()`, `compare_entries()`.
   - Provide multi-item conflict resolution (`skip`, `keep_both`, `replace`).
   - Wire REST endpoints `/api/files/*` in `cSS_pipeline_v4.13/app/css_app.py`.

### Priority 2: Working Directory Migration Engine
1. Implement `cSS_pipeline_v4.13/unified_engine/uengine/working_dir_migration.py`:
   - Pre-migration validation: destination directory writeability, available headroom, active job lock check.
   - Persistent migration journal: `app_data/working_dir_migration_journal.json`.
   - Safe copy loop with SHA-256 validation.
   - Rollback capability upon interruption or error.
   - Update configuration only after 100% verification.
   - Keep old working directory intact as safe backup.
2. Wire migration endpoints into `css_app.py` (`/api/storage/migrate_working_dir`).

### Priority 3: Independent Destination Configuration
1. Update `app/css_app.html` & `app/setup_view.js`:
   - Add independent destination selection table in Settings under **Storage & Locations**.
   - Categories: Working Directory, Scratch Directory, Original MRI, Imported MRI, Processed MRI, ALBUS Outputs, LUMOS Outputs, NOX Outputs, Expert Annotations, Reports & Exports, Models & Checkpoints, Pensieve Backups, Data Vault.
   - Display absolute path, capacity, and live status badge (`Verified`, `Missing`, `Read-only`, `Disconnected`).
2. Add independent destination selection step in the First Installation Wizard.

### Priority 4: Test Suite & Release Verification
1. Author comprehensive integration tests in `tests/test_storage_and_file_manager.py`.
2. Rebuild canonical release package `Percival_v5.25-dev_*.zip` with updated manifest and SHA-256.
3. Deploy updated `.app` bundle to `/Applications/Percival Dev.app`, workspace, and project folders.
