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

## v5.7-C - skull-base zone rule E24 (fitted from review/zone_probe on M02-M11)
Probe result (224 shown objects: 64 protected cSS, 160 non-cSS): OUT (outside the hull) and INFRA (cerebellum / brainstem) flag NO shown object -
those were audit objects, already excluded by the old rules; the shown non-cSS objects sit on the cortical surface. Zone rules that do pay off:
- **E24 skull-base cortex zone** (opt-in CSS_V53=1; parcellated T1 labels only): >= 50 % of the object's voxels nearest to lateral / medial
  orbitofrontal, frontal pole, temporal pole, entorhinal or pars orbitalis cortex -> excluded ("skull-base cortex zone"). Shown non-cSS flagged:
  15; protected cSS flagged: 0 of 67; nearest protected cSS 0.09 vs threshold 0.5. Fusiform / inferior temporal / parahippocampal are NOT in the
  set (occipital and inferior temporal cortex over the tentorium is kept). New column skullbase_frac (appended).
- Still shown after E24 (not separable from real cSS by anatomy): medial-surface cingulate / precuneus objects that hug one surface
  (M04 #11, #19, M05 #4, #5): same fissure measures as the protected cSS M11 #12 / M07 #11.
- The three old rules that removed a called cSS in the audit: E13 midline (M03 excluded #5, precuneus, both hemispheres within 3 mm),
  E17 outside the cortex (M04 excluded #18), E18 ill-defined (M03 excluded #28) - each 1 of 16 / 15 / 21 objects, each called cSS in ONE read
  only; waiting for the re-decision before touching them.
- Findings about the installed state: E22 objects (M02 #8, M03 #15, M04 #6 and #12 ...) were still shown in M02-M06 = that detection was made
  without E22; M07-M11 still carry the v5.2 detection (six objects > 3000 mm3 shown). Both need a redetect with v5.7-C.
- Test: check_v53.py builds PHB (left cortex relabelled 1012): every left object excluded by E24, right objects unchanged.

## v5.7-D (reader's final decisions applied; fissure rule E25; shape probe)
- docs/adjudication_M02-M11_v1.csv = the reader's final decisions (M03 excluded #5 and #28, M04 excluded #18, M04 #13: not cSS; M05 #3: cSS). Copy to
  review/adjudication.csv: zone_probe / shape_probe then use them instead of the individual reads (probe_common.apply_adjudication).
- With these decisions all three old rules that "removed a cSS" in the audit are vindicated: E13 midline, E17 outside the cortex, E18 ill-defined
  removed no protected cSS (63 protected, 0 excluded).
- **E25 interhemispheric fissure** (CSS_V53=1): left AND right cortex both within 3 mm of >= 30 % of the object's voxels (dual_contact_frac, appended):
  8 shown non-cSS flagged, 0 of 63 cSS (highest cSS 0.17 = M05 #3, which curves into adjacent cortex). Checked before the older E13. Test: PHD
  relabels the cortex around one true lesion half left / half right -> that lesion is excluded by E25, lesions >= 15 mm away are kept.
- scripts/css_shape.py + shape_probe.py + tests/check_shape.py, check_shape_probe.py: blob (l_over_m, m_over_s, fill, support) and sulcus measures
  (bend_ratio, depth range, crown / deep share, regions touched) next to the calls, plus axis_angle_deg (long axis vs the axial plane). Findings from the unit
  test: on 3 mm slices a round 4.8 mm blob reads l_over_m 1.5 (slice quantisation), and bend only ranks shapes (slice thickness dominates) - thresholds must
  be set per slice thickness. Rule grids BLOB (microbleed) and STRAIGHT (straight in a sulcus without tracking into the adjacent cortex) are fitted offline
  from shape_probe.csv; nothing is switched on until then.
