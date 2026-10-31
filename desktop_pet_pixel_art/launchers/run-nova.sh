#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"
SYSTEM_PYTHON="/usr/bin/python3"
KEY_HELPER="$APP_DIR/src/keyring_secret.py"

if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "Ambiente Python da Nova não encontrado: $PYTHON" >&2
    printf '%s\n' "Consulte o README para instalar as dependências." >&2
    exit 1
fi

if [ -x "$SYSTEM_PYTHON" ] && [ -f "$KEY_HELPER" ]; then
    for PROVIDER in gemini groq mistral; do
        if [ "$PROVIDER" = gemini ] && [ -n "${GEMINI_API_KEY-}" ]; then
            continue
        elif [ "$PROVIDER" = groq ] && [ -n "${GROQ_API_KEY-}" ]; then
            continue
        elif [ "$PROVIDER" = mistral ] && [ -n "${MISTRAL_API_KEY-}" ]; then
            continue
        fi
        SECRET="$("$SYSTEM_PYTHON" "$KEY_HELPER" load "$PROVIDER" 2>/dev/null || true)"
        if [ -n "$SECRET" ]; then
            if [ "$PROVIDER" = gemini ]; then
                export GEMINI_API_KEY="$SECRET"
            elif [ "$PROVIDER" = groq ]; then
                export GROQ_API_KEY="$SECRET"
            else
                export MISTRAL_API_KEY="$SECRET"
            fi
        fi
        unset SECRET
    done
fi

exec "$PYTHON" "$APP_DIR/src/desktop_pet.py"
