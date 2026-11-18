# reference_audit/ — blinded reference-standard and production-sensitivity audit (read-only on production)
inventory.py (all production objects at every recorded stage, concealed metadata) -> sample.py (stratified, seeded, no duplicates) ->
render_batch.py (blinded images) | ws_prepare.py (whole-scan blinded packet) -> validate_annotations.py -> agreement.py -> evaluate.py.
annotation_schema.py holds every field and allowed value. Writes only to $CSS_BASE/reference_audit/. Imports nothing from scripts/.
Documents: docs/ (audit, protocol, specification, sampling plan, templates, agreement plan, false-negative analysis, Mac guide, final safety audit). Test: bash reference_audit/tests/check_reference_audit.sh
