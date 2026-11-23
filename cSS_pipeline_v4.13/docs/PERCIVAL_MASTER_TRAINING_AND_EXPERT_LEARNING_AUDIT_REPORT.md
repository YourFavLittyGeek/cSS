# PERCIVAL MASTER FORENSIC AUDIT: TRAINING RECONSTRUCTION, EXPERT-ANNOTATION LEARNING, STORAGE MIGRATION & IMPLEMENTATION

**Mission ID:** `PERCIVAL-MASTER-IMPLEMENTATION-REPAIR-2026`  
**Date:** November 22, 2026  
**Auditor:** Principal Architect, Neuroimaging Scientist & Mathematical Auditor  
**Baseline:** Percival v5.25-dev (`feature/v5.25-final-master-delivery`)  

---

## 1. Executive Summary

A comprehensive forensic audit of the Percival code repository, GUI frontend, unified engine, and machine-learning pipelines was conducted. While core neuroimaging, ALBUS candidate detection, and preliminary storage engines exist, critical gaps and disconnections were identified:

1. **Training Cycle Failure (`FAILING`)**: `Start Training Cycle` fails immediately with `KeyError: 'features'` in `percival_gui.py` (`selection()` and `candidates_of()`) due to unguarded dictionary lookups on uninitialized settings. Furthermore, when insufficient expert labels exist, the engine abruptly raises an unhandled `ValueError`, marking the entire run as crashed rather than providing a structured, informative diagnostic state.
2. **Training Centre Terminology & Structure (`PARTIALLY IMPLEMENTED / DISCONNECTED`)**: Internal technical jargon ("Mathematical detection", "Unsupervised score", "Characteristic features", "ML fusion", "Meta-learning", "Raw confidence") is displayed without clinical explanation. Standard vs. Advanced Research view toggling is absent, and the 14 required structural sections are collapsed into prototype summaries.
3. **Candidate-by-Candidate Review & Clinical Vocabulary (`PARTIALLY IMPLEMENTED`)**: Basic candidate voting exists, but the requested clinical alternative classification vocabulary (cortical/pial vessel, prominent vessel/vein, vascular flow-related signal, other vascular structure, susceptibility artifact, calcification, etc.) is incomplete.
4. **Missed-Lesion Learning (`DISCONNECTED`)**: The MRI viewer provides pen and rectangle drawing for missed cSS (`scripts/review_web.py` and `scripts/review_web.html` writing to `review/{sid}_missed.csv`), but these annotations are **never ingested into Pensieve**, never loaded into `label_summary()`, and completely omitted from candidate detection training datasets.
5. **Study-Level Review Completion (`PARTIALLY IMPLEMENTED`)**: The system marks studies as reviewed without formally tracking whether the reviewer completed the missed-lesion assessment, creating the severe scientific risk of conflating a study with zero ALBUS candidates with a true cSS-negative study.
6. **Task-Specific Training Eligibility Engine (`PARTIALLY IMPLEMENTED`)**: Eligibility checks in `uengine/percival/eligibility.py` use a single generic pipeline rather than isolating candidate classification (cSS vs. mimics/vessels), lesion detection/localization (including reviewer-drawn missed lesions), and segmentation.

---

## 2. Requirement-by-Requirement Implementation Matrix

