#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    printf '%s\n' "Python 3 não foi encontrado. Instale Python 3.10 ou superior." >&2
    if [ -r /etc/os-release ] &&
        grep -E '^(ID|ID_LIKE)=' /etc/os-release | grep -Eiq 'linuxmint|ubuntu|debian'; then
        printf '%s\n' \
            "No Linux Mint/Debian/Ubuntu, execute manualmente: sudo apt update && sudo apt install python3 python3-venv python3-tk" \
            "A Nova não executa comandos administrativos." >&2
    fi
    exit 1
fi

exec "$PYTHON" "$APP_DIR/tools/nova_setup.py"
