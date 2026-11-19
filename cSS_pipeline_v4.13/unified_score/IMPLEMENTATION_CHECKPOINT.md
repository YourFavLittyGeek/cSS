# Unified cSS score: implementation checkpoint

EXPERIMENTAL research software. Not for clinical use. Nothing here is a diagnosis.
Nothing is committed, pushed or merged. Production is unchanged.

## 1. Branch
- `experimental/unified-score`, created from `115721f8ee0431d6aca4d5aee8b84f0c0d78da3f` (= `css/main`).
- It is a separate worktree at `/home/user/unified-score`. The v5.13 work stays uncommitted on `experimental/morphology-v513`.
- No branch was merged or cherry-picked. Only `decompose()` and `S26` were copied verbatim, with the source hash recorded.

## 2. Status: what ran here and what did not
- **Ran here:** the whole engine is implemented and tested on synthetic data.
- **Not run here:** this container holds no patient data. So the development fit, the nested validation, the cohort metrics and the v5.10 comparison on M02–M11 have **not been run**. They need the commands in section 8, on the Mac.
- **No number in this checkpoint is a performance result.**

## 3. File inventory (all new; no tracked file modified)
| File | Role |
|---|---|
| `unified_score/uscore/common.py` | versions, `Cohort` (M-only; development / held-out roles), `LabelAccess` (held-out labels refused outside held-out mode; every access logged), registration state |
| `unified_score/uscore/core_decompose.py` | verbatim v5.13 `decompose()` + `S26`, provenance hash; `decompose_experimental()` wrapper (copies; original candidate kept; masked-voxel preparation; output labelled experimental) |
| `unified_score/uscore/features.py` | x1–x5: definitions, three-state reliability, `FEATURE_SPEC` (unit, range, inputs, reliability, missing data, failure modes) |
| `unified_score/uscore/detectors.py` | surface-vein, extracranial-continuation and skull-interface detectors (support / against / reliability / unresolved / status) |
| `unified_score/uscore/perturb.py` | 16 perturbations; stability summary; instability → protective flag only |
| `unified_score/uscore/model.py` | ridge logistic regression (IRLS), effective df, nested LOPO, inner-fold Platt, bootstrap CIs, coefficient stability, fallback, ordering cut |
| `unified_score/uscore/decision.py` | protective conditions, three categories, suppression record / audit view / restore (**disabled**) |
| `unified_score/uscore/pipeline.py` | read-only study loading, crops, extract / train / score / held-out evaluation, per-candidate reports |
| `unified_score/uscore/report.py` | cohort report (development and held-out sections separate) |
| `unified_score/run_unified.py` | CLI: `extract`, `train`, `score`, `report`, `heldout HASH` |
| `unified_score/cohort_audit.py` | Mac-side read-only audit: per-group scoreability, test-base refusal, noise-fixture detection |
| `unified_score/reconcile/*` | `reconcile_cohort.py`, `shift_sensitivity.py`, reconciliation CSVs and report, import diff |
| `unified_score/cohort_manifest_RECONCILED.csv` | final machine-readable manifest (108 identifiers) |
| `unified_score/CHANGES_DURING_DEVELOPMENT.md` | every definition or threshold changed during development, and why |
| `unified_score/DESIGN_BEFORE_IMPLEMENTATION.md`, `PHASE1_AUDIT.md`, `cohort_manifest_PROVISIONAL.csv` | earlier design (revision 3), kept for the record |
| `tests/check_core_decompose.py` | dark-core import tests (thin, adjacent, curved, fragmented, unstable, masked edge, regime table) |
| `tests/check_uscore_features.py` | unit tests per predictor and reliability state |
| `tests/uscore_synth.py`, `tests/check_uscore_adversarial.py`, `tests/check_uscore_seeds.py` | 17 adversarial scenes; 5-seed sweep |
| `tests/uscore_synthbase.py`, `tests/check_uscore_pipeline.py` | guards, model mechanics, leakage test, end-to-end on a synthetic `SYN` base |
| `tests/run_uscore_tests.sh` | runs all of the above |
| `unified_score/output/*` | test outputs, synthetic cohort report and example reports (all marked SYNTHETIC) |

