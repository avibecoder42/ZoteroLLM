#!/usr/bin/env bash
# Zotivity – Einrichtung unter macOS und Linux (einmalig)
set -euo pipefail
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  uv venv .venv --python 3.13
  uv pip install --python .venv/bin/python -e .
else
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi

if ! .venv/bin/python -c "import sys; from zotivity.keystore import get_store; sys.exit(0 if get_store().backend_info()['secure'] else 1)"; then
  echo "Hinweis: Für die verschlüsselte Ablage der API-Schlüssel wird ein Secret-Service benötigt"
  echo "(z. B. gnome-keyring oder KWallet). Alternativ Umgebungsvariablen wie ANTHROPIC_API_KEY setzen."
fi
echo "Fertig. Starten mit ./start.sh"
