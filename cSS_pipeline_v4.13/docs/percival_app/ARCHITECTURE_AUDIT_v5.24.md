# Percival v5.24: architecture audit, root causes and redesign (2026-11-21)

Synthetic data only. No clinical MRI, review file or identifier was opened. The user's projects (`~/css_project`, `~/cSS_experimental`,
`~/Percival_project`) were not read; their running reviewer sessions were not touched. Every finding below comes from following the code paths.

## 1. Recovered state
- Branch `feature/unified-score-ml-integration`. The v5.20–v5.23 work was committed and pushed as `a2637fa`, as the user asked.
  The v5.24 work described here is uncommitted.
- Earlier backup refs: `refs/backup/handover-2026-11-21`, `refs/backup/v523-engine`, `refs/backup/v523-final`.
- Three separate app variants each have their own project folder:
  - production: `~/css_project`, port 8800
  - Percival RC: `~/cSS_experimental`, port 8810
  - Percival Dev: `~/Percival_project`, port 8830
  
  Each variant refuses the other variants' folders.

## 2. Actual execution path (code, not documentation)

| Step | Code | Input → output | Stored | Used by the Percival Score |
|---|---|---|---|---|
| Import / identity | `app/import_wizard.py`, `app/identity.py` (registry schema-checked), `app/study_library.py` | DICOM/NIfTI → `raw/`, `app_data/patients.json`, `app_data/identity/registry.json` | yes | study list, patient key (patient-level splits) |
| Reuse of earlier processing | `processing_manager.import_study` | other project's `data/ work/ review/` → verified copy; **reviewer files → `historical/ID/review/` "for comparison only"** | yes | **no (before v5.24)** |
| Processing | `scripts/run_css.sh` → `prep_anat.sh` → `detect_css.py` | SWI (+T1/FLAIR) → `review/ID_candidates.csv/.nii.gz` | yes | MATH + characteristics |
| MATH | `detect_css.py` `score_v4` (deterministic definition rule) | candidate measurements → `score_v4` | candidates.csv | component `math` |
| Unified Score predictors | `unified_score/uscore` (`run_unified.py app`, opt-in step; also extracted on demand by Percival) | → `uscore/features/ID.json` (5 predictors with reliability states) | yes | component `unified` |
| Stage-1 "Shadow ML" engine | `unified_engine/uengine/{math,characteristics,ml}_component.py`, `unified_fusion.py`, `shadow.py`; app `shadow_engine_gui.py` | → `unified_engine/shadow/ID.json` | yes | **no** (separate prototype) |
| Image ML prototype | `uengine/imaging/image_infer.py`, `train_image_model.py`; app `image_ml_gui.py` | **synthetic projects only** → `unified_engine/image_ml/ID.json` | yes | **no** (separate prototype) |
| Predictor model (Unified) | `unified_gui.py` + `run_unified.py train/freeze` | → `uscore/` model | yes | **no** (separate model) |
| Percival components | `uengine/percival/meta.py` `Components`: characteristic ML (`learners.py`), image ML (`learners.PixelLogistic` / `cnn.py` on patches from `uengine/imaging/patches.py`), fusion | rows from `percival_gui.gather` | model.json | yes |
| Percival Intelligence + Score | `meta.py` (meta-model discovery, calibration, thresholds), `intelligence.py` (ablation, disagreement, OOD, reliability) | → registry, `scores/ID.json`, immutable ledger | yes | the score |
| Review | `scripts/review_web.py/.html`; `scripts/call_ledger.py` (effective calls, fingerprint re-attachment, lineage, policy) | → `review/ID_calls_<reviewer>.csv`, `ID_final_<reviewer>.json`, shared `ID_calls.csv` | yes | labels |
| Learning (v5.22–5.23) | `percival_gui._labels / selection / _train` | **read only `review/ID_calls.csv` by candidate number; only studies in state "Reviewed"** | registry | |

Data flow after v5.24 (one pipeline, one score):

```
MRI ─► processing ─► candidates ─► MATH (score_v4) ─────────────┐
                         ├─► Unified Score predictors (uscore) ─┤
                         ├─► detector measurements ─► Characteristic ML ─┐
                         └─► MRI patch ─► Image ML ───────────────────────┼─► Fusion ─┐
                                                                           │          ▼
                         MATH + Unified + Fusion ─► Percival meta-model ─► calibration ─► Percival Score (+ Intelligence: OOD, disagreement, QC, reasons)
expert calls (call ledger + earlier-version reviews) ─► Training Eligibility Engine ─► dataset manifest dsNNN ─► training cycle ─► registry vNNN ─► acceptance ─► active
```

## 3. Root causes

1. **Old reviews never became labels (the reported failure: "both classes are needed (cSS 1, not cSS 33)")**
   - (a) Percival read only `review/ID_calls.csv`, by candidate number.
   - (b) Calls named `Vein` (the name before v5.9.1) failed the label map, so they were dropped.
   - (c) A study counted only in review state *Reviewed*: every candidate called plus a final save. Older reviews almost never meet that.
   - (d) Reviews brought in with "reuse earlier processing" were copied to `historical/ID/review/` and never read.
   - (e) Studies reviewed on disk but missing from `patients.json` were invisible.
   - The result: only a handful of candidates reached training.
