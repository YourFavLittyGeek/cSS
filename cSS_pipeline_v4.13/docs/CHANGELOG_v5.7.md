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

## Stage A, part 2 - visible changes (sketches approved; Microbleed moved to B at the user's request)
- **Microbleed** button, key **B** (colour purple-red). The magnifier moved from B to **W** (W still switches rectangle / pen
  while the missed-cSS drawing tool is active). Help and menus updated.
- **Validation read** (Settings; default ON for a study this reviewer has not finally saved; the choice is remembered per study
  and reviewer): blue VALIDATION READ badge; AI meter, AI score, AI column of Calls summary and CSV export hidden and locked
  (K refused); comparison window off; candidates shown in a shuffled order numbered 1..N; a deterministic 20 % sample of the
  excluded objects (at least 1) is mixed in, unmarked. Their calls go to ID_excluded_audit_<name>.csv with the rule that
  excluded them, are never scored, and the final record lists any excluded object called cSS ("Excluded objects called cSS
  (audit)" in css_report). Final record and report carry the read mode.
- File > **Import earlier calls...** (window: source, only-uncalled / replace; refused in a validation read) and Settings >
  **Primary reviewer...** (shows who; makes you primary after a confirmation).
- A newer study load always wins (two quick loads could mix candidate lists).
- Tests: check_review_web.py (audit sample, audit file, never scored, labels, import refused), check_viewer.py (browser).
