# PERCIVAL — macOS Host-System Forensic Inventory & Storage Cleanup Recommendations

**Document Classification:** Forensic Systems Audit & Storage Reclamation Report  
**Host Platform:** macOS (Darwin Kernel 25.1.0, Apple Silicon aarch64, 36 GB Unified RAM)  
**Host User:** `tarabeah.selim`  
**Execution Mode:** STRICTLY READ-ONLY (No files have been deleted, moved, or modified)  
**Date:** November 22, 2026  
**Target Release:** PERCIVAL v5.25  

---

## 1. Executive Summary & Storage Emergency Alert

A comprehensive forensic audit of the host macOS storage architecture was conducted to identify disk bottlenecks, legacy research pipelines, virtual environment caches, and potential space reclamation targets.

### Critical Capacity Finding:
- **Total Mac SSD Storage:** `460 GiB` (`/dev/disk3s1` APFS Data container)
- **Currently Used Storage:** `410 GiB` (`97%` Capacity)
- **Available Free Space:** **`14.0 GiB`** (**`3.0%` free space — EMERGENCY TIER**)
- **Safety Threshold:** PERCIVAL requires at least `20.0 GiB` (ideally `> 50.0 GiB`) of headroom for concurrent FreeSurfer `recon-all` runs, SynthSeg deep learning inference, and temporary NIfTI co-registration buffers. At `14.0 GiB`, the system is in the **EMERGENCY TIER**, where unexpected OS-level swap pressure or large MRI batch imports risk disk exhaustion.

### Primary Space Reclamation Opportunity:
Forensic discovery identified **`38.2 GB`** of legacy research MRI workspaces, duplicate intermediate outputs, and candidate tables occupying local Mac SSD storage across three prior directories (`~/css_project`, `~/cSS_experimental`, and `~/Percival_project`). 

Migrating these completed research datasets to the external **PERCIVAL DATA VAULT** will recover **`38.2 GB`**, immediately raising host Mac SSD free headroom from **`14.0 GB`** to **`52.2 GB`** (`> 11%` free space, exiting Emergency mode).

---

## 2. Strict Safety & Non-Destructive Ingestion Guarantee

> [!CAUTION]
> **READ-ONLY GUARANTEE:** This document is an informational forensic audit. **Zero automated file deletions or moves have been executed.**
> 
> - Original patient MRI acquisitions, expert radiologist labels, ground truth candidate annotations, and neural network checkpoint weights **must never be deleted**.
> - Any action listed under `SAFE TO CLEAN AFTER APPROVAL` or `MOVE TO VAULT` requires explicit manual execution or confirmed user authorization via the PERCIVAL Settings & Migration GUI.

---

## 3. Comprehensive Host-System Forensic Inventory

### Summary by Classification Category

| Category | Description | Count | Total Size | Primary Recommendation |
| :--- | :--- | :---: | :---: | :--- |
| **`KEEP`** | Active code, conda environment, system files | 5 items | `3.6 GB` | Maintain on Mac SSD without alteration |
| **`MOVE TO VAULT`** | Legacy MRI datasets, candidates, reviews | 3 workspaces | `38.2 GB` | Ingest and archive to external Data Vault |
| **`ARCHIVE`** | Historical version snapshots & devlogs | 11 items | `660 MB` | Compress to cold archive or external vault |
| **`SAFE TO CLEAN AFTER APPROVAL`** | Pip caches, conda package archives, dev caches | 4 items | `110 MB` | Purge after user approval |
| **`MANUAL REVIEW`** | Local LLM weights, downloads, personal files | 2 items | `18.5 GB` | Review manually for retention |

---

### Detailed Inventory Table

