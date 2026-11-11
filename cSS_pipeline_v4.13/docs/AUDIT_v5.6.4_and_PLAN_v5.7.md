# Audit of v5.6.4 and plan for v5.7 (research software; expert review required)

Scope: the code as committed at v5.6.4 (`detect_css.py` 1121 lines, `review_web.py/.html`, `score_css.py`, the v5.3 tooling),
read against what the M02-M11 reads, the M02-M06 redo, `midline_probe` and `compare_reads` showed. Nothing here has been
implemented. Every proposed rule must be measured on the real cohort before it is switched on (section 6).

## 1. What the evidence says today

| Fact | Source |
|---|---|
| v5.3 rules removed 48 of 134 old calls in M02-M06 and lost 0 of 31 cSS calls | compare_reads |
| Same reader, second read: cSS vs not-cSS agreement 85 %, kappa 0.65; exact class 62 % | compare_reads |
| 10 objects flipped cSS status (5 each way); M03 score 1 -> 3, M06 4 -> 3 | compare_reads |
| The AI score is above the reader in 4 of 5 studies (by 1-2 points) | css_report |
| E13 midline rule catches almost nothing that is still shown; E22 sheet rule flags 11 non-cSS, 0 cSS (offline) | midline_probe |
| M02 #4 (occipital fissure) has the same geometry as a called cSS (M07 #11) | midline_probe |
| All thresholds E12-E22 were fitted on the same 10 patients read by one non-expert reader; M12-M15, M01 untouched | history |

Consequence: the reference labels themselves move (kappa 0.65). Thresholds set "just beyond the most extreme cSS call" inherit
that noise. More hand rules on the same 10 patients will overfit; the plan below therefore measures first and freezes a test set.

## 2. Mistakes and weak points found in the code

### 2.1 Detector (`detect_css.py`)
1. **Microbleeds pass the shape gate (your observation is right).** Gate G3 uses `axis_major_length / axis_minor_length`
   = longest / SHORTEST principal axis (line 668). A flat disc passes as "elongated". On thick slices (3 mm, 1.5 T cases) a
   round microbleed that spans 2 slices is measured as a disc or a short rod and passes. The gate also is skipped for merged objects.
2. **`cmb_like` cannot fire on the microbleeds that are actually shown.** It needs >= 50 % of the 1-voxel shell in parenchyma
   (line 775). The search zone excludes white matter, so only SUPERFICIAL (cortical / juxtacortical) microbleeds become
   candidates, and those have half their shell in CSF -> `cmb_like = 0`. The flag is also only a tier, never an exclusion.
   E11 (opt-in) counts clusters of >= 2 blobs, not a single blob.
3. **Shape is measured on the ridge-thinned mask.** The object mask is the hysteresis of a per-slice 2-D ridge filter, so a
   blob is thinned and a blob/line decision on it is unreliable. Shape must be measured on the dark support (connected voxels
   with z below the weak threshold around the object), as E11 already does.
