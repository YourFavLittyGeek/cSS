# KNOWN_LIMITATIONS.md

## Scientific
1. **No clinical evidence of any kind.** Every number comes from a synthetic generator whose class distributions were invented; the
   generator decides every gain. A real data set may contain no information beyond MATH.
2. **No clinically trained model exists.** For every real study the ML output is withheld and the deterministic output is shown.
3. **The incremental-value decision needs the permutation test.** The paired bootstrap CI gave 1 / 13 false positives on pure noise and its
   null is not centred at 0 (up to +0.020). The permutation test is implemented in the workspace (`ablation.permutation_test_increment`),
   not yet exposed in the app.
4. **Informative missingness** can create spurious gains through the missingness indicator.
5. **MATH is sensitive to darkness calibration** (score_v4 uses darkness z directly); the offset fusion inherits part of it.
6. The 10 inputs were prespecified from the cSS definition, not selected on data; whether they are the right ones is unknown.
7. Labels in the existing project are non-expert reader calls; the radiologist reference is patient-level only; exam -> patient keys are
   absent (the engine records "one study = one patient (unverified)").

## Engineering
8. The engine scores the detector's TABLES (candidates.csv / excluded.csv). It does not re-measure images; gate-dropped objects and
   never-generated lesions are outside its reach. E12 (internal flag) and the 0-4 score (label images) are carried as recorded.
9. The demo base contains tables only (no images): image-based screens (QC, reviewer) are not meaningful on it.
10. The shadow run is per study and on demand (or after each finished study when switched on); no cohort-level shadow report or export yet.
11. The app's existing "Unified (experimental)" tab (uscore) is unchanged and independent; the two experimental outputs are not reconciled.
12. No third-party linter / type checker (not installed; a minimal AST check is used).
13. Screenshots and DOM checks use headless Google Chrome if installed; without it the browser checks are reported as not run.
14. The unchanged app re-serialises app_data/patients.json at start-up (formatting only); tests therefore compare that file by content.
15. `run_uscore_tests.sh` (existing suite) rewrites 3 tracked `unified_score/output/` files (verified); they were restored after the run and
    never committed.
16. Existing-suite issues on this Mac (diagnosed 2026-11-20, HANDOVER.md section 3): `check_export_safety` (2 FAIL) and `check_write_guard`
    (hang) were TEST-HARNESS problems - fixed in the tests only, no app / guard / launcher code changed, no assertion weakened.
    `check_ui_poll` needs Node / npm + Playwright (environment; not installed) and remains not run.
17. GUI checks use the DOM of a headless Chrome render and screenshots; no click-through automation (Playwright for Python / Node is not
    installed). Interactive behaviour (buttons, switch) is tested through the same HTTP API the buttons call.
