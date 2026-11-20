# Unified cSS candidate score: design before implementation, revision 3

Revision 3 adds the user's final corrections: cohort reconciliation, simplified model, nested calibration, suppression off by default, branch and module isolation (sections 0, 1, 3, 3b, 6, 11, 12).

This revision incorporates the user's eight revisions and the M-only cohort rule. Research decision support, not
diagnosis. **No model code is written, production is untouched, and nothing is committed.**

Items 1 and 2 (architecture audit and feature inventory) are in `PHASE1_AUDIT.md`, superseded where this revision
differs. In particular, the cohorts there are replaced by section 0, and v5.10 is a comparator only (section 3).

---

## 0. Cohort rule and manifest (M-only)

- **Eligible:** only MRI studies whose identifier starts with **M**. Every other identifier (P, PH, T, synthetic S
  copies) is **ineligible**. It contributes to nothing: not training, not feature selection, not thresholds, not
  calibration, not validation, not metrics, not model comparison, and not as a negative control or false-positive example.
- **Explicitly excluded:** P006 and PH6, together with every other P and PH study.
- **T01–T15** are re-exports of the **same patients** as M01–M15. They are excluded (non-M) and are also a duplicate
  identity: they must never appear next to their M twin.
- **Allocation** (fixed; a held-out study is never moved to development to increase the sample size):
  - **development:** M02–M11 (10 studies). Their reader calls already shaped v5.3 rules E12–E24 and the v5.10 model, so
    they are development only.
  - **held-out:** M01, M12–M15 and M16–M26 (16 studies). They are used only after the model and thresholds are frozen,
    and only once they have candidate-level expert labels.
- **Provisional manifest:** `cohort_manifest_PROVISIONAL.csv`, **95 identifiers**: 26 included (10 development, 16
  held-out) and 69 excluded, each with a reason, scoreability and source.
