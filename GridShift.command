#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_HOME="${HOME}/Library/Application Support/GridShift"
UV_HOME="${APP_HOME}/uv"
UV_BIN="${UV_HOME}/uv"
VENV_DIR="${APP_HOME}/venv"
UV_CACHE_DIR="${HOME}/Library/Caches/GridShift/uv"

mkdir -p "$UV_HOME" "$UV_CACHE_DIR"

if [[ ! -x "$UV_BIN" ]]; then
  echo "Preparing GridShift's small runtime manager…"
  curl --fail --location --silent --show-error https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR="$UV_HOME" UV_NO_MODIFY_PATH=1 sh
fi

export UV_CACHE_DIR
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Installing Python 3.12 for GridShift (first launch only)…"
  "$UV_BIN" venv --python 3.12 "$VENV_DIR"
fi

echo "Checking GridShift's runtime packages…"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
  --quiet --requirement "$ROOT/requirements-macos.txt"

cd "$ROOT"
exec "$VENV_DIR/bin/python" "$ROOT/launcher_macos.py"
