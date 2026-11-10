#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    printf '%s\n' "Python 3 não foi encontrado. Instale Python 3.10 ou superior." >&2
    exit 1
fi

exec "$PYTHON" "$APP_DIR/tools/nova_setup.py"
