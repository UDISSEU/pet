#!/usr/bin/env bash
# Stop only the process groups recorded by one Nova GUI test session.
set -uo pipefail

if [[ $# -ne 1 ]]; then
  echo "Uso: $0 DIRETORIO_DA_SESSAO" >&2
  exit 2
fi

run_dir=$(realpath -m -- "$1")
if [[ ! -f "$run_dir/.nova-gui-session" || ! -f "$run_dir/processes.tsv" ]]; then
  echo "Sessão Nova GUI inválida ou já limpa: $run_dir" >&2
  exit 1
fi
if [[ $(stat -c %u "$run_dir") != "$(id -u)" ]]; then
  echo "A sessão não pertence ao usuário atual; nenhuma ação foi tomada." >&2
  exit 1
fi

proc_fields() {
  local pid=$1 line rest
  [[ -r "/proc/$pid/stat" ]] || return 1
  line=$(<"/proc/$pid/stat")
  rest=${line##*) }
  read -r -a fields <<< "$rest"
  printf '%s %s %s\n' "${fields[1]}" "${fields[2]}" "${fields[19]}"
}

is_recorded_process() {
  local pid=$1 start=$2 comm=$3 state pgrp actual_start actual_comm
  [[ -r "/proc/$pid/comm" ]] || return 1
  read -r state pgrp actual_start < <(proc_fields "$pid") || return 1
  actual_comm=$(<"/proc/$pid/comm")
  [[ "$actual_start" == "$start" && "$actual_comm" == "$comm" && "$pgrp" == "$pid" ]]
}

terminate_group() {
  local pid=$1 start=$2 comm=$3 signal=${4:-TERM}
  is_recorded_process "$pid" "$start" "$comm" || return 0
  kill -s "$signal" -- "-$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do
    is_recorded_process "$pid" "$start" "$comm" || return 0
    sleep 0.1
  done
  is_recorded_process "$pid" "$start" "$comm" && kill -KILL -- "-$pid" 2>/dev/null || true
}

# Plugins can create their own sessions. Discover descendants before stopping
# Nova and terminate only process groups rooted in this Nova process tree.
app_pid=
while read -r kind pid start comm; do
  [[ "$kind" == "app" ]] && app_pid=$pid
done < "$run_dir/processes.tsv"
if [[ -n "$app_pid" ]]; then
  app_start=$(awk '$1=="app" {print $3}' "$run_dir/processes.tsv")
  app_comm=$(awk '$1=="app" {print $4}' "$run_dir/processes.tsv")
  if is_recorded_process "$app_pid" "$app_start" "$app_comm"; then
    python3 - "$app_pid" <<'PY' | while read -r pid start comm; do
import glob
import sys

root = int(sys.argv[1])
rows = {}
for path in glob.glob('/proc/[0-9]*/stat'):
    try:
        line = open(path, encoding='ascii').read()
        pid = int(line.split(' ', 1)[0])
        rest = line[line.rfind(') ') + 2:].split()
        comm = open(f'/proc/{pid}/comm', encoding='ascii').read().strip()
        rows[pid] = (int(rest[1]), int(rest[2]), int(rest[19]), comm)
    except (OSError, ValueError, IndexError):
        continue
descendants = set()
pending = [root]
while pending:
    parent = pending.pop()
    for pid, (ppid, _pgid, _start, _comm) in rows.items():
        if ppid == parent and pid not in descendants and pid != root:
            descendants.add(pid)
            pending.append(pid)
leaders = []
for pid in descendants:
    _ppid, pgid, start, comm = rows[pid]
    if pgid == pid:
        leaders.append((pid, start, comm))
for pid, start, comm in sorted(leaders, reverse=True):
    print(pid, start, comm)
PY
      [[ -n "$pid" ]] && terminate_group "$pid" "$start" "$comm"
    done
    terminate_group "$app_pid" "$app_start" "$app_comm"
  fi
fi

while read -r kind pid start comm; do
  [[ "$kind" == "app" ]] || terminate_group "$pid" "$start" "$comm"
done < <(tac "$run_dir/processes.tsv")

rm -f -- "$run_dir/Xauthority" "$run_dir/display" "$run_dir/processes.tsv" "$run_dir/.nova-gui-session"
rm -rf -- "$run_dir/home" "$run_dir/config" "$run_dir/cache" "$run_dir/data" "$run_dir/run"
rm -f -- "$run_dir/xserver.log" "$run_dir/smoke.log" "$run_dir/nova.log" "$run_dir/soak.log"
rmdir -- "$run_dir" 2>/dev/null || true
echo "Limpeza concluída para a sessão $run_dir"
