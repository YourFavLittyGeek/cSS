# PERCIVAL — Integrated File Manager & Storage Management Guide

**Target Version:** PERCIVAL v5.25  
**Platform:** macOS Graphical User Interface & Headless Server  
**Modules:** `uengine/file_manager.py`, `app/css_app.py`, `app/percival_view.js`, `app/css_app.html`  

---

## 1. Overview & Interface Layout

PERCIVAL v5.25 introduces a fully integrated **Storage Dashboard & File Manager** embedded directly within the primary application interface (accessible via the **Data Vault & Storage** tab). 

The File Manager bridges clinical neuroimaging workflows with underlying macOS storage topology, giving researchers direct, transparent control over local NVMe SSD staging, external drive archival, and cryptographic data integrity without requiring manual terminal operations.

```
+-----------------------------------------------------------------------------------------+
| PERCIVAL — Data Vault & Storage Dashboard                                               |
+-----------------------------------------------------------------------------------------+
| [LOCAL SSD CAPACITY]                               [EXTERNAL DATA VAULT CAPACITY]       |
| Total: 494.4 GB | Free: 14.2 GB (97.1% Full)       Total: 1863.0 GB | Free: 1200.0 GB   |
| [██████████████████████████████░] EMERGENCY        [███████████░░░░░░░░░░░░░░░░░] OK    |
+-----------------------------------------------------------------------------------------+
| STUDY BROWSER & LIFECYCLE MANAGEMENT                                                   |
| Filter: [ All Studies | Staged | Archived | Synchronized | Drive Required ]            |
+-------------------+----------------+-------------+-----------------------+--------------+
| Study Identifier  | Modality       | Storage Size| Lifecycle Status      | Actions      |
+-------------------+----------------+-------------+-----------------------+--------------+
| SUBJ_042_BL       | T1w + SWI      | 1.84 GB     | SYNCHRONIZED          | [View] [Chk] |
| SUBJ_089_Y1       | T1w + GRE      | 1.42 GB     | STAGED                | [Archive]    |
| SUBJ_101_BL       | T1w + T2*      | 2.10 GB     | ARCHIVED              | [Stage SSD]  |
| SUBJ_004_Y2       | T1w + SWI      | 1.95 GB     | ARCHIVED — DRIVE REQ  | [Info]       |
+-------------------+----------------+-------------+-----------------------+--------------+
```

---

## 2. Real-Time Storage Capacity Telemetry

At the top of the interface, dual telemetry bars continuously report filesystem statistics for both storage domains:

1. **Local SSD Capacity Tile:**
   - Evaluates internal macOS APFS container capacity.
   - Live color-coded status badges:
     - `HEALTHY` (Green): `> 50 GB` free.
     - `WARNING` (Amber): `20 GB - 50 GB` free.
     - `CRITICAL` (Orange): `5 GB - 20 GB` free.
     - `EMERGENCY` (Red): `< 5 GB` free.
   - Recommended actions and one-click reclamation options when approaching threshold limits.

2. **External Data Vault Capacity Tile:**
   - Displays volume name, mount path, filesystem format (APFS / ExFAT / HFS+), and bound hardware Volume UUID.
   - Dynamic status indicator:
     - `CONNECTED & BOUND`: Green checkmark indicating full read/write readiness.
     - `DISCONNECTED / DEGRADED`: Amber alert notifying the operator that long-term storage is offline.

---

## 3. Study Lifecycle Status Badges

Each neuroimaging study cataloged in PERCIVAL displays a color-coded lifecycle status badge:

| Badge | Meaning & Storage Topology Location | Recommended Clinical Action |
| :--- | :--- | :--- |
| <span style="background-color:#0284c7; color:white; padding:2px 6px; border-radius:4px; font-size:11px;">LOCAL_ONLY</span> | Study exists only in local workspace; not yet staged or archived to vault. | Run analysis pipeline or archive to external vault. |
| <span style="background-color:#d97706; color:white; padding:2px 6px; border-radius:4px; font-size:11px;">STAGED</span> | Study is staged on internal high-speed SSD for processing or re-analysis. | Analysis ready; archive when complete. |
| <span style="background-color:#059669; color:white; padding:2px 6px; border-radius:4px; font-size:11px;">ARCHIVED</span> | Fully processed and stored on external Data Vault; local scratch removed. | Safe for long-term retention; stage to SSD if re-running. |
| <span style="background-color:#16a34a; color:white; padding:2px 6px; border-radius:4px; font-size:11px;">SYNCHRONIZED</span> | Identical, verified copies exist on both local fast SSD and external vault. | Optimal state for rapid interactive exploration. |
| <span style="background-color:#dc2626; color:white; padding:2px 6px; border-radius:4px; font-size:11px;">ARCHIVED — DRIVE REQ</span> | Stored on external vault, but the external physical drive is disconnected. | Connect physical external USB/Thunderbolt drive to access raw series. |

---

## 4. User Actions & Operations

Researchers can execute granular storage operations on individual studies or in bulk batches:

### A. Stage to Fast SSD (`stage_to_ssd`)
- **Use Case:** Preparing cold archived studies for computationally intensive re-analysis (e.g., re-running FreeSurfer segmentation with updated atlases or training Lumos CNNs).
- **Behavior:** Reads study assets from the external vault, verifies available local NVMe space, copies necessary anatomical files to `staging/<STUDY_ID>`, and transitions lifecycle state to `STAGED`.

### B. Archive to External Vault (`archive_to_vault`)
- **Use Case:** Moving completed study analyses, cortical surfaces, and derived biomarker maps from internal SSD to external storage to reclaim local space.
- **Behavior:** 
  1. Computes SHA-256 digests for all output files.
  2. Atomically writes files to `/Volumes/<VAULT>/PERCIVAL_VAULT/<STUDY_ID>`.
  3. Re-reads and confirms file integrity on the target drive.
  4. Updates Pensieve database record and sets lifecycle status to `ARCHIVED`.

### C. Verify Cryptographic Integrity (`verify_integrity`)
- **Use Case:** Quality assurance audits, regulatory compliance, and silent bit-rot detection.
- **Behavior:** Computes SHA-256 hashes of all stored NIfTI files, FreeSurfer mesh files, and JSON sidecars, comparing them against the original cryptographic signatures stored in the Pensieve provenance ledger. Displays `PASS` (Green) or `CORRUPTED` (Red).

### D. Clean Local Staging (`clean_staging`)
- **Use Case:** Immediate reclamation of internal Mac SSD headroom.
- **Safety Precondition:** Disabled unless the study is confirmed `SYNCHRONIZED` or `ARCHIVED` with verified checksums.
- **Behavior:** Removes heavy intermediate cortical meshes and temporary volumetric resamplings from local SSD while leaving the external vault pristine and metadata accessible in the GUI.

---

## 5. Navigating the Hierarchical Study Tree

Clicking the **View** button on any study opens the interactive modal file tree:

```
SUBJ_042_BL/
|-- raw/
|   |-- T1w_MPRAGE.nii.gz         (24.8 MB) [SHA-256: 7a8f...3d12]
|   `-- SWI_axial.nii.gz          (18.2 MB) [SHA-256: 9b2c...5e89]
|-- freesurfer/
|   |-- mri/
|   |   |-- orig.mgz              (12.1 MB)
|   |   |-- aparc+aseg.mgz        (3.4 MB)
|   |   `-- synthseg.nii.gz       (4.8 MB)
|   `-- surf/
|       |-- lh.pial               (5.6 MB)
|       `-- rh.pial               (5.6 MB)
|-- derivatives/
|   |-- css_surface_profile.json  (142 KB)
|   |-- nox_uncertainty_map.nii.gz(18.2 MB)
|   `-- lumos_gradcam.png         (890 KB)
`-- reports/
    |-- PERCIVAL_CLINICAL_REPORT.pdf (1.2 MB)
    `-- provenance_manifest.json     (18 KB)
```

From this view, operators can inspect individual file sizes, review cryptographic hashes, view DICOM acquisition parameters, or trigger targeted re-computation of specific algorithmic pipelines.
