#!/bin/bash
# ==============================================================================
# PERCIVAL — Clean-Slate Launch Script
# Clears old processing artifacts and scratch caches while preserving all
# original MRI datasets, then launches the updated PERCIVAL application.
# ==============================================================================
set -euo pipefail

WORKSPACE="${CSS_BASE:-$HOME/Percival_project}"
REPO_DIR="/Users/tarabeah.selim/percival_code_only/cSS_pipeline_v4.13"
PORT="${1:-8800}"

echo "=========================================================="
echo " [PERCIVAL] Initializing Fresh-Start Scientific Workspace "
echo "=========================================================="
echo " Workspace: $WORKSPACE"
echo " Code Repo: $REPO_DIR"

# 1. Safely clear old ephemeral processing data, leaving original MRIs intact
echo "--> Clearing obsolete generated derivatives and scratch buffers..."
for dir in "work" "review" "runs" "results" "data" "app_data/staging" "app_data/scratch" "app_data/quarantine"; do
    target="$WORKSPACE/$dir"
    if [ -d "$target" ]; then
        find "$target" -mindepth 1 -delete 2>/dev/null || true
    fi
    mkdir -p "$target"
done

# 2. Reset active study queue and transient ledgers to zero state
echo "--> Initializing fresh study state registers..."
echo "[]" > "$WORKSPACE/app_data/patients.json" 2>/dev/null || true
echo "{}" > "$WORKSPACE/app_data/timings.json" 2>/dev/null || true
echo "[]" > "$WORKSPACE/app_data/transfer_queue.json" 2>/dev/null || true
echo "[]" > "$WORKSPACE/app_data/notifications.json" 2>/dev/null || true

# 2b. Ensure pipeline scripts and unified components are 100% synchronized into workspace
echo "--> Synchronizing verified pipeline scripts to $WORKSPACE/scripts..."
mkdir -p "$WORKSPACE/scripts" "$WORKSPACE/unified_engine" "$WORKSPACE/unified_score" "$WORKSPACE/app"
cp -f "$REPO_DIR"/scripts/* "$WORKSPACE/scripts/" 2>/dev/null || true
chmod +x "$WORKSPACE"/scripts/*.sh "$WORKSPACE"/scripts/*.py 2>/dev/null || true

# 3. Ensure conda environment is activated
echo "--> Activating conda environment 'css'..."
eval "$(conda shell.bash hook 2>/dev/null || true)"
conda activate css 2>/dev/null || true

# 4. Launch PERCIVAL application
echo "--> Launching PERCIVAL on http://127.0.0.1:$PORT ..."
cd "$REPO_DIR"
export CSS_BASE="$WORKSPACE"
export PYTHONPATH="unified_engine:.:$WORKSPACE/scripts"
exec python3 app/css_app.py --port "$PORT"
