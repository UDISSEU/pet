#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! python3 -m venv --help >/dev/null 2>&1; then
    printf '%s\n' "O módulo venv do Python não está disponível. Instale python3-venv e tente novamente." >&2
    exit 1
fi
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    printf '%s\n' "Tkinter não está disponível. Instale python3-tk e tente novamente." >&2
    exit 1
fi
if ! python3 -m venv "$APP_DIR/.venv"; then
    printf '%s\n' "Não consegui criar o ambiente virtual. Instale python3-venv e tente novamente." >&2
    exit 1
fi
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPLICATIONS_DIR"
SED_APP_DIR="$(printf '%s\n' "$APP_DIR" | sed 's/[\\&|]/\\&/g')"
sed "s|@APP_DIR@|$SED_APP_DIR|g" "$APP_DIR/launchers/nova.desktop.in" > "$APPLICATIONS_DIR/nova.desktop"
chmod 644 "$APPLICATIONS_DIR/nova.desktop"
printf 'Nova instalada em %s\n' "$APPLICATIONS_DIR/nova.desktop"
