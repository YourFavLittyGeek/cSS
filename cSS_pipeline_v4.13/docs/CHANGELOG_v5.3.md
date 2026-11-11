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

## v5.3.1 — after the first acceptance test (M02–M11, user's Mac)
v5.3.0 result: cSS calls still shown 45 / 61 (9 lost to the extent rule, 3 to the skull-band rule, 3 below the size
gates, 1 not generated), Artifact 20 / 78, Normal 80 / 114, cSS in tier 3 18 -> 3; 10 merged candidates joined a cSS
call with a vein / normal / artifact / near-ICH call; candidate counts rose in M06, M07, M10. Changes:
- Generation is unchanged from v5.2 (same zone, same ridge percentiles). Narrowing the zone had moved the percentile
  thresholds and cut hysteresis seeds. Instead, object voxels more than 1.5 mm outside the labelled cortex are
  removed after generation ("outside the skull" / dura band).
- E12 extent: volume > 3,000 mm³ only (the 60 mm length test removed thin cSS).
- E15 skull band: only for objects whose median position is on / outside the brain surface (pial distance > 0).
- E16 ventricles (new): >= 30 % of the object within 3 mm of a ventricle or choroid plexus label.
- E13 midline unchanged; E1 infratentorial (cerebellum / brainstem) unchanged and always on.
- Second merge: 5 mm and only between objects with the same cortical region label.
- v53_compare.py also prints the excluded counts by rule and reader call.
New column: vent_frac (appended). Still tuned on M02–M11 only.

## v5.3.2 — after the second acceptance test
v5.3.1 result: cSS calls shown 58 / 61 (lost M07-5, M07-10, M09-2: all below the size gates after the 1.5 mm trim);
Artifact 50 / 78 (target < 25), Normal 95 / 114 (target < 80), cSS in tier 3 9 (target < 6), 6 merges joining a cSS
call with another call. Remaining shown artifacts: precentral 11, superior frontal 9, rostral middle frontal 5
(convexity); Normal: superior frontal 23, precuneus 13, insula 10 (midline / medial and insula).
- No voxels are removed after generation any more (the 1.5 mm trim caused the 3 losses). Instead a new rule E17
  "outside the cortex" excludes objects with >= 60 % of their voxels > 1 mm outside the brain surface AND cortex
  share < 0.4 AND no tram-track. Every object keeps a traceable fate (shown / excluded by a named rule).
- v53_compare.py now writes each candidate's v5.3 features (v53_* columns) and review/v53_objects.csv (every v5.3
  object, shown and excluded, with the reader calls mapped onto it), so the rule thresholds can be checked against
  the calls without another run.

## v5.3.3 — thresholds from the 287 read candidates (v53_compare.csv of v5.3.2)
v5.3.2 result: cSS 58 / 61 (M04-32, M04-46, M06-25 excluded by the skull-band rule at skull share 0.51–0.64),
Artifact 29 / 78, Normal 101 / 114. Using the per-object features of that run, each rule below was set just beyond the
most extreme of the 61 cSS calls (cSS range in brackets) and checked offline on all 287 calls:
- E15 skull band: skull share >= 0.70 and outside the surface (cSS max 0.64; was 0.50).
- E13 midline: >= 50 % within 3 mm of the hemisphere boundary, at any depth (cSS max 0.36) — the fissure is excluded
  as asked; medial cSS within the fissure would be lost.
- E18 ill-defined: edge contrast < 1.5 SD (cSS min 1.72).
- E19 / E20 / E21, only for objects at least 30 % skull-backed: darker than 4.5 SD (cSS max 4.3), larger than
  1,000 mm³ (cSS max 895), cortex share < 0.33 (cSS min 0.38). Without the skull condition these rules removed every
  synthetic phantom lesion (darker and larger than any read cSS): absolute darkness and size depend on scanner, TE and
  disease extent.
Expected on M02–M11 (offline, from the v5.3.2 features): cSS 61 / 61, Artifact 22 / 78, Normal 90 / 114, Vein 14 / 20,
Near ICH 5 / 11. The Normal target (< 80) is not reached: the remaining Normal calls are dark normal cortex (medial
superior frontal, precuneus, insula) that no measured feature separates from the cSS calls.
These thresholds are FITTED to M02–M11 with little margin; M12–M15 (and M01) are the real test.
