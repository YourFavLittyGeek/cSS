# Review cycle 2: checkpoint (branch `experimental/unified-gui`, uncommitted)

- **Not done:** no commit, push, merge, tag or archive; no held-out evaluation run.
- **Production:** `css/main` = `3bbfa14`. Detector, rules and 0–4 score unchanged: the nine detector / scorer / registration files are identical to 3bbfa14.

## 1. Files (30, against the state before this cycle)
Full list: `FILES_changed_cycle2.txt`. Complete diff: `DIFF_cycle2_vs_previous_state.patch` (1,640 lines; screenshots and test logs excluded).

| Area | Files |
|---|---|
| Resolution confidence (Task 1) | M `scripts/css_morph3d.py`, M `scripts/morph3d_view.js`, M `scripts/review_web.html`, A `tests/check_morph3d_resolution.py`, M `tests/check_morph3d.py`, M `tests/check_morph3d_api.py`, A `docs/gui_v514/morph3d_resolution_matrix.csv`, M `docs/INVESTIGATION_morph3d_cylinder.md` |
| Feature audit (Task 2) | M `unified_score/uscore/features.py` (exploratory x4b, not in the model), M `tests/check_uscore_features.py`, A `docs/FEATURE_DICTIONARY_v514.md`, M `app/unified_view.js` + M `scripts/review_web.html` (x4 labelled "surface conformity") |
| Held-out protection (Task 3) | M `unified_score/uscore/common.py`, M `model.py`, M `pipeline.py`, M `unified_score/cohort_audit.py`, M `app/gui_protocol.py`, A `tests/check_heldout_protection.py`, A `docs/HELDOUT_PROTECTION_AUDIT_v514.md` |
| Protocol clarity (Task 4) | M `app/gui_protocol.py`, M `app/unified_view.js` |
| Failure / timeout / restart (Task 5) | M `app/unified_gui.py`, M `tests/check_app_unified.py` |
| Bug found by the audit tests | M `unified_score/uscore/detectors.py`: extracranial detector crashed when stability was not measured |
| Suites / docs | M `tests/run_tests.sh` (resolution matrix added), M `tests/run_uscore_tests.sh` (held-out tests added), M `CLAUDE.md` |
| Bundle copies | M `app/mac/…/Resources/app/{gui_protocol.py, unified_gui.py, unified_view.js}` (identical to `app/`) |
| Regenerated test outputs | M `unified_score/output/COHORT_REPORT_SYNTHETIC_TEST.md`, `adversarial_seeds.json` |

## 2. Task 1: morph3d resolution confidence
See `docs/INVESTIGATION_morph3d_cylinder.md`.
- **Principle:** a shape class is claimed only when the directions it depends on span more than two samples (k ≥ 2.2). k comes from the physical extent along the neighbourhood's own axes divided by the anisotropic sampling interval along that axis.
- **New outcomes:** *unresolved* (too small for the grid) and *acquisition-limited* (only the coarse slice direction prevents the decision).
- **Sheet versus unresolved tube:** a sheet whose thickness is below resolution must be at least 2× wider than the thickness the slices could hide.
- **Results:**

  | Test | Result |
  |---|---|
  | 100-case matrix (85 representable, 15 vanish under sampling) | **all pass** |
  | the original 0.5 × 0.5 × 2 mm cylinder | now acquisition-limited (was 100 % sheet) |
  | original checks | pass, with the expectation changes documented in the files |

- **Four design iterations were needed**; each is recorded with its synthetic evidence.

## 3. Task 2: feature dictionary
See `docs/FEATURE_DICTIONARY_v514.md`.
- **x4 is not sulcal-axis alignment.**
  - Sheet mode (lies in the surface / sulcal wall) matches the intent.
  - Line mode measures only tangency to the surface. A synthetic line along a sulcus and one across a crown both give 1.00.
- **Proposed correction, for your decision:**
  - A: rename x4 to "surface conformity" (the GUI already says so);
  - B: replace line mode with the structure-tensor sulcal axis (implemented as exploratory `x4b`, not in the model: 1.0 along, 0.0 across, unavailable on a flat convexity).
- **Non-model descriptors:** all are listed in the dictionary.

## 4. Task 3: held-out protection
See `docs/HELDOUT_PROTECTION_AUDIT_v514.md`.
- **Fixed:**
  - authorization moved into `LabelAccess`;
  - the model hash is recomputed from the file content;
  - the model is re-verified before every read;
  - the label reader is now private;
  - training refuses a non-development boundary;
  - `cohort_audit.py` no longer opens held-out calls;
  - the protocol's integrity check no longer reads reader-file content.
- **Tested:** 24 negative tests pass, including "flipping every held-out label leaves the trained model identical" and "an edited model with its old hash is refused".

## 5. Task 4: protocol clarity
- **Display:** Screen C has separate "Automatic checks (AUTO)" and "Manual checks (MANUAL — you must confirm)" sections.
- **Naming:** T5a reads "3-D viewer files installed (does NOT test the viewer)" and T5 "3-D viewer works (you confirm)".
- **Guards (tested):**
  - automatic runs never set manual items;
  - automatic results cannot be overwritten by hand.

## 6. Task 5: test results (logs in this folder)
| Suite | Result |
|---|---|
| `run_uscore_tests.sh`: dark core, features (incl. x4 audit), 17 adversarial scenes, 5-seed sweep, pipeline, **held-out protection (new)**, **end-to-end GUI incl. failure / timeout / restart (new)** | all passed (`TEST_uscore.txt`) |
| `test_shell.sh` | passed |
| `run_tests.sh` (corrected harness), **first full run** | **FAILED** at `check_morph3d_api` (PH6 vein #6 now "unresolved"). Kept: `TEST_run_tests_attempt1_FAILED_morph3d_api.txt` |
| `run_tests.sh` after the documented expectation change for PH6 #6 | **ALL TESTS PASSED**: morph3d OK, morph3d_api OK, morph3d_resolution OK (`TEST_run_tests.txt`) |

**Failure-mode results (all through the real app, restarted with test-only settings):**
- **injected failure:** status "failed", patient still "done", results workbook present;
- **timeout:** a hung step is stopped at the 4 s test limit and reported as such;
- **app killed during a running step:** after restart it is "interrupted", never left "running";
- **integrity:** original inputs and reader files unchanged throughout.

**Integrity everywhere:** reader files are untouched by unified scoring (T11, `check_app_unified`).

**One earlier test result corrected this cycle:** the first restart test reported a pass condition ("pending") that did not exercise "running". It was fixed so that "running" is actually reached.

## 7. Screenshots (changed sections, synthetic demo)
- `C2_test_protocol_auto_vs_manual.png`: automatic and manual sections; manual items "not run".
- `A4b_train_validate_x4_note.png`: the x4 note on the validation page.
- `B1b_reviewer_unified_card.png`: the x4 label in the reviewer card.
- `B2b_3d_resolution_classes.png`: the 3-D panel with the new resolution classes, legend and rule.

## 8. Open decisions for you
1. **x4:** Option A (rename) or Option B (sulcal axis, re-train).
2. **Viewer expectations:** accept the changed 3-D viewer expectations. Thin veins and cSS, and in-plane structures on 3 mm scans, will often show "not resolvable" instead of a confident shape.
3. **Next steps:** commit, push or further cycles, only on your approval.
