#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/package"
mkdir -p "$BUILD"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON="$(command -v python3.12)"
else
  echo "Python 3.12 is required to build the Lambda package." >&2
  exit 1
fi
if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
  "$PYTHON" -m ensurepip --upgrade
fi
"$PYTHON" -m pip install --ignore-installed --disable-pip-version-check -r "$ROOT/requirements.txt" -t "$BUILD"
cp -R "$ROOT/ski_signal" "$BUILD/"
cp "$ROOT/config.yaml" "$BUILD/config.yaml"
cp "$ROOT/weights.yaml" "$BUILD/weights.yaml"
(
  cd "$BUILD"
  zip -qr "$ROOT/build/ski_signal.zip" .
)