| Path | Size | Last Modified | Category | Justification & Recommended Action |
| :--- | :---: | :---: | :---: | :--- |
| `/Users/tarabeah.selim/percival_code_only` | `776 MB` | Nov 22, 2026 | **`KEEP`** | **Active PERCIVAL Git Repository.** Holds production source code, unit tests, and build infrastructure. Retain on fast Mac SSD. |
| `/Users/tarabeah.selim/miniforge3` | `2.1 GB` | Nov 22, 2026 | **`KEEP`** | **Active Python Runtime & Conda Environments.** Hosts the `css` Python 3.11 environment with PyTorch, Nibabel, Scikit-Learn, and SciPy. Retain. |
| `/Users/tarabeah.selim/.zshrc` / `.config` | `< 5 MB` | Nov 22, 2026 | **`KEEP`** | **Shell and Host System Configuration.** Critical for PATH, environment variables (`FREESURFER_HOME`). Retain. |
| `/Users/tarabeah.selim/.percival_vault_config.json` | `< 1 KB` | Nov 22, 2026 | **`KEEP`** | **PERCIVAL Volume Mount Config.** Stores external Data Vault mount pointer and volume UUID. Retain. |
| `/Users/tarabeah.selim/css_project` | **`25.0 GB`** | Nov 22, 2026 | **`MOVE TO VAULT`** | **Historical Research Pipeline Run.** Contains 64 legacy study folders, SynthSeg brain segmentations, Darboux frame caches, and candidate CSVs. **Action:** Ingest candidate calls into PENSIEVE memory; transfer raw MRI files to external Data Vault (`/Volumes/PERCIVAL_VAULT/studies/`). Expected space recovery: **`25.0 GB`**. |
| `/Users/tarabeah.selim/cSS_experimental` | **`9.2 GB`** | Nov 21, 2026 | **`MOVE TO VAULT`** | **Experimental Research Cohorts.** Contains secondary SWI / MP2RAGE test volumes and older pipeline outputs. **Action:** Archive to Data Vault (`archive/cSS_experimental/`). Expected space recovery: **`9.2 GB`**. |
| `/Users/tarabeah.selim/Percival_project` | **`4.0 GB`** | Nov 21, 2026 | **`MOVE TO VAULT`** | **Previous Percival Milestone Workspace.** Holds duplicate processing folders and candidate logs. **Action:** Archive to Data Vault. Expected space recovery: **`4.0 GB`**. |
| `/Users/tarabeah.selim/percival_code_only/.percival_backup_*` (9 folders) | `653 MB` | Nov 22, 2026 | **`ARCHIVE`** | **Pre-Mission Local Safety Snapshots.** Nine timestamped milestone backups generated during autonomous development phases (`135501` through `205600`). **Action:** Move to external Data Vault `backups/` directory or compress into a single `.tar.zst` archive. |
| `/Users/tarabeah.selim/cSS_ml_work` | `6.3 MB` | Nov 20, 2026 | **`ARCHIVE`** | **Historical ML Notebooks & Scripts.** Contains exploratory prototype scripts and model performance notes. **Action:** Archive to repository `docs/historical_ml/` or Data Vault. |
| `/Users/tarabeah.selim/Percival_backups` | `1.1 MB` | Nov 22, 2026 | **`ARCHIVE`** | **Archived Settings & Manifests.** Lightweight metadata backups. Move to Data Vault `backups/`. |
| `/Users/tarabeah.selim/.claude` | `102 MB` | Nov 22, 2026 | **`SAFE TO CLEAN AFTER APPROVAL`** | **Claude Code Session Transcripts & Caches.** Temporary agent conversation logs and file caches from earlier sessions. **Action:** Safe to purge if past session playback is no longer required. |
| `/Users/tarabeah.selim/.cache` | `8.0 MB` | Nov 22, 2026 | **`SAFE TO CLEAN AFTER APPROVAL`** | **User Pip & Font Caches.** Temporary download caches. Safe to purge via `pip cache purge`. |
| `/Users/tarabeah.selim/.conda/pkgs` | `4.0 KB` | Oct 2, 2026 | **`SAFE TO CLEAN AFTER APPROVAL`** | **Conda Package Tarballs.** Safe to clean via `conda clean --all`. |
| `/Users/tarabeah.selim/.lmstudio` | **`18.0 GB`** | Nov 22, 2026 | **`MANUAL REVIEW`** | **LMStudio Local LLM Weights.** Large GGUF language model weights downloaded for local LLM inference. Independent of PERCIVAL. **Action:** User manual review; if models are no longer needed or can reside on an external drive, user may delete or relocate them to reclaim 18 GB. |
| `/Users/tarabeah.selim/Downloads` | Variable | Nov 22, 2026 | **`MANUAL REVIEW`** | **Browser Downloads.** Temporary installers, papers, zip files. User should review and empty periodically. |
| `/Users/tarabeah.selim/.Trash` | Variable | Nov 22, 2026 | **`MANUAL REVIEW`** | **macOS Trash Can.** Emptying via Finder `Empty Trash` will immediately reclaim deleted block storage on APFS. |

---

## 4. Storage Reclamation Execution Roadmap

### Step 1: Connect External Storage
Attach an external SSD or HDD formatted with APFS or Mac OS Extended (Journaled) with at least `100 GB` of free space, designated as `/Volumes/PERCIVAL_VAULT`.

### Step 2: Ingest Legacy Datasets via PERCIVAL Migration Engine
1. Launch PERCIVAL:
   ```bash
   cd /Users/tarabeah.selim/percival_code_only/cSS_pipeline_v4.13
   ./run.sh
   ```
2. Navigate to **Research › Percival Intelligence › Data Vault**.
3. Click **Scan for Legacy Research Data**. The engine will enumerate studies across `~/css_project` and `~/cSS_experimental`.
4. Select **Option C (Import into PENSIEVE Memory)** for candidate review tables and **Option D (Archive to Data Vault)** for raw MRI volumes.
5. Click **Execute Migration**. The engine verifies SHA-256 checksums before and after transfer.

### Step 3: User Approval for Local Reclamation
Once verified by PERCIVAL:
```bash
# Optional manual cleanup only after verified Data Vault archival:
# rm -rf /Users/tarabeah.selim/css_project
# rm -rf /Users/tarabeah.selim/cSS_experimental
# rm -rf /Users/tarabeah.selim/Percival_project
```
**Net Space Reclaimed:** **`38.2 GB`**.  
**Resulting Mac SSD Free Space:** **`52.2 GB`** (Status: **HEALTHY**).

---

## 5. Verification Sign-Off

- **Audit Methodology:** Strictly read-only filesystem traversal using POSIX `stat`, `diskutil info`, and APFS container queries.
- **Safety Guarantee:** Zero modifications were made to any user data or research files.
- **Auditor:** Autonomous Principal Systems Architect & Clinical Software Quality Auditor.
