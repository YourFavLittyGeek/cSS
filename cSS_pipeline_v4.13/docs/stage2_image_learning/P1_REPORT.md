# P1_REPORT.md - Stage 2 P1: image index + geometry gate (SYNTHETIC data only), 2026-11-20

Research software. No clinical file was opened, copied or processed. Every reading function refuses a non-synthetic base or study
before opening a file (no override exists in P1). The Stage 1 scoring engine, `scripts/` and `unified_score/` are unchanged.

## Decisions recorded (user approval 2026-11-20: "Approve D1-D6 as proposed")
| decision | recorded as |
|---|---|
| D1 | option A (image-derived features + penalised model) first; 2.5D CNN gated; 3D CNN and joint hybrid rejected |
| D2 | label classes of css-labels/2.0; conversion from 1.0 with confidence >= 4 = definite |
| D3 | both representations: surface-aligned patch (existing css-patch/1.0) + native 2.5D stack |
| D4 | image stream retained only if within-patient permutation p < 0.05 AND within-patient AUC gain >= 0.02 |
| D5 | PyTorch may be added for P9 only; NOT installed now (P1-P8 need numpy / scipy only) |
| D6 | the roadmap listed two options without marking one as the proposal. **Open: needs your explicit choice** (reuse the existing 10 held-out studies, or define a new frozen set). Nothing before P10 depends on it |

## What was built (`unified_engine/uengine/imaging/`)
| module | content |
|---|---|
| `__init__.py` | versions (`uengine-imaging/0.1`, schema `css-image-index/1.0`), pinned sha256 of `css_qc.py`, `css_surface.py`, `detect_css.py`, `NotSynthetic` |
| `geometry.py` | `describe()` (shape, zooms, affine + hash, qform / sform codes, axis codes, world bounding box); css_qc's orientation / obliquity block EXECUTED VERBATIM; the detector's stop condition evaluated verbatim; `gate()` with findings geometry_refused / quality_refused / low_confidence; world-mm sampling helpers |
| `registration.py` | LTA record via `css_surface.read_lta` (pinned): type, RAS->RAS, rigidity, rotation / translation, volume-info check against the SWI, freshness; `reg.json` method + cost against css_qc's `REG_COST_LOW_CONF` (0.8); image-based residual shift (normalised mutual information, contrast-agnostic) for channels already on the SWI grid; acquisition via `css_qc.read_acq` (already a whitelist) |
| `index.py` | `index_study()` -> ImageRecord per channel (swi, phase, flair, labels, pial_sd) with status ok / missing / stale / off_grid / geometry_refused / quality_refused / low_confidence / misregistered / registration_invalid; dependency of resampled channels on their LTA; anatomy source (css_qc's rule); inputs hashed before / after; content hash; `verify_index()`; writes only `$base/unified_engine/image_index/ID.json` |
| `synthetic_images.py` | world-defined phantom (WM, cortex, CSF, sulci, dark tubes; FLAIR with scalp), grids with any voxel size / storage order / obliquity, LTA writer (type 0 and 1 with volume info), `write_study()` laid out like `$CSS_BASE`, refuses folders with non-synthetic content |
| `unified_engine/run_imaging.py` | CLI: `verify`, `demo DIR --n`, `index SID --base DIR [--write]` (exit 3 = refused) |

Thresholds: design envelope in-plane <= 1.0 mm, slice <= 2.5 mm (approved design proposal); css_qc's provisional THICK_SLICE_MM 2.0,
OBLIQUE_LOW_CONF_DEG 20, REG_COST_LOW_CONF 0.8 read from the pinned file; residual shift ok <= 1.0 mm, misregistered > 2.0 mm,
search +-4 mm (PROVISIONAL, set on synthetic tests only).

## Tests (executed; `unified_engine/tests/test_imaging_*.py`, 37 tests, ResourceWarning = error)
- **geometry (13)**: pinned sources; css_qc block == independent replica == detector stop condition on 300 random affines;
  storage-order invariance (LAS, LPS, RPI, LPI, PRS, ALS: world samples identical to 1e-4, same world box, gate ok); oblique grid samples
  the same world object; refusals: slice axis not S-I (ASR, SAR, RSA, LIP; single finding), header codes 0, NaN / singular affine,
  zooms vs affine, qform vs sform, 4-D; obliquity 10 deg ok / 28 deg low confidence; voxel envelope; same-grid tolerance.
- **registration (10)**: type 0 and type 1 LTAs give the same RAS->RAS; rigid parameters recovered; non-rigid refused; LTA made for
  another image refused (volume info); missing / stale / unreadable; reg.json cost threshold is css_qc's; residual shift recovered within
  0.35 mm and classified at 0 / 0.6 / 1.5 / 2.4 / 2.8 mm; contrast-inverted FLAIR; beyond the search; noise-only channel unmeasurable.
- **index (14)**: non-synthetic base and non-SYN codes refused with the folder unchanged; generator refuses a real-looking folder;
  clean study record complete; only `image_index/SYN01.json` written and nothing else touched; deterministic hash; tampered index
  detected; missing channels absent (not zero); stale / off-grid / misregistered channels; registration state propagates (cost,
  stale LTA, missing LTA); refused SWI -> nothing usable; acquisition whitelist (planted name / date never copied); CLI incl. exit 3.

Exit criterion (roadmap): geometry invariance 1e-4 - met; every refusal path tested - met.

## Findings during P1
1. **nibabel's `as_reoriented` rewrites a 0 sform code to 2** ("aligned"): a reoriented copy of an image without valid header codes
   would look valid. The test generator now preserves the source codes; the gate always reads the file's own header, never a
   re-saved copy. Relevant for any future preprocessing step: never reorient before the gate.
2. **Production `css_surface.read_lta` and `css_qc.read_acq` leave their file open** (ResourceWarning). Not changed (production code);
   contained in `registration.py`.
3. The FLAIR residual-shift check uses mutual information inside the SWI brain mask, so a non-skull-stripped FLAIR (as written by
   `mri_vol2vol`) does not produce false misregistration on the synthetic data. Its thresholds are provisional until checked on the
   P3 generator with acquisition variability.

## Not in P1 (later phases)
Patch extraction (P2), the parametric generator with acquisition variability (P3), labels (P4), models (P5+), GUI (P7).
