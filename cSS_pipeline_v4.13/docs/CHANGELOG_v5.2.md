# v5.2 — surface-aligned patches, patch classifier, ranker upgrade

Source: the user's master plan (surface-aligned patches, `classify_surface_patches.py`, ablations A–G, required
tests) and Priority 3 of the v5.1 review prompt (nested CV, PR-AUC, Brier, baselines, model card).
Research software: everything here **ranks candidates for expert review**. Nothing is a diagnosis, nothing is a
calibrated probability, and nothing changes which objects are shown or excluded.

**Output-preserving.** The detector's candidates, exclusions, order and every existing CSV column are unchanged.
`detect_css.py` additionally writes `work/ID_pial_sd.nii.gz` (the signed pial distance it already computed), which the
patch extractor needs. With no model trained, nothing downstream changes.

## What was added

| # | Change | Where | Changes output? |
|---|---|---|---|
| 1 | **Surface-aligned patches.** Per object (shown and excluded) a patch of fixed physical size (default 24 × 12 × 8 mm, 0.5 mm grid) in a right-handed frame: u = the object's long axis projected into the cortical tangent plane, v = across the surface, n = outward pial normal (tissue → CSF) from the gradient of `work/ID_pial_sd.nii.gz`, mapped to world space with the inverse transpose of the affine (oblique / anisotropic data handled). The sign is checked against the labels and flipped if reversed (`normal_flipped`). Channels swi / phase / flair / labels on one world grid; a missing, off-grid or stale channel is **not zero-filled** — it is absent, its validity mask is all False and the reason is recorded. Intensity voxels outside the brain mask are never valid. Objects with < 3 voxels are listed as skipped with the reason (no silent loss). | `scripts/surface_aligned_patch.py` | new files `review/ID_patches/*.npz`, `review/ID_patches.csv` |
| 2 | **Patch classifier** (cSS vs vein): `features` (per channel in a fixed order: validity fraction, robust-z distribution, mean gradient along u / v / n, 8-bin profiles along each axis; label channel: tissue share along n; every channel adds `<ch>_missing`, `<ch>_valid_fraction`; optional geometry and vessel columns from the detector CSVs), `train` (dev split only, `--split test` refused, ≥ `--min-studies` studies and both classes; LOPO with nested L2; ablations A swi, B +phase, C +labels/geometry, D +vessel, E +flair, F swi+phase+labels+geometry+vessel, G all; AUC with patient-bootstrap CI, PR-AUC, Brier, sensitivity at 1 FP/scan; model JSON with feature schema, channel order, preprocessing, training studies, fold log, out-of-fold predictions, label hash, build, model hash, `research_only`), `predict` (refuses training studies, schema / channel-order mismatches and a model whose hash does not match; writes provenance per row). | `scripts/classify_surface_patches.py` | new files only |
| 3 | **Shared model code**: class-balanced L2 logistic regression, LOPO by patient with optional nested L2 selection (grid 0.1 / 1 / 10), one-class training folds skipped and logged (never filled in), AUC, average precision, Brier, patient bootstrap, sensitivity at k FP per scan, model hash. numpy / scipy only. | `scripts/css_model.py` | — |
| 4 | **Ranker upgrade**: `train_ranker.py` uses `css_model`; nested LOPO by default (`--no-nested` = fixed `--l2`); reports model, `score_v4`, darkness-only and vessel-only models on the same folds (AUC + CI, PR-AUC, sensitivity at 1 and 3 FP/scan, Brier for fitted models); writes `review/ranker_model_card.md`; the JSON adds `evaluation`, `lopo_fold_status`, `build`, `research_only`, `model_hash`. All keys `rank_candidates.py` reads are unchanged. | `scripts/train_ranker.py` | model JSON / card only |

## Tests (`tests/check_v52.py`, in `run_tests.sh`)

Master-plan tests covered: sheet vs tube patch (dark extent across the surface 12 mm vs 2 mm; sheet below, tube
above the surface; tissue on −n); reversed normal flipped by the labels; oblique 1 × 1 × 2 mm affine (n = rotated
slice axis); < 3 voxels skipped with reason; missing phase; FLAIR off the SWI grid and FLAIR older than the SWI
(each recorded as missing, features NaN, `<ch>_missing` 1); partial patch at the array edge (fixed shape, valid
fraction 0.68); outside-brain voxels never valid; patient grouping (a patient's out-of-fold scores ignore its own
labels, plain and nested); one-class fold skipped; schema persistence (predict refuses a schema mismatch); model hash
(a tampered model is refused); test split refused; too few studies refused; training study not predicted. On PH3 every
shown and excluded object gets a manifest row.

### External contract suite