4. **E13 midline rule fails when the fissure is wide.** `midline_frac` = share of voxels within 3 mm of the surface that is
   equidistant from left and right labelled tissue. With atrophy the fissure is 6-10 mm wide, so an object on the falx or
   hugging one medial surface is > 3 mm from that surface -> `midline_frac` near 0 (M02 #4: 0.08). The rule measures the
   wrong thing: it should ask "is this in the interhemispheric fissure", not "is it within 3 mm of the mid-surface".
5. **Two different mid-plane constructions.** Section 7 (mirror check) and section 7b (E22) fit the plane from different
   hemisphere masks (`Lm/Rm` with deep nuclei vs cortex + white matter). One should be removed.
6. **"Continuous line" is Euclidean, not anatomical.** Merging joins pieces within 3-4 mm in space (cap 40 mm), the v5.3
   second pass joins within 5 mm only inside ONE aparc label, and `score_css` counts lines as pieces within 6 mm. So: one
   lining that crosses a label border (pre -> postcentral) stays split; two different structures on opposite sides of a thin
   gyrus or across a sulcus can join; a vein lying next to cSS joins it (7 merged candidates still mix cSS with other calls).
7. **Generation is axial 2-D only.** The Sato ridge runs per axial slice. Siderosis lying parallel to the slice (vertex,
   flat convexity) is a patch, not a ridge, in that slice and is under-detected; sensitivity depends on slice orientation
   and thickness.
8. **Fixed darkness thresholds across protocols.** z < -2.5 / -2.0 and E19 (> 4.5 SD) are the same for 1.5 T TE 40 3 mm and
   3 T thin-slice SWI; blooming and contrast differ, so the same rule behaves differently per scanner.
9. **Rule stack fitted to extremes.** Eleven opt-in rules, each cut at the most extreme of 61 cSS calls. Each new patient has a
   real chance of a true cSS falling outside one of them. No per-rule estimate of that risk exists yet.

### 2.2 Reviewer (`review_web.py`, `review_web.html`)
10. **Shared calls file is overwritten by whoever saved last.** Every save also writes the legacy `ID_calls.csv`
    (`save_calls`, in `Study.save`). `score_css.py` reads that file. With two readers the score silently follows the last one.
11. **A new reviewer name inherits the old reader's calls** when only the legacy file exists (`load_calls` fallback). This is
    why the redo needed the files moved away by hand. A new name should start empty unless the user asks to import.
12. **The AI meter is visible by default during reads used for validation.** All five redo reads had it visible; flips may be
    anchored. Default should be hidden for a "validation read" mode, visible only in a "training / second look" mode.
13. **AI meter / AI score over-call.** `meter = css_evidence / (css + vein)` x tier factor; midline objects are only reduced
    when `midline_frac >= 0.5` (rarely true, see 4), microbleed-like only when `cmb_like` (rarely true, see 2). So fissure
    objects and blobs can stay green and are counted in the AI score.
14. **No call class for microbleed.** The reader can only say Normal / Artifact for a microbleed, so the data needed to fit a
    blob rule is not being collected. `css_common.LABELS` already has the fine code `MB`.
15. **Side check is crude** (candidate x vs the middle of the brain bounding box); it should use the world x coordinate
    of the labelled hemispheres.
16. **No browser test in the repository.** The Playwright checks were run from a scratch folder; `tests/` has only the
    server check. A viewer regression would not be caught by `run_tests.sh`.

### 2.3 Tooling and process
17. `v53_change_report.py` line 96: dead expression (`~tb.cand_id.isin([])`), harmless but wrong-looking.
18. `compare_reads.py` calls `ai_opinion` twice per row (cosmetic); M02's old calls only partly match the snapshot.
19. `CLAUDE.md` "detect_css.py (v4)" section and `HOW_TO_TEST_v5.4.md` describe older behaviour; `ALL_CODE.md` is rebuilt by
    an ad-hoc snippet, not a script.
20. **Nothing from this session has reached GitHub** (the working branch has no remote copy; an earlier push was refused, 403). The commits exist only in this session's container and in the zips sent.
    The container is temporary. This is the largest practical risk in the project.
21. The full `tests/run_tests.sh` was not re-run after E22 until this audit (result: see section 8).

## 3. Recommendations: exclusion rules

### 3.1 Microbleeds (blob, not tram-line) - new rule E23, opt-in with CSS_V53
Measure on the DARK SUPPORT of the object (voxels with z < weak threshold connected to it within 1 voxel, capped at 15 mm):
- `blob_esd_mm` equivalent-sphere diameter; `blob_ax1/ax2/ax3_mm` principal extents in mm
- `blob_l_over_m` = longest / middle axis (line: large; disc and sphere: about 1)
- `blob_m_over_s` = middle / shortest axis, with the shortest floored at one slice thickness (sphere about 1; plate large)
- `blob_fill` = support volume / volume of its bounding ellipsoid (blob high, curved line low)
- `line_cont_mm` = dark continuation along the pial band beyond both ends (already `local_cont_max_mm`)
- existing `tram_frac`, `n_pieces`, `extent_mm`
Candidate rule (thresholds to be fitted, see section 6): `extent <= 12 mm AND blob_l_over_m <= 1.6 AND blob_m_over_s <= 2.0
AND blob_fill >= 0.5 AND tram_frac < 0.2 AND line_cont_mm < 5` -> "compact blob (microbleed-like), not a line".
Keep excluded objects in `ID_excluded.csv`; list them in a "microbleeds" count in the report (they matter for CAA).
Also fix `cmb_like` so it no longer needs the parenchymal shell (use the blob measures), and add generation gate G3b
(longest/middle on the support) for single-piece objects on thin-slice scans only.

### 3.2 Interhemispheric fissure - replace E13's measure
Build a **fissure mask** once per case: non-tissue voxels where a ray along +normal and a ray along -normal of the fitted
mid-sagittal plane (local normal re-estimated in 20 mm blocks so a bowed falx is followed) reach LEFT hemisphere tissue on one
side and RIGHT hemisphere tissue on the other within 15 mm. This is independent of how wide the fissure is.
Per object: `fissure_frac` (share of voxels in the mask or within 1 mm of it), `fissure_side_bias` (0 = centred between the two
medial surfaces, 1 = hugging one), `medial_surface` (nearest cortex is medial-surface cortex).
- Exclude (E13b): `fissure_frac >= t1 AND fissure_side_bias <= t2 AND tram_frac < 0.2` -> lies free in the fissure
  (falx, sinus, fissure veins).
- Keep but flag: hugging one medial surface (possible medial cSS; M11 #7, #12 are called cSS there) -> hint "medial surface,
  check coronal", meter capped at yellow.
- Keep E22 (sheet) as it is. Remove the old 3 mm `midline_frac` from the rule (keep the column).
- Check label alignment first: M02 #4 is labelled 7 mm from the fissure although the image shows it in the fissure; print
  `label_shift_vec_mm` and the posterior edge agreement from `M02_qc.json` before trusting any label-based measure there.
- Honest limit: calcarine / parieto-occipital cSS and occipital fissure objects of 20 mm overlap in every measure tried.
  The fissure mask may separate them (the fissure object is BETWEEN hemispheres, the sulcus is INSIDE one); if it does not,
  they stay shown with the hint.

### 3.3 Risk control for the whole rule stack
- For every rule print, on the labelled cohort: cSS lost, non-cSS removed, and the **margin** (distance of the nearest cSS
  to the threshold, in units of the cSS spread). Rules whose nearest cSS is within 10 % of the threshold are marked fragile.
- Freeze thresholds, then run M12-M15 + M01 ONCE, read them blind (meter hidden), and report per rule how many called cSS sit
  in `ID_excluded.csv` (the reviewer needs an "excluded objects" audit list for this: show a random 20 % of excluded objects
  mixed into the read, unmarked - `expert_sheet --include-excluded` already does this for the sheet).

## 4. Recommendations: detection, cSS as continuous lines

1. **Surface-geodesic linking (new module `css_lines.py`).** Graph = voxels of the pial band (|pial_sd| <= 1.5 mm). Two
   objects belong to one line when the shortest path between their ends inside the band is <= 8 mm AND at least 60 % of that
   path is at least weakly dark (z < -1.5) AND the end tangents differ by < 60 degrees. No aparc-label condition (a line may
   cross a label border); never across the fissure; white matter is not part of the graph, so opposite sides of a gyrus do
   not join through it. Output per candidate: `line_id`, `line_length_mm` (geodesic), `line_dark_cover`, `line_n_pieces`,
   `line_gap_max_mm`; a label volume `ID_lines.nii.gz`.
2. **Use lines, do not change the 0-4 definition.** The score stays sulcus-based. `score_css` replaces its 6 mm Euclidean
   "lines" by `line_id` groups and reports line count and total line length per hemisphere.
3. **Lines as evidence.** A long, dark-covered, surface-following line is the definition of cSS; a blob has length about its
   width. Add `line_length_mm`, `line_dark_cover` and `length / width` to `css_evidence` and to the ranker features; do NOT
   make them a hard rule before M12-M15 (short true foci exist: M11 #31 is 8 mm).
4. **Reviewer shows lines.** Pieces of one line share one colour and a "line 3 (pieces 4, 7, 9), 41 mm" label; one key applies
   the call to the whole line, with "split" to call a piece separately. Fewer decisions per patient, and the reader judges
   the structure the definition talks about.
5. **Stop cross-structure merges.** Do the tram-track join (two banks of one sulcus) as now; replace the Euclidean second pass
   by the geodesic link; keep per-piece evidence so a vein joined to cSS is flagged `mixed_object`.
6. **Plate filter in 3-D for flat-lying siderosis.** Add a 3-D Hessian sheetness (in mm, on the mask-filled image) as a second
   seed source next to the axial ridge: voxels that are plate-like, dark and in the pial band seed the hysteresis too.
   Recorded-only first (`gen` bit), then compare candidate counts and the missed-cSS marks before enabling.
7. **Protocol-aware thresholds.** Express darkness cuts per case in robust units of that case's cortex AND record field/TE;
   report rule behaviour separately for the 1.5 T 3 mm and 3 T thin-slice groups before any further tuning.

## 5. Recommendations: reviewer and process

- New call **Microbleed** (fine code MB, counted as not-cSS; button + free key `W`), so the blob rule can be fitted on your
  own labels; show a microbleed count in the summary and Excel report.
- **Validation read mode** (default for M12-M15): meter hidden and locked, comparison window off, excluded-object audit
  sample mixed in; "second look" mode keeps today's behaviour. The mode is stored in `ID_final.json`.
- A new reviewer name starts empty; "Import earlier calls..." is an explicit menu action. Scoring reads the named reviewer's
  file (`--reviewer`), and the legacy `ID_calls.csv` is written only for the reviewer marked primary.
- Meter: cap at yellow for `fissure_frac` high, blob-like, or tier 3-5; AI score counts green only -> fewer over-calls.
- Adjudicate the 10 flipped objects + 2 mixed merges blind in a third pass; use the 2-of-3 majority as the reference label.
- Get the commits out of the container: fix GitHub access for this session (Claude GitHub App on the repository) or keep
  installing the zips; add `tools/make_all_code.py` and `tools/make_release.sh` so a release is reproducible.
- Add `tests/check_viewer.js` (Playwright, skipped when not installed): zoom stays at fit, layouts, mirror round-trip,
  panel states, snapshot name.

## 6. Order of work (each stage stops for your data before the next)

| Stage | What | Output you run / send | Gate to continue |
|---|---|---|---|
| A | Bug fixes without behaviour change: items 5, 10, 11, 15, 17-19; Microbleed call; validation-read mode; meter caps | new reviewer | tests pass |
| B | `shape_probe.py` (read-only): blob measures on the dark support + fissure mask measures for every object, next to calls | `shape_probe.csv` + summary on M02-M11 | you label >= 15 microbleeds (re-open studies, key W) |
| C | Fit E23 and E13b offline from the probe; print cSS lost / removed / margin | table | 0 cSS lost and margin not fragile |
| D | Implement E23, E13b, cmb_like fix in `detect_css.py` (opt-in), phantom tests with synthetic microbleeds at the surface and a fissure sheet | `v53_compare` on M02-M11 | 61/61 cSS kept |
| E | `css_lines.py` recorded-only + reviewer line display; `score_css` line groups | redetect M02-M06, look | line groups look anatomically right to you |
| F | Freeze. Run M12-M15 + M01, validation-read mode, excluded audit sample | css_report + audit | report: sensitivity vs your read, cSS in excluded list, per-rule table |
| G | Only after F: 3-D plate seeds, line evidence in the ranker, protocol-aware thresholds | - | - |

## 7. What should NOT be done
- No further threshold tightening on M02-M11 alone. No rule from fewer than 5 supporting objects without a margin.
- No exclusion of medial-surface or occipital sulcal objects on geometry alone (M07 #11 would be lost).
- No use of the AI score as a result; it is a comparison column until it has been tested on M12-M15.

## 8. Test status at the time of this audit
See the end of this file (filled in after the full suite finished).
