# DATA_SCHEMA.md - Stage 2 data contracts (design, not implemented)

All new tables are NEW files with a schema version; no existing table, column or file is changed or overwritten.
Existing contracts that stay authoritative: `review/ID_candidates.csv` / `ID_excluded.csv` (columns up to
`long_structure` frozen, new columns appended), `labels/candidate_labels.csv` (`css-labels/1.0`), `css-patch/1.0`.

## 1. Identity

| key | definition | source |
|---|---|---|
| `study_id` | study code (e.g. SYN01 / M12); never a name or MRN | existing |
| `patient_key` | pseudonymous patient key; several studies may share it | NEW `labels/patient_keys.csv` (user-provided, blocker 2); absent -> `one study = one patient (unverified)` recorded |
| `cand_uid` | `study:vox_i:vox_j:vox_k:volume_mm3` | `css_common.cand_uid` |
| `list`, `obj_id` | `candidate` / `excluded`, detector id | detector |
| `detector_version`, `rule_version` | from the candidate table | detector |
| `object_key` | sha256(cand_uid + detector_version) - the training row key | NEW |

## 2. Image record (`ImageRecord`, one per study x channel) - `labels/` is NOT used; stored in `unified_engine/image_index/ID.json`

| field | meaning |
|---|---|
| `channel` | swi / phase / flair / labels / pial_sd |
| `path_rel`, `sha256`, `mtime` | file relative to `$CSS_BASE`, content hash, modification time |
| `shape`, `zooms_mm`, `affine` (4 x 4), `affine_sha` | geometry as loaded by nibabel |
| `qform_code`, `sform_code`, `axcodes` | header provenance (e.g. LAS) |
| `si_axis`, `slice_axis_ok` | the detector's axis-2 = S-I gate result |
| `on_swi_grid` | same shape and affine (tolerance 1e-4 mm) as the SWI |
| `fresh` | not older than the SWI (`css_common.stale_against`) |
| `registration` | chain to the SWI grid: list of `{from, to, file, sha256, method (bbregister / mri_coreg / identity), cost}` from `work/ID_swi2t1.lta`, `work/ID_flair2swi.lta` |
| `anatomy_source` | recon-all / T1 SynthSeg / SWI SynthSeg (css_qc) |
| `acquisition` | sequence (SWI / T2*-GRE), field, TE, vendor, from `raw/ID/SWI/*.json` as already read by `score_css.py` |
| `qc_status` | ok / low_confidence_review / insufficient_quality (css_qc) |

## 3. Candidate label (`css-labels/2.0`, NEW table `labels/candidate_labels_v2.csv`, long format)

One row per study x reader x session x object. Required columns: `study_id, patient_key, reader_id, reader_role
(expert / trainee / consensus), session, blinded, list, obj_id, cand_uid, object_key, detector_version,
primary_class, mimic_subtype, confidence (1-5), quality_reason, scope_reason, timestamp, label_schema_version`.

`primary_class` (exactly one):

| class | meaning | training use |
|---|---|---|
| `definite_css` | definite cortical superficial siderosis | positive |
| `definite_mimic` | definite non-cSS; `mimic_subtype` required | negative (subtype kept for error analysis / optional multiclass) |
| `indeterminate` | reader cannot decide on adequate images | excluded from fitting; reported; used in a sensitivity analysis |
| `insufficient_quality` | image quality does not allow a decision; `quality_reason` required (motion, susceptibility, coverage, registration, other) | excluded from fitting; trains nothing; counted in QC |
| `out_of_scope` | object outside the task; `scope_reason` required (infratentorial, ICH-related, outside brain, not an object / detector artefact) | excluded from fitting |

`mimic_subtype` vocabulary (maps 1:1 to the existing `css_common.LABELS` fine codes, so `css-labels/1.0` rows can
be converted without loss): vein_unspecified (V), vein_surface (VS), vein_sulcal (VC), vein_transcortical (VT),
vein_sinus_adjacent (VX), thrombosed_vein (TV), artifact_airbone (A), artifact_motion (AM), normal_other (N),
normal_iron_cortex (NI), microbleed (MB), calcification (CA), acute_cSAH (SAH), laminar_necrosis (LN),
haemorrhagic_infarct (HI).

Conversion of `css-labels/1.0`: C -> definite_css only if confidence >= 4 (else indeterminate); U -> indeterminate;
IS -> out_of_scope/infratentorial; H -> out_of_scope/ICH-related; other codes -> definite_mimic with that subtype if
confidence >= 4, else indeterminate; confidence missing -> indeterminate. The thresholds are a proposal for approval.

Consensus (`labels/candidate_consensus_v2.csv`): one row per object; `method` = agreed / adjudicated / single_reader
/ pending; only `agreed` and `adjudicated` rows train by default.

Missed lesions (sensitivity, not training rows): existing `review/ID_missed.csv` and `labels/ID_missed_READER.nii.gz`
are referenced, not changed.

## 4. Patch record (`css-patch/2.0`, extends 1.0 by appending fields)

Arrays: `image_<ch>` float32 [U, V, N] in the surface frame (default 24 x 12 x 8 mm at 0.5 mm -> 48 x 24 x 16),
`valid`, `valid_<ch>` bool, `native_stack_<ch>` float32 [S, H, W] (NEW, 2.5D native-slice context: the candidate's
own axial slices +-2, native in-plane spacing, 32 x 32 mm), `object_mask` bool in both grids.
Metadata: everything of 1.0 plus `frame_hash` (u, v, n, centre), `image_sha256` per channel, `affine_sha`,
`registration` (from ImageRecord), `normal_flipped`, `edge_fraction`, `interp` (linear / nearest), `extractor_version`,
`synthetic` flag (true only on synthetic bases).

## 5. Prediction record (shadow result schema 2, `unified_engine/shadow/ID.json`; schema 1 fields unchanged)

Per candidate, new block `image`: `available`, `status` (ok / channel_missing / geometry_refused / quality_refused /
model_missing / withheld_real_study), `increment` (log-odds), `uncertainty` (5-95 %), `channels_used`,
`model_hash`, `model_version`, `patch_schema`, `frame_hash`, `image_sha256`. Unified block gains `streams_used`
(M / C / I) and `weights` (a, b, g_C, g_I). Header gains `image_index_sha`.

## 6. Training record (hash-protected, inside the model file)

`data_kind` (synthetic / clinical), `cohort_manifest_sha`, `patient_split` (patient_key -> fold / held_out),
`label_table_sha`, `label_schema_version`, `detector_version`, `extractor_version`, `feature_list` or network
architecture hash, `seed`, `software` (python, numpy, scipy, torch if used), `code_sha` (engine files),
`hyperparameter_search` (grid, inner folds, selection metric), `calibration` (method, fitted on which folds).
