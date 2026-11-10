import random
import time
from config import THUMBS_UP_ANIMATION_SECONDS, VANISHING_ANIMATION_SECONDS
from nova_ai.personality.speech import (
    can_speak_spontaneously,
    pick_line,
    record_spontaneous_speech,
)


class SpeechControllerMixin:
    def random_speech(self):
        if (self.auto_speech_var.get() and self.state == "walk"
                and self._can_speak_spontaneously()):
            self._show_personality_line("idle_chatter", duration=3500, spontaneous=True)
        interval = (90000, 150000) if self.settings["mode"] == "proativa" else (180000, 300000)
        self.root.after(random.randint(*interval), self.random_speech)

    def _can_speak_spontaneously(self, allow_focus=False):
        return (
            not self._closing
            and self.settings.get("mode") != "quietinha"
            and not self._is_quiet_time()
            and (
                self.focus_mode == "idle"
                or allow_focus and self.focus_mode in ("focus", "break")
            )
            and not self.busy
            and not self.dragging
            and not self.bubble_text
            and not self.ai_request_active
            and not self.is_covered()
        )

    def _speech_cooldown_seconds(self):
        """Keep unsolicited comments sparse; proactive mode remains configurable."""
        return 90 if self.settings.get("mode") == "proativa" else 180

    def _spontaneous_ready(self):
        return can_speak_spontaneously(cooldown=self._speech_cooldown_seconds())

    def _show_personality_line(
        self, category, duration=5000, spontaneous=False, allow_focus=False,
        bypass_cooldown=False, **context,
    ):
        if spontaneous:
            if (not self._can_speak_spontaneously(allow_focus=allow_focus)
                    or (not bypass_cooldown and not self._spontaneous_ready())):
                return False
        elif self._closing:
            return False
        line = pick_line(
            category,
            name=self.settings.get("user_name", ""),
            rng=random,
            history=self._speech_history,
            **context,
        )
        if spontaneous:
            record_spontaneous_speech()
        self.show_bubble(line, duration=duration)
        return True

    def _show_spontaneous_pose(
        self, category, state, duration=5000, bypass_cooldown=False, **context
    ):
        if (not self._can_speak_spontaneously()
                or (not bypass_cooldown and not self._spontaneous_ready())):
            return False
        self.state = state
        if not self._show_personality_line(
            category, duration, spontaneous=True,
            bypass_cooldown=bypass_cooldown, **context
        ):
            return False
        return True

    def _finish_temporary_pose(self, expected_state, final_state="walk"):
        if not self._closing and self.state == expected_state:
            self.state = final_state

    def _schedule_pose_callback(self, delay_ms, expected_state, callback):
        generation = self._state_generation
        return self.root.after(
            delay_ms,
            lambda: self._run_pose_callback(
                expected_state, generation, callback
            ),
        )

    def _run_pose_callback(self, expected_state, generation, callback):
        if (
            self._closing
            or self.state != expected_state
            or self._state_generation != generation
        ):
            return False
        callback()
        return True

    def _schedule_pose_return(self, delay_ms, expected_state, final_state="walk"):
        return self._schedule_pose_callback(
            delay_ms,
            expected_state,
            lambda: self._finish_temporary_pose(expected_state, final_state),
        )

    def _show_oops(self, duration=5000):
        if not self._interaction_speech_allowed():
            return False
        self.state = "curious"
        if not self._show_personality_line("oops", duration=duration):
            return False
        self._schedule_pose_callback(3500, "curious", self.finish_curious)
        return True

    def _interaction_speech_allowed(self, allow_drag=False):
        return (
            not self._closing
            and self.settings.get("mode") != "quietinha"
            and not self._is_quiet_time()
            and self.focus_mode == "idle"
            and not self.busy
            and (allow_drag or not self.dragging)
            and not self.ai_request_active
            and not self.is_covered()
        )

    def _handle_local_personality(self, category, animation):
        if not self._interaction_speech_allowed():
            return False
        state = {
            "wave": "greeting",
            "celebrate": "celebrating",
            "thumbs_up": "thumbs_up",
            "sleep": "sitting",
            "rest": "resting",
            "vanishing": "vanishing",
        }[animation]
        self.state = state
        if animation == "thumbs_up":
            self._thumbs_up_started_at = time.monotonic()
        if animation == "vanishing":
            self._vanishing_started_at = time.monotonic()
            self._user_requested_vanish = True
        line = self._show_personality_line(category, duration=5000)
        if animation == "vanishing":
            self._schedule_pose_callback(
                round(VANISHING_ANIMATION_SECONDS * 1000),
                "vanishing",
                self._hide_after_vanishing,
            )
        else:
            if animation == "thumbs_up":
                duration = round(THUMBS_UP_ANIMATION_SECONDS * 1000)
            elif animation == "celebrate":
                duration = 4000
            else:
                duration = 5000
            self._schedule_pose_return(duration, state)
        return line

    def show_bubble(self, text, duration=None):
        if self._dismiss_job:
            self.root.after_cancel(self._dismiss_job)
            self._dismiss_job = None
        self.bubble_text = text
        self.busy = True
        readable_duration = min(20000, max(3500, len(text.split()) * 300))
        if duration is None:
            duration = readable_duration
        elif duration < 999999:
            duration = max(duration, readable_duration)
        if duration < 999999:
            self._dismiss_job = self.root.after(duration, self.hide_bubble)

    def hide_bubble(self):
        self._dismiss_job = None
        self.bubble_text = None
        self.busy = False
        self._show_idea_icon = False
        if self.state == "thinking":
            self.state = "walk"

    def say_something(self):
        self._show_personality_line("idle_chatter", duration=3500)
