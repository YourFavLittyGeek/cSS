# Percival v5.25 development log (session continuity)

Resume here: read this file, then `git -C ~/Projects/cSS-unified-score-ml status` before continuing. Never repeat the backup step blindly.

## Protected baseline (2026-11-22 02:34)
- Canonical source: `~/Projects/cSS-unified-score-ml` (git worktree of `~/Projects/cSS/.git`), branch `feature/unified-score-ml-integration`,
  HEAD `5bca173` "Percival v5.24". Installed copy `~/Percival_project/app` is byte-identical to the worktree `app/`.
- Backup: `~/Percival_backups/baseline_20261122_023422/` (worktree source + .git pointer, live-project metadata: percival store, review,
  labels, private, small app_data files, and `Percival_v6.0.zip`). MRI volumes were not copied (they are not modified by this work).
- Live project `~/Percival_project` (real data) is READ-ONLY for this work. All testing uses synthetic projects in temp folders.
- Baseline tests (unmodified code): `unified_engine/run_tests.sh` -> 0 failing stages (119 engine tests OK, 78 imaging tests OK, 3 app +
  browser stages ALL PASS). App-level Percival checks: see `baseline/percival_summary.txt` (recorded in the test report).

## Design decision (latest intended design)
- Selected: the v5.24 Percival GUI (branch feature/unified-score-ml-integration): sidebar Studies / Add studies / Activity / Review /
  Anatomy QC, RESEARCH: Percival Intelligence (tabs Overview, Components & agreement, Evidence & reliability, Meta-model, Candidate explorer,
  Training, Registry), ADVANCED: Training, Predictor model, Shadow ML, Image ML; Standard / Incognito switch; setup wizard; import wizard.
- Not selected: `~/Downloads/cSS_pipeline_v4.13` "Percival v6.0" (2026-11-22). It was built on v5.14.2-rc5 (experimental/unified-gui) - the
  OLDER GUI (nav: Studies / Add studies / Activity / Review / Model / Intelligence, no identity vault, no import wizard, no Anatomy QC) - with a
  separate, simpler learning package (`app/percival/`) that duplicates the v5.24 engine. Its useful ideas (heartbeat, stall detection,
  resource sampling, ETA range) are re-implemented natively in v5.25; its code is not merged.

## Findings verified in code (not from reports)
1. CRITICAL - Fusion indirect validation leakage (`meta.component_oof`, v5.24): Fusion of outer fold i was trained on `img_oof[tr]`, image
   out-of-fold logits produced by image models fitted on folds that INCLUDE fold i. Proven by `test_nested_leakage.TestFusionCrossFitting`:
   on the v5.24 code, flipping only the held-out fold's labels changes its Fusion log-odds (e.g. 3.9 -> 46.8); on v5.25 they are identical.
2. HIGH - single-level stacking: meta-model discovery, family selection, calibration and thresholds were evaluated on the same out-of-fold
   table they were chosen on. Development metrics were optimistic. (The locked test cohort was never touched - its metrics stay valid.)
3. HIGH - `css_app.patient_of` silently returned the STUDY code when a study had no identity record; legacy studies were migrated as
   "one new patient per study" without any record that this is an assumption.
4. MEDIUM - development threshold sensitivities/specificities were in-sample for calibration + threshold choice (now labelled; nested
   held-out figures added).
5. Training Center: no heartbeat, no stall detection, no cancellation, no ETA, no resource monitoring (job states idle/running/finished/failed).

## Changes so far
- `uengine/percival/meta.py`: Fusion trained on inner-CV inputs restricted to the training fold; per-fold provenance; `check_partitions`;
  nested evaluation in `train_cycle`; locked-test patient classes; acceptance gates (test patients per class, CI, nested evidence,
  identity); in-sample labelling.
- `uengine/percival/nested.py` (new): nested cross-fitting of the whole procedure + 12 ablations with paired patient-bootstrap CIs.
- `unified_engine/tests/test_nested_leakage.py` (new): 8 tests, all pass (169 s).

## Next
- Patient identity verification layer (app), Training Center monitor, GUI integration of nested/ablation/identity, registry gates in GUI,
  image geometry audit, regression runs, screenshots, release package, reports.