## 4. Cohort
Full detail: `reconcile/REPORT_COHORT_RECONCILIATION.md`; reproduce with `reconcile_cohort.py`.
- **108 identifiers.** The earlier 95 missed 13 identifiers present only in the container.
- **The 33 / 62 / 21 split:**
  - 33 = phantoms present in both the container and the manifest. The 21 added variants are a subset of these 33.
  - 62 = the 53 manifest-only identifiers + 9 M-named random-noise app fixtures.
- **Final cohort:** 26 M studies.
  - development M02–M11;
  - held-out M01, M12–M26;
  - everything else excluded, each with a reason.
- **M18 and M23** (label shift 4.25 / 3.16 mm): unreliable for surface distance and for sulcal alignment, assessed separately in a synthetic shift test; also for vessel continuity and extracranial continuation. Core contrast stays scoreable.
- **M25** (no T1): anatomy comes from SynthSeg on the SWI, so location, sulcal, vessel and extracranial features are coarse. Destrieux / recon-all features are unavailable.
- **Data-quality issue:** the container holds noise fixtures with patient names (M16–M21, M24–M26). The audit refuses to run on test bases and flags any such fixture.

## 5. Features
`features.py` docstring and `FEATURE_SPEC` give the exact definitions.

| # | Feature | Unit | Becomes unreliable when |
|---|---|---|---|
| x1 | vessel continuity: sum of the two largest reaches of the vessel centreline entering and exiting the candidate; 0 if it only touches | mm | registration not ok / marginal |
| x2 | median dark-core contrast | noise units | no core, or > 50 % of core voxels unstable |
| x3 | median signed pial distance of the core | mm | label shift > 1.0 mm, SWI-only anatomy, or unverified |
| x4 | surface conformity: line 1 − \|t·n\|, sheet \|m·n\| | 0–1 | label shift > 0.5 mm, no clear shape, or incoherent surface normal |
| x5 | dark continuation beyond the brain mask on the unmasked SWI, through non-void tissue | mm | registration |

- An unreliable or unavailable value **contributes exactly 0** (tested).
- Feature unit tests: 22 / 22 pass.

## 6. Dark-core import
- Verbatim function hash re-checked by the tests; the module depends only on numpy and scipy.
- `check_core_decompose`: 0 FAIL, 3 known limits:
  - a weak band next to a strong one is lost (recall 0.16);
  - the core fragments;
  - verbatim `decompose()` on masked input recovers only 3 % of the deposit (fixed in the wrapper).
- Regime table: core recall ≥ 0.8 only when the deposit contrast is ≥ ~5 noise units.

## 7. Model and training procedure
- **Primary model:** z = b0 + Σ b_j x_j over the five predictors; ridge penalty from an 11-value log grid (0.01–1000).
- **Nested LOPO:**
  1. The inner leave-one-patient-out runs on the training patients only and chooses the penalty.
  2. Platt scaling is fitted on the inner out-of-fold scores.
  3. The model is refitted on the training patients and applied to the outer patient.
- **Leakage test:** flipping the outer patient's labels leaves its calibrated predictions unchanged (pass).
- **Fallback:** if events / slopes < 10, drop x4, then x5.
- **Probability withheld** when coefficient signs agree in < 80 % of folds or the calibration slope is outside 0.7–1.3. The report then shows the raw score with a warning.
- **Ordering cut:** the outer-fold sensitivity 0.9 point. It orders the reading list only.
- **Freezing:** the final model is frozen and hashed. `train` refuses held-out studies.

