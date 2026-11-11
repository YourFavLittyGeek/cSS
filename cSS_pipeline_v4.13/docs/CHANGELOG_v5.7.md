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
- compare_reads.py --old-reviewer NAME: compares two reads of the SAME detection (e.g. Redo_v53 vs Blind_v57).
- docs/HOW_TO_REDO_M02-M06_v5.7.md: install, primary fixed to Redo_v53, blind read as Blind_v57, reports.

## Stage A, part 3 (viewer) + zone probe
- Theme switch is a symbol slider (moon = dark, drop = eye-preserving blue, sun = light): click a symbol or drag the knob; T cycles.
- Validation read is the eye-with-a-lock symbol (click: Settings menu); the text badge is gone.
- Decision buttons: sized to their text, wrapped, text centred, shorter padding; the button label "Normal cortex" is "Normal" (tooltip keeps the full name).
- Audit reveal: the excluded objects mixed into a validation read are listed in the summary after the final save (rule, region, your call;
  those called cSS are flagged), outlined dotted in the strip, and Candidate > Excluded audit objects jumps between them. Before the final
  save the rule stays hidden (also in the API). Infratentorial objects are never in the audit sample (not cSS by definition).
- scripts/zone_probe.py (read-only) + tests/check_zone_probe.py: where does each object lie in an anatomical compartment map
  (outside a smooth hull of the cerebrum / cortex contact / free CSF / cerebellum-brainstem / skull-base cortex / interhemispheric fissure),
  next to the calls of two reads (css_any = PROTECTED when rules are fitted). Rule grid: protected cSS flagged, shown non-cSS flagged,
  excluded objects also caught. Decisions taken: midline = only objects free in / running along the fissure (not medial-surface hugging);
  skull base = whole orbitofrontal / temporal-pole / inferior surface excluded; occipital / inferior temporal cortex over the tentorium kept
  when the nearest tissue is cerebral cortex.
