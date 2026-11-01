#!/usr/bin/env bash
# Zotivity im Hintergrund starten und Oberfläche öffnen (macOS/Linux)
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./install.sh
nohup .venv/bin/python -m zotivity serve --quiet --open >/dev/null 2>&1 &
echo "Zotivity läuft (PID $!)."
