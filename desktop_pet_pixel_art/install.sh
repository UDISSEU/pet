#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPLICATIONS_DIR"
sed "s|@APP_DIR@|$APP_DIR|g" "$APP_DIR/launchers/nova.desktop.in" > "$APPLICATIONS_DIR/nova.desktop"
chmod 644 "$APPLICATIONS_DIR/nova.desktop"
printf 'Nova instalada em %s\n' "$APPLICATIONS_DIR/nova.desktop"
