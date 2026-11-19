# Held-out label protection: source-code path audit (cycle 2, branch `experimental/unified-gui`)

**Method:**
- Every place that can read reader labels was found with a full-text search for the label readers (`load_calls`, `match_calls`, `_read_calls`), calls files (`*_calls*.csv`), `labels/` and the `LabelAccess` boundary. The search covered `unified_score/`, `app/` and the tests.
- Each path was then read.
- No held-out evaluation was run on real data. One synthetic authorized read proves that the boundary still opens when every condition holds.

## 1. The label-access boundary
- **`uscore/common.py` → `LabelAccess` is the only gate.**
- **The reader is private.** The function that parses reader calls is `_read_calls` (common.py:133), called exactly once, inside `LabelAccess.labels`.
  - Static test: no module in `unified_score/` or `app/` references `_read_calls`, `load_calls` or `match_calls` outside common.py (`check_heldout_protection` 1).
- **Development mode:** grants development studies only, refuses every held-out study, and logs every attempt (time, study, role, mode, granted).
- **Held-out mode (changed in this cycle):** everything is now enforced inside the boundary, not by the caller:
  1. the frozen model file exists and `frozen` is true;
  2. **its hash is recomputed from the file content** (`model.model_hash`, the same function used when writing) and must equal both the hash stored in the file and the hash given by the caller, so an edited model with its old stored hash is refused;
  3. the model's `train_studies` contain no held-out study;
  4. a **written authorization file** (`uscore/heldout_authorization.json`) names that hash, a person, a date and the exact statement. Before this cycle that check lived only in `pipeline.evaluate_heldout`;
  5. **before every label read** the model is re-verified and its file sha256 must equal the value at authorization, so the model can't be swapped after authorization.

## 2. Every path, traced
| Path | Code | Reads labels? | Can held-out labels reach it? |
|---|---|---|---|
| Cohort loading | `common.Cohort` | no: the manifest gives roles only | no |
| Cohort audit (in-app) | `app/unified_gui.audit` | no: file presence, QC registration and the SWI hash only | no |
| Cohort audit (Mac script) | `unified_score/cohort_audit.py` | **before this cycle** it counted non-empty reader calls for every study, held-out included (counts only, never values) | **fixed:** held-out calls files are no longer opened (`"not inspected (held-out)"`). It still reads study identifiers from `labels/*.csv` ID columns to list studies (identifiers, not label values) |
| Feature extraction | `pipeline.extract_study` / `candidate_record` | no. It reads the candidate mask, SWI, vessel map, pial distance, unmasked SWI, QC and the detector CSV. From the CSV only `infra_frac`, `infratentorial`, `near_ich_suggest`, `region` (detector outputs) and `confidence_pct` (the v5.10 model output, a comparator) | no. Test: feature files contain no reader-call field |
| Training | `pipeline.train` | yes, through `LabelAccess(mode="development")` for `cohort.studies("development")` only. `check_fit_set` refuses non-development studies, and **training refuses a non-development boundary** (new) | no. Spy test: labels requested for development studies only. **Flipping every held-out label leaves the trained model hash identical** |
| Cross-validation | `model.nested_lopo` / `inner_lopo` | only the labels handed over by `train` (development) | no. Leakage test: flipping one outer patient's labels leaves its own out-of-fold predictions unchanged |
| Calibration | `model.platt_fit` inside each outer fold | inner out-of-fold scores of the training patients (development) | no |
| Freezing | `pipeline.freeze` | no | no |
| Scoring / decision / app step | `pipeline.score`, `score_application` | no | no. Test: reports contain no reader-call field |
| Reporting | `report.cohort_report` | reads `development_report.json` (development OOF) and `heldout_report.json` only if it exists | the held-out report can exist only after an authorized evaluation |
| Export | `app/unified_gui.export` | no (reports, model info, validation summary) | no |
| GUI | `app/css_app.unified_post` / `unified_get` | no route to held-out evaluation | no. Static test plus `/api/u/heldout` is refused |
| Test protocol | `app/gui_protocol` | **before this cycle** T9 / T11 hashed the contents of a finished patient's reader files (possibly a held-out patient's calls; bytes, never parsed) | **fixed:** reader files are signed by (size, modification time) only and their content is never opened |
| CLI held-out evaluation | `run_unified.py heldout HASH` → `pipeline.evaluate_heldout` → `LabelAccess(mode="heldout_evaluation")` | yes, only through the boundary with all five conditions above | only with a frozen, unedited model, its hash and your written authorization |

**Outside the unified engine (not part of model development, listed for completeness):**
- the reviewer (`review_web.py`) reads and writes reader calls, which is its purpose;
- the app's Results table counts a patient's own calls;
- `tests/check_uscore_pipeline.py` reads synthetic calls to compare categories.

None of these feeds training, calibration or tuning.

## 3. Negative tests: `tests/check_heldout_protection.py` (24 checks, all pass)
1. **Static:** only common.py references the label reader, and `_read_calls` is called only inside `LabelAccess.labels`.
2. **Development boundary:** refuses every held-out study, and the refusals are logged with granted = 0.
3. **Training:** labels are read for development studies only (spy), and a held-out-mode boundary is refused.
4. **Influence:** flipping every held-out label leaves the trained model identical (same hash).
5. **Held-out mode is refused for each of:**
   - no authorization file (a hash alone is not enough);
   - an altered statement;
   - authorization for another model;
   - no name;
   - a wrong caller hash;
   - **an edited model with its old stored hash**;
   - an unfrozen model;
   - a model trained on a held-out study (even with a consistent hash);
   - **a model swapped after authorization**.

   With every condition met (synthetic), the read is granted and logged.
6. **No leakage into outputs:** no reader-call field in feature files or reports, and the development OOF table holds development studies only.
7. **GUI:** no held-out operation in the app's Unified routes.

## 4. Real defect found and fixed during the audit
- **What happened:** `detectors.extracranial` compared `None < 5.0` when perturbation stability was not measured and the continuation was under 5 mm, and crashed. The GUI path always measures stability, so it was latent. The audit test exercised the `do_perturb=False` path and found it.
- **Fix:** guard the comparison.
