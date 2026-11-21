#!/usr/bin/env bash
# All tests of the EXPERIMENTAL unified score + app + Percival (synthetic; no patient data).
# v5.23: every check runs (a failure no longer hides the checks after it); exit non-zero if ANY check failed.
# A check that cannot run on this computer is reported as SKIPPED with its reason - never counted as passed.
cd "$(dirname "$0")/.."
mkdir -p unified_score/output
FAILED=(); SKIPPED=(); PASSED=0
run() { echo "=== $*"; if python3 "$@"; then PASSED=$((PASSED+1)); else FAILED+=("$1"); fi; }
skip() { echo "=== SKIPPED $1: $2"; SKIPPED+=("$1 ($2)"); }
run tests/check_core_decompose.py
run tests/check_uscore_features.py
run tests/check_uscore_adversarial.py
run tests/check_uscore_seeds.py 5
run tests/check_uscore_pipeline.py
run tests/check_heldout_protection.py
run tests/check_processing_manager.py
run tests/check_link_study.py
run tests/check_write_guard.py
run tests/check_production_models.py
run tests/check_pm_full_pipeline.py
run tests/check_export_safety.py
run tests/check_audit_local.py
run tests/check_local_only.py
if command -v npm >/dev/null 2>&1; then run tests/check_ui_poll.py; else skip tests/check_ui_poll.py "needs Node / npm, not installed"; fi
run tests/check_selection_notifications.py
run tests/check_app_unified.py
run tests/check_call_ledger.py   # v5.15: every reviewer kept, effective call policy, review states, consolidation hard stop
run tests/check_duplicate_detection.py   # v5.15: no false duplicate on first-time import; genuine repeats still caught
run tests/check_app_review_qc.py   # v5.15: Anatomy QC restored, review status, reviewer-call API / Excel
run tests/check_identity.py   # v5.16: vault, uuids, unique identifiers, audited edits, manifest, import wizard
run tests/check_app_identity.py   # v5.16: Standard / Incognito through the app, no identifier leaks, guided import
run tests/check_gui_js_syntax.py   # every GUI script parses (a syntax error blanks the screen)
run tests/check_lineage.py   # v5.17: re-processing keeps history; candidate lineage; calls move only on confident matches
run tests/check_app_training.py   # v5.17: Training screen A-D; synthetic vs clinical apart; evaluation never changes the model
run tests/check_app_add_layout.py   # v5.18: Add studies preview: no horizontal scrolling or clipped controls at 1280 / 1500 px (replaces the batch-table check)
run tests/check_app_setup.py   # v5.17: first-run setup wizard, FreeSurfer / licence validation (content never exposed), readiness report
run tests/check_app_import_v518.py   # v5.18: one Add-studies pathway, identification rules, series choice, study library, export with files
run tests/check_app_study_admin.py   # v5.20: identifier rule, study panel, edit checkpoint, archive, remove / purge, import duplicates, previous-version reuse
run tests/check_percival.py              # v5.22/v5.23: Percival Score engine - families, fusion, intelligence, calibration, ledger, rollback
run tests/check_percival_learning.py     # v5.24: review-to-learning, eligibility, datasets, store migration, older-version reviews
run tests/check_unified_prerequisites.py   # v5.24: Unified predictors reliable / unreliable / unavailable by prerequisite; never misleading evidence
run tests/check_image_ml_integration.py    # v5.24: Image ML learns from reviewed patches (vs shuffled control), consumed by Fusion + score, image OOD
run tests/trace_candidate.py             # v5.24: one synthetic candidate through every ML component (real code paths)
run tests/check_app_percival.py          # v5.22/v5.23: Percival Intelligence screen + reviewer score through the real app
echo; echo "checks passed: $PASSED  failed: ${#FAILED[@]}  skipped: ${#SKIPPED[@]}"
for s in "${SKIPPED[@]}"; do echo "  SKIPPED $s"; done
if [ ${#FAILED[@]} -gt 0 ]; then for f in "${FAILED[@]}"; do echo "  FAILED $f"; done; exit 1; fi
echo "unified-score / app / Percival tests: all executed checks passed"
