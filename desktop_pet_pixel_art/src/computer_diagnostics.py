"""Bounded read-only network and system health services for Meu Computador."""

import ipaddress
import re
import shutil
import socket
import struct
import subprocess
import time
from collections import deque
from pathlib import Path


def _gateway_routes(path="/proc/net/route"):
    routes = {}
    try:
        lines = Path(path).read_text(encoding="ascii").splitlines()[1:]
    except (OSError, UnicodeError):
        return routes
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            gateway = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
            if flags & 2 and ipaddress.ip_address(gateway).is_global is False:
                routes[fields[0]] = gateway
        except (ValueError, OSError, struct.error):
            continue
    return routes


def _dns_servers(path="/etc/resolv.conf"):
    servers = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            fields = line.split("#", 1)[0].split()
            if len(fields) >= 2 and fields[0] == "nameserver":
                try:
                    address = str(ipaddress.ip_address(fields[1]))
                except ValueError:
                    continue
                if address not in servers:
                    servers.append(address)
    except (OSError, UnicodeError):
        pass
    return servers


def _interface_type(name):
    lowered = name.casefold()
    if lowered.startswith(("wl", "wifi")):
        return "Wi-Fi"
    if lowered.startswith(("wwan", "rmnet")):
        return "Celular"
    if lowered.startswith(("tun", "tap", "wg", "tailscale")):
        return "VPN / túnel"
    if lowered.startswith(("en", "eth", "eno", "ens")):
        return "Ethernet"
    try:
        if (Path("/sys/class/net") / name / "wireless").is_dir():
            return "Wi-Fi"
    except OSError:
        pass
    return "Não identificado"


class NetworkSampler:
    """Sample interface counters; history exists only while the owner is alive."""

    def __init__(self, history_limit=60):
        self.history = deque(maxlen=max(2, history_limit))
        self._previous = None

    def sample(self, *, now=None, stats=None, addresses=None, counters=None,
               gateways=None, dns_servers=None):
        import psutil

        now = time.monotonic() if now is None else now
        stats = psutil.net_if_stats() if stats is None else stats
        addresses = psutil.net_if_addrs() if addresses is None else addresses
        counters = psutil.net_io_counters(pernic=True) if counters is None else counters
        gateways = _gateway_routes() if gateways is None else gateways
        dns_servers = _dns_servers() if dns_servers is None else dns_servers
        interfaces = []
        for name, status in stats.items():
            if name == "lo":
                continue
            ip_addresses = []
            for address in addresses.get(name, ()):
                if address.family not in (socket.AF_INET, socket.AF_INET6):
                    continue
                candidate = address.address.split("%", 1)[0]
                try:
                    parsed = ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                if not parsed.is_loopback and candidate not in ip_addresses:
                    ip_addresses.append(candidate)
            counter = counters.get(name)
            interfaces.append({
                "name": name, "type": _interface_type(name),
                "is_up": bool(status.isup),
                "connected": bool(status.isup and ip_addresses),
                "speed_mbps": status.speed or None,
                "addresses": ip_addresses,
                "gateway": gateways.get(name),
                "bytes_sent": counter.bytes_sent if counter else 0,
                "bytes_received": counter.bytes_recv if counter else 0,
            })
        active = [item for item in interfaces if item["is_up"]]
        connected = [item for item in active if item["connected"]]
        total_sent = sum(item["bytes_sent"] for item in interfaces)
        total_received = sum(item["bytes_received"] for item in interfaces)
        elapsed = None
        sent_rate = received_rate = None
        if self._previous is not None:
            previous_time, previous_sent, previous_received = self._previous
            elapsed = now - previous_time
            if elapsed > 0:
                sent_rate = max(0, total_sent - previous_sent) / elapsed
                received_rate = max(0, total_received - previous_received) / elapsed
        self._previous = (now, total_sent, total_received)
        if connected:
            connection_state = "Conectada à rede local"
        elif active:
            connection_state = "Interface ativa, endereço de rede indisponível"
        else:
            connection_state = "Nenhuma interface ativa"
        snapshot = {
            "connection_state": connection_state,
            "internet_state": "Não verificada",
            "interfaces": interfaces,
            "active_interfaces": len(active),
            "connected_interfaces": len(connected),
            "bytes_sent": total_sent, "bytes_received": total_received,
            "upload_bytes_per_second": sent_rate,
            "download_bytes_per_second": received_rate,
            "sample_interval": elapsed,
            "gateway": next((item["gateway"] for item in connected
                             if item["gateway"]), None),
            "dns_servers": dns_servers,
            "timestamp": now,
        }
        self.history.append({
            "timestamp": now,
            "upload": sent_rate or 0.0,
            "download": received_rate or 0.0,
        })
        snapshot["history"] = list(self.history)
        return snapshot


