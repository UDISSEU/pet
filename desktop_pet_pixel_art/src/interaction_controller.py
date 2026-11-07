import logging
import time
import tkinter as tk
from datetime import datetime
from autonomy import save_settings
from config import VIDEO_REACTION_SECONDS


class InteractionControllerMixin:
    def _record_interaction(self):
        self.settings["interaction_count"] = self.settings.get("interaction_count", 0) + 1
        self.settings["last_seen_date"] = datetime.now().astimezone().date().isoformat()
        if not save_settings(self.settings, getattr(self, "settings_path", None)):
            logging.getLogger(__name__).warning(
                "Não foi possível salvar os metadados da interação da Nova."
            )

    def start_drag(self, event):
        self._last_user_activity_at = time.monotonic()
        try:
            self._drag_focus_widget = self.root.focus_get()
        except tk.TclError:
            self._drag_focus_widget = None
        self.dragging = True
        self.was_drag = False
        self.drag_tilt = 0.0
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = self.root.winfo_pointerx()
        self._last_drag_event_at = time.monotonic()
        self._last_drag_motion_at = self._last_drag_event_at
        self._pickup_spoken = False
        if self.state == "sitting":
            self.sit_win_id = None
        self.state = "held"
        self.drag_offset = (event.x, event.y)

    def do_drag(self, event):
        if not self.was_drag:
            if self._pending_click_job is not None:
                self.root.after_cancel(self._pending_click_job)
                self._pending_click_job = None
            self._pickup_spoken = False
            if self._interaction_speech_allowed(allow_drag=True):
                self._show_personality_line("pickup", duration=1400)
                self._pickup_until = time.monotonic() + 1.4
                self._pickup_spoken = True
        self.was_drag = True
        now = time.monotonic()
        pointer_x = self.root.winfo_pointerx()
        elapsed = max(now - self._last_drag_event_at, 0.001)
        pointer_speed = (pointer_x - self._last_drag_pointer_x) / elapsed
        self.drag_target_tilt = max(-18.0, min(18.0, pointer_speed * 0.012))
        if pointer_x != self._last_drag_pointer_x:
            self._last_drag_motion_at = now
        self._last_drag_pointer_x = pointer_x
        self._last_drag_event_at = now
        self.x = pointer_x - self.drag_offset[0]
        self.y = self.root.winfo_pointery() - self.drag_offset[1]
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    def stop_drag(self, event):
        ignore_click = self._ignore_next_click
        if ignore_click:
            self._ignore_next_click = False
        was_drag = self.was_drag
        self.dragging = False
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = None
        if self.state == "held":
            self.state = self._post_drag_state()
        focus_widget = self._drag_focus_widget
        self._drag_focus_widget = None
        if focus_widget is not None:
            try:
                if focus_widget.winfo_exists():
                    focus_widget.focus_set()
            except tk.TclError:
                pass
        if ignore_click:
            return
        if was_drag:
            self._record_interaction()
            if self._pickup_spoken:
                delay = max(0, round((self._pickup_until - time.monotonic()) * 1000))
                self.root.after(delay, self._speak_drop)
        else:
            self._handle_simple_click()

    def _speak_drop(self):
        if self._interaction_speech_allowed():
            self._show_personality_line("drop", duration=2500)

    def _post_drag_state(self):
        if self.focus_mode == "focus":
            return "focused"
        if self.focus_mode == "break":
            return "sitting"
        return "walk"

    def _handle_simple_click(self):
        now = time.monotonic()
        self._click_timestamps = [
            timestamp for timestamp in self._click_timestamps
            if now - timestamp <= 3.0
        ]
        self._click_timestamps.append(now)
        self._record_interaction()
        if len(self._click_timestamps) >= 5:
            if self._pending_click_job is not None:
                self.root.after_cancel(self._pending_click_job)
                self._pending_click_job = None
            self._irritated_started_at = now
            self._irritated_until = now + VIDEO_REACTION_SECONDS
            if self.busy and not self.ai_request_active:
                self.hide_bubble()
            if self._interaction_speech_allowed():
                self._show_personality_line("rapid_click", duration=2500)
            return
        if self.busy and not self.ai_request_active:
            self.hide_bubble()
        if self._pending_click_job is not None:
            return
        self._pending_click_job = self.root.after(600, self._finish_simple_click)

    def _finish_simple_click(self):
        self._pending_click_job = None
        if not self._interaction_speech_allowed():
            return
        waking_up = self.state in ("sitting", "resting")
        self.state = "greeting"
        category = "wake" if waking_up else "click"
        if self._show_personality_line(category, duration=2500):
            self._schedule_pose_return(
                round(VIDEO_REACTION_SECONDS * 1000), "greeting"
            )

    def _handle_double_click(self):
        self._ignore_next_click = True
        self.root.after(1000, self._clear_double_click_guard)
        if self._pending_click_job is not None:
            self.root.after_cancel(self._pending_click_job)
            self._pending_click_job = None
        self._record_interaction()
        if not self._interaction_speech_allowed(allow_drag=True):
            return
        self.state = "celebrating"
        if self._show_personality_line("dance", duration=4000):
            self._schedule_pose_callback(
                4000, "celebrating", self.finish_celebration
            )

    def _clear_double_click_guard(self):
        self._ignore_next_click = False
