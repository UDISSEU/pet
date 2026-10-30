#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "Ambiente Python da Nova não encontrado: $PYTHON" >&2
    printf '%s\n' "Consulte o README para instalar as dependências." >&2
    exit 1
fi

exec "$PYTHON" "$APP_DIR/src/desktop_pet.py"
