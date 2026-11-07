import logging
import random
import time
import tkinter as tk
from datetime import datetime, timedelta
from autonomy import is_quiet_now, save_settings, valid_reminder_time
from config import APP_COMMENTS, REMINDER_ANIMATION_SECONDS, THUMBS_UP_ANIMATION_SECONDS, VIDEO_REACTION_SECONDS
from nova_ai.memory.errors import MemoryStorageError
from personality import pick_line, record_spontaneous_speech


def _project_topic(content):
    return " ".join(content.replace("\n", " ").replace("\t", " ").split())[:100]


class RoutineControllerMixin:
    def _update_visit_metadata(self):
        today = datetime.now().astimezone().date()
        previous = self.settings.get("last_seen_date", "")
        try:
            previous_date = datetime.strptime(previous, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            previous_date = None
        self._miss_you_pending = bool(
            previous_date is not None and (today - previous_date).days >= 2
        )
        self.settings["last_seen_date"] = today.isoformat()
        if not save_settings(self.settings, getattr(self, "settings_path", None)):
            logging.getLogger(__name__).warning(
                "Não foi possível salvar a data da última visita da Nova."
            )

    def maybe_curious(self):
        if self._closing:
            return
        if (self.state == "walk" and self.focus_mode == "idle" and not self.busy
                and not self.dragging and not self.ai_request_active
                and self.settings.get("mode") != "quietinha"
                and not self._is_quiet_time() and not self.is_covered()
                and not self.bubble_text and random.random() < 0.5):
            self.state = "curious"
            self._schedule_pose_callback(3500, "curious", self.finish_curious)
        self.root.after(random.randint(45000, 90000), self.maybe_curious)

    def check_idle_yawn(self):
        if self._closing:
            return
        idle_long_enough = time.monotonic() - self._last_user_activity_at >= 300
        available = (
            self.settings.get("routine_idle_yawn")
            and idle_long_enough and self.state == "walk"
            and self._can_speak_spontaneously()
        )
        if available and random.random() < 0.2 and self._spontaneous_ready():
            self.state = "yawning"
            self._show_personality_line("yawning", duration=5000, spontaneous=True)
            self._schedule_pose_callback(5000, "yawning", self.finish_surprise)
            self._last_user_activity_at = time.monotonic()
        self.root.after(300000, self.check_idle_yawn)

    def finish_curious(self):
        if not self._closing and self.state == "curious":
            self.state = "walk"

    def _is_quiet_time(self):
        return is_quiet_now(self.settings.get("quiet_start"), self.settings.get("quiet_end"))

    def observe_apps(self):
        if (self.observe_apps_var.get() and self._can_speak_spontaneously()
                and self.state == "walk" and self.x11.ok):
            info = self.x11.get_active_window_info()
            if info:
                klass, name = info
                haystack = f"{klass} {name}".lower()
                app_key = None
                for key in APP_COMMENTS:
                    if key in haystack:
                        app_key = key
                        break
                if app_key is None and random.random() < 0.4:
                    app_key = "generic_app_comment"
                if app_key:
                    music_apps = ("spotify", "music", "rhythmbox")
                    duration = 3500
                    if app_key in music_apps:
                        if self._can_speak_spontaneously() and self._spontaneous_ready():
                            self.state = "celebrating"
                            if self._show_personality_line(
                                app_key, duration=duration, spontaneous=True
                            ):
                                self._schedule_pose_return(
                                    duration, "celebrating"
                                )
                    else:
                        self._show_personality_line(
                            app_key, duration=2800, spontaneous=True
                        )
        interval = (120000, 210000) if self.settings["mode"] == "proativa" else (240000, 420000)
        self.root.after(random.randint(*interval), self.observe_apps)

    def check_reminders(self):
        if self._closing:
            return
        now = time.time()
        available = (
            self.state == "walk"
            and self._can_speak_spontaneously()
            and self._spontaneous_ready()
        )
        due = []
        due_items = []
        for item in self.settings.get("reminders", []):
            parsed = valid_reminder_time(item.get("at")) if isinstance(item, dict) else None
            if (available and parsed and not item.get("done")
                    and parsed.timestamp() <= now):
                due_items.append((item, "done" in item, item.get("done")))
                item["done"] = True
                due.append(item.get("text", "Você tem um lembrete."))
        if due:
            if not save_settings(self.settings, getattr(self, "settings_path", None)):
                for item, had_done, previous_done in due_items:
                    if had_done:
                        item["done"] = previous_done
                    else:
                        item.pop("done", None)
                logging.getLogger(__name__).error(
                    "Não foi possível salvar lembretes vencidos; eles permanecem pendentes."
                )
                if not getattr(self, "_reminder_save_warning_shown", False):
                    self.show_bubble(
                        "Não consegui salvar o lembrete. Ele continua pendente e tentarei novamente.",
                        duration=6000,
                    )
                    self._reminder_save_warning_shown = True
            else:
                self._reminder_save_warning_shown = False
                self._reminder_started_at = time.monotonic()
                self._reminder_animation_until = (
                    self._reminder_started_at + REMINDER_ANIMATION_SECONDS
                )
                line = pick_line(
                    "reminder_due", name=self.settings.get("user_name", ""),
                    rng=random, history=self._speech_history,
                )
                record_spontaneous_speech()
                self.show_bubble(f"{line} {'; '.join(due)}", duration=12000)
        self.root.after(15000, self.check_reminders)

    def show_start_greeting(self):
        if self._closing or self._routine_greeted or not self.settings.get("routine_greeting"):
            return
        category = "miss_you" if self._miss_you_pending else "greeting"
        now = datetime.now().astimezone()
        if not self._show_greeting_pose(category, now):
            self.root.after(60000, self.show_start_greeting)
            return
        self._routine_greeted = True
        self._miss_you_pending = False
        self.settings["last_context_date"] = now.date().isoformat()
        save_settings(self.settings, getattr(self, "settings_path", None))
        self._schedule_pose_callback(
            round(VIDEO_REACTION_SECONDS * 1000),
            "greeting",
            self.finish_greeting,
        )

    def finish_greeting(self):
        if not self._closing and self.state == "greeting":
            self.state = "walk"

    def _project_followup_candidate(self, now):
        if not self.settings.get("routine_context"):
            return None
        integration = getattr(self, "nova_integration", None)
        if integration is None:
            return None
        try:
            records = integration.project_memories(limit=20)
        except MemoryStorageError:
            logging.getLogger(__name__).exception(
                "Não foi possível recuperar memórias de projetos para a saudação."
            )
            return None
        history = self.settings.get("proactive_project_followups")
        if not isinstance(history, dict):
            history = {}
            self.settings["proactive_project_followups"] = history
        for record in records:
            last_seen = history.get(record.memory_id)
            if isinstance(last_seen, str):
                try:
                    last_seen_at = datetime.fromisoformat(last_seen)
                    if last_seen_at.tzinfo is None:
                        last_seen_at = last_seen_at.astimezone()
                    cooldown_days = self.settings.get("project_followup_days", 7)
                    if now - last_seen_at < timedelta(days=cooldown_days):
                        continue
                except ValueError:
                    pass
            topic = _project_topic(record.content)
            if topic:
                return record, topic
        return None

    def _show_greeting_pose(self, category, now):
        candidate = self._project_followup_candidate(now)
        if candidate:
            record, topic = candidate
            if self._show_spontaneous_pose(
                "project_followup", "greeting", duration=6500, topic=topic
            ):
                history = self.settings["proactive_project_followups"]
                history[record.memory_id] = now.isoformat()
                if len(history) > 100:
                    oldest = sorted(history.items(), key=lambda item: item[1])[:-100]
                    for memory_id, _observed_at in oldest:
                        history.pop(memory_id, None)
                if not save_settings(
                    self.settings, getattr(self, "settings_path", None)
                ):
                    logging.getLogger(__name__).warning(
                        "A pergunta sobre projeto foi exibida, mas o cooldown não foi salvo."
                    )
                return True
        return self._show_spontaneous_pose(category, "greeting", duration=6500)

    def show_context_greeting(self):
        if self._closing or not self.settings.get("routine_context"):
            return
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        if self.settings.get("last_context_date") == today:
            return
        if self._routine_greeted:
            self.settings["last_context_date"] = today
            save_settings(self.settings, getattr(self, "settings_path", None))
            return
        category = "miss_you" if self._miss_you_pending else "greeting"
        if not self._show_greeting_pose(category, now):
            self.root.after(60000, self.show_context_greeting)
            return
        self._routine_greeted = True
        self._miss_you_pending = False
        self.settings["last_context_date"] = today
        save_settings(self.settings, getattr(self, "settings_path", None))
        self._schedule_pose_callback(
            round(VIDEO_REACTION_SECONDS * 1000),
            "greeting",
            self.finish_greeting,
        )

    def check_occasional_note(self):
        if self._closing:
            return
        now = time.time()
        available = (
            self.settings.get("routine_note")
            and now - self.settings.get("last_note_at", 0) >= 30 * 60
            and self.state == "walk"
            and self._can_speak_spontaneously()
        )
        if available and random.random() < 0.08:
            self.settings["last_note_at"] = int(now)
            save_settings(self.settings, getattr(self, "settings_path", None))
            self._show_personality_line("compliment", duration=6000, spontaneous=True)
        self.root.after(300000, self.check_occasional_note)

    def check_idle_dance(self):
        if self._closing:
            return
        now = time.monotonic()
        available = (
            self.settings.get("routine_dance")
            and self.settings.get("mode") in ("companhia", "proativa")
            and self.state == "walk"
            and now - self._last_dance_at >= 20 * 60
            and self._can_speak_spontaneously()
            and self._spontaneous_ready()
        )
        if available and random.random() < 0.04:
            if self._show_spontaneous_pose("dance", "celebrating", duration=4000):
                self._last_dance_at = now
                self._schedule_pose_return(4000, "celebrating")
        self.root.after(60000, self.check_idle_dance)

    def check_healthy_break(self):
        if self._closing:
            return
        now = time.monotonic()
        available = (
            self.settings.get("routine_break_tip")
            and self.settings.get("automations", {}).get("enabled", {}).get("pause_reminder", True)
            and now - self._last_break_tip_at >= 50 * 60
            and self.state == "walk"
            and self._can_speak_spontaneously()
            and self._spontaneous_ready()
        )
        if available and self._show_spontaneous_pose(
            "break_tip", "resting", duration=6500
        ):
            self._last_break_tip_at = now
            self._schedule_pose_return(
                6500, "resting"
            )
        self.root.after(300000, self.check_healthy_break)

    def check_daily_routine(self):
        if self._closing:
            return
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        if (self.settings.get("routine_evening")
                and self.settings.get("last_evening_date") != today
                and now.strftime("%H:%M") >= self.settings.get("evening_time", "20:30")
                and self.state == "walk" and self._can_speak_spontaneously()
                and self._spontaneous_ready()):
            self.settings["last_evening_date"] = today
            save_settings(self.settings, getattr(self, "settings_path", None))
            self.state = "yawning"
            record_spontaneous_speech()
            self._schedule_pose_callback(
                2500, "yawning", self._finish_evening_routine
            )
        self.root.after(30000, self.check_daily_routine)

    def _finish_evening_routine(self):
        if self._closing or self.state != "yawning":
            return
        if not self._can_speak_spontaneously():
            self.state = "walk"
            return
        self.state = "sitting" if self._quiet_time_approaching() else "walk"
        self._show_personality_line("evening_wrap", duration=9000)

    def _quiet_time_approaching(self):
        now = datetime.now().astimezone()
        try:
            quiet_start = datetime.strptime(
                self.settings.get("quiet_start", "22:00"), "%H:%M"
            ).time()
        except (TypeError, ValueError):
            return False
        next_start = now.replace(
            hour=quiet_start.hour, minute=quiet_start.minute,
            second=0, microsecond=0,
        )
        if next_start <= now:
            next_start += timedelta(days=1)
        return next_start - now <= timedelta(minutes=30)

    def check_daily_surprise(self):
        if self._closing:
            return
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        available = (
            self.settings.get("routine_surprise")
            and self.settings.get("last_surprise_date") != today
            and self.state == "walk"
            and self._can_speak_spontaneously()
            and self._spontaneous_ready()
        )
        if available and random.random() < 0.15:
            if random.choice(("cheering", "yawning")) == "yawning":
                shown = self._show_spontaneous_pose(
                    "yawning", "yawning", duration=6500
                )
            else:
                shown = self._show_spontaneous_pose(
                    "surprise", "cheering", duration=6500
                )
            if shown:
                self.settings["last_surprise_date"] = today
                save_settings(self.settings, getattr(self, "settings_path", None))
                self._schedule_pose_callback(
                    6500, self.state, self.finish_surprise
                )
        self.root.after(300000, self.check_daily_surprise)

    def finish_surprise(self):
        if not self._closing and self.state in ("celebrating", "cheering", "yawning"):
            self.state = "walk"

    def start_focus(self, goal, focus_minutes, break_minutes):
        if self.focus_mode != "idle":
            self.show_bubble("Já estamos em uma sessão de foco ou pausa.", duration=3500)
            return False
        if self.ai_request_active or self.dragging:
            self.show_bubble("Termino o que estou fazendo e já começamos.", duration=3500)
            return False
        self.focus_goal = goal.strip() or "sua prioridade"
        self.focus_minutes = int(focus_minutes)
        self.break_minutes = int(break_minutes)
        self.focus_mode = "focus"
        self._focus_routine_started_at = time.monotonic()
        self._focused_started_at = self._focus_routine_started_at
        self.state = "focused"
        self.sit_win_id = None
        line = pick_line(
            "focus_start", name=self.settings.get("user_name", ""),
            rng=random, history=self._speech_history,
        )
        self.show_bubble(
            f"{line} Prioridade: {self.focus_goal}.", duration=6500
        )
        self.root.after(
            self.focus_minutes * 30_000, self._focus_midpoint
        )
        self._focus_job = self.root.after(self.focus_minutes * 60_000, self.finish_focus)
        return True

    def _focus_midpoint(self):
        if self._closing or self.focus_mode != "focus" or self.state != "focused":
            return
        if not self._can_speak_spontaneously(allow_focus=True) or not self._spontaneous_ready():
            self.root.after(30000, self._focus_midpoint)
            return
        self._show_personality_line(
            "focus_mid", duration=5000, spontaneous=True, allow_focus=True
        )

    def finish_focus(self):
        self._focus_job = None
        if self._closing or self.focus_mode != "focus":
            return
        self.focus_mode = "break"
        self.state = (
            "thumbs_up" if getattr(self, "settings", {}).get("routine_focus_celebration")
            else "sitting"
        )
        if self.state == "thumbs_up":
            self._thumbs_up_started_at = time.monotonic()
        self._show_personality_line(
            "focus_done", duration=12_000, spontaneous=True, allow_focus=True
        )
        if self.state == "thumbs_up":
            self._schedule_pose_callback(
                round(THUMBS_UP_ANIMATION_SECONDS * 1000),
                "thumbs_up",
                self.enter_focus_break,
            )
        self._focus_job = self.root.after(self.break_minutes * 60_000, self.finish_break)

    def enter_focus_break(self):
        if not self._closing and self.focus_mode == "break" and self.state == "thumbs_up":
            self.state = "sitting"

    def finish_break(self):
        self._focus_job = None
        if self._closing or self.focus_mode != "break":
            return
        self._finish_focus_routine_timer()
        self.focus_mode = "idle"
        self.state = "celebrating"
        self._show_personality_line("break_end", duration=7000, spontaneous=True)
        self.focus_goal = ""
        self._schedule_pose_callback(
            4000, "celebrating", self.finish_celebration
        )

    def _finish_focus_routine_timer(self):
        started_at = getattr(self, "_focus_routine_started_at", None)
        if started_at is not None:
            self._last_break_tip_at = getattr(
                self, "_last_break_tip_at", started_at
            ) + max(0.0, time.monotonic() - started_at)
            self._focus_routine_started_at = None

    def finish_celebration(self):
        if not self._closing and self.state == "celebrating":
            self.state = "walk"

    def stop_focus(self):
        if self.focus_mode == "idle":
            return
        self._finish_focus_routine_timer()
        if self._focus_job is not None:
            try:
                self.root.after_cancel(self._focus_job)
            except tk.TclError:
                pass
            self._focus_job = None
        self.focus_mode = "idle"
        self.focus_goal = ""
        self.state = "walk"
        self.show_bubble("Sessão encerrada. Vamos no seu ritmo.", duration=4500)
