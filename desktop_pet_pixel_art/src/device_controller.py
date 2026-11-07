import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from autonomy import save_settings


class DeviceControllerMixin:
    @staticmethod
    def _scan_usb_storage_devices():
        """Return connected USB mass-storage devices keyed by stable sysfs IDs."""
        devices = {}
        usb_root = Path("/sys/bus/usb/devices")
        try:
            interfaces = tuple(usb_root.glob("*:*"))
        except OSError:
            interfaces = ()
        for interface in interfaces:
            try:
                if (interface / "bInterfaceClass").read_text(
                    encoding="ascii"
                ).strip().lower() != "08":
                    continue
                parent = interface.resolve().parent
                key = parent.name
                parts = []
                for field in ("manufacturer", "product"):
                    try:
                        value = (parent / field).read_text(encoding="utf-8").strip()
                    except (OSError, UnicodeError):
                        value = ""
                    if value and value not in parts:
                        parts.append(value)
                devices[key] = " ".join(parts)[:48] or "pendrive USB"
            except (OSError, RuntimeError):
                continue
        if devices:
            return devices

        # Fallback for systems whose USB interfaces do not expose class files.
        try:
            blocks = tuple(Path("/sys/class/block").iterdir())
        except OSError:
            blocks = ()
        for block in blocks:
            try:
                if (block / "removable").read_text(encoding="ascii").strip() != "1":
                    continue
                target = str((block / "device").resolve())
                if "/usb" not in target:
                    continue
                try:
                    model = (block / "device" / "model").read_text(
                        encoding="utf-8"
                    ).strip()
                except (OSError, UnicodeError):
                    model = ""
                devices[f"block:{block.name}"] = model[:48] or "pendrive USB"
            except (OSError, RuntimeError):
                continue
        return devices

    @staticmethod
    def _external_power_connected():
        """Read external power state from sysfs, with psutil as a fallback."""
        root = Path("/sys/class/power_supply")
        observed = False
        known_states = []
        try:
            supplies = tuple(root.iterdir())
        except OSError:
            supplies = ()
        for supply in supplies:
            try:
                kind = (supply / "type").read_text(encoding="ascii").strip().lower()
                if kind == "battery":
                    continue
                if not (kind in ("mains", "wireless", "ac") or kind.startswith("usb")):
                    continue
                online = (supply / "online").read_text(encoding="ascii").strip()
                observed = True
                if online == "1":
                    return True
                if online == "0":
                    known_states.append(False)
            except (OSError, UnicodeError):
                continue
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is not None:
                plugged = bool(battery.power_plugged)
                if plugged:
                    return True
                if observed:
                    return False
        except Exception:
            pass
        if observed and known_states:
            return False
        return None

    def _device_monitor_worker(self):
        # Baseline prevents announcements for devices/power present at launch.
        previous_power = self._external_power_connected()
        previous_usb = self._scan_usb_storage_devices()
        logging.getLogger(__name__).info(
            "Monitor de dispositivos iniciado (energia externa: %s; armazenamentos USB: %d).",
            previous_power, len(previous_usb),
        )
        while not self._device_monitor_stop.wait(2.0):
            try:
                power = self._external_power_connected()
                if power is not None:
                    if previous_power is False and power is True:
                        logging.getLogger(__name__).info("Conexão do carregador detectada.")
                        self._device_event_results.put(("charger_connected", None))
                    previous_power = power
            except Exception:
                logging.getLogger(__name__).debug("Falha ao verificar alimentação externa.", exc_info=True)
            try:
                current_usb = self._scan_usb_storage_devices()
                for key, label in current_usb.items():
                    if key not in previous_usb:
                        logging.getLogger(__name__).info("Armazenamento USB conectado: %s.", label)
                        self._device_event_results.put(("usb_connected", label))
                previous_usb = current_usb
            except Exception:
                logging.getLogger(__name__).debug("Falha ao verificar armazenamento USB.", exc_info=True)

    def _drain_device_event_results(self):
        received = False
        while True:
            try:
                event = self._device_event_results.get_nowait()
            except queue.Empty:
                break
            category = event[0]
            enabled_key = "announce_charger" if category == "charger_connected" else "announce_usb"
            if self.settings.get(enabled_key, True):
                self._pending_device_announcements.append(event)
                received = True
        if received:
            self._try_announce_device_event()

    def _schedule_device_announcement_retry(self):
        if (self._pending_device_announcements
                and self._device_announcement_retry_job is None
                and not self._closing):
            self._device_announcement_retry_job = self.root.after(
                5000, self._try_announce_device_event
            )

    def _try_announce_device_event(self):
        self._device_announcement_retry_job = None
        while self._pending_device_announcements:
            category, device = self._pending_device_announcements[0]
            enabled_key = "announce_charger" if category == "charger_connected" else "announce_usb"
            if not self.settings.get(enabled_key, True):
                self._pending_device_announcements.pop(0)
                continue
            break
        if not self._pending_device_announcements or self._closing:
            return
        if not self._can_speak_spontaneously():
            self._schedule_device_announcement_retry()
            return
        category, device = self._pending_device_announcements.pop(0)
        state = "greeting" if category == "charger_connected" else "curious"
        if not self._show_spontaneous_pose(
            category, state, duration=4500, bypass_cooldown=True,
            **({"device": device} if device else {})
        ):
            self._pending_device_announcements.insert(0, (category, device))
            self._schedule_device_announcement_retry()
            return
        self._schedule_pose_return(4500, state)
        self._schedule_device_announcement_retry()

    def check_low_battery(self):
        if self._closing:
            return
        enabled = self.settings.get("automations", {}).get("enabled", {}).get("low_battery_alert", True)
        if enabled and not self._battery_check_active:
            self._battery_check_active = True
            threading.Thread(target=self._low_battery_worker, daemon=True).start()
        self.root.after(120000, self.check_low_battery)

    def _low_battery_worker(self):
        reading = None
        try:
            import psutil
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is not None:
            reading = (float(battery.percent), bool(battery.power_plugged))
        else:
            # psutil não encontra a bateria em alguns notebooks/ambientes Linux.
            # O sysfs oferece uma segunda leitura local, sem depender de rede.
            try:
                for supply in Path("/sys/class/power_supply").iterdir():
                    if (supply / "type").read_text(encoding="ascii").strip().lower() != "battery":
                        continue
                    percent = float((supply / "capacity").read_text(encoding="ascii").strip())
                    try:
                        status = (supply / "status").read_text(encoding="ascii").strip().lower()
                    except OSError:
                        status = ""
                    reading = (percent, status in ("charging", "full"))
                    break
            except (OSError, ValueError):
                reading = None
        self._battery_check_results.put(reading)

    def _drain_low_battery_results(self):
        try:
            reading = self._battery_check_results.get_nowait()
        except queue.Empty:
            return
        self._battery_check_active = False
        if reading is None:
            label = getattr(self, "_automation_status_labels", {}).get("low_battery_alert")
            if label is not None:
                try:
                    label.configure(text="Não consegui ler a bateria neste sistema.")
                except tk.TclError:
                    pass
            return
        percent, plugged = reading
        if plugged or percent > 25:
            self._low_battery_alerted = False
            self._low_battery_pending = False
        elif percent <= 20 and not self._low_battery_alerted:
            self._low_battery_pending = True
            self._low_battery_percent = percent
            label = getattr(self, "_automation_status_labels", {}).get("low_battery_alert")
            if label is not None:
                try:
                    label.configure(
                        text=f"Bateria baixa · {percent:.0f}% · aviso pendente"
                    )
                except tk.TclError:
                    pass
            self._schedule_low_battery_retry()

    def _schedule_low_battery_retry(self):
        if (self._low_battery_pending and self._low_battery_retry_job is None
                and not self._closing):
            self._low_battery_retry_job = self.root.after(
                15000, self._try_show_low_battery_alert
            )

    def _try_show_low_battery_alert(self):
        self._low_battery_retry_job = None
        enabled = self.settings.get("automations", {}).get("enabled", {}).get(
            "low_battery_alert", True
        )
        if not self._low_battery_pending or not enabled or self._closing:
            return
        if (not self._can_speak_spontaneously(allow_focus=True)
                or not self._spontaneous_ready()):
            self._schedule_low_battery_retry()
            return

        percent = (
            20 if self._low_battery_percent is None
            else self._low_battery_percent
        )
        previous_state = self.state
        if self.focus_mode == "idle":
            self.state = "curious"
        if not self._show_personality_line(
            "low_battery", duration=7000, spontaneous=True, allow_focus=True
        ):
            self.state = previous_state
            self._schedule_low_battery_retry()
            return

        self._low_battery_pending = False
        self._low_battery_alerted = True
        label = getattr(self, "_automation_status_labels", {}).get("low_battery_alert")
        message = f"Bateria baixa · {percent:.0f}% · avisada agora"
        self.settings.setdefault("automations", {}).setdefault("last_run", {})[
            "low_battery_alert"
        ] = message
        save_settings(self.settings, getattr(self, "settings_path", None))
        if label is not None:
            try:
                label.configure(text=message)
            except tk.TclError:
                pass
        if self.state == "curious":
            self._schedule_pose_return(3500, "curious")
