#!/usr/bin/env bash
set -uo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODE=smoke
BACKEND=xvfb
REPORTS=/tmp/nova-gui-reports
RUNTIME_DIR=
SCENARIO=30m

usage() {
  cat <<'EOF'
Uso:
  tools/nova_gui_test.sh [opções] [smoke|capture|launch|soak [30m|1h|3h]]
  tools/nova_gui_test.sh status DIRETORIO_DA_SESSAO
  tools/nova_gui_test.sh cleanup DIRETORIO_DA_SESSAO

Opções:
  --backend xvfb|xephyr   Xvfb isolado (padrão) ou Xephyr aninhado
  --reports DIRETORIO     destino das capturas e relatórios
  --runtime-dir DIRETORIO diretório privado da sessão (temporário por padrão)
EOF
}

if [[ ${1:-} == status ]]; then
  session=${2:-}
  [[ -n "$session" && -f "$session/processes.tsv" ]] || { echo "Sessão não encontrada." >&2; exit 1; }
  while read -r kind pid start comm; do
    if [[ -r "/proc/$pid/stat" ]]; then
      line=$(<"/proc/$pid/stat"); rest=${line##*) }; read -r -a fields <<< "$rest"
      actual_comm=$(<"/proc/$pid/comm")
      if [[ "${fields[19]}" == "$start" && "$actual_comm" == "$comm" ]]; then
        echo "$kind ativo: PID $pid ($comm)"
      else
        echo "$kind não está mais ativo"
      fi
    else
      echo "$kind não está mais ativo"
    fi
  done < "$session/processes.tsv"
  exit 0
fi
if [[ ${1:-} == cleanup ]]; then
  exec "$ROOT/tools/nova_gui_cleanup.sh" "${2:-}"
fi

while (($#)); do
  case "$1" in
    --backend) BACKEND=${2:?faltou backend}; shift 2 ;;
    --reports) REPORTS=${2:?faltou diretório de relatórios}; shift 2 ;;
    --runtime-dir) RUNTIME_DIR=${2:?faltou diretório da sessão}; shift 2 ;;
    smoke|capture|launch|soak) MODE=$1; shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argumento desconhecido: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if (($#)); then SCENARIO=$1; shift; fi
if (($#)); then echo "Argumentos excedentes: $*" >&2; exit 2; fi
[[ "$BACKEND" == xvfb || "$BACKEND" == xephyr ]] || { echo "Backend inválido: $BACKEND" >&2; exit 2; }
if [[ "$MODE" == soak && ! "$SCENARIO" =~ ^(30m|1h|3h)$ ]]; then
  echo "Cenário de soak inválido: use 30m, 1h ou 3h." >&2
  exit 2
fi

for tool in setsid xauth mcookie xdpyinfo; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Dependência ausente: $tool" >&2; exit 2; }
done
if [[ "$BACKEND" == xvfb ]]; then
  command -v Xvfb >/dev/null 2>&1 || { echo "Dependência ausente: Xvfb" >&2; exit 2; }
else
  command -v Xephyr >/dev/null 2>&1 || { echo "Dependência ausente: Xephyr" >&2; exit 2; }
  [[ -n ${DISPLAY:-} && -r ${XAUTHORITY:-$HOME/.Xauthority} ]] || {
    echo "Xephyr precisa de um display X11 pai acessível e Xauthority legível." >&2
    exit 2
  }
  parent_authority=${XAUTHORITY:-$HOME/.Xauthority}
  if ! XAUTHORITY="$parent_authority" xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    echo "Xephyr não consegue autenticar no display pai; a sessão principal não foi alterada." >&2
    exit 2
  fi
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Ambiente virtual ausente: $ROOT/.venv/bin/python" >&2
  exit 2
fi

socket_dir=/tmp/.X11-unix
if [[ ! -d "$socket_dir" || $(stat -c %u "$socket_dir") != 0 ]]; then
  owner=ausente
  [[ -d "$socket_dir" ]] && owner=$(stat -c '%U:%G (uid %u)' "$socket_dir")
  echo "Xvfb/Xephyr não iniciado: $socket_dir pertence a $owner; o servidor X exige diretório de sockets local de propriedade de root." >&2
  echo "Nenhuma permissão ou propriedade global foi alterada. Use uma sessão/container configurado pelo administrador ou corrija o host fora deste script." >&2
  exit 1
fi

if [[ -z "$RUNTIME_DIR" ]]; then
  RUNTIME_DIR=$(mktemp -d /tmp/nova-gui-session.XXXXXX) || exit 1
else
  mkdir -m 700 -- "$RUNTIME_DIR" 2>/dev/null || {
    echo "Não foi possível criar o diretório de sessão: $RUNTIME_DIR" >&2; exit 1;
  }
  RUNTIME_DIR=$(realpath -- "$RUNTIME_DIR")
fi
chmod 700 "$RUNTIME_DIR"
umask 077
touch "$RUNTIME_DIR/.nova-gui-session" "$RUNTIME_DIR/processes.tsv"
chmod 600 "$RUNTIME_DIR/.nova-gui-session" "$RUNTIME_DIR/processes.tsv"
printf 'owner=%s\n' "$(id -u)" > "$RUNTIME_DIR/.nova-gui-session"
mkdir -p "$RUNTIME_DIR/home" "$RUNTIME_DIR/config" "$RUNTIME_DIR/cache" "$RUNTIME_DIR/data" "$RUNTIME_DIR/run"
chmod 700 "$RUNTIME_DIR/run"
cleanup() {
  if [[ -f "$RUNTIME_DIR/.nova-gui-session" ]]; then
    "$ROOT/tools/nova_gui_cleanup.sh" "$RUNTIME_DIR" || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
trap 'exit 129' HUP

record_process() {
  local kind=$1 pid=$2 expected=$3 line rest comm
  for _ in $(seq 1 20); do
    if [[ -r "/proc/$pid/stat" && -r "/proc/$pid/comm" ]] &&
       [[ "$(<"/proc/$pid/comm")" == "$expected" ]]; then break; fi
    sleep 0.05
  done
  [[ -r "/proc/$pid/stat" && "$(<"/proc/$pid/comm")" == "$expected" ]] || return 1
  line=$(<"/proc/$pid/stat"); rest=${line##*) }; read -r -a fields <<< "$rest"
  comm=$(<"/proc/$pid/comm")
  printf '%s\t%s\t%s\t%s\n' "$kind" "$pid" "${fields[19]}" "$comm" >> "$RUNTIME_DIR/processes.tsv"
}

display_number=
for candidate in $(seq 90 199); do
  if [[ ! -e "$socket_dir/X$candidate" && ! -e "/tmp/.X$candidate-lock" ]]; then
    display_number=$candidate
    break
  fi
done
[[ -n "$display_number" ]] || { echo "Nenhum display virtual livre no intervalo :90–:199." >&2; exit 1; }
printf ':%s\n' "$display_number" > "$RUNTIME_DIR/display"
display=":$display_number"
cookie=$(mcookie)
xauth -f "$RUNTIME_DIR/Xauthority" add "$display" MIT-MAGIC-COOKIE-1 "$cookie" >/dev/null
unset cookie
chmod 600 "$RUNTIME_DIR/Xauthority"

if [[ "$BACKEND" == xvfb ]]; then
  setsid env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$RUNTIME_DIR/home" Xvfb "$display" -screen 0 1280x900x24 -nolisten tcp -auth "$RUNTIME_DIR/Xauthority" -noreset >"$RUNTIME_DIR/xserver.log" 2>&1 &
else
  setsid env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" DISPLAY="$DISPLAY" XAUTHORITY="$parent_authority" Xephyr "$display" -screen 1280x900 -nolisten tcp -auth "$RUNTIME_DIR/Xauthority" >"$RUNTIME_DIR/xserver.log" 2>&1 &
fi
server_pid=$!
expected_server=Xvfb
[[ "$BACKEND" == xephyr ]] && expected_server=Xephyr
record_process server "$server_pid" "$expected_server" || {
  echo "Não foi possível registrar o servidor X." >&2
  kill -- "-$server_pid" 2>/dev/null || true
  exit 1
}
ready=0
for _ in $(seq 1 80); do
  if XAUTHORITY="$RUNTIME_DIR/Xauthority" xdpyinfo -display "$display" >/dev/null 2>&1; then ready=1; break; fi
  if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
  sleep 0.1
done
if [[ "$ready" != 1 ]]; then
  echo "O servidor X não ficou pronto; diagnóstico:" >&2
  sed -n '1,60p' "$RUNTIME_DIR/xserver.log" >&2
  exit 1
fi
echo "Display isolado pronto: $display (PID $server_pid; TCP desativado)"
echo "Sessão temporária: $RUNTIME_DIR"

safe_env=(
  env -i PATH=/usr/local/bin:/usr/bin:/bin
  HOME="$RUNTIME_DIR/home" XDG_CONFIG_HOME="$RUNTIME_DIR/config"
  XDG_CACHE_HOME="$RUNTIME_DIR/cache" XDG_DATA_HOME="$RUNTIME_DIR/data"
  XDG_RUNTIME_DIR="$RUNTIME_DIR/run" TMPDIR="$RUNTIME_DIR"
  DISPLAY="$display" XAUTHORITY="$RUNTIME_DIR/Xauthority"
  LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONPATH="$ROOT/src"
)
python="$ROOT/.venv/bin/python"

if [[ "$MODE" == smoke || "$MODE" == capture ]]; then
  mkdir -p "$REPORTS"
  capture_dir=
  if [[ "$MODE" == capture ]]; then
    capture_dir=$(mktemp -d "$REPORTS/nova-gui-capture.XXXXXX")
    safe_env+=(NOVA_GUI_CAPTURE_DIR="$capture_dir")
    echo "Capturas: $capture_dir"
  fi
  setsid "${safe_env[@]}" "$python" -m unittest discover -s "$ROOT/tests" -p test_ui_windows.py -v >"$RUNTIME_DIR/smoke.log" 2>&1 &
  test_pid=$!
  record_process test "$test_pid" python || {
    echo "Não foi possível registrar o processo do smoke test." >&2
    kill -- "-$test_pid" 2>/dev/null || true
    exit 1
  }
  wait "$test_pid"
  result=$?
  cat "$RUNTIME_DIR/smoke.log"
  if [[ $result -ne 0 ]]; then exit "$result"; fi
  if [[ "$MODE" == capture && -z "$(find "$capture_dir" -maxdepth 1 -type f -name '*.png' -print -quit)" ]]; then
    echo "O smoke test terminou sem produzir capturas. Verifique se ImageGrab/Pillow suporta este display." >&2
    exit 1
  fi
elif [[ "$MODE" == launch || "$MODE" == soak ]]; then
  setsid "${safe_env[@]}" "$python" "$ROOT/src/desktop_pet.py" >"$RUNTIME_DIR/nova.log" 2>&1 &
  app_pid=$!
  record_process app "$app_pid" python || {
    echo "Não foi possível registrar o processo da Nova." >&2
    kill -- "-$app_pid" 2>/dev/null || true
    exit 1
  }
  sleep 2
  if ! kill -0 "$app_pid" 2>/dev/null; then
    echo "A Nova encerrou durante a inicialização:" >&2
    cat "$RUNTIME_DIR/nova.log" >&2
    exit 1
  fi
  echo "Nova isolada iniciada (PID $app_pid). Use o menu para fechar ou Ctrl+C."
  if [[ "$MODE" == launch ]]; then
    while kill -0 "$app_pid" 2>/dev/null; do sleep 1; done
  else
    report="$REPORTS/nova-soak-$SCENARIO-$(date +%Y%m%d-%H%M%S).jsonl"
    mkdir -p "$REPORTS"
    echo "O monitor acompanha separadamente a Nova e o servidor X quando possível."
    setsid "${safe_env[@]}" "$python" "$ROOT/tools/nova_soak.py" --scenario "$SCENARIO" \
      --target-pid "$app_pid" --display-pid "$server_pid" --output "$report" \
      >"$RUNTIME_DIR/soak.log" 2>&1 &
    soak_pid=$!
    record_process test "$soak_pid" python || {
      echo "Não foi possível registrar o processo de soak." >&2
      kill -- "-$soak_pid" 2>/dev/null || true
      exit 1
    }
    while kill -0 "$soak_pid" 2>/dev/null; do
      if ! kill -0 "$app_pid" 2>/dev/null; then
        echo "A Nova encerrou antes do fim do soak; interrompendo o cenário." >&2
        kill -- "-$soak_pid" 2>/dev/null || true
        wait "$soak_pid" 2>/dev/null || true
        exit 1
      fi
      sleep 1
    done
    wait "$soak_pid"
    result=$?
    cat "$RUNTIME_DIR/soak.log"
    [[ $result -eq 0 ]] || exit "$result"
    echo "Relatório de soak: $report"
  fi
fi
