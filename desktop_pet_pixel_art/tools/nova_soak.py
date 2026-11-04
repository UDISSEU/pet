#!/usr/bin/env python3
"""Run a configurable, real-process soak of Nova's event/UI/notification services.

This is deliberately separate from the regular test suite. It measures the
current Python process and the real bounded service queues; it does not start
Tk or claim to measure rendered animation performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from animation import frame_index_at_elapsed  # noqa: E402
from desktop_pet import DesktopPet  # noqa: E402
from event_bus import Event, EventBus, EventType  # noqa: E402
from notifications import NotificationCategory, NotificationManager  # noqa: E402
from system_monitor import SystemMonitor  # noqa: E402


SCENARIOS = {"30m": 30 * 60, "1h": 60 * 60, "3h": 3 * 60 * 60}


def run(duration, interval, output, target_pid=None, display_pid=None):
    import psutil

    with tempfile.TemporaryDirectory(prefix="nova-soak-") as temp_dir:
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet._ui_callbacks = queue.Queue()
        pet.event_bus = EventBus()
        pet.system_monitor = SystemMonitor(history_limit=120)
        pet.notification_manager = NotificationManager(
            Path(temp_dir) / "notifications.json", event_bus=pet.event_bus,
            limit=200, cooldown_seconds=0,
        )

        stop = threading.Event()
        produced = [0]

        def produce_worker_events():
            while not stop.is_set():
                if pet.event_bus.post(Event(EventType.SYSTEM_METRICS_UPDATED, {"source": "soak"})):
                    produced[0] += 1
                pet.post_ui_callback(lambda: None)
                stop.wait(interval)

        worker = threading.Thread(target=produce_worker_events, name="nova-soak-producer", daemon=True)
        worker.start()
        process = psutil.Process(os.getpid())
        target_process = psutil.Process(target_pid) if target_pid else None
        display_process = psutil.Process(display_pid) if display_pid else None
        for monitored_process in (target_process, display_process):
            if monitored_process is not None:
                try:
                    monitored_process.cpu_percent(interval=None)
                except psutil.Error:
                    pass
        started_at = datetime.now(timezone.utc).isoformat()
        samples = 0
        max_event_queue = 0
        max_callback_queue = 0
        max_children = 0
        started = time.monotonic()
        next_notification = started
        last_frame = 0
        try:
            while time.monotonic() - started < duration:
                loop_started = time.monotonic()
                pet.event_bus.drain(limit=1000)
                pet._drain_ui_callbacks()
                now = time.monotonic()
                elapsed_ms = int((now - started) * 1000)
                last_frame = frame_index_at_elapsed(elapsed_ms, 12, fps=12)
                if now >= next_notification:
                    pet.notification_manager.create(
                        "Soak heartbeat", "Nova soak test is active",
                        category=NotificationCategory.INFO,
                    )
                    next_notification = now + max(60.0, interval)
                metrics = pet.system_monitor.collect(extra={
                    "process_cpu_percent": process.cpu_percent(interval=None),
                    "process_memory": process.memory_info().rss,
                    "event_queue": pet.event_bus._queue.qsize(),
                    "notification_history": len(pet.notification_manager.items),
                    "ui_callback_queue": pet._ui_callbacks.qsize(),
                    "animation_frame": last_frame,
                    "events_produced": produced[0],
                    "children": len(process.children(recursive=True)),
                })
                for prefix, monitored_process in (
                    ("nova", target_process), ("x_server", display_process),
                ):
                    if monitored_process is None:
                        continue
                    try:
                        monitored_children = monitored_process.children(recursive=True)
                        process_group = os.getpgid(monitored_process.pid)
                        plugin_groups = {
                            group for child in monitored_children
                            for group in [os.getpgid(child.pid)]
                            if group != process_group
                        }
                        threads = monitored_process.num_threads()
                        metrics.update({
                            f"{prefix}_cpu_percent": monitored_process.cpu_percent(interval=None),
                            f"{prefix}_memory": monitored_process.memory_info().rss,
                            f"{prefix}_threads": threads,
                            f"{prefix}_worker_threads_estimate": max(0, threads - 1),
                            f"{prefix}_children": len(monitored_children),
                        })
                        if prefix == "nova":
                            plugin_children = []
                            other_children = []
                            for child in monitored_children:
                                child_group = os.getpgid(child.pid)
                                (plugin_children if child_group in plugin_groups
                                 else other_children).append(child)
                            plugin_memory = sum(
                                child.memory_info().rss for child in plugin_children
                            )
                            other_memory = sum(
                                child.memory_info().rss for child in other_children
                            )
                            plugin_cpu = sum(
                                child.cpu_percent(interval=None) for child in plugin_children
                            )
                            other_cpu = sum(
                                child.cpu_percent(interval=None) for child in other_children
                            )
                            metrics["nova_isolated_child_groups"] = len(plugin_groups)
                            metrics["nova_plugin_processes_estimate"] = sum(
                                1 for child in plugin_children
                                if child.name() in {"bwrap", "bubblewrap", "prlimit"}
                            )
                            metrics["nova_plugin_group_memory"] = plugin_memory
                            metrics["nova_plugin_group_cpu_percent"] = plugin_cpu
                            metrics["nova_other_child_processes"] = len(other_children)
                            metrics["nova_other_child_memory"] = other_memory
                            metrics["nova_other_child_cpu_percent"] = other_cpu
                    except (psutil.Error, OSError):
                        metrics.update({
                            f"{prefix}_cpu_percent": None,
                            f"{prefix}_memory": None,
                            f"{prefix}_threads": None,
                            f"{prefix}_worker_threads_estimate": None,
                            f"{prefix}_children": None,
                        })
                max_event_queue = max(max_event_queue, metrics["event_queue"])
                max_callback_queue = max(max_callback_queue, metrics["ui_callback_queue"])
                max_children = max(max_children, metrics["children"])
                record = {
                    "kind": "sample", "elapsed_seconds": round(now - started, 3),
                    **metrics,
                }
                output.write(json.dumps(record, sort_keys=True) + "\n")
                output.flush()
                samples += 1
                remaining = interval - (time.monotonic() - loop_started)
                if remaining > 0:
                    stop.wait(min(remaining, max(0.01, duration - (time.monotonic() - started))))
            elapsed = time.monotonic() - started
        finally:
            stop.set()
            worker.join(timeout=max(2.0, interval + 1.0))
            pet._closing = True
            pet.event_bus.close()
        final = {
            "kind": "summary", "started_at": started_at,
            "duration_seconds": round(elapsed, 3), "samples": samples,
            "events_produced": produced[0], "threads_after_worker_exit": threading.active_count(),
            "children_after_worker_exit": len(process.children(recursive=True)),
            "monitored_nova_pid": target_pid,
            "monitored_x_server_pid": display_pid,
            "max_event_queue": max_event_queue,
            "max_ui_callback_queue": max_callback_queue,
            "max_children": max_children,
            "notification_history_final": len(pet.notification_manager.items),
            "monitor_history_final": len(pet.system_monitor.history),
            "animation_frame_final": last_frame,
            "worker_stopped": not worker.is_alive(),
        }
        output.write(json.dumps(final, sort_keys=True) + "\n")
        output.flush()
        return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="30m")
    parser.add_argument("--duration-seconds", type=float,
                        help="Override scenario duration for short reproducibility checks")
    parser.add_argument("--sample-interval", type=float, default=10.0)
    parser.add_argument("--output", type=Path, help="JSONL report path (default: stdout)")
    parser.add_argument("--target-pid", type=int, help="Also sample a running Nova process")
    parser.add_argument("--display-pid", type=int, help="Also sample the isolated X server")
    args = parser.parse_args()
    duration = args.duration_seconds if args.duration_seconds is not None else SCENARIOS[args.scenario]
    if duration <= 0 or args.sample_interval <= 0:
        parser.error("duration and sample interval must be positive")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as stream:
            run(duration, args.sample_interval, stream, args.target_pid, args.display_pid)
    else:
        run(duration, args.sample_interval, sys.stdout, args.target_pid, args.display_pid)


if __name__ == "__main__":
    main()
