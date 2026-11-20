#!/usr/bin/env bash
# All tests of the Unified Score engine (SYNTHETIC data only). Each stage runs once; full output in $LOG.
#   1 pinned production sources   2 static check   3 engine unit / integration tests (unittest)   4 app + browser integration (shadow mode)
#   5-6 Stage 2 P1 image index + geometry gate (pinned sources, unit tests)
# usage: bash unified_engine/run_tests.sh [LOG]      exit code = number of failing stages
set -u
E="$(cd "$(dirname "$0")" && pwd)"; R="$(dirname "$E")"; PY="${PY:-python3}"; LOG="${1:-$(mktemp -t uengine_tests)}"; : > "$LOG"; bad=0
stage() { echo "=== $1" | tee -a "$LOG"; shift; "$@" >> "$LOG" 2>&1; local rc=$?; tail -3 "$LOG" | sed 's/^/    /'; [ $rc -eq 0 ] || { bad=$((bad+1)); echo "    -> FAILED (exit $rc)"; }; }
stage "1 pinned production sources" "$PY" "$E/run_engine.py" verify
stage "2 static check" "$PY" "$E/tools/static_check.py"
cd "$E/tests"
stage "3 engine tests" "$PY" -W error::ResourceWarning -m unittest -v test_engine_provenance test_schema test_math_preservation test_characteristics \
  test_patient_split test_funnel test_ml test_evaluation test_leakage test_auc_investigation test_fusion test_synthetic test_end_to_end \
  test_prototype_components test_prototype_fusion test_prototype_scenarios test_registry_shadow test_ablation test_port_fidelity
stage "4 app + browser integration (shadow mode)" "$PY" "$R/tests/check_app_shadow_engine.py"
stage "5 Stage 2 P1 imaging: pinned sources" "$PY" "$E/run_imaging.py" verify
stage "6 Stage 2 P1 imaging tests (synthetic)" "$PY" -W error::ResourceWarning -m unittest -v test_imaging_geometry test_imaging_registration test_imaging_index
echo "=== SUMMARY: $bad failing stage(s); log $LOG"; exit $bad