## 8. Nested validation results
**Not run: no patient data here.** On the Mac:
```
cd <branch checkout>/cSS_pipeline_v4.13
CSS_BASE=~/css_project python unified_score/cohort_audit.py        # measured scoreability
CSS_BASE=~/css_project python unified_score/run_unified.py extract  # all 26 studies; no labels
CSS_BASE=~/css_project python unified_score/run_unified.py train    # M02-M11 only; nested LOPO; freezes the model
CSS_BASE=~/css_project python unified_score/run_unified.py score
CSS_BASE=~/css_project python unified_score/run_unified.py report   # ~/css_project/uscore/COHORT_REPORT.md
```
Do **not** run `heldout` until you approve it.

The synthetic end-to-end test exercises the whole path. Its AUC of 1.0 comes from trivially separable synthetic data and is **not a result**.

## 9. Alternative detectors (synthetic)
Status counts below are from the 5-seed sweep.

| Scene | Detector | Confirmed |
|---|---|---|
| surface vein | surface_vein | 4 / 5 |
| extracranial artefact | extracranial_continuation | 5 / 5 |
| skull-interface artefact | skull_interface | 5 / 5 |
| vein parallel to a sulcus | surface_vein | 0 / 5 (not confirmed / protected: uncertain) |

- The detectors were **revised on these scenes** (`CHANGES_DURING_DEVELOPMENT.md`), so these are not independent results.

## 10. Adversarial results
- 17 scenes × 5 seeds = 85 runs: **0 critical failures**. No genuine cSS reached "high-confidence alternative" or a suppression proposal.
- **During development there was one critical failure:** a subarachnoid cSS band 1.3 mm off the pial surface was confirmed as a skull artefact. The fix was a ≥ 3 mm off-cortex requirement. It passed afterwards; the margin is about 0.6 mm against a cSS in 2.4 mm of CSF.
- Every candidate is preserved (36 / 36 reports in the synthetic base).
- Suppression is never applied; audit records carry the model hash, input hash and feature reliability.

## 11. Known limitations and unresolved issues
1. **No real-data result yet.** All thresholds (detector criteria, reliability limits, perturbation tolerances) are PROVISIONAL, set from first principles and synthetic scenes.
2. **Detectors were developed on the adversarial scenes.** Only the four scenes added afterwards are a partial independent check.
3. **Thin structures lose x2:** core instability makes x2 "unreliable" for about half of thin synthetic cSS. Such candidates go to "uncertain"; they are not lost.
4. **Vein confirmation is rare by design:** it needs a resolved cross-section. Real thin surface veins at 0.5–1 mm will mostly be "unresolved".
5. **x5 and bone:** x5 does not follow continuation across a bone void, and blooming adds about 1–1.5 mm to its length.
6. **x4:** it does not separate a surface vein running along a sulcus from cSS.
7. **Dark core:** about 35 % blooming retained; it fragments; it is biased near the mask edge without the wrapper's preparation. This could also affect earlier v5.13 figures computed on masked images (unverified).
8. **Statistics:** about 61 development events for 5 slopes. A ≤ 2 % false-exclusion bound needs ~150 independent cSS patients. Suppression stays off.
9. **Comparator:** v5.10 was fitted on the same M02–M11 calls, so its development AUC is in-sample. A fair comparison is only possible on held-out data.
10. **GAM / spline / interaction comparisons:** not implemented in this stage. They are exploratory only.
11. **Runtime:** about 1.5 s per candidate with perturbations.

## 12. Held-out labels
- None accessed. This container has none, and no held-out command was run against real data.
- `LabelAccess` refuses held-out labels in development mode and logs every attempt (tested).
- The only held-out evaluation ran on the synthetic SYN base, to test the mechanism.

## 13. Production
`css/main` = `115721f`; `git diff 115721f css/main` is empty. No tracked file in the worktree is modified.

## 14. Git diff against 115721f
Untracked additions only: `unified_score/` (package, CLI, audit, reconciliation, documents, outputs) and eight files in `tests/`. Modified tracked files: none.
