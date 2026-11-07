#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/nova.desktop"
VENV_DIR="$APP_DIR/.venv"
INSTALL_MARKER="$VENV_DIR/.nova-desktop-file-path"
SAVED_DESKTOP_FILE=
if [ -f "$INSTALL_MARKER" ]; then
    IFS= read -r SAVED_DESKTOP_FILE < "$INSTALL_MARKER" || SAVED_DESKTOP_FILE=
fi
YES=0
ACTION=install

usage() {
    cat <<'EOF'
Uso:
  ./install.sh [--yes]
  ./install.sh --uninstall [--yes]

Opções:
  --yes          Não solicita confirmação (adequado para automação).
  --uninstall    Remove o ambiente virtual e o lançador; preserva os dados pessoais.
  -h, --help     Mostra esta ajuda.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes|-y) YES=1 ;;
        --uninstall) ACTION=uninstall ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Opção desconhecida: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

confirm() {
    prompt=$1
    if [ "$YES" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        printf '%s\n' "$prompt (use --yes para confirmar em modo não interativo)." >&2
        return 1
    fi
    printf '%s [s/N] ' "$prompt"
    IFS= read -r answer || answer=
    case "$answer" in
        s|S|sim|SIM|y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

launcher_belongs_to_app() {
    [ -f "$1" ] &&
        grep -Fq "$APP_DIR/launchers/run-nova.sh" "$1"
}

if [ "$ACTION" = uninstall ]; then
    LAUNCHER_TO_REMOVE=
    if [ -n "$SAVED_DESKTOP_FILE" ] && launcher_belongs_to_app "$SAVED_DESKTOP_FILE"; then
        LAUNCHER_TO_REMOVE=$SAVED_DESKTOP_FILE
    elif launcher_belongs_to_app "$DESKTOP_FILE"; then
        LAUNCHER_TO_REMOVE=$DESKTOP_FILE
    fi
    if [ -e "$VENV_DIR" ] || [ -n "$LAUNCHER_TO_REMOVE" ]; then
        if ! confirm "Remover o ambiente virtual da Nova e seu lançador?"; then
            printf '%s\n' "Desinstalação cancelada."
            exit 1
        fi
    else
        printf '%s\n' "Nenhuma instalação da Nova foi encontrada."
        exit 0
    fi
    if [ -e "$VENV_DIR" ] || [ -L "$VENV_DIR" ]; then
        rm -rf -- "$VENV_DIR"
    fi
    if [ -n "$LAUNCHER_TO_REMOVE" ]; then
        rm -f -- "$LAUNCHER_TO_REMOVE"
    fi
    printf '%s\n' "Nova removida. Configurações e dados pessoais foram preservados."
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "Python 3 não foi encontrado. Instale Python 3.10 ou superior." >&2
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    printf 'Python 3.10 ou superior é necessário (encontrado: %s).\n' \
        "$(python3 --version 2>&1)" >&2
    exit 1
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
    printf '%s\n' "O módulo venv não está disponível. Em Debian/Ubuntu, instale python3-venv." >&2
    exit 1
fi
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    printf '%s\n' "Tkinter não está disponível. Em Debian/Ubuntu, instale python3-tk." >&2
    exit 1
fi

printf '%s\n' "Diagnóstico de recursos opcionais:"
if python3 -c 'import Xlib' >/dev/null 2>&1; then
    printf '%s\n' "  Integração X11: disponível (python-xlib)."
else
    printf '%s\n' "  Integração X11: indisponível; observação e posicionamento em janelas ficam desativados."
fi
if command -v bwrap >/dev/null 2>&1 && command -v prlimit >/dev/null 2>&1; then
    printf '%s\n' "  Plugins externos isolados: disponíveis (bubblewrap e prlimit)."
else
    printf '%s\n' "  Plugins externos isolados: indisponíveis; bubblewrap e prlimit são necessários."
fi
if command -v ollama >/dev/null 2>&1; then
    printf '%s\n' "  Ollama: encontrado."
else
    printf '%s\n' "  Ollama: não encontrado; a conversa local com IA ficará indisponível."
fi

if [ -e "$VENV_DIR" ] && { [ ! -x "$VENV_DIR/bin/python" ] || [ ! -f "$VENV_DIR/pyvenv.cfg" ]; }; then
    printf 'Existe um ambiente incompleto ou inválido em %s.\n' "$VENV_DIR" >&2
    if ! confirm "Removê-lo e recriar o ambiente?"; then
        exit 1
    fi
    rm -rf -- "$VENV_DIR"
fi
if [ -x "$VENV_DIR/bin/python" ] &&
    ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    printf 'O ambiente existente usa uma versão incompatível do Python: %s\n' \
        "$("$VENV_DIR/bin/python" --version 2>&1)" >&2
    if ! confirm "Recriá-lo com $(python3 --version)?"; then
        exit 1
    fi
    rm -rf -- "$VENV_DIR"
fi
if [ -e "$DESKTOP_FILE" ] && ! launcher_belongs_to_app "$DESKTOP_FILE"; then
    printf 'O lançador existente não pertence a esta instalação: %s\n' "$DESKTOP_FILE" >&2
    exit 1
fi
if [ -e "$VENV_DIR" ] || launcher_belongs_to_app "$DESKTOP_FILE"; then
    printf '%s\n' "Instalação anterior detectada."
    if ! confirm "Atualizar/reutilizar a instalação existente?"; then
        printf '%s\n' "Instalação cancelada."
        exit 1
    fi
fi

if ! python3 -m venv "$VENV_DIR"; then
    printf '%s\n' "Não consegui criar/reutilizar o ambiente virtual. Verifique python3-venv." >&2
    exit 1
fi
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
"$VENV_DIR/bin/python" -m pip check
PYTHONPATH="$APP_DIR/src" "$VENV_DIR/bin/python" -c \
    'import cv2, numpy, psutil; from PIL import Image; import desktop_pet'

mkdir -p "$APPLICATIONS_DIR"
SED_APP_DIR="$(printf '%s\n' "$APP_DIR" | sed 's/[\\&|]/\\&/g')"
sed "s|@APP_DIR@|$SED_APP_DIR|g" "$APP_DIR/launchers/nova.desktop.in" > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE"
if [ -n "$SAVED_DESKTOP_FILE" ] && [ "$SAVED_DESKTOP_FILE" != "$DESKTOP_FILE" ] &&
    launcher_belongs_to_app "$SAVED_DESKTOP_FILE"; then
    rm -f -- "$SAVED_DESKTOP_FILE"
fi
printf '%s\n' "$DESKTOP_FILE" > "$INSTALL_MARKER"
chmod 600 "$INSTALL_MARKER"
printf 'Nova instalada em %s\n' "$DESKTOP_FILE"
printf '%s\n' "Verificação de dependências e importação de inicialização concluída."
printf '%s\n' "Nenhum serviço Ollama foi iniciado e nenhum modelo foi baixado."
