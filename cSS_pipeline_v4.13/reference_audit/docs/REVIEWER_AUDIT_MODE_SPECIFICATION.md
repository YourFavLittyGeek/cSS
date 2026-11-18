# Reviewer-audit mode — specification and implementation (`cSS_pipeline_v4.13/reference_audit/`)

A standalone toolset. It reads production outputs and writes only under `$CSS_BASE/reference_audit/`. No file in `scripts/` is changed or
imported-with-side-effects (it imports nothing from production at all), no threshold or decision changes, and the reviewer web app is
not modified (its `--show-excluded` mode reveals exclusion rules and therefore is NOT used for blinded reads).

## Requirements -> implementation
| Requirement | Implementation |
|---|---|
| Preserve production completely | read-only; every production file read is sha256-recorded in `inventory/ID_inventory_manifest.json` |
| Capture objects excluded at every recorded stage | `inventory.py`: shown (`review/ID_candidates`), rule-excluded incl. confidence cut E30 (`review/ID_excluded`), generation-gate drops G1-G4 (`work/ID_dropped`). Never-generated lesions cannot be listed by any tool - only pathway A finds them |
| Exact exclusion reason | `objects_concealed.csv: reason` verbatim + `mechanism` category + gate id / measured / threshold |
| Masks, coordinates, anatomy, MRI reference | one label map per study `ID_audit_objects.nii.gz` (value = stage code x 100000 + production id), voxel + mm centre, hemisphere, lobe + DK region (nearest cortex label when the object has none), path + sha256 of the SWI |
| Score and measurements concealed | only in `*_concealed.csv` / `key_CONCEALED.csv` (score_v4, confidence %, darkness, extent, ...); review material contains case id, study code and centre only |
| Reproducible random sampling | `sample.py --seed` (default 20261119), seed + strata + plan stored in `batch_config.json` |
| Stratified by reason, size, confidence, location | `--strata` any of mechanism, size_bin, lobe, confidence_bin; `--plan` CSV (e.g. EXCLUDED_OBJECT_SAMPLING.csv; size_bin "all" rows are spread over size bins) |
| No duplicates across batches | `batches/ledger.csv`: every sampled uid; later batches exclude them; batch names are never overwritten; all batches must share the strata definition (checked) so the union stays a stratified SRS |
| Equal inclusion probability within a stratum | SRS without replacement per stratum; a per-study cap was removed because it would break this (`--max-per-study` is refused) |
| Blinding of object type | `--include-shown K` mixes K shown objects per study as controls; order shuffled; case ids carry no stage |
| Design-based estimation | `sampling_frame.csv`: population N, sampled n, weight N/n per stratum; `key_CONCEALED.csv: inclusion_prob` |

## Files
`inventory.py` -> `sample.py` -> `render_batch.py` (blinded PNG + optional single-object mask + annotation sheet) ->
readers -> `validate_annotations.py` -> `agreement.py objects` -> adjudication -> `evaluate.py`.
Pathway A: `ws_prepare.py` (blinded case folders without any detector output, per-reader random order, empty templates) -> readers ->
`agreement.py whole_scan` (lesion clusters across readers, agreement, adjudication template) -> `evaluate.py`.

## Concealment rules (who sees what)
| File | Reader | Adjudicator | Analyst |
|---|---|---|---|
| `cases/<CODE>/*` (images only), `review/<case_id>.png`, `cases_blinded.csv`, templates | yes | yes | yes |
| other readers' annotation files | no | categories + comments only (identities hidden) | yes |
| `key_CONCEALED.csv`, `*_objects_concealed.csv`, `sampling_frame.csv`, lists, scores, reasons | **no** | **no** | yes |
Practical rule: copy only `whole_scan/<PACKET>/cases`, the reading order and the templates (or `batches/<B>/review/`) to the reader;
keep everything else on the analyst's machine.

## Tested (sandbox, phantom data only - plumbing, no results): `bash reference_audit/tests/check_reference_audit.sh`
PH3 + PH6: inventory 823 objects (15 shown, 9 excluded, 799 gate drops); two batches without duplicates; plan with "all" rows;
blinded images; whole-scan packet; synthetic two-reader annotations -> clusters, kappas, adjudication template, evaluation with all
four fates (retained / excluded / dropped / never generated) and the stratified estimate. All scripts compile under Python 3.11.
