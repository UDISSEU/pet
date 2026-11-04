import random
import time
import tkinter as tk
from config import BASE_HEIGHT, VANISHING_ANIMATION_SECONDS, WIDTH


class WindowControllerMixin:
    def _set_nova_window_icon(self, window):
        """Give user-facing windows Nova's icon."""
        try:
            if self._window_icon is not None:
                window.iconphoto(False, self._window_icon)
        except tk.TclError:
            pass
        return window

    def set_window_height(self, new_height):
        old_bottom = self.y + self.cur_height
        self.cur_height = new_height
        max_y = max(0, self.screen_h - new_height)
        self.y = max(0, min(old_bottom - new_height, max_y))
        self._window_x = int(round(self.x))
        self._window_y = int(round(self.y))
        self.root.geometry(
            f"{WIDTH}x{new_height}+{self._window_x}+{self._window_y}"
        )

    def toggle_behind_mode(self):
        self.behind_mode = self.behind_var.get()
        if hasattr(self, "settings"):
            self.persist_preferences()
        try:
            if self.behind_mode:
                self.root.attributes("-topmost", False)
                self.root.lower()
            else:
                self._hidden = False
                self.root.attributes("-topmost", True)
                self.root.lift()
        except tk.TclError:
            pass

    def toggle_peekaboo(self):
        self.persist_preferences()
        if not self.peekaboo_var.get() and self._hidden:
            self._reappear()

    def toggle_auto_sit(self):
        self.persist_preferences()
        if not self.auto_sit_var.get() and self.state == "sitting":
            self._stand_up("Vou deixar as janelas em paz!")

    def is_covered(self):
        """Ela só é considerada 'coberta' quando não está por cima da pilha
        de janelas (modo atrás das janelas, ou escondida no peekaboo)."""
        if not (self.behind_mode or self._hidden):
            return False
        if not self.x11.ok:
            return False
        my_cx = self.x + WIDTH / 2
        my_cy = self.y + self.cur_height / 2
        for win in self.x11.get_open_windows(exclude_win_id=self.root.winfo_id()):
            if win["x"] <= my_cx <= win["x"] + win["w"] and win["y"] <= my_cy <= win["y"] + win["h"]:
                return True
        return False

    def peekaboo(self):
        if (self.peekaboo_var.get() and not self._is_quiet_time() and self.focus_mode == "idle"
                and not self.behind_mode and not self.dragging and not self.busy
                and not self.ai_request_active and self.state == "walk"
                and not self._hidden and self.settings.get("mode") != "quietinha"
                and self.is_covered() is False):
            self.state = "vanishing"
            self._vanishing_started_at = time.monotonic()
            self.root.after(
                round(VANISHING_ANIMATION_SECONDS * 1000),
                self._hide_after_vanishing,
            )
        self.root.after(random.randint(40000, 80000), self.peekaboo)

    def _hide_after_vanishing(self):
        if self._closing or self.state != "vanishing":
            return
        user_requested = getattr(self, "_user_requested_vanish", False)
        self._user_requested_vanish = False
        if (self._is_quiet_time() or self.focus_mode != "idle"
                or self.behind_mode or self.dragging or self.busy
                or self.ai_request_active or self.is_covered()
                or self.settings.get("mode") == "quietinha"
                or not user_requested and not self.peekaboo_var.get()):
            self.state = "walk"
            return
        self.state = "walk"
        self._hidden = True
        try:
            self.root.attributes("-topmost", False)
            self.root.lower()
        except tk.TclError:
            pass
        self.root.after(random.randint(3000, 7000), self._reappear)

    def _reappear(self):
        self._hidden = False
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except tk.TclError:
            pass
        if (self.auto_speech_var.get() and self.state == "walk"
                and self._can_speak_spontaneously() and self._spontaneous_ready()):
            self._show_personality_line(
                "peekaboo", duration=2500, spontaneous=True
            )

    def maybe_sit(self):
        if (self.auto_sit_var.get() and self._can_speak_spontaneously()
                and not self.stay_in_place_var.get()
                and self.state == "walk" and self.x11.ok
                and self._spontaneous_ready() and random.random() < 0.7):
            windows = self.x11.get_open_windows(exclude_win_id=self.root.winfo_id())
            if windows:
                target = random.choice(windows)
                max_offset = max(target["w"] - WIDTH, 0)
                self.x = target["x"] + random.randint(0, max_offset)
                self.y = target["y"] - BASE_HEIGHT + 20
                self.x = max(0, min(self.x, self.screen_w - WIDTH))
                self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

                self.state = "sitting"
                self.sit_win_id = target["id"]
                self._show_personality_line(
                    "sit_down", duration=2500, spontaneous=True
                )
                sit_time = random.randint(15000, 35000)
                self.root.after(sit_time, self._sit_timeout)
        self.root.after(random.randint(35000, 70000), self.maybe_sit)

    def _sit_timeout(self):
        if self.state == "sitting":
            self._stand_up("stand_timeout")

    def _stand_up(self, line):
        self.state = "walk"
        self.sit_win_id = None
        if line in ("stand_timeout", "stand_closed"):
            self._show_personality_line(line, duration=2200, spontaneous=True)
        else:
            self.show_bubble(line, duration=2200)
