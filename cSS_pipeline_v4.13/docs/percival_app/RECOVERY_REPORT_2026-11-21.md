# Percival - recovery report (handover, 2026-11-21)

Written by the continuing Claude session from repository evidence only (the previous conversation was not available).
Synthetic data only; no clinical MRI or identifier was opened.

## 1. Repository state at handover

| Item | Value |
|---|---|
| Worktree | `/Users/tarabeah.selim/Projects/cSS-unified-score-ml` (git worktree of `~/Projects/cSS`) |
| Branch | `feature/unified-score-ml-integration` (not switched) |
| HEAD | `e45227c` Percival v5.19: Studies list ... and import series review |
| Main / PR base | `claude/css-detection-audit-2esnbb` (checked out in the main worktree) |
| Remote | `origin` = github.com/YourFavLittyGeek/cSS (nothing pushed by this session) |
| Uncommitted | 20 modified tracked files (+428 / -97), 16 untracked source/doc/test files, 6 screenshots, `uengine/percival/` package, `dist/` build output, `.DS_Store` files |
| **Safety snapshot** | the whole working tree (excluding `dist/`, `.DS_Store`, `__pycache__`) is stored as commit `41b0d27` under `refs/backup/handover-2026-11-21` - not on any branch, working tree and index untouched. Restore a file with `git checkout refs/backup/handover-2026-11-21 -- <path>` |

The uncommitted work is three increments the previous session had not yet committed:
- **v5.20 study administration** - `app/study_admin.py`, `study_admin_view.js`, `known_projects.py`, `docs/percival_app/STUDY_ADMINISTRATION.md`, `tests/check_app_study_admin.py`, identifier rule (accession / code) through app, reviewer and notifications.
- **v5.21 Unified Score in the packaged app** - empty cohort manifest when the clinical-derived manifest is not shipped (`unified_gui.py`).
- **v5.22 Percival Score** - `unified_engine/uengine/percival/{meta.py, cnn.py}`, `app/percival_gui.py`, `app/percival_view.js`, the
  "Percival Intelligence" screen, Percival Score card in the reviewer, `tests/check_percival.py`, `tests/check_app_percival.py`.

## 2. Component status (verified against code and by running tests)

| Pipeline component | Status at handover | Evidence |
|---|---|---|
| MRI import / identification | Complete (Phases B, v5.16-v5.20) | `import_wizard.py`, `identity.py`, check_app_identity / import_v518 / study_admin |
| MRI processing & preparation | Complete for the existing pipeline (run_css.sh, prep_anat, QC) | `scripts/`, `css_qc.py`, check_qc, Anatomy QC screen |
| Candidate detection | Complete (detect_css v4-v5.x, stable `cand_id`, lineage across re-runs) | detect_css.py, `lineage`, check_lineage |
| MATH | Implemented: `score_v4` (deterministic, untrained) in `scripts/detect_css.py:1028-1040`; **not documented as a component** | see `PERCIVAL_ARCHITECTURE.md` §MATH |
| Unified Score | Implemented (v5.14): 5 predictors x1-x5 with reliable / unreliable / unavailable states, ridge LR, nested LOPO | `unified_score/uscore`, run_uscore_tests |
| Image ML | Implemented twice: (a) Stage-2 prototype (`uengine/imaging`, synthetic only, option A), (b) v5.22 numpy CNN on surface-aligned patch maps inside Percival | `cnn.py`, check_percival "image component better than chance" |
| Characteristic ML | Implemented as one L2 logistic on 9 detector characteristics; **no algorithm comparison** | `meta.py` `Components.char` |
| Fusion | Implemented as feature-level fusion only; **late / hybrid not compared; no evidence that fusion beats each input** | `meta.py` `Components.fusion` |
| Percival Intelligence | Partly: meta-model discovery (7 candidates, 1-SE rule), pairwise Spearman agreement, disagreement terms, patient-bootstrap uncertainty, controlled cycles, registry, rollback, acceptance. **Missing: component ablation / incremental value, input-overlap (provenance) map, disagreement-pattern learning from expert labels, out-of-distribution check, image-quality input** | `meta.py`, `percival_gui.py` |
| Percival Score | Implemented: calibrated 0-100, data-driven red / yellow / green, 'insufficient evidence' when no learned source, immutable prediction ledger. **Defect: thresholds collapse (red == green) when the development data separate well -> no yellow band** | check_percival output `red_below == green_from` |
| Expert review & local learning | Reviewer, calls ledger, review status, re-processing keeps calls, controlled retraining. **Missing: a snapshot that binds each expert label to the exact model outputs shown at review time** | `review_web.py`, `percival_gui.py` |
| GUI | Percival Intelligence screen (6 tabs), Percival Score card in the reviewer. **The reviewer has no "why" (evidence) view per candidate** | screenshots v522_* |
| Offline / local only | Static scan + netguard runtime test exist, but the **static scan skips `unified_engine/`** where all Percival ML lives, and the Percival tests are not run under the netguard | `tests/check_local_only.py` |
| Docs | `percival_gui.py` cites `docs/percival_app/LOCAL_AI_ARCHITECTURE.md` - **file does not exist**. No model / data-flow / evaluation documentation for v5.22 | - |

## 3. Known GUI issues from the handover brief - verification

All were addressed by earlier commits (Phases B-G); each is verified by an automated test in `tests/run_uscore_tests.sh`
(result in `IMPLEMENTATION_REPORT_v5.23.md`).

| Issue | Fixed in | Test |
|---|---|---|
| Process Manager reports duplicate imports wrongly | Phase B / v5.16 (fingerprints), v5.20 duplicate choices | check_duplicate_detection, check_app_study_admin |
| AI processing bugs | Phase B, v5.14.1 (unified step opt-in, status) | check_app_unified, check_pm_full_pipeline |
| Missing FreeSurfer QC screen | v5.15 Anatomy QC | check_app_review_qc |
| Studies not changing to Reviewed | v5.15 review status | check_app_review_qc |
| Reprocessing must keep expert calls | Phase C lineage | check_lineage, check_inherit |
| Training screen clutter | Phase E Training A-D | check_app_training |
| Poor Quick Add | Phase D | check_review_web |
| Reviewer identity vs AI labels | Phase D (human vs AI labels) | check_review_web, check_call_ledger |
| Batch import text overflow | Phase E, v5.18 | check_app_add_layout |
| First-run setup wizard | Phase F / G | check_app_setup |

## 4. Implementation sequence chosen (v5.23)

1. Commit nothing without the user's permission; snapshot refs at milestones instead.
2. Fix the threshold collapse (bootstrap-stable thresholds, documented).
3. Characteristic ML: compare logistic / gradient-boosted trees / random forest (numpy) by patient-grouped CV, 1-SE rule.
4. Fusion: compare feature-level / late / hybrid against Characteristic and Image alone; record whether fusion earns its place.
5. Image ML: flip test-time augmentation spread as image uncertainty; pixel-logistic baseline so the CNN must beat a simple model.
6. Percival Intelligence: component ablation (incremental value), input-provenance overlap map, disagreement-pattern table from
   expert labels, out-of-distribution distance, study image quality (QC status) as a reliability input -> 'review' flag.
7. Expert-review snapshots binding labels to the outputs shown at review time.
8. GUI: evidence ("why") panel in the reviewer under the single score; new analyses in the Intelligence screen.
9. Local-only: static scan extended to `unified_engine/`, Percival tests under the netguard.
10. Docs: architecture, local-AI architecture, data flow, training & evaluation, MATH / Unified audit, limitations; final report.