| Requirement | Current Status | Source Location | GUI Location | Root Cause / Defect | Required Correction |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Start Training Cycle Execution** | `FAILING` | `app/percival_gui.py:438` | Percival Intelligence › Training Center › Start button | `KeyError: 'features'` when `CTX["SET"]["features"]` is missing; `ValueError` crash on empty labels | Guard dictionary lookup; handle insufficient data gracefully with diagnostic guidance |
| **User-Facing Terminology** | `PARTIALLY IMPLEMENTED` | `app/percival_view.js` | Percival Intelligence header & cards | Internal engineering terms shown directly | Add Standard vs. Advanced Research View; map terms to clinical equivalents |
| **14 Training Centre Sections** | `PARTIALLY IMPLEMENTED` | `app/percival_view.js` | Percival Intelligence › Training Center | Collapsed into monolithic cards; sections 1-14 not fully modularized | Implement all 14 discrete sections with real telemetry |
| **Candidate-by-Candidate Review** | `FULLY IMPLEMENTED` | `scripts/review_web.py`, `scripts/review_web.html` | Reviewer Window (`#dec`) | Buttons exist for Y, V, N, A, U, H | Retain candidate-level review; preserve original model prediction |
| **Alternative Finding Vocabulary** | `PARTIALLY IMPLEMENTED` | `scripts/review_web.html:940` | Reviewer Window (`#dec .chip`) | Limited subtype chips (`VS`, `VC`, `VT`, `NI`, `CA`) | Expand to full 10-class clinical classification vocabulary |
| **Missed-Lesion Drawing & Coordinates** | `PARTIALLY IMPLEMENTED` | `scripts/review_web.py:462` | Reviewer Window (Pen/Rect tool, `<kbd>X</kbd>`) | Saves to `review/{sid}_missed.csv` with affine coordinates, but disconnected from Pensieve | Connect `missed_edit` to `Pensieve.record_missed_lesion()` |
| **Missed-Lesion Training Ingestion** | `DISCONNECTED` | `app/percival_gui.py:label_summary` | Backend only | `label_summary()` ignores `*_missed.csv`; detection models never see missed lesions | Ingest missed lesions into `label_summary` and dataset builder as positive examples |
| **Study-Level Review Completion** | `PARTIALLY IMPLEMENTED` | `scripts/review_web.py:finalSave` | Reviewer Window (Final Save dialog) | Does not distinguish candidate-level negative from study-level negative | Require explicit missed-lesion assessment status before study-level review completion |
| **Task-Specific Eligibility Engine** | `PARTIALLY IMPLEMENTED` | `uengine/percival/eligibility.py` | Training Center › Eligibility | Evaluates meta/char/image components, lacks explicit detection & segmentation rules | Add `detection` and `segmentation` component rules and validation |
| **Training Dataset Builder** | `PARTIALLY IMPLEMENTED` | `uengine/percival/datasets.py` | Training Center › Datasets | Builds manifests for meta-model, lacks missed-lesion positive examples | Add missed lesions with provenance to dataset builder |
| **Leakage & Patient Isolation** | `FULLY IMPLEMENTED` | `uengine/percival/datasets.py`, `uengine/pensieve.py` | Backend & verification tests | Grouped CV and locked test split by patient hash | Maintain patient partition isolation |
| **External HDD Transfer Workflow** | `FULLY IMPLEMENTED` | `uengine/vault.py`, `app/css_app.py` | Setup Wizard & Settings | Preview, copy, verify, rollback, volume UUID binding | Connect directly to external volume `/Volumes/Percival` |
| **Dedicated File Manager Screen** | `FULLY IMPLEMENTED` | `app/file_manager_view.js`, `uengine/file_manager.py` | Primary Sidebar (`<button data-v="files">`) | 15 categories, browse, multi-select, copy, move, rename, delete, archive, restore | Fully operational in application bundle |
| **Working Directory Migration** | `FULLY IMPLEMENTED` | `uengine/working_dir_migration.py` | Settings › Storage & Locations | Transactional migration, journal, active-job check, rollback, non-destructive retention | Operational in application bundle |
| **20 Settings Sections** | `FULLY IMPLEMENTED` | `app/css_app.html`, `app/css_app.py` | Primary Sidebar (`<button data-v="set">`) | All 20 sections mapped and operational | Keep operational |
| **First-Installation Launch State** | `FULLY IMPLEMENTED` | `app/setup_gui.py`, `app/css_app.html` | Startup Router | Clean-slate when `setup_done.json` is absent | Guaranteed routing to `#setup` on fresh launch |
| **Candidate Re-detection & Calling** | `FULLY IMPLEMENTED` | `app/processing_manager.py`, `app/percival_gui.py` | Setup Step 2 & Processing | Centroid & volume fingerprinting carries calls over re-detected candidates | Enabled and verified |
| **19-Point Startup Health Check** | `FULLY IMPLEMENTED` | `uengine/health.py` | Startup & Settings | Checks integrity, paths, permissions, Pensieve, Vault | Operational on every launch |

