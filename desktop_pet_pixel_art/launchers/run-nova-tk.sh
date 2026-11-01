#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export NOVA_LEGACY_TK=1
exec "$APP_DIR/launchers/run-nova.sh" "$@"