def run_connectivity_diagnostics(snapshot, *, cancel_event=None,
                                 socket_module=socket, run=subprocess.run,
                                 ping_path=None):
    """Run explicit, bounded reachability checks; never changes network setup."""
    results = []

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    connected = snapshot.get("connected_interfaces", 0) > 0
    results.append({
        "name": "Rede local",
        "state": "Conectada" if connected else "Sem interface conectada",
        "evidence": (f"{snapshot.get('connected_interfaces', 0)} interface(s) ativa(s) com endereço IP"
                     if connected else "Nenhuma interface ativa com endereço IP foi observada."),
        "latency_ms": None, "packet_loss_percent": None,
    })

    gateway = snapshot.get("gateway")
    if cancelled():
        return {"checks": results, "cancelled": True}
    ping = ping_path or shutil.which("ping")
    if not gateway:
        results.append({"name": "Gateway", "state": "Indisponível",
                        "evidence": "Nenhum gateway padrão foi identificado.",
                        "latency_ms": None, "packet_loss_percent": None})
    elif not ping:
        results.append({"name": "Gateway", "state": "Não verificável",
                        "evidence": "O utilitário ping não está disponível.",
                        "latency_ms": None, "packet_loss_percent": None})
    else:
        try:
            ipaddress.ip_address(gateway)
            started = time.monotonic()
            response = run([ping, "-n", "-c", "1", "-W", "2", "--", gateway],
                           capture_output=True, text=True, timeout=3, check=False)
            output = (response.stdout or "") + (response.stderr or "")
            loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
            time_match = re.search(r"time[=<]([\d.]+)\s*ms", output)
            reachable = response.returncode == 0
            results.append({
                "name": "Gateway",
                "state": "Acessível" if reachable else "Sem resposta ao ping",
                "evidence": "Um pacote ICMP enviado; um resultado sem resposta pode indicar bloqueio de ICMP.",
                "latency_ms": float(time_match.group(1)) if time_match else
                             round((time.monotonic() - started) * 1000, 1) if reachable else None,
                "packet_loss_percent": float(loss_match.group(1)) if loss_match else
                                       0.0 if reachable else 100.0,
            })
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            results.append({"name": "Gateway", "state": "Não verificável",
                            "evidence": f"Consulta indisponível ({type(exc).__name__}).",
                            "latency_ms": None, "packet_loss_percent": None})

    if cancelled():
        return {"checks": results, "cancelled": True}
    started = time.monotonic()
    try:
        socket_module.getaddrinfo("example.com", 443,
                                  type=socket_module.SOCK_STREAM)
        dns_latency = round((time.monotonic() - started) * 1000, 1)
        results.append({"name": "Resolução DNS", "state": "Funcionando",
                        "evidence": "example.com foi resolvido usando a configuração DNS do sistema.",
                        "latency_ms": dns_latency, "packet_loss_percent": None})
    except (OSError, socket_module.gaierror) as exc:
        results.append({"name": "Resolução DNS", "state": "Falha nesta consulta",
                        "evidence": f"example.com não foi resolvido ({type(exc).__name__}).",
                        "latency_ms": None, "packet_loss_percent": None})

    if cancelled():
        return {"checks": results, "cancelled": True}
    started = time.monotonic()
    try:
        connection = socket_module.create_connection(("1.1.1.1", 443), timeout=2)
        connection.close()
        results.append({"name": "Acesso externo", "state": "Conexão TCP estabelecida",
                        "evidence": "Conexão de teste com 1.1.1.1:443; nenhum conteúdo foi enviado.",
                        "latency_ms": round((time.monotonic() - started) * 1000, 1),
                        "packet_loss_percent": None})
    except OSError as exc:
        results.append({"name": "Acesso externo", "state": "Sem confirmação",
                        "evidence": f"Não foi possível abrir uma conexão TCP de teste ({type(exc).__name__}).",
                        "latency_ms": None, "packet_loss_percent": None})
    return {"checks": results, "cancelled": cancelled()}