- **Reconciliation of 95 vs 74 (revision 3):**
  - the earlier container audit reported 95 = 33 identifiers with data in the container test base + 62 manifest entries
    without data there (all M, P and T studies live only on the user's Mac);
  - the 74-entry manifest lacked 21 container test-phantom variants (PH4S, PHA, PHC, PHG, PHI, PHK, PHL0, PHM, PHM0,
    PHO15, PHO25, PHQ1, PHQ2, PHR, PHS0, PHS1, PHS2, PHS4, PHT, PHU, PHX), created by `tests/run_tests.sh`;
  - they are now listed as excluded (non-M), so every previously discovered identifier is accounted for. Nothing is missing.
- **M18, M23 and M25 stay in the manifest** (held-out) with a scoreability note:
  - M18 and M23: T1 / SWI misaligned (4.25 / 3.16 mm). They are re-registered if possible. Otherwise they are recorded as
    unscoreable for registration-dependent features and are **not dropped**.
  - M25: no T1, so location / sulcal features are "unavailable"; signal, vessel and morphology are measurable.
- **Definitive manifest:** produced on the user's Mac by `cohort_audit.py`, which is read-only and changes nothing. It:
  - lists every identifier in raw/, data/, review/, labels/ and the app;
  - applies the M rule and the approved roles; an M study without a role becomes "unassigned" and is left out;
  - checks:
    - patient-level separation;
    - duplicate scans (same SWI content under two IDs);
    - T/M twins;
    - candidate counts and reader-call counts per study;
    - any non-M identifier inside label files;
  - writes `cohort_manifest.csv`. **Training cannot start until this manifest reports no problems** (revision 8).
- **Open verification items** (on the Mac):
  1. Did any rule or model see labels of M01 or M12–M15?
  2. Which export (the original M or the clean T re-export) currently sits under M01–M15?
  3. Are any M studies repeat scans of one patient?
  4. M18 / M23 registration failures and M25 (no T1) need resolution or must be recorded as unscoreable.
- **Enforcement in code:** every new script loads `cohort_manifest.csv` and refuses any identifier that is not
  `decision = include`. A test asserts that no non-M identifier reaches any dataset.

## 1. Branch baseline (revision 7)

- **Production = `css/main` = `phase1/safety-fixes` = commit `115721f`** (2026-11-16, "PROJECT_HANDOFF.md updated for
  v5.11.0-phase1"). The tag `baseline-v5.10.6` (`4b4059d`) is the state before Phase 1.
- Every later branch is experimental and **not inherited**:
  - `experimental/phase2-reference-audit` (`1c843d2`, app + reviewer + reference audit);
  - `experimental/3d-morphology-viewer` (`d7af64a`, v5.12);
  - `experimental/morphology-v513` (uncommitted v5.13).
- **Approved:** `experimental/unified-score` created from `115721f`. No experimental branch is merged into it, in whole or
  in part, except the single isolated import in section 12, after approval.
- **v5.13 dark core:** imported in isolation (section 12), not by merging.
- **Reviewer / app UI integration: deferred** until the scoring engine and its outputs are established. The mockup is a
  design artifact only.
- **Note:** the app on the user's Mac currently runs from `experimental/phase2-reference-audit`, not from production.

## 2. Anatomical scope (revision 3)

- **Target:** cortical superficial siderosis, meaning curvilinear hemosiderin along the superficial cortex / subarachnoid
  space of the **cerebral convexities and sulci, supratentorial** (Boston v2.0 / STRIVE-2 cSS definition).
- **Out of scope but not artifacts:**
  - infratentorial or classical (generalised) superficial siderosis;
  - acute convexity subarachnoid haemorrhage;
  - siderosis adjacent to a lobar ICH (handled by the existing ICH rules).
  
  Candidates there are labelled "other superficial siderosis pattern", **never** "artifact". They stay visible with a
  scope note and are never suppressed by this system.
- **No automatic anatomical exclusion** from deep / ventricular / infratentorial labels. Anatomy enters P(cSS) as
  features with a reliability status. The **E-anatomy detector is removed** from the suppression set. It may be shown
  as a scope note only, and only when label QC and registration QC are both ok.
- The existing production E-rules (E1–E24) are not changed and not used by the new engine.

## 3. Independent scoring engine (revisions 4 and 3-final): simplified initial model

- Built **independently** of v5.10. Not used as predictors: `vein_evidence`, `css_evidence`, `score`, `score_v3`,
  `score_v4`, `confidence_pct`, `review_tier`, `review_priority*`, `accept`, `struct_verdict`, or any composite.
  **v5.10 `confidence_pct` is a comparator only.**
- **Initial model: small ridge logistic regression with 5 predictors**, one per highest-priority group. Each is
  standardised on the training fold.

  | # | Predictor | Group | Unit before standardising |
  |---|---|---|---|
  | x1 | vessel continuity: traverse length of the vessel map through the candidate (0 if contact without traverse) | C | mm |
  | x2 | dark-core contrast: median c of the core | B | noise units |
  | x3 | median signed pial distance of the core | A | mm |
  | x4 | along-sulcus alignment: \|cos\| between the skeleton tangent and the local sulcal direction | E | – |
  | x5 | extracranial continuation length on the unmasked SWI | G | mm |

- **Unreliability indicators (3):** u_reg (registration QC not ok, or the pial relation is unstable under ± 1 voxel),
  u_core (no core, or core-unstable fraction > 0.5), u_res (morphology unresolved). An unreliable value is set to the
  training mean (contribution 0), and the indicator carries the information.
- **No interactions in the initial model.** The three pre-declared interactions are exploratory and are entered only if
  they improve nested LOPO log-loss beyond the bootstrap CI in **both** of two repeated nested runs.
- **GAM / splines: exploratory only.** Reported separately, never the primary model, until a reproducible improvement is
  shown.
- **Parameter count:** nominal = 1 intercept + 5 slopes + 3 indicators = **9**. The effective degrees of freedom of the
  ridge fit (trace of the hat matrix) are reported per fold and will be ≤ 9. With about 61 cSS events in M02–M11 this is
  about 7 events per nominal parameter, which is acceptable only with penalisation. If the count of cSS events after the
  cohort audit is lower, predictors x4 then x5 are dropped (in that declared order) to keep ≥ 10 events per nominal slope.
- **Stability check of the fit:** if the coefficient signs agree in < 80 % of outer folds, or the calibration slope is
  outside 0.7–1.3, the report states that the data do not support a stable calibrated model, and the viewer shows **no
  probability**, only measured features.
- **Group features not in the initial model** (D morphology, F Hessian, H size, I context) are computed and reported
  descriptively. They are candidates for a later model only.

## 3b. Calibration without leakage (revision 2-final)

Nested leave-one-patient-out on the development patients D (M02–M11):

```
for each outer patient k in D:
    T = D \ {k}                                         # training patients of this fold
    for each candidate penalty lambda:                   # inner LOPO inside T only
        for each inner patient j in T: fit ridge on T \ {j}, score j  -> inner out-of-fold scores s_in(T, lambda)
    lambda_k = argmin inner log-loss
    Platt_k  = fit (a_k, b_k) on the inner out-of-fold scores s_in(T, lambda_k) and their labels   # T only
    M_k      = ridge fit on all of T with lambda_k
    p_k      = Platt_k( M_k(candidates of k) )           # applied to the held-out patient only
outer predictions {p_k} -> discrimination and calibration (slope, intercept, Brier, reliability) with patient bootstrap
```

- No calibrator ever sees the patient it is applied to. Outer predictions are never used to fit anything.
- Thresholds for the shadow-mode decisions are explored on {p_k} only, and are not re-fitted on them.
- **Final frozen model:** the same procedure on all of D (λ and Platt from inner LOPO over D). sha256 recorded before any
  held-out label is opened.

## 4. Stability analysis (revision 5)

For every candidate, recompute the features and the final score under the following perturbations (on copies; the
original mask is never changed):

| Perturbation | Variants |
|---|---|
| mask | one-voxel erosion, one-voxel dilation (26-neighbour) |
| intensity | detector darkness threshold ± 0.25 noise units, i.e. a re-grown candidate from the same seed (computed by the new engine, not by changing production) |
| registration | label / pial-distance map shifted ± 1 voxel along x, y, z (6 variants) |

- **Reported per candidate, for each of geometry, vessel overlap / continuity, Hessian summary, sulcal relation and final
  P(cSS):** range, standard deviation, and whether the outcome (display / uncertain / suppress) changes.
- **Use:** instability **increases uncertainty and protects from suppression**. A candidate whose outcome changes under
  any perturbation, or whose P(cSS) range exceeds 0.2, can never be suppressed. Instability is **not** a feature
  against cSS.

## 5. Alternative-explanation detectors (suppression evidence)

These are separate from P(cSS); each confirms an alternative from independently measured facts.

**E-vessel (conservative "confirmed vessel")** is "confirmed" only if **all** hold:
1. the vessel map enters **and** exits the candidate (two contacts ≥ 2 mm apart, or a traverse);
2. the tube-compatible cross-section is **resolved** (≥ 2 slices and ≥ 2 voxels in-plane across);
3. ≥ 60 % of candidate voxels lie within one voxel of the vessel centreline;
4. the result is stable under all mask and registration perturbations;
5. there is no sheet-compatible region of ≥ 25 % of voxels (mixed objects are never confirmed).

Mandatory adversarial tests (new phantoms, not PH6):

| Case | Expected outcome | Critical failure |
|---|---|---|
| small cortical vein (r 0.4–0.8 mm) | not confirmed (unresolved) or possible | – |
| parallel veins | possible | – |
| partial vein / cSS overlap | **never confirmed** | cSS suppressed |
| surface vein | confirmed only if criteria 1–5 hold | – |
| incomplete vessel map (gaps) | not confirmed | – |
| blooming-related sheet-like vein | not confirmed | – |
| thin / curved / fragmented cSS next to a vein | **never confirmed** | cSS suppressed |

**E-extracranial:** the dark band continues ≥ 5 mm outside the brain mask on the **unmasked** SWI, connected to the
candidate, stable under perturbation.

**E-skull-interface:** the candidate lies in an air–bone zone **and** shows a field-gradient band pattern (parallel to the
interface, no cortical conformity). **Skull proximity alone never counts.**

There is **no** E-anatomy detector (section 2).

## 6. Outcomes and thresholds (revisions 1 and 6)

```
DISPLAY-prioritised  P(cSS) >= t_pos                                        (ordering only; nothing is removed)
SUPPRESS             P(cSS) <= t_excl  AND an alternative detector "confirmed"
                     AND no protective flag  AND suppression enabled
DISPLAY-uncertain    everything else, including every moderate-probability candidate
```

- **Protective flags:**
  - morphology unresolved;
  - registration QC not ok;
  - outcome or P(cSS) unstable under perturbation (section 4);
  - mixed object;
  - core-unstable fraction > 0.5;
  - any input group of the alternative detector unavailable;
  - out-of-scope pattern (section 2).
- **t_pos only orders the list.** It never removes anything (revision 6).
- **False exclusion is defined at two levels (revision 1):**
  - **candidate level:** genuine cSS candidates suppressed / all genuine cSS candidates;
  - **patient level:** patients with ≥ 1 suppressed genuine cSS candidate / patients with ≥ 1 genuine cSS candidate.
  - Also reported: the change in patient cSS score (0–4) when suppressed candidates are removed.
- **Uncertainty:**
  - **patient-cluster bootstrap** (resampling patients with their candidates, 2,000 replicates) for both rates;
  - as a sensitivity analysis, an exact Clopper–Pearson bound at patient level (independent units);
  - the bootstrap upper bound is unreliable when there are few events, so the reported upper bound is the **larger** of
    the two;
  - counts are always reported: number of patients, number of genuine cSS candidates, number suppressed.
- **Target: upper 95 % bound ≤ 2 % at candidate level and at patient level.** t_excl is the largest value meeting this on
  development out-of-fold predictions. It is then **confirmed on the frozen held-out set**.
- **Suppression is permanently disabled by default (revision 3).** It stays in shadow mode until independent patient-level
  evidence meets the target. The current held-out cohort cannot establish it.
  - Honest expectation: zero false exclusions among n patients gives an exact upper bound of 3 / n. Showing ≤ 2 % at
    patient level needs about **150 held-out patients with cSS**, far more than M01 and M12–M26 (16 studies).
  - So with the current data **suppression will remain in shadow mode.** Decisions and reasons are recorded for every
    candidate; nothing is hidden.
- **Switches** (all independent, all off by default):
  - `CSS_USCORE=1` computes features, score and decisions;
  - `CSS_USCORE_SHOW=1` shows them in the viewer;
  - `CSS_USCORE_SUPPRESS=1` hides suppressed candidates, and refuses unless the threshold file records held-out
    confirmation meeting the target.
- **Never permanent:** suppressed candidates stay in the outputs with reason, model version and inputs hash, in an audit /
  recovery view with a logged **Restore**.

## 7. Feature dependency and redundancy (development data only)

- Within groups, Spearman |ρ| > 0.8 is reduced to one feature; VIF is reported across groups.
- "Tubular" has three views kept apart:
  - vessel continuity (C) is the only view allowed to feed E-vessel;
  - Hessian (F) and mask morphology (D) enter P(cSS) only.
- Group ablation (nested LOPO Δ log-loss with CI) shows whether each group, I in particular, adds independent information.

## 8. Feature priorities

Unchanged order:

1. C vessel split (proximity / contact / overlap / continuity / alignment);
2. G extracranial continuation;
3. B signal with dark core;
4. A location (with ± 1-voxel ranges);
5. E along-sulcus trajectory;
6. F Hessian summary;
7. D morphology (resolvability status; weak);
8. H size;
9. I context.

The percentages in the brief are development priorities, not coefficients.

## 9. Data and annotation requirements

- **Label codes:** C2 / C1 (definite / probable cSS), V2 / V1 (definite / probable vessel, with subtype), A (artifact,
  with subtype), N (other structure), S (other superficial siderosis pattern, out of scope), U (indeterminate).
  Optionally per candidate: an outline of the underlying structure and of the visible blooming extent. The detector mask is
  never ground truth.
- **Readers:** a second reader on ≥ 30 % of held-out patients; agreement reported with kappa and patient-bootstrap CIs.
- **Held-out labelling** of M01, M12–M15 and M16–M26 is needed before any held-out claim.

## 10. Validation design

- **Development:** nested LOPO on M02–M11.
- **Held-out:** frozen model and thresholds (sha256 recorded before the held-out labels are opened), run once on M01,
  M12–M15 and M16–M26.
- **Metrics:**
  - discrimination and calibration (patient-bootstrap CIs);
  - comparison with v5.10;
  - the two-level false exclusion (section 6);
  - workload (candidates per patient displayed, uncertain, suppressed);
  - stability.
- **Strata:** size, lobe, slice thickness (1.5 T 3 mm vs 3 T), morphology status, vein-adjacent / attached.
- **Adversarial phantoms** (section 5 and the brief's list): new, frozen before running; software and mechanism tests only.

## 12. v5.13 dark-core import (isolated, revision 4-final)

**Focused code review** of `scripts/css_morph3d_v2.py` (uncommitted, branch `experimental/morphology-v513`):

- **Needed:** only `decompose(cand, img, vox, shell=(2.0, 5.0), r_peak=2.0)` (about 30 lines) and the constant `S26`.
- **Dependencies:** `numpy` and `scipy.ndimage` only. It does **not** use `css_morph3d` (v5.12), `cKDTree`, skimage, the
  v5.13 morphology functions, or the phantom generators.
- **Not imported:** `normal_tensor` (A2, abandoned), `resolvable_voxels` / `describe` (gate weakly calibrated),
  `thickness` (chord fix gave no improvement), `inplane`, `mst_length`, `context`, the v5.12 module, `tests/morph_phantoms.py`,
  `morph_v513/*`.
- **Review findings to carry over as known limits:**
  1. The noise σ comes from the MAD of a 2–5 mm shell. On real SWI that shell mixes cortex, CSF and white matter, so σ may
     be inflated and c deflated (untested on real data).
  2. The core may extend one voxel outside the candidate (reported as `core_inside_candidate`).
  3. A thin second band near a stronger one can be lost (PH6 #1, tram-track).
  4. About 35 % of blooming remains in the core, and about 33 % of core voxels are unstable (v5.13 held-out).
  5. Fewer than 20 shell voxels returns an error (status "unavailable").

**Proposed import:**

| New file on `experimental/unified-score` | Content |
|---|---|
| `unified_score/core_decompose.py` | a verbatim copy of `decompose()` + `S26`, a provenance header (source path, sha256 of the source file `css_morph3d_v2.py` at the time of copying, date), no other code |
| `tests/check_core_decompose.py` | **new independent tests** with their own small generator (fresh seeds and shapes, not the v5.13 development or held-out sets): flat band, tube, two adjacent bands, low contrast (expect "unavailable"), shell too small (expect error); assertions on core-inside-candidate, low-contrast handling, determinism, input arrays unchanged |

The v5.13 module and branch stay uncommitted and untouched.

## 11. Implementation plan (after approval)

1. **Branch** `experimental/unified-score` from `115721f`. Run `cohort_audit.py` on the Mac; continue only with a clean
   manifest.
2. `unified_score/features.py`: groups A–I with (value, status). Read-only on detector outputs; refuses non-included IDs.
3. `unified_score/stability.py`: the perturbation set of section 4.
4. `unified_score/alternatives.py`: E-vessel, E-extracranial, E-skull-interface, with adversarial tests.
5. `unified_score/model.py`: ridge LR (+ splines), nested LOPO, Platt calibration, contributions, model card, v5.10
   comparison.
6. `unified_score/decide.py`: three outcomes, protective flags, shadow mode, threshold file, audit records.
7. **Reports:** per-candidate explanations (markdown / xlsx) and the 12 post-implementation deliverables, with numbers only
   from runs that exist.
8. **Viewer: deferred** until the engine and its outputs are established (revision 4-final).
9. **Tests:** every feature, detector and decision rule; the M-only enforcement; the adversarial phantoms.

**Where things run:** code and tests here; feature extraction, fitting and evaluation on the Mac with codes-only exports.

## Production status (checked at revision 3)

- `css/main` = `115721f8ee0431d6aca4d5aee8b84f0c0d78da3f`, unchanged: fetched, and `git diff 115721f css/main` is empty.
- No commit, push, merge or branch creation has been made for this project.
- The working tree is on `experimental/morphology-v513` (uncommitted v5.13 + audit files). Production files are not
  modified by it.

## Final checkpoint: approval requested for

1. The reconciled manifest (95 identifiers; 26 included).
2. Nested calibration (section 3b).
3. The simplified initial model (section 3).
4. The isolated v5.13 import (section 12).

After approval: create `experimental/unified-score` from `115721f` and start with `cohort_audit.py` on the Mac.
