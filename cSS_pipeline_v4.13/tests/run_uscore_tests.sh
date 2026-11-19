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
echo "unified-score tests: all passed"
