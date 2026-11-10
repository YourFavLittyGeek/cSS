# v5.3 — from the M02–M11 reading (opt-in: `CSS_V53=1`)

Research software; expert review required. Plan and evidence: `docs/PLAN_v5.3_from_M02-M11.md`.
**Not validated.** Every threshold below was chosen on the 10 read patients (M02–M11). Phantom tests show the
mechanics only. Without the switch the detector output is unchanged; four columns are appended.

## What the switch does (needs T1 anatomy; without it the switch turns itself off and says so)
1. **Search stays within the cortex outline.** Zone = cortex + 1.0 mm outside the labelled pial boundary
   (was 4 mm); the brain-mask edge band is no longer searched. The grown brain mask (labels + 5 mm) is still used
   for registration and display.
2. **New exclusions** (listed in `review/ID_excluded.csv` like all others, confidence "low"):
   - `E15` skull band — at least half of the object lies within 6 mm of the mask edge with dark signal (or the mask
     edge) 3–6 mm further out.
   - `E12` extent — one connected object > 3,000 mm³ or > 60 mm. Judged before merging, so a lining merged from
     several foci is never removed for its length.
   - `E13` midline — at least half of the object within 3 mm of the hemisphere boundary and lying outside the cortex
     (falx, sagittal sinus, midline veins). cSS on the medial cortex itself (inside the tissue) is kept.
   - `E14` orbitofrontal — orbitofrontal label and within 8 mm of the mask edge.
3. **One cSS = one candidate.** Second merge pass: objects within 6 mm join (not across white matter, never across
   hemispheres, capped at 80 mm). The score counts sulci per focus, so a merged focus keeps all its sulci.
4. **Tiers.** "Off the cortex, in the CSF, vessel-shaped" alone no longer gives tier 3; it needs a second vascular sign.

New columns (always written, last): `midline_frac`, `mask_edge_mm`, `skull_frac`, `v53_active`.

## Different from the plan
- Candidates are not grown to the full dark band and merging is by distance (6 mm), not geodesic along the sulcus.
- Insula: nothing done yet.
- A cSS that lies only in sulcal CSF more than 1 mm from the cortex, or on a gyral crown directly under dark skull,
  can be lost. `v53_compare.py` counts this.

## Found while testing
The first version applied the extent rule after merging: on the phantom two true lesions were merged into a 64 mm
object and excluded. Fixed (extent is judged per connected object before the second merge); `tests/check_v53.py`
covers it.

## How to check on the read patients (main project is not modified)
    python scripts/v53_compare.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
Runs v5.3 in `$CSS_BASE/v53_eval/` and reports, per reader call, whether each current candidate is still shown,
excluded (rule), dropped or no longer generated → `review/v53_compare_summary.txt`, `review/v53_compare.csv`.
Targets (plan step 5): cSS calls shown 61/61 or each loss explained; Artifact < 25; Normal < 80; cSS in tier 3 < 6.
Only if that passes: run M12–M15 with `CSS_V53=1` and read them (untouched test cases).
