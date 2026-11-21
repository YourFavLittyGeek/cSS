#!/bin/bash
# Percival Dev - one-time INSTALLATION of the Python environment, started by the app itself (no Terminal needed).
# This is the only Percival code that uses the internet, and only after the user agreed in a dialog: it downloads Miniforge (conda-forge,
# when no conda is installed) and the open-source packages of percival_environment.yml. It sends no project data anywhere.
# After it finished, Percival runs offline. It creates its OWN environment "percival"; an existing "css" environment is never changed.
# usage (by the launcher): first_run_setup.sh <bundled percival_environment.yml> <log file>
set -u
ENVYML="$1"; LOG="$2"
dlg() { /usr/bin/osascript -e "display dialog \"$1\" with title \"Percival setup\" buttons {\"OK\"} default button 1 ${2:-}" >/dev/null 2>&1; }
note() { /usr/bin/osascript -e "display notification \"$1\" with title \"Percival setup\"" >/dev/null 2>&1; echo "$(date '+%H:%M:%S') $1" >> "$LOG"; }
CONDA=""
for c in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3"; do
  [ -f "$c/etc/profile.d/conda.sh" ] && { CONDA="$c"; break; }
done
if [ -z "$CONDA" ]; then
  note "Downloading Miniforge (conda-forge)..."
  ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] || ARCH="x86_64"
  INST="$(mktemp -d)/Miniforge3.sh"
  /usr/bin/curl -fsSL -o "$INST" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-${ARCH}.sh" >> "$LOG" 2>&1 \
    || { dlg "Miniforge could not be downloaded. Check the internet connection and open Percival again.\n\nDetails: $LOG" "with icon stop"; exit 1; }
  note "Installing Miniforge into your home folder..."
  /bin/bash "$INST" -b -p "$HOME/miniforge3" >> "$LOG" 2>&1 || { dlg "Miniforge could not be installed.\n\nDetails: $LOG" "with icon stop"; exit 1; }
  rm -f "$INST"; CONDA="$HOME/miniforge3"
fi
source "$CONDA/etc/profile.d/conda.sh"
if conda env list | awk '{print $1}' | grep -qx percival; then
  note "Updating the Percival environment..."; conda env update -n percival -f "$ENVYML" >> "$LOG" 2>&1
else
  note "Installing the Percival environment (about 5-15 minutes)..."; conda env create -f "$ENVYML" >> "$LOG" 2>&1
fi
conda activate percival >> "$LOG" 2>&1 && python -c "import numpy, scipy, nibabel, pandas, skimage, cryptography, openpyxl, webview" >> "$LOG" 2>&1 \
  || { dlg "The Percival environment could not be completed.\n\nDetails: $LOG" "with icon stop"; exit 1; }
note "Percival is installed. Starting..."
exit 0
