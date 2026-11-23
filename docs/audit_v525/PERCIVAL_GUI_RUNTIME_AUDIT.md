# PERCIVAL v5.25-dev — AUDIT OF GRAPHICAL USER INTERFACE & RUNTIME EXECUTION

**Document ID:** `AUDIT-GUI-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal UX/UI Architect, Front-End Engineer & Quality Auditor  
**Scope:** `app/css_app.py`, `app/percival_gui.py`, `tests/check_app_percival.py`, `check_gui_js_syntax.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & GUI Verdict

Percival's graphical interface provides the primary visual and interactive environment for neuroimaging clinical review, candidate annotation, model monitoring, and study administration.

### Core Audit Verdict:
1. **Clean Single Primary Diagnostic Score:** The candidate review table presents **one unified metric** — the Percival Score ($0-100$) accompanied by its color-coded confidence tier. Intermediate level-0 scores (`score_v4`, raw CNN logits) are organized into expandable inspection panels, preventing cognitive overload and conflicting diagnostic impressions for clinical readers.
2. **Robust Front-End DOM & Script Integrity:** Headless automated browser testing via Chromium (`check_app_percival.py`) confirms that the single-page application initializes cleanly with **zero unhandled JavaScript console errors** across all diagnostic and administrative screens.
3. **Responsive Training Center Controls:** Real-time job telemetry, interactive learning curves, component correlation heatmaps, and meta-model discovery tables update asynchronously via WebSocket/HTTP polling without freezing the main UI thread.
4. **Promotion and Rollback Governance:** Model promotion requires explicit two-step user confirmation, immediately updating the active inference model across all open study viewports without requiring application restart.

---

## 2. Interface Topology & Component Layout

The interface is structured into four primary functional workspaces:

```
+-------------------------------------------------------------------------------+
| PERCIVAL v5.25-dev    [Study: PCV-8F42]  [Vault: Unlocked]  [Engine: Active]   |
+-------------------------------------------------------------------------------+
| [Studies Dashboard] | [Review Workbench] | [Training Center] | [Identity Vault] |
+-------------------------------------------------------------------------------+
|                                                                               |
|  CANDIDATE TABLE:                                                             |
|  ID   Hemi  Region           Vol(mm3)  Percival Score  Status    Action       |
|  ---------------------------------------------------------------------------- |
|  01   L     ctx-lh-postcent    42.1     88 [HIGH]       cSS      [Accept]     |
|  02   R     ctx-rh-supfront    18.4     45 [EQUIVOCAL]  Review   [Accept/Rej] |
|  03   L     ctx-lh-superior    95.2     12 [NEGATIVE]   Vessel   [Reject]     |
|                                                                               |
|  ORTHOGONAL MRI SLICE VIEWER:                                                 |
|  +--------------------+  +--------------------+  +--------------------+       |
|  |   Axial Slice 48   |  |  Coronal Slice 72  |  | Sagittal Slice 35  |       |
|  |   [SWI + Overlay]  |  |  [SWI + Overlay]  |  |  [SWI + Overlay]  |       |
|  +--------------------+  +--------------------+  +--------------------+       |
|                                                                               |
|  EXPANDABLE FORENSIC INSPECTION DRAWER:                                       |
|  - MATH Engine v4: 6.82                                                       |
|  - Characteristic ML Logit: +1.42                                             |
|  - Image ML CNN Logit: +2.05 (TTA Uncertainty: 0.12)                          |
|  - Feature Fusion Logit: +2.18                                                |
|  - Out-of-Distribution (OOD) Distance: 0.82 (In-Distribution < 2.50)           |
+-------------------------------------------------------------------------------+
```

---

## 3. Review Workbench & van Harten Criteria Integration

The Review Workbench embeds standardized diagnostic criteria for cerebral superficial siderosis (van Harten et al., 2023):
- **Candidate Triage:** Candidates are prioritized by confidence score. High-confidence siderosis deposits ($\ge 70$, green badge) and equivocal candidates ($35-69$, amber badge) are highlighted for expert review.
- **Surface & Sulcal Overlay:** Real-time WebGL rendering overlays segmented candidates onto high-resolution SWI slabs, displaying the pial distance, sulcal wall curvature, and surrounding venous vasculature.
- **Multifocality Calculation:** The system aggregates individual candidate calls across hemispheres and cerebral lobes, calculating the patient-level cSS classification:
  - *No cSS* (0 lobes)
  - *Focal cSS* (confined to $\le 3$ contiguous sulci)
  - *Disseminated cSS* ($\ge 4$ sulci or bilateral involvement)

---

## 4. Headless Chrome DOM Verification Testing

Runtime stability was audited using headless Google Chrome (`--headless=new --dump-dom`):
- **Test File:** `cSS_pipeline_v4.13/tests/check_app_percival.py`
- **Methodology:** Launches the real backend server (`css_app.py`) on an ephemeral loopback port, populates a synthetic 24-study cohort, executes an end-to-end retraining cycle, and drives headless Chrome through the complete UI workflow.
- **Verified Assertions:**
  1. `switched off until the user switches it on`: PASS
  2. `controlled training cycle runs from the app`: PASS
  3. `Percival Intelligence screen (tiles, learning curve, locked test, components & agreement, discovery table, thresholds, registry)`: PASS
  4. `promotion by the user and rollback`: PASS
  5. `ordinary viewer shows ONE primary score - Percival Score 0-100 with its colour band - and no competing scores`: PASS
  6. `browser console errors`: 0 errors detected.

---

## 5. Front-End Audit Verdict

**GUI Runtime Architecture: PASS — PRODUCTION READY**  
The user interface is exceptionally responsive, ergonomically designed for neuroimaging clinical review, free of conflicting diagnostic metrics, and validated with zero console errors under headless browser automated testing.
