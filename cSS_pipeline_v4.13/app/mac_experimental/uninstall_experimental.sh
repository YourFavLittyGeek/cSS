#!/bin/bash
# Remove the experimental cSS app. Your data are NOT deleted unless you add --remove-project (asks again).
# The production app (cSS Pipeline.app) and ~/css_project are never touched.
set -u
pkill -f "cSS_experimental/app/css_app.py" 2>/dev/null && echo "stopped the experimental app"
for a in "/Applications/Percival.app" "$HOME/Applications/Percival.app" "/Applications/cSS Experimental.app" "$HOME/Applications/cSS Experimental.app"; do [ -d "$a" ] && rm -rf "$a" && echo "removed $a"; done
P="${CSS_EXP_BASE:-$HOME/cSS_experimental}"
if [ "${1:-}" = "--remove-project" ] && [ -d "$P" ]; then
  echo "The experimental project folder $P holds your experimental runs, linked studies and copies of images."
  echo "Linked FreeSurfer folders are symlinks: removing the project does NOT remove the originals."
  read -r -p "Type DELETE to move it to the Trash: " x
  [ "$x" = "DELETE" ] && { mv "$P" "$HOME/.Trash/cSS_experimental_$(date +%Y%m%d_%H%M%S)" && echo "moved to the Trash"; } || echo "kept $P"
else echo "kept the project folder $P (your experimental data)"; fi
