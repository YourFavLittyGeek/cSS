# Training readiness report (2026-11-28)

## 1. Is the next real training cycle permitted?
**Yes, as an internal development experiment, once the new build is installed** — the software and scientific blockers found by the audit are
corrected (see IMPLEMENTATION_REPORT rows 1–15). It is **not** yet evidence of generalisation: that needs the sealed fresh test cohort.
The app itself now decides with the training gate (PERCIVAL › Training Center › readiness card); the stages below are what it checks.

| Gate stage | Blocks training | What it needs | User's project (read-only aggregate, 2026-11-28) |
|---|---|---|---|
| data imported | yes | studies with a candidate list | 79 candidate lists |
| expert review completed | yes | completed blind expert reads + a designated expert | 72 studies with a final review file; expert role set (2026-11-25) |
| ground truth available | yes | development ≥ 3 cSS, ≥ 3 not-cSS, ≥ 10 eligible labels | ds001 (48 studies): 33 cSS in 16 development patients - met |
| training dataset eligible | yes | the above + verified/declared patient identities | identities declared at import (MRN grouping) |
| validation dataset eligible | no (acceptance only) | ≥ 5 test patients with cSS candidates and ≥ 5 without | split v002: 15 test patients; v001 test had cSS candidates in only 4 patients → acceptance will most likely still fail on this gate |
| model training permitted | — | all blocking stages + local learning on | on (v001 was trained) |

Before the next cycle the user must (in the app):
1. Install the new build. At its first start the identity vault is encrypted (keep the recovery key offline; empty the Trash afterwards).
2. Declare the next milestone (M2: "validation 2.0 - stratified shared folds, within-fold calibration, paired selection, marks in 3-D").
   M1 is used: v001 consulted the locked test group under M1, and every consultation now uses the milestone.
3. Decide the split plan already chosen on 2026-11-26 ("mix"): System › Locked test group › Send new patients to development
   (the project is still on the random policy).

## 2. What the next cycle can and cannot show
- **Can**: honest development estimates (nested, within-fold AUC; informative flag), the component comparison (ALBUS / NOX / LUMOS) on the
  same folds, a calibration that cannot reverse the order, an early-warning check on the current test group.
- **Cannot**: a reliable test AUC, sensitivity or specificity — 4–5 test patients with cSS; patient-level CIs are flagged unreliable below 10
  patients per class. Acceptance will most likely refuse ("candidate-level test AUC rests on 4 patients…"); that is the intended outcome.

## 3. Real data and annotations still required
| Need | Why | Amount (approximate; reassess with a learning curve) |
|---|---|---|
| more reviewed patients with cSS | stable model choice and calibration | development ≥ 40–50 patients with cSS (now 16) |
| the fresh sealed test cohort | the only independent test | 30 with cSS + 30 without, consecutive (System › Locked test group) |
| a second expert reader on a subset | inter-reader agreement (κ), credibility of the reference | ≥ 20 studies, blinded |
| expert reference masks | segmentation accuracy (Dice, HD95, boundary F1) | 20–30 positive patients, edit the dashed extent outline; 10 double-read |
| re-marking of missed cSS drawn before 2026-11-25 | those marks were never saved (HANDOVER) | per study |

## 4. Updated roadmap (next steps, each needs the user's go)
1. User: install, milestone M2, split policy → train once → read Model Center (development numbers, informative flag).
2. ALBUS version 2 (detector-side audit items: mm-based neighbourhoods, one rule set for SWI-only studies, the `_dil` guard, mm call matching,
   coronal/sagittal QC) with a recorded non-inferiority comparison on frozen development studies.
3. Expert mask editing in the reviewer (brush on the dashed extent) → first segmentation accuracy report.
4. LUMOS: footprint-channel ablation, within-scanner reporting; verify that the ALBUS tuning cases are not in the test cohorts.
5. GUI items left open (Activity shows PERCIVAL cycles, quit dialog, read-only health check, global error overlay, `/api/percival/identity`).
6. Storage (shared Microsoft 365) and Windows remain future projects (audit documents 05, 06); not started.