class SystemHealthSampler:
    """Bounded in-memory CPU/RAM/disk/process samples for one open panel."""

    def __init__(self, history_limit=60, process_limit=20):
        self.history = deque(maxlen=max(2, history_limit))
        self.process_limit = max(5, process_limit)
        self._process_previous = {}
        self._previous_at = None

    def sample(self, system_monitor=None):
        import psutil

        now = time.monotonic()
        base = system_monitor.collect() if system_monitor is not None else {}
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home()))
        cpu_percent = base.get("cpu_percent")
        if not isinstance(cpu_percent, (int, float)):
            cpu_percent = psutil.cpu_percent(interval=0.1)
        try:
            temperatures = psutil.sensors_temperatures(fahrenheit=False)
            readings = [sensor.current for group in temperatures.values()
                        for sensor in group if sensor.current is not None]
            temperature = max(readings) if readings else None
        except (AttributeError, OSError):
            temperature = None

        elapsed = now - self._previous_at if self._previous_at is not None else None
        current = {}
        inaccessible = 0
        for process in psutil.process_iter(
            attrs=("pid", "name", "username", "memory_info", "cpu_times", "create_time"),
            ad_value=None,
        ):
            try:
                info = process.info
                if not info.get("pid"):
                    continue
                memory_info = info.get("memory_info")
                cpu_times = info.get("cpu_times")
                rss = memory_info.rss if memory_info else 0
                cpu_total = (cpu_times.user + cpu_times.system) if cpu_times else None
                identity = (info["pid"], info.get("create_time"))
                previous = self._process_previous.get(identity)
                process_cpu = None
                if previous and elapsed and elapsed > 0 and cpu_total is not None:
                    process_cpu = max(0.0, (cpu_total - previous) / elapsed * 100)
                current[identity] = cpu_total
                info_row = {
                    "pid": info["pid"], "name": info.get("name") or "Processo indisponível",
                    "username": info.get("username"), "cpu_percent": process_cpu,
                    "memory_bytes": rss,
                    "memory_percent": rss / max(1, memory.total) * 100,
                }
                # Keep a bounded union of highest-memory and highest-CPU tasks.
                current.setdefault("_rows", []).append(info_row)
            except (psutil.Error, OSError, AttributeError, TypeError):
                inaccessible += 1
        rows = current.pop("_rows", [])
        top_memory = sorted(rows, key=lambda item: item["memory_bytes"], reverse=True)[:self.process_limit // 2]
        cpu_rows = [item for item in rows if item["cpu_percent"] is not None]
        top_cpu = sorted(cpu_rows, key=lambda item: item["cpu_percent"], reverse=True)[:self.process_limit // 2]
        unique = {item["pid"]: item for item in (*top_memory, *top_cpu)}
        processes = list(unique.values())
        self._process_previous = {key: value for key, value in current.items()
                                  if isinstance(key, tuple)}
        self._previous_at = now
        processes.sort(key=lambda item: item["memory_bytes"], reverse=True)
        snapshot = {
            "cpu_percent": float(cpu_percent), "memory_percent": memory.percent,
            "memory_used": memory.used, "memory_total": memory.total,
            "memory_available": memory.available, "disk_percent": disk.percent,
            "disk_used": disk.used, "disk_total": disk.total,
            "disk_free": disk.free, "temperature_c": temperature,
            "processes": processes, "inaccessible_processes": inaccessible,
            "timestamp": time.time(), "process_interval": elapsed,
        }
        snapshot["issues"] = diagnose_system_health(snapshot)
        self.history.append({key: snapshot[key] for key in (
            "timestamp", "cpu_percent", "memory_percent", "disk_percent",
            "temperature_c",
        )})
        snapshot["history"] = list(self.history)
        return snapshot


def diagnose_system_health(snapshot):
    """Return evidence-backed findings with cautious severity thresholds."""
    findings = []

    def add(name, severity, evidence, cause, recommendation, limitation):
        findings.append({"name": name, "severity": severity, "evidence": evidence,
                         "possible_cause": cause, "recommendation": recommendation,
                         "limitation": limitation})

    memory_percent = snapshot.get("memory_percent")
    if isinstance(memory_percent, (int, float)) and memory_percent >= 95:
        severity = "Crítico" if snapshot.get("memory_available", 0) < snapshot.get("memory_total", 1) * 0.03 else "Atenção"
        add("Memória RAM muito utilizada", severity,
            f"{memory_percent:.1f}% em uso; {snapshot.get('memory_available', 0)} bytes disponíveis.",
            "Aplicativos abertos ou cache do sistema podem elevar o uso.",
            "Confira os processos com maior memória e feche apenas os que você reconhece e não precisa.",
            "Uma amostra isolada não comprova lentidão; o Linux também usa RAM para cache.")
    elif isinstance(memory_percent, (int, float)) and memory_percent >= 85:
        add("Uso de memória elevado", "Atenção", f"{memory_percent:.1f}% de RAM em uso.",
            "Muitos aplicativos ou tarefas simultâneas podem contribuir.",
            "Confira a lista de processos e observe se o uso continua alto.",
            "O uso pode variar e cache recuperável também aparece como memória ocupada.")

    cpu = snapshot.get("cpu_percent")
    if isinstance(cpu, (int, float)) and cpu >= 90:
        add("Carga de CPU elevada", "Atenção", f"CPU em {cpu:.1f}% na amostra atual.",
            "Uma tarefa pode estar usando processador intensamente.",
            "Ordene os processos por CPU e aguarde outra amostra para confirmar persistência.",
            "Uma amostra curta não distingue uma operação normal de uma carga persistente.")

    disk = snapshot.get("disk_percent")
    if isinstance(disk, (int, float)) and disk >= 98:
        add("Armazenamento quase cheio", "Crítico", f"{disk:.1f}% ocupado.",
            "Arquivos e caches acumulados podem reduzir o espaço disponível.",
            "Revise os maiores diretórios no Analisador de armazenamento antes de remover qualquer arquivo.",
            "O indicador corresponde ao volume da pasta pessoal e não avalia todos os volumes.")
    elif isinstance(disk, (int, float)) and disk >= 90:
        add("Pouco espaço livre", "Atenção", f"{disk:.1f}% do volume da pasta pessoal está ocupado.",
            "O volume pode estar se aproximando do limite.",
            "Consulte os maiores diretórios e avalie os arquivos manualmente.",
            "O uso de outros volumes pode ser diferente.")

    temperature = snapshot.get("temperature_c")
    if isinstance(temperature, (int, float)) and temperature >= 95:
        add("Temperatura elevada", "Crítico", f"Sensor mais quente: {temperature:.1f} °C.",
            "Carga intensa ou refrigeração insuficiente são possibilidades.",
            "Reduza tarefas pesadas e confira ventilação e refrigeração do equipamento.",
            "A disponibilidade e a localização dos sensores dependem do hardware.")
    elif isinstance(temperature, (int, float)) and temperature >= 85:
        add("Temperatura acima do usual", "Atenção", f"Sensor mais quente: {temperature:.1f} °C.",
            "Uma tarefa pesada pode elevar a temperatura.",
            "Observe novamente após alguns minutos e verifique a ventilação.",
            "O limite recomendado varia entre componentes e o sensor pode não ser o da CPU.")

    for process in snapshot.get("processes", ()):
        if process.get("cpu_percent") is not None and process["cpu_percent"] >= 80:
            add(f"Processo com CPU elevada: {process['name']}", "Atenção",
                f"PID {process['pid']} · {process['cpu_percent']:.1f}% de CPU na última amostra.",
                "O processo executou trabalho intensivo durante o intervalo medido.",
                "Confira se a tarefa é esperada; não encerre o processo sem entender sua função.",
                "O percentual pode ultrapassar 100% em processos multithread.")
            break
    return findings


def build_computer_consultant_context(system_snapshot=None, network_snapshot=None):
    """Build a compact factual payload for a future Nova conversation tool."""
    context = {"schema": "computer-health-context.v1"}
    if system_snapshot:
        context["system"] = {
            key: system_snapshot.get(key) for key in (
                "cpu_percent", "memory_percent", "memory_available",
                "disk_percent", "disk_free", "temperature_c", "issues",
            )
        }
        context["top_processes"] = [
            {key: item.get(key) for key in
             ("name", "pid", "cpu_percent", "memory_bytes")}
            for item in system_snapshot.get("processes", ())[:5]
        ]
    if network_snapshot:
        context["network"] = {
            key: network_snapshot.get(key) for key in (
                "connection_state", "internet_state", "gateway",
                "download_bytes_per_second", "upload_bytes_per_second",
                "dns_servers",
            )
        }
    context["limitations"] = [
        "Observações locais são amostras momentâneas e não substituem diagnóstico especializado.",
        "Acesso à internet só é avaliado após uma verificação de conectividade solicitada pelo usuário.",
    ]
    return context