`tests/verify_updated_architecture.py` (supplied by the user, unchanged, in `run_tests.sh`): 5 PASS, 1 SKIP. To meet
it, `surface_aligned_patch.extract_patch()` became the library entry (the CLI now calls it; PH3 patches are
bit-identical before / after) and `classify_surface_patches.py` gained `read_manifest` (duplicate or missing patch ->
error), `build_matrix` (features named `<channel>:<feature>`, e.g. `phase:missing`; labels other than cSS / vein codes
-> error), `grouped_lopo` and the `lopo-manifest` subcommand. SKIP: the optional `scripts/object_ledger.py` - the fate
invariant is already enforced inside `detect_css.py` (exit 4, manifest `fates`), so no separate module was added.

## What the synthetic test shows about the ablations (honest)

On the synthetic tables the single informative column sits among ~190 patch features: LOPO AUC A_swi 0.997, G_all
0.83 with 120 rows from 6 studies. **Adding channels costs accuracy when labelled studies are few** (more
weights, same data). The ablation table is there to show whether phase / FLAIR / geometry add anything on real
labels; do not default to G_all.

## Not done / limits

- No real labelled data yet: every number above is synthetic. The classifier must beat `score_v4` on held-out
  **test** studies (`evaluate.py`) before it is used for any reading order.
- The patch frame depends on the label-derived pial surface: on the SWI-only route (SynthSeg on SWI) it is coarse.
- Patch features are hand-designed summaries (no CNN); a learned encoder is for when ~10+ labelled patients exist.
- The 0.5 mm patch grid oversamples typical 0.8–1.2 mm SWI; patches carry the native resolution's blur.

## v5.2.1 — cohort import / batch run and patient-level grade comparison (detector unchanged)

- `scripts/cohort.py import COHORT_DIR`: one folder per study code with T1 / SWI / FLAIR sub-folders (DICOM or NIfTI);
  everything copied or converted into `raw/ID/`; picks the processed SWI (never the minIP, magnitude only as fallback),
  the phase on the SWI grid, the most isotropic T1 / FLAIR (a sagittal 3-D beats a thick axial MPR); flags thick SWI,
  non-3-D T1, missing series -> `review/cohort_import.csv`. `cohort.py run`: run_css.sh per study, one at a time, logs and
  `review/cohort_run.csv` (ok / qc_insufficient / failed), skips detected studies unless `--redo`.
- `scripts/compare_grades.py`: expert patient-level grades (.csv / .xlsx: study_id, expert_L, expert_R, expert_total)
  vs `review/css_scores.csv` -> `results/grade_comparison_{patients,summary,confusion_total}.csv` and `.xlsx` (openpyxl).
  Exact / within-1 agreement, quadratic and unweighted kappa (patient bootstrap CI), Spearman, Bland-Altman, presence
  sensitivity / specificity per patient and hemisphere; patients without a score listed; unreviewed candidates,
  QC status, Euclidean scoring and total != L + R flagged.
- `tests/check_cohort.py` (in run_tests.sh): series choice, run arguments with a stub run_css.sh, hand-computed
  statistics. Full suite not re-run for this release (no detector, scoring or existing-script change).

## v5.2.2 — broken DICOM exports (detector unchanged)

First real cohort (M01-M15, an external drive): every series of every patient had 5-15 % of its files unreadable
(JPEG Lossless files cut off part-way by a browser download; 457 `*.crswap` files beside them; dcmdjpeg could not
decode them). dcm2niix had failed on the compressed files and, where it converted, volumes with gaps would have been
silent. Now:
- `cohort.py import` stages every DICOM folder in `raw/ID/MOD/_dicom`, decompresses JPEG files with dcmdjpeg (DCMTK)
  and records the files that do not decode (`unreadable_files.txt`, flag `<mod>_N_crswap_files`). A series with
  unreadable files is never converted with gaps: it is removed (flag `_incomplete_`), or with `--repair-missing`
  rebuilt by `scripts/dicom_repair.py`: missing slices interpolated linearly from the nearest readable slices,
  positions from a straight-line fit of position vs instance number (<= 0.1 mm), refused above 20 % missing, more
  than 2 consecutive missing slices, for phase series and irregular positions (`--max-missing-frac`,
  `--max-missing-run`); decisions in `repair.json`. dcm2niix messages kept in `dcm2niix.log`; exit 2 (no DICOM) is
  now flagged (was accepted). `cohort.py run` skips studies without a usable T1 (`--allow-no-t1`).
- `compare_grades.py`: column `repaired_series` and a "preliminary" flag for patients with interpolated slices.
- `tests/check_dicom_repair.py` (real dcm2niix, stub dcmdjpeg): without repair nothing with gaps is converted; with
  repair the volume equals the intact series' geometry, readable slices bit-identical, interpolated slices exact on a
  linear signal, unrepairable and phase series removed.
