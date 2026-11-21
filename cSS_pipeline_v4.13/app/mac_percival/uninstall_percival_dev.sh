#!/bin/bash
# Remove the Percival development app. Your project folder is NOT deleted unless you add --remove-project (asks again).
# The production app / ~/css_project and the Percival RC app / ~/cSS_experimental are never touched.
set -u
P="${PERCIVAL_BASE:-$HOME/Percival_project}"
case "$(cd "$P" 2>/dev/null && pwd -P)" in "$HOME/css_project"*|"$HOME/cSS_experimental"*) echo "refused: $P is a protected project"; exit 1;; esac
pkill -f "$P/app/css_app.py" 2>/dev/null && echo "stopped Percival Dev"
for a in "/Applications/Percival Dev.app" "$HOME/Applications/Percival Dev.app"; do [ -d "$a" ] && rm -rf "$a" && echo "removed $a"; done
if [ "${1:-}" = "--remove-project" ] && [ -d "$P" ]; then
  echo "The project folder $P holds your studies, calls, results and (if used) the encrypted identity vault."
  read -r -p "Type DELETE to move it to the Trash: " x
  [ "$x" = "DELETE" ] && { mv "$P" "$HOME/.Trash/Percival_project_$(date +%Y%m%d_%H%M%S)" && echo "moved to the Trash"; } || echo "kept $P"
else echo "kept the project folder $P"; fi
