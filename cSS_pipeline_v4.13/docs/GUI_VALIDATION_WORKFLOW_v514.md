# v5.14-gui: graphical validation workflow (branch `experimental/unified-gui`)

EXPERIMENTAL research software. Nothing here is a diagnosis. Every step below runs from the app: no Terminal command is needed after installation.

## 0. Install and launch
1. Install the package as usual. `install.sh` now also installs:
   - the unified package;
   - the reviewer page and the 3-D viewer script (a pre-existing gap: they were never installed before);
   - the synthetic robustness suite;
   - the real build stamp.
2. Open **cSS Pipeline.app**.
3. The header shows `pipeline v5.14.1-gui (experimental/unified-gui)`.
4. Test protocol T1 shows the build commit.

## 1. The end-to-end graphical workflow (your 13 steps)
| # | What you do | Where in the app |
|---|---|---|
| 1 | Open the app | Dock / cSS Pipeline.app |
| 2 | See the M-only cohort: development M02–M11, held-out (labels locked) | **Unified (experimental)** tab → left panel "Cohort" |
| 3 | Run the cohort audit | step **1 Cohort audit** → *Run cohort audit*: checks, problems, per-study registration, excluded identifiers with reasons |
| 4 | Extract candidate features | step **2 Features** → *Extract all included studies* (progress bar, Stop, Log) |
| 5 | Review missing / unreliable measurements | step **3 Reliability**: per study × feature reliable / unreliable / unavailable, reasons, flagged list |
| 6 | Train on M02–M11 | step **4 Train & validate** → *Train (development only)* (confirmation) |
| 7 | Inspect nested validation and calibration | step 4: estimate type **CROSS-VALIDATION**, out-of-fold calibration plot, slope / intercept / Brier, AUC with patient-bootstrap CI |
| 8 | Review coefficients and contributions | step 4: coefficients across outer folds with sign agreement; step 6: per-candidate contributions |
| 9 | Freeze the model | step **5 Model & freeze** → *Freeze model…* (type **FREEZE**) |
| 10 | Process a patient normally | **Add patients** → queue → it finishes as before. With "Run after each patient: On", the unified step runs **afterwards**, in the background (pending → running → completed / failed) |
| 11 | Unified results beside the detector results | step **6 Candidates** (category, score, reliability, detectors, perturbation table); **Results** tab columns `unified_*`; **Review**: "Unified score (experimental)" card under the detector's AI card |
| 12 | 3-D morphology | step 6 → *Open in reviewer (3-D + layers)*, or Review → *Open 3-D analysis*: layers **Dark core (experimental)** and **Blooming / support** |
| 13 | Export | step **8 Export** → unified Excel (+ cohort report); the original results workbook is unchanged |

## 2. Test protocol (screen C)
**Unified (experimental) → Test protocol.**
- *Run automatic checks* covers T1–T4, T5a, T6–T13. T5, T14 and T15 are ticked by you (Pass / Fail with a note).
- *Save test record* writes `results/test_record_<time>.xlsx` + `.json`.
- Recommended order on the Mac:
  1. process 1–2 real M patients with the unified score OFF;
  2. run the checks (T2–T4 then have data);
  3. turn the score ON;
  4. run steps 1–6;
  5. run step 7 (synthetic suite);
  6. run the checks again;
  7. tick T5, T14 and T15 while using the reviewer;
  8. save the record.

## 3. Safety properties (each covered by an automated test)
| Property | How | Test |
|---|---|---|
| Original detector, rules, 0–4 score unchanged | no detector / scorer file modified; T4 compares installed files with reference hashes | `check_app_unified`, T4 |
| Unified step can never block the pipeline | runs after "done" and the results save, in a background thread and subprocess, 15-minute limit; failure only sets status "failed" | T9 (injected failure), `check_app_unified` |
| Opt-in | `unified_score` off by default; switch in the Unified tab with confirmation | `check_app_unified` |
| No suppression | `SUPPRESSION_ENABLED = False`; any audit record says "not_applied" | T6, `check_uscore_*` |
| Reader files untouched | unified writes only to `uscore/` and the results folder; T11 hashes review/ and work/ files around a real run | T11, `check_app_unified` |
| Blind reading protected | unified card and core / support layers are hidden in a validation read until the final save | `check_app_unified` (code path), T14 manual |
| Held-out labels protected | no GUI route at all; the CLI also needs a frozen model AND a written authorization file (`uscore/heldout_authorization.json`, exact statement, name, date, model hash). A hash or a GUI confirmation alone is refused | T13, `check_uscore_pipeline` |
| Estimates kept apart | cross-validation labelled as such; v5.10 shown only in a separate "not comparable" box; held-out section "Not run" | report + screenshots |
| Synthetic never mixed with M | synthetic demo / tests use SYN studies with their own manifest; a synthetic model is refused for a real cohort, and the reverse | `check_uscore_pipeline` |

## 4. Synthetic demo mode (screenshots / tests only)
`CSS_USCORE_DEMO=1` + `CSS_USCORE_MANIFEST=<synthetic manifest>` before starting the app. A red **SYNTHETIC DEMO** banner is shown on every Unified page, and every export file name contains `SYNTHETIC`. Never set these on the real project.
