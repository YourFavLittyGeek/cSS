# experimental/ — opt-in structural cSS analysis (NOT production)

Nothing in `scripts/` imports this folder. All flags default to 0; production output is unchanged (checked by `run_all_checks.sh`).

- `structural_detection/` modules A (Hessian fingerprint), B (surface coordinates), C (vessel graph), D (multi-view seeding),
  E (sulcal reference), F (candidate decomposition), fusion (7 categories, recorded only), `run_structural.py`, `evaluate_structural.py`.
- `stage0/` read-only audit scripts (reconciliation, volume-gate phantom sweep, figures).
- Baseline audit: `../reports/EXPERIMENTAL_UPGRADE_BASELINE_AUDIT.md`.

Run (from this folder):
```zsh
CSS_HESSIAN_FINGERPRINT=1 CSS_SURFACE_COORDINATES=1 CSS_VESSEL_GRAPH=1 CSS_MULTIVIEW_SEEDING=1 CSS_SULCUS_REFERENCE=1 CSS_CANDIDATE_SPLITTING=1 CSS_EXPERIMENTAL_FUSION=1 python -m structural_detection.run_structural M02 --include-excluded
python -m structural_detection.evaluate_structural ~/css_project/experimental/structural ~/css_project/experimental/eval_dev
bash run_all_checks.sh /tmp/struct_checks        # tests, no patient data
```
Outputs go to `$CSS_BASE/experimental/structural/ID_<UTC>/` (never overwritten). Phantom results are not clinical evidence.