- Interpolated slices cannot show a lesion confined to that slice: results on repaired data are preliminary; the
  studies should be exported again (uncompressed, complete) when possible.

## v5.2.3 — results in the radiologist's layout (detector unchanged)

- `compare_grades.py` reads the radiologist's own sheet as it is: columns "Patient name", "ID", "R css", "L css",
  "cSS score (0-4)" are recognised (case, spaces and brackets ignored), .xlsx or .csv. The workbook's first sheet
  `results` has that layout - Patient name, ID, R cSS, L cSS, cSS score (0-4) from the pipeline, then the
  radiologist's three values, the difference, agree yes/no, field strength, QC and notes - followed by the
  patients / summary / confusion sheets as before. `--results-only` writes `results/css_results.xlsx` with the
  pipeline columns alone (no comparison).
- First cohort, clean re-export (T01-T15 = study codes M01-M15): 1.5 T with 3 mm SWI, TE 40 ms in M01 / M05 / M11 /
  M12 / M13; 3 T with 1.2-2 mm SWI, TE 18-20 ms in the other ten; phase only in M08. Report the two strata separately.

## v5.2.4 — memory: SynthStrip only where it is used (detector unchanged)

On the user's 36 GB Mac SynthStrip peaked at **30.9 GB** on M01's 1 mm whole-head T1 (`/usr/bin/time -l`); in the
batch it died without a message (M01 "failed" after 9 min), and a second SynthStrip started by hand next to M02's
run froze the Mac (~90 GB swap). Detection itself peaked at 1.6 GB on a 7-million-voxel 0.57 mm SWI (phantom).
- `prep_anat.sh`: the T1 skull-strip runs only on the SynthSeg + mri_coreg route, the only place its output is used
  (recon-all strips the skull itself); every SynthStrip call gets `-t ${CSS_THREADS:-4}`; T1 / FLAIR / SWI messages
  kept in `work/ID_*synthstrip.log` and shown on failure; a failed FLAIR skull-strip now stops prep_anat with its
  reason.
- Run one patient at a time and nothing heavy next to the batch.

## v5.2.5 — no SynthStrip when a T1 is given (detector unchanged)

SynthStrip used **64 GB** on M02's 2 mm SWI (python3.8 = FreeSurfer's Python; memory pressure red, 35 GB swap) after
30.9 GB on M01's T1: it cannot be relied on with 36 GB. With `--t1`, run_css.sh now
- imports the SWI whole-head; prep_anat.sh registers whole-head images (bbregister after recon-all; mri_coreg to the
  whole-head T1 on the SynthSeg route) and the whole-head FLAIR to the SWI - no SynthStrip on any of them;
- after prep_anat, `scripts/swi_mask_from_t1.py`: brain mask = the T1 labels on the SWI grid, holes filled, grown by
  5 mm (detect_css.py ignores a 3 mm rim inside the mask edge, so 2 mm of CSF beyond the label boundary stays in the
  search zone), largest piece; masks the SWI (modification time kept) and the FLAIR on the SWI grid; reports the
  brain volume (warning outside 900-2300 cm3).
- SynthStrip remains only for the SWI-only route, or with `CSS_SWI_SKULLSTRIP=synthstrip`.
- PH3 with a synthetic skull + scalp: the same 6 candidates at the same positions as on the brain-only phantom,
  volumes within 0.8 %, all 6 true lesions, same exclusions (tests/check_swi_mask.py; test_shell 4 / 4b / 5).
  On real SWI the mask edge differs from SynthStrip's (label-based, not intensity-based): compare candidates on P006
  (check_known 6/6) before trusting a cohort result.

## v5.2.6 — classic recon-all (no FreeSurfer 8 deep-learning steps)

With v5.2.5 installed, M02 still reached 85 GB in FreeSurfer's own python3.8: FreeSurfer 8's recon-all adds
`-synthstrip -synthseg -synthmorph -fix-vsinus -fix-mca-dura -fix-ento-wm -fix-ga -fix-acj -transfer-base-bfs` by
default (`$FREESURFER/etc/global-expert-options.v8.txt`, switched by `FS_V8_XOPTS`; its log showed
`mri_synthstrip --threads 2 -i .../orig.mgz`). `prep_anat.sh` now calls `recon-all ... -all -no-v8` (the classic
stream: watershed skull-strip, atlas-based aseg, a few GB); `CSS_RECON_V8=1` keeps the v8 defaults. Default
CSS_THREADS for recon-all lowered from 8 to 4. Earlier subjects (P006, LEMON) were reconstructed with the v8 defaults:
compare like with like.

