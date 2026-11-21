#!/usr/bin/env bash
# All tests of the EXPERIMENTAL unified score (synthetic; no patient data). Exit non-zero on the first failure.
set -e
cd "$(dirname "$0")/.."
mkdir -p unified_score/output
python3 tests/check_core_decompose.py
python3 tests/check_uscore_features.py
python3 tests/check_uscore_adversarial.py
python3 tests/check_uscore_seeds.py 5
python3 tests/check_uscore_pipeline.py
python3 tests/check_heldout_protection.py
python3 tests/check_processing_manager.py
python3 tests/check_link_study.py
python3 tests/check_write_guard.py
python3 tests/check_production_models.py
python3 tests/check_pm_full_pipeline.py
python3 tests/check_export_safety.py
python3 tests/check_audit_local.py
python3 tests/check_local_only.py
python3 tests/check_ui_poll.py
python3 tests/check_selection_notifications.py
python3 tests/check_app_unified.py
python3 tests/check_call_ledger.py         # v5.15: every reviewer kept, effective call policy, review states, consolidation hard stop
python3 tests/check_duplicate_detection.py # v5.15: no false duplicate on first-time import; genuine repeats still caught
python3 tests/check_app_review_qc.py      # v5.15: Anatomy QC restored, review status, reviewer-call API / Excel
python3 tests/check_identity.py            # v5.16: vault, uuids, unique identifiers, audited edits, manifest, import wizard
python3 tests/check_app_identity.py        # v5.16: Standard / Incognito through the app, no identifier leaks, guided import
python3 tests/check_gui_js_syntax.py      # every GUI script parses (a syntax error blanks the screen)
echo "unified-score tests: all passed"
