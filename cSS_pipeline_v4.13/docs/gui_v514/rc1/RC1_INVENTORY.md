# Experimental application RC1: feature inventory (honest status)

**Branch:** `experimental/unified-gui`, uncommitted, on top of production `3bbfa14` (css/main, unchanged).

**Evidence levels used below:**
- **T** = automated test passes;
- **V** = seen working in the real app GUI here, on synthetic data (headless Chromium on Linux; screenshots `R01…R14`);
- **M** = still needs you on the Mac;
- **C** = still needs clinical judgement on real studies.

Nothing below was run on real MRI data, on macOS, or with a real FreeSurfer installation.

## A. Implemented and integrated in the RC app
| Feature | Evidence | Still needed |
|---|---|---|
| **Separate experimental app.** `cSS Experimental.app`, own folder `~/cSS_experimental`, port 8810, bundle id; the launcher refuses `~/css_project`; the bundle installs its own pipeline with a build stamp | T, V (launcher run on Linux) | **M**: Gatekeeper first open, osascript dialogs, conda / FreeSurfer discovery, window |
| **Processing tab: recognition of studies on disk.** Includes studies never added through the app (Terminal-era) | T, V (R02–R05) | M, C (your real folder layout) |
| **Bring in studies read-only from another project.** Copy + sha256 record; FreeSurfer symlinked and never written; reader files to `historical/`; source unchanged (every file's content and modification time checked) | T (11 checks), V | M (Finder alias, disk space) |
| **MRI identity.** sha256, dimensions, voxel size, orientation; FreeSurfer version and `-no-v8`; previous detection version | T, V (R04) | C: real FreeSurfer `build-stamp.txt` format |
| **Compatibility per stage, six categories.** Plus not-applicable / missing / needs re-run, each with evidence; dependency order; FreeSurfer completeness, IsRunning, T1 match; registration QC; detection input hashes; QC low confidence; unified older than candidates; header / gzip integrity | T, V | C: whether the rules flag your real studies sensibly |
| **Confirm (adopt) earlier outputs.** Records them as the first run, with no file change | T, V | — |
| **Fresh detection with anatomy reuse.** New run = real detect_css (production flags) + surface features (when surfaces exist) + AI score + unified score / explanations; FreeSurfer, registration and labels reused | T, V (real detector on synthetic SWI) | **M + C: run on your studies, check run time and candidates** |
| **Versioned runs.** Archive before every run; failed run → previous outputs restored, own outputs kept in `failed_outputs/`; interrupted run (app closed) → marked at restart, outputs restored; Resume; Make active with confirmation | T, V (restart test in the E2E) | M |
| **Normal pipeline recorded too** (Add patients / Patients → Re-run): previous outputs archived, restored on failure, FreeSurfer never renamed | T (unit-level; the real pipeline is not run here) | **M**: one Re-run of an app patient |
| **Morphology resolution classes.** Unresolved / acquisition-limited; the 3-D panel explains why, and says unresolved ≠ absent | T (100-case matrix), V (R14, real detector on a 2.4 mm-slice synthetic study) | C: 1.5 T 3 mm studies |
| **3-D morphology viewer.** Surface / voxels, local shape, Hessian, thickness, skeleton, cross-sections, layers incl. dark core / support | T, V (R13, R14) | M: WebGL on the Mac GPU (seen here only in software rendering) |
| **Five-predictor unified score + explanations.** x4 named "surface conformity", reliability states, reviewer card, Results columns | T, V (reports regenerated after the new run) | Note: **no model is fitted** (training is off by your instruction), so on your data the unified output is detector categories + predictor values, without a fitted probability |
| **Export / share / backup safety.** Verified local folder only; Desktop / Documents / cloud refused (real path checked); warning + confirmation every export | T (16 checks), V (R10, R11) | M: iCloud folder names on your Mac |
| **Local-only.** Servers on 127.0.0.1, no external scripts; the whole E2E ran with every outside connection blocked and logged, and none was attempted | T, V | **M: your Wi-Fi-off run** |
| **Held-out protection.** Unchanged from cycle 2: LabelAccess, authorization, recomputed hash | T (24 checks) | — |
| **Unified tab (audit, features, train / freeze workflow, test protocol)** | T (from cycle 1/2, synthetic demo mode) | Not to be used for clinical training now |

## B. Implemented but not part of the app (by design)
- `scripts/audit_local_dataset.py`: standalone read-only audit; awaits your review.
- x4b sulcal-axis descriptor: exploratory, computed, not shown and not in the model.
- `app/mac/cSS Pipeline.app` **inside this branch**: the production-style bundle. Its app copies are synced with this branch, but **don't install it from this branch**: it targets `~/css_project`. Use only `tools/build_experimental_app.sh`.

## C. Partially implemented
- **Re-running anatomy / registration from the Processing tab:** not available. It is routed to Patients → Re-run, which needs the raw series. Linked studies have no raw series in the experimental project, so their anatomy / registration can only be reused, not redone (stated in the app).
- **Integrity checks:** headers, gzip streams, JSON, CSV header, LTA. Uncompressed NIfTI voxel data are not fully read, and only three FreeSurfer files are checked.
- **Provenance of Terminal-era outputs:** they can't be proven to belong to the current MRI, so they show as *unknown* until you confirm them.
- **Unified step in the normal pipeline:** runs after "done" (opt-in). In a Processing-tab run it is part of the run; in the normal pipeline its result isn't in the run's file archive.
- **Stopping a patient:** recorded as a failed attempt with outputs restored. Not tested with the real pipeline here.

## D. Tests pass, not visually verified on the target
- Everything Mac-specific:
  - Gatekeeper first open;
  - native window (pywebview) and Dock icon;
  - osascript folder / file pickers ("Choose…" buttons);
  - notifications;
  - caffeinate.
- Real FreeSurfer surfaces → surface_features in a new run (only stub surfaces here).
- Running both apps at the same time on one Mac.

## E. Not implemented (planned later, by your instruction)
- AI Learning & Review, the blinded pilot workflow (sketch v3), Model Laboratory, the local conversational LLM.
- Clinical model training.
- Code signing / notarisation of the app (unsigned: right-click → Open once).

## F. Known limitations
1. Unsigned app; macOS asks once.
2. The experimental project duplicates image / work files of linked studies (disk use). FreeSurfer is not duplicated.
3. The app has its own settings file: set FreeSurfer folder / licence, export folder and backup folder once.
4. The AI score and unified score are **not validated**; unified has no fitted model.
5. Thick-slice studies will often show *acquisition-limited* in the 3-D view. That is intended, and it's not evidence against cSS.
6. A changed rule in this branch: detection itself is the production code. The only change in `scripts/score_css.py` is a print-line fix (a crash when regions are numeric, which happens without the FreeSurfer colour table). Scores are unchanged.
7. Studies whose earlier outputs are incompatible (e.g. a different SWI) can't get a fresh detection from the Processing tab until anatomy / labels are re-run from the raw series.
8. The E2E ran on Linux with a fake conda and FreeSurfer-like stub files; real-data run times are unknown.
