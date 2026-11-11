# v5.7 (research software; expert review required) - plan: docs/AUDIT_v5.6.4_and_PLAN_v5.7.md

## Stage A, part 1 - server side and clean-ups (no change to detection)
- **Reviewers are separate.** A reviewer name with no file of its own starts EMPTY (the silent fall-back to the shared
  ID_calls.csv is gone). `/api/import` copies calls from the shared file or another reviewer's file onto yours, only for
  candidates you have not called (or all, on request); imported calls carry "[imported from X]" and stay dashed until you
  press the same key. The import is logged.
- **Primary reviewer** per study (review/ID_primary.json; the first reviewer who saves; `/api/primary` changes it). Only the
  primary reviewer writes the shared ID_calls.csv, the accept column of ID_candidates.csv and ID_score.json. Every other
  reviewer's score goes to ID_score_rev_<name>.json (score_css.py --accept-ids ... --ich-ids ... --reviewed-ids ... --tag).
- **Final record per reviewer**: ID_final_<name>.json (the old single ID_final.json is still read when it is yours).
  css_report.py: one row per study AND reviewer (newest wins), new columns "Microbleeds called", "Primary reviewer", "Read mode".
- **Microbleed** is a valid call (server, counts, final record, report; coarse class not-cSS; fine code MB already in
  css_common.LABELS). The button / key W are part 2 (sketch first).
- **Meter caps**: the AI meter is never green (capped at 0.65, reason shown) for a blob-like object (cmb_like, or the
  stage-D column e23_blob), a fissure-like object (fissure_frac >= 0.5 when present, the midline hint, or midline_frac >= 0.5)
  or tiers 3-5. This lowers the AI score where it over-called; it is still not validated.
- **Side check** uses world coordinates: left-labelled tissue must lie left of right-labelled tissue (labels_ok), and each
  candidate on the side of its hemisphere label.
- **One mid-sagittal plane** in detect_css.py: the mirror check uses the plane of section 7b. PH3 with and without CSS_V53:
  every column of ID_candidates.csv and ID_excluded.csv identical before / after.
- Clean-ups: dead code in v53_change_report.py, one ai_opinion call per row in compare_reads.py, tools/make_all_code.py,
  tools/make_release.sh, tests/check_viewer.js + check_viewer.py (Playwright; skipped without it; in run_tests.sh),
  check_review_web.py covers the new reviewer rules.

## Stage A, part 2 - visible changes (waiting for approval of the sketches sA/sB/sC)
Microbleed button + key W; "VALIDATION READ" badge and mode (meter hidden and locked, comparison off, 20 % excluded-object
audit sample mixed in unmarked, audit calls in ID_excluded_audit_<name>.csv, never scored); File > Import earlier calls...;
Settings > primary reviewer.
