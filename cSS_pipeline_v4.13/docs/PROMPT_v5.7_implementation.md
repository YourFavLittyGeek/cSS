# Prompt to implement v5.7 (paste into Claude Code, in the repository root)

You are working on the cSS pipeline in `cSS_pipeline_v4.13/` (research software for grading cortical superficial siderosis on
SWI; not for clinical use). Read `CLAUDE.md`, `docs/AUDIT_v5.6.4_and_PLAN_v5.7.md`, `docs/CHANGELOG_v5.3.md` and
`docs/CHANGELOG_v5.6.md` first. Then implement the plan of that audit **stage by stage, stopping after each stage** for me
to run it on my Mac (Apple M3, 36 GB, FreeSurfer 8.2, conda env `css`, python 3.11, data in `~/css_project`). You have no
patient data: everything you fit must come from the CSV files I send back.

## Rules that always apply
- One stage per turn. End each stage with: what changed, what you tested and the result, what you did NOT test, and the
  exact zsh commands I must run (copy-paste ready, one study at a time for anything heavy, never while a batch runs).
- Detector changes are opt-in under `CSS_V53=1`, append-only for CSV columns, and every excluded object stays in
  `ID_excluded.csv` with a rule id and a plain-language reason. No object may lose its fate (the detector's invariant).
- No threshold is chosen by eye. Fit it offline from my probe CSV, and print for each rule: cSS calls lost, non-cSS removed,
  the nearest cSS to the threshold and its margin. Stop and ask if any cSS call would be lost or the margin is under 10 %.
- Never tune on M12-M15 or M01. They are the frozen test set.
- Python 3.11 only (no same-quote nesting in f-strings), numpy / scipy / nibabel / pandas / scikit-image only, no network.
- Run `bash tests/run_tests.sh` after any change to detect or score logic and report the real result. Add a test for every
  new rule (phantom objects that must be excluded AND true lesions that must be kept).
- Sketch any visible reviewer change as an image first and wait for my approval before coding it.
- Keep `CLAUDE.md` and a `docs/CHANGELOG_v5.7.md` up to date; regenerate `ALL_CODE.md`; give me an installable zip each stage.

## Stage A - fixes with no change to detection
1. `review_web.py`: a new reviewer name starts with no calls; add an explicit "Import earlier calls..." action. Write the
   legacy `ID_calls.csv` only for the primary reviewer (first reviewer of the study, changeable in Settings); `score_css.py`
   and `/api/finish` score the named reviewer's own file.
2. New call class **Microbleed** (fine code MB in `css_common.LABELS`, coarse class not-cSS): button, key `W`, colour, in the
   summary, in `css_report` (count per study), in `compare_reads` and the calls tables. Old files stay readable.
3. **Validation read mode** (Settings, default ON for studies with no final record): AI meter hidden and locked, comparison
   window off, and a random 20 % sample of excluded objects mixed into the candidate list unmarked (their calls are stored
   in `ID_excluded_audit_<reviewer>.csv`, never scored). The mode is written to `ID_final.json` and the report.
4. Meter caps in `ai_opinion`: never green when the object is blob-like or fissure-like (use the columns of stage D when
   present, otherwise today's hints), or in tier 3-5.
5. Clean-ups: one mid-sagittal plane construction in `detect_css.py` (keep 7b, make the mirror check use it; prove the
   phantom outputs are unchanged apart from the documented columns), `side_check` from world coordinates of the labelled
   hemispheres, dead code in `v53_change_report.py`, single `ai_opinion` call in `compare_reads.py`,
   `tools/make_all_code.py`, `tools/make_release.sh`, `tests/check_viewer.js` (Playwright; skipped when not installed),
   refresh the detector section of `CLAUDE.md`.

## Stage B - `scripts/shape_probe.py` (read-only, like `midline_probe.py`)
For every shown and excluded object of the given studies, next to my calls (same call lookup as `midline_probe.py`):
- dark support = voxels with z below the weak threshold, 26-connected to the object within 1 voxel, capped at 15 mm from it
  (recompute z as the detector does or read `work/ID_dark.nii.gz` if it is equivalent - check and say which);
- blob measures on the support in mm: `blob_esd_mm`, principal extents, `blob_l_over_m`, `blob_m_over_s` (shortest axis
  floored at one slice thickness), `blob_fill`, support volume / object volume, slices spanned;
- fissure measures: build the fissure mask described in audit 3.2 (rays along the local plane normal reaching left tissue on
  one side and right tissue on the other within 15 mm), then `fissure_frac`, `fissure_side_bias`, `medial_surface`;
- existing columns copied through: `tram_frac`, `n_pieces`, `extent_mm`, `local_cont_max_mm`, `plane_dist_mm`, `cos_plane`,
  `ext_major_mm`, field strength and slice thickness.
Print call-by-call distributions, the cSS objects closest to "blob" and to "fissure", and a rule grid with cSS lost /
non-cSS removed / margin. Unit-test the measures on synthetic shapes (sphere, disc, rod, curved sheet, tram-track; thin and
3 mm slices) with hand-checked values. I will also re-open M02-M11 and label microbleeds with the new key before running it.

## Stage C - fit and report (no code change to the detector)
From my `shape_probe.csv`: propose E23 (compact blob) and E13b (free in the fissure) with thresholds, the table above, and
the list of objects each would remove, by study. Split the table by 1.5 T 3 mm vs 3 T. Wait for my go.

## Stage D - detector rules
Implement E23, E13b and the `cmb_like` fix with the approved thresholds; keep E22; keep the old `midline_frac` column but
drop it from the rule. New phantom tests: surface microbleeds (2-6 mm, thin and thick slices) excluded, a free fissure
sheet excluded, a tram-track and a short single-bank cSS next to the fissure kept, PH3/PH6 true lesions all kept. Then I run
`v53_compare.py` on M02-M11: all 61 cSS calls must still be shown.

## Stage E - continuous lines (recorded only)
`scripts/css_lines.py`: geodesic linking along the pial band as in audit section 4.1 (path <= 8 mm, >= 60 % weakly dark,
end tangents < 60 degrees, no aparc condition, never across the fissure, white matter not in the graph). Columns `line_id`,
`line_length_mm`, `line_dark_cover`, `line_n_pieces`, `line_gap_max_mm`; `review/ID_lines.nii.gz`. `score_css.py` reports
lines from `line_id` (the 0-4 rule itself is unchanged). Reviewer (after an approved sketch): pieces of a line share a
colour and a label, one key calls the whole line, "split" calls one piece. Tests: a line broken by two 3 mm gaps = 1 line;
two parallel lines on the two sides of a gyrus = 2; a line crossing an aparc border = 1; a vein branching off is not joined
when the tangent turns > 60 degrees.

## Stage F - frozen test
Freeze thresholds (write them and the build id into the manifest). Give me the commands to detect M12-M15 and M01 with
`CSS_V53=1`, read them in validation-read mode, and produce: `css_report`, per-rule exclusion table, the excluded-audit
result (any called cSS among excluded objects, by rule), microbleed counts, and reader-vs-radiologist grades with
`compare_grades.py` if the radiologist sheet is available.

## Stage G - only after F
3-D plate (sheetness) seeds as a second, recorded-only generation source; line features in `css_evidence` and the ranker;
per-protocol threshold report. Each behind its own switch, each with a before/after table on M02-M11.

## Known facts you must respect
- Reader labels are from one non-expert reader with intra-rater kappa 0.65 for cSS vs not; treat them as noisy.
- `M07 #11` (left pericalcarine, 21 mm) is a called cSS and looks geometrically like the occipital fissure object `M02 #4`:
  a rule that removes one removes the other unless the fissure mask separates them. If it does not, keep both shown.
- Medial-surface cSS exists (M11 #7 paracentral, #12 superior frontal): hugging one medial surface is not an exclusion.
- Short true foci exist (M11 #31, 8 mm): line length must not become a hard rule before stage F.
- Memory: never run FreeSurfer tools by hand or two detections at once on my Mac.