2. **Code and data mixed in one folder.** The Percival store lived in `<project>/unified_engine/percival/`, the folder the launcher refreshes
   with new engine code on every update. It had no schema version, so a newer app could not tell what it was reading.
3. **No dataset versioning.** A model could not be traced to the examples it learned from.
4. **Four parallel ML implementations** (Training, Predictor model, Shadow ML, Image ML) appeared in the menu next to Percival.
   - They train separate models that never feed the score shown to the reviewer.
   - Image ML refuses every non-synthetic project, which looks like "the model is not switched on".
5. **One vague status per study.** "Review not finished" covered unprocessed, unreviewed, partly reviewed, re-detected and left-out studies alike.
6. **Calls attached by number.** After re-detection a call could point to a different lesion. Percival bypassed the call ledger that the
   reviewer uses, and that ledger already handled this correctly.

## 4. Recommendations: what was done and why

| # | Problem | Decision | Why | Migration / risk |
|---|---|---|---|---|
| R1 | Labels read four different ways | Labels now come only from the **call ledger** (the same effective calls the Review screen shows), plus **earlier-version reviews** matched by fingerprint (centroid within 2 voxels, volume within 15 %) | One source of truth; handles `Vein`, re-detection, lineage, reviewer policy | No file rewritten. Earlier-version labels are marked and can be switched off |
| R2 | Eligibility implicit and scattered | **Training Eligibility Engine** (`uengine/percival/eligibility.py`, rules `percival-eligibility/1.0`): per candidate and per component (characteristic / image / fusion / meta), with reason codes | The screen, the manifest and training use the same function | None |
| R3 | No dataset versions | **Dataset manifests** `percival/datasets/dsNNN.json`, materialised at every cycle, content-hashed (unchanged data → same id), stored in each model | Reproducibility and traceability; small (no pixels copied) | Models trained before v5.24 show "no manifest" |
| R4 | Store inside the code folder, unversioned | **`<project>/percival/` with `STORE.json` schema 3** and a sequential migration registry (`store.py`). Backup first (`backups/percival/`); copy verified by sha256; old folder renamed, never deleted; a store from a newer app is refused untouched | Updates replace code only; data has a version | Runs automatically at start-up. On failure the old store is unchanged and the reason is shown |
| R5 | Earlier-project reviews unreachable | **Review recovery**: same image fingerprint in an enabled earlier project → verified copy into `historical/ID/review/`, plus `SOURCE.json` provenance. A current call always wins | Old expert work is used without copying it into the reviewer's own files (blind reads stay blind) | Runs only when the user presses the button |
| R6 | Confusing menu | Percival screen reorganised as **Overview** (how the parts fit), **Training Center**, **Model Center**, **Data integrity**, plus **Advanced** assessment tabs. The four prototypes are hidden by default (Settings › Show the older research prototypes) | One workflow, one score | Nothing deleted |
| R7 | Database | **Kept files (JSON/CSV) rather than SQLite** | Every pipeline script, the reviewer and the tests read these files. Replacing them would be a large, risky rewrite. Versioned stores, immutable ledgers and manifests give the guarantees needed | Remaining: `patients.json` has no schema version (the identity registry has one) |
| R8 | Fusion vs Intelligence double counting | Kept as in v5.23: no meta-model combines Fusion with the Characteristic or Image source it already contains. Intelligence analyses reliability and does not add evidence twice | Already correct; documented | None |
| R9 | Stage-1 engine modules duplicate Percival (`uengine/*_component.py`, `unified_fusion.py`, `calibration.py`, `patient_split.py`) | **Not deleted.** They are the Shadow ML prototype and have their own tests. Marked as prototypes | Removing them risks breaking studies that have shadow results | Candidate for removal in a later release |
| R10 | Code installed into the project folder (`scripts/`, `app/`, `unified_engine/`, `unified_score/`) | Kept (the pipeline scripts resolve `$CSS_BASE/scripts`). All persistent Percival data is now outside the code folders. The launcher keeps backups of old scripts | Moving every script would change the production pipeline | Code files the launcher overwrites contain no user data (checked: shipped engine files are code plus two versioned synthetic models) |

Considered and not done:
- No new framework layer.
- No automatic training after each review (cycles stay controlled).
- No migration of `patients.json` to a database.

## 5. Where things live (project folder = the user's data directory)

```
<project>/                       chosen on first start; remembered in ~/Library/Application Support/Percival Dev/project_path
  app_data/                      study list, identity registry (+ encrypted vault), settings, logs
  raw/ data/ work/ synthseg/ subjects/ runs/    MRI and processing
  review/                        candidates, reviewer calls / finals / scores (per reviewer), call ledger files
  historical/ID/review/          reviews of earlier versions / projects (verified copies + SOURCE.json)
  uscore/                        Unified Score predictors and reports
  percival/                      Percival store (STORE.json schema 3): registry/, active.json, ledger/, scores/, reviews/, datasets/, cache/
  backups/percival/              copies taken before every migration
  app/ scripts/ unified_engine/ unified_score/ tests/   program files, replaced by updates (old scripts backed up)
```

The application bundle (`Percival Dev.app`) holds code only. Updating means replacing the bundle; the project folder is never
replaced.