---

## 3. Root-Cause Analysis of Training Centre Failures

### 3.1 Unhandled `KeyError: 'features'`
In `cSS_pipeline_v4.13/app/percival_gui.py`:
```python
def selection():
    S = CTX["SET"]
    ex = set(S.get("learner_exclude", []))
    arch_ok = S["features"].get("train_include_archived", True)  # <-- CRASHES IF S["features"] IS NOT INITIALIZED!
```
When `CTX["SET"]` is passed without an explicit `"features"` key or when features are defaulted, `S["features"]` immediately raises `KeyError: 'features'`. The exact same defect occurs in `candidates_of(sid)` at line 465.

**Correction:**
Use safe dictionary access:
```python
arch_ok = S.get("features", {}).get("train_include_archived", True) if isinstance(S.get("features"), dict) else True
```

### 3.2 Abrupt `ValueError` on Insufficient Expert Labels
In `_train(reason)`:
```python
if not sel:
    raise ValueError("no study has an eligible expert label yet - Training Center lists every study and the reason it is not used")
...
if min(c1, c0) < 3 or len(dv) < 10:
    raise ValueError(f"not enough expert labels to learn yet...")
```
When raised, `_train()` catches the exception as an unexpected failure, transitions `JOB` into `state="failed"`, and records a failed run record in `runs/runNNN.json`.

**Correction:**
Instead of marking the run as an unexpected system failure:
1. Provide proactive pre-flight checks in the GUI and backend.
2. If triggered when data is insufficient, transition `JOB` into a structured `state="insufficient_data"` (or informative idle) with clear guidance:
   - Exactly how many expert-confirmed cSS and rejected/mimic labels exist vs. how many are required.
   - List of studies awaiting review with one-click links to open them in the Reviewer.
   - Clarification that unlabelled MRI can still undergo candidate detection (ALBUS) without being treated as negative.

---

## 4. Architectural Integration Plan

1. **Pensieve Memory Extension (`uengine/pensieve.py`)**:
   - Add `missed_lesions_memory` table and methods (`record_missed_lesion`, `get_missed_lesions`).
   - Add `study_review_status` table and methods (`get_study_review_status`, `set_study_review_status`).
   - Add `get_status()` method for memory telemetry.

2. **MRI Viewer Connection (`scripts/review_web.py` & `scripts/review_web.html`)**:
   - In `missed_edit(action="add")`: forward missed lesion to `Pensieve.record_missed_lesion()`.
   - In `save()`: forward candidate calls to `Pensieve.record_expert_annotation()`.
   - Expand `QA` and `FINELBL` to include all requested clinical alternative classifications.
   - In `finalSave()`: record formal study review status (candidate review complete + missed lesion assessment complete).

3. **Backend Training Ingestion (`app/percival_gui.py`)**:
   - In `label_summary()`: read `review/{sid}_missed.csv` and Pensieve missed lesions.
   - In `_examples()`: emit missed lesions as positive examples (`albus_detected=False`, `y=1`) eligible for detection/localization models.
   - In `selection()` and `candidates_of()`: fix `KeyError: 'features'`.
   - In `_train()`: handle insufficient data gracefully.

4. **Training Centre UI (`app/percival_view.js`)**:
   - Add `Standard View` vs. `Advanced Research View` toggle.
   - Implement user-facing terminology replacements.
   - Implement the 14 discrete structural sections with live data bindings.

5. **Testing & Verification**:
   - Execute unit tests for Pensieve, storage, and training.
   - Run complete end-to-end acceptance script validating candidate review, missed-lesion drawing, training dataset building, and model cycle.
