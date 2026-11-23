# PERCIVAL v5.25-dev — RECOMMENDED ROADMAP & CLINICAL VALIDATION STRATEGY

**Document ID:** `AUDIT-ROADMAP-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Neuroimaging Scientist & Biostatistician  
**Scope:** Strategic Clinical and Algorithmic Roadmap for Future Phases  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & Strategic Context

Percival v5.25-dev has achieved architectural stability, strict patient-grouped nested cross-validation, cryptographic PHI vaulting, and fully offline local execution. All algorithmic components have been verified via synthetic cohorts and automated unit/integration suites.

However, **passing synthetic software tests does not establish clinical validity.** Synthetic lesion phantoms—while essential for deterministic software verification—cannot replicate the biological heterogeneity, scanner variability, and subtle vascular mimicry encountered in real-world human clinical practice.

This document outlines the required four-stage scientific roadmap to transition Percival from an experimental research pipeline to a clinically validated medical device.

---

## 2. Phase A: Multi-Center Clinical Validation Study

### 2.1 Study Design & Cohort Composition
To establish real-world sensitivity and specificity, Percival must be validated across a multi-center retrospective cohort of at least **$N = 200$ patients**:
1. **Target Population (Cerebral Amyloid Angiopathy & Stroke):**
   - $N = 75$ confirmed cerebral superficial siderosis (cSS) cases (stratified: 35 focal, 40 disseminated).
   - $N = 50$ cerebral amyloid angiopathy (CAA) patients with cortical cerebral microbleeds (CMBs) but no cSS.
   - $N = 40$ neurovascular mimics (acute convexity subarachnoid hemorrhage, superficial cortical vein thrombosis, prior intracerebral hemorrhage, dural arteriovenous fistulas).
   - $N = 35$ age-matched healthy elderly controls.

### 2.2 Multi-Vendor Scanner Heterogeneity
Scans must be sourced across multiple field strengths and MRI manufacturers:
- Siemens (1.5T, 3T: Prisma, Skyra, Vida)
- Philips (1.5T, 3T: Ingenia, Achieva)
- GE HealthCare (1.5T, 3T: Premier, Architect)
- Sequences: High-resolution 3D SWI, 2D T2* GRE, multi-echo susceptibility acquisitions.

---

## 3. Phase B: Clinical Reader Study Protocol

### 3.1 Inter-Rater Agreement & Reference Standard
A formal multi-reader multi-case (MRMC) study protocol:
- **Reference Standard:** Consensus ground truth established by a blinded panel of three senior board-certified neuroradiologists.
- **Reader Cohort:** Four independent radiologists (two academic neuroradiologists, two general radiologists).
- **Study Arms:**
  - Arm 1: Unassisted manual review (van Harten et al., 2023 criteria).
  - Arm 2: Percival-assisted review (candidates prioritized by Percival Score).
- **Primary Endpoints:**
  1. Patient-level diagnostic accuracy (focal vs. disseminated cSS vs. negative).
  2. Candidate-level sensitivity and false-positive rate per scan.
  3. Reader review time (minutes per scan).
  4. Inter-rater reliability (Fleiss' $\kappa$ / Cohen's $\kappa$).

---

## 4. Phase C: Algorithmic & Imaging Enhancements

### 4.1 3D Volumetric CNN (Depth-Resolved Patch Analysis)
- **Current Limitation:** Compression of the $24 \times 12 \times 8\text{ mm}$ patch into 2D MinIP maps discards the through-plane depth profile along the cortical normal $n$.
- **Proposed Enhancement:** Transition to a lightweight 3D CNN utilizing depthwise separable 3D convolutions. This preserves laminar distinction between true subpial deposits ($-0.5\text{ mm}$) and sulcal veins ($+1.5\text{ mm}$ in CSF) with fewer than 5,000 parameters.

### 4.2 Multi-Contrast Fusion (FLAIR & Phase Imaging)
- Integrate co-registered 3D T2-FLAIR to automatically rule out acute convexity subarachnoid hemorrhage (cSAH) and cortical vein thrombosis, which present with high sulcal FLAIR signal, unlike chronic cSS.
- Integrate high-pass filtered SWI phase images to distinguish paramagnetic hemosiderin (positive phase shift) from diamagnetic calcifications (negative phase shift).

---

## 5. Phase D: Regulatory & SaMD Compliance Roadmap

For future clinical deployment as Software as a Medical Device (SaMD):
1. **IEC 62304 Compliance:** Establish formal Software Development Life Cycle (SDLC) processes, software safety classification (Class B), and hazard traceability.
2. **ISO 14971 Risk Management:** Comprehensive Failure Mode and Effects Analysis (FMEA) for false negatives (missed disseminated cSS predisposing to anticoagulant-related hemorrhage) and false positives (unwarranted withholding of anticoagulation).
3. **FDA 510(k) / CE Mark Technical Documentation:** Compile verification & validation (V&V) reports, cybersecurity controls, and algorithm change protocols.

---

## 6. Prioritized Action Matrix

| Priority | Action Item | Target Milestone | Complexity |
|---|---|---|---|
| **P1** | Ingest and benchmark real clinical multi-center MRI scans | Phase 6 | High |
| **P2** | Conduct 4-radiologist MRMC clinical reader study | Phase 7 | High |
| **P3** | Prototype lightweight 3D depth-resolved patch CNN | Phase 8 | Medium |
| **P4** | Co-register 3D FLAIR for automated acute mimic rejection | Phase 8 | Medium |
| **P5** | IEC 62304 / ISO 14971 regulatory documentation package | Phase 9 | High |
