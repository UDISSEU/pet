#!/usr/bin/env python3
"""
Nova — mascote de desktop em pixel art com IA local (Ollama)
----------------------------------------------------
Personagem animada com vídeos de caminhada, aceno, descanso e sono.

Ela observa (sem mexer em nada) os apps que você tem aberto, comenta
quando percebe que você tá no YouTube, senta cansada em cima de
janelas abertas de vez em quando, balança feito num carro em
movimento quando você arrasta ela com o mouse, e levanta se a janela
em que estava sentada for fechada.

DEPENDÊNCIAS:
    pip install -r requirements.txt
    sudo apt install python3-tk

- Pillow e OpenCV: obrigatórios para exibir e decodificar os vídeos.
- python-xlib: opcional. Sem ela, ela ainda funciona (anda, fala,
  responde), só perde a transparência real, observar apps e sentar
  em janelas — cai tudo graciosamente sem travar.

Como rodar:
    python3 desktop_pet.py

Como usar:
    Clique e segure       -> pega ela, arrasta rápido pra ver o balanço "de carro"
    Soltar o clique         -> ela volta ao normal
    Clique simples (sem arrastar) -> fecha o balão de fala mais cedo
    Duplo clique             -> abre o claude.ai no navegador
    Clique direito             -> menu (perguntar / falar algo / esquecer conversa / fechar)
"""

import logging
import math
import queue
import random
import shlex
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox
from tkinter import ttk

from animation import load_video_frames
from autonomy import (
    is_quiet_now,
    find_installed_apps,
    load_settings,
    resolve_app_command,
    save_settings,
    valid_reminder_time,
)
from assistant_actions import current_date_answer, is_open_calendar_request
from calendar_view import open_calendar_window
from config import (
    APP_COMMENTS,
    BASE_HEIGHT,
    FONT_BUBBLE,
    GENERIC_COMMENTS,
    ICONS_DIR,
    LOGIC_STEP_MS,
    MAX_HISTORY_MESSAGES,
    SCALE,
    SCREEN_MARGIN,
    SIT_DOWN_LINES,
    SPEECH_LINES,
    STAND_CLOSED_LINES,
    STAND_TIMEOUT_LINES,
    TICK_MS,
    VIDEO_FRAME_INTERVAL_MS,
    VIDEO_REACTION_SECONDS,
    MOVEMENT_VIDEOS,
    WALK_ACCELERATION,
    WALK_DIRECTION_VECTORS,
    WALK_SPEED,
    WALK_DIRECTION_CHANGE_MAX_SECONDS,
    WALK_DIRECTION_CHANGE_MIN_SECONDS,
    WIDTH,
)
from ollama_client import ask_local_ai, load_history, save_history
from x11_helper import X11Helper

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    import sys
    print("Falta a biblioteca Pillow. Instale com:\n"
          "    pip install --break-system-packages Pillow", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Personagem
# ---------------------------------------------------------------------------
class DesktopPet:
    def __init__(self):
        self.history = load_history()
        self.settings = load_settings()
        self.x11 = X11Helper()
        self.shape_supported = None

        self.root = tk.Tk()
        self._closing = False
        self._ai_results = queue.Queue()
        self._last_render_key = None
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self._window_background = "#f4f4f4"
        self.root.configure(bg=self._window_background)
        try:
            self.root.wm_attributes("-type", "splash")
        except tk.TclError:
            pass

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self.x = float(random.randint(100, max(101, self.screen_w - 200)))
        self.y = float(self.screen_h - BASE_HEIGHT - SCREEN_MARGIN)
        self.cur_height = BASE_HEIGHT
        self.label = tk.Label(
            self.root, bd=0, highlightthickness=0, bg=self._window_background
        )
        self.label.pack(fill="both", expand=True)
        self._window_x = int(round(self.x))
        self._window_y = int(round(self.y))
        self.root.geometry(f"{WIDTH}x{self.cur_height}+{self._window_x}+{int(self.y)}")

        self.tk_image = None
        self.idea_icon = self._load_status_icon(ICONS_DIR / "icon de lampada.png")
        self._show_idea_icon = False
        self._thinking_started_at = 0.0

        self.walk_dx, self.walk_dy = random.choice(WALK_DIRECTION_VECTORS)
        self._walk_velocity_x = 0.0
        self._next_walk_direction_change_at = (
            time.monotonic()
            + random.uniform(
                WALK_DIRECTION_CHANGE_MIN_SECONDS,
                WALK_DIRECTION_CHANGE_MAX_SECONDS,
            )
        )
        self.step = 0
        self.animation_time_ms = 0.0
        self._logic_accumulator = 0.0
        self.bubble_text = None
        self.dragging = False
        self.was_drag = False
        self.drag_offset = (0, 0)
        self.state = "walk"  # walk | held | thinking | sitting
        self.busy = False
        self.sit_win_id = None
        self.behind_mode = False  # true = ela fica sempre atrás das janelas
        self.ai_request_active = False
        self._dismiss_job = None
        self._hidden = False
        self.video_frames = {
            name: load_video_frames(filename)
            for name, filename in MOVEMENT_VIDEOS.items()
        }
        self._video_frame_cache = {}
        self.drag_tilt = 0.0
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = None
        self._last_drag_event_at = 0.0
        self._last_drag_motion_at = 0.0
        self._irritated_until = 0.0
        self._irritated_started_at = 0.0

        self.label.bind("<Button-1>", self.start_drag)
        self.label.bind("<B1-Motion>", self.do_drag)
        self.label.bind("<ButtonRelease-1>", self.stop_drag)
        self.label.bind("<Double-Button-1>", self.ask_menu)
        self.label.bind("<Button-3>", self.show_menu)

        self.behind_var = tk.BooleanVar(value=self.settings.get("behind", False))
        self.stay_in_place_var = tk.BooleanVar(value=self.settings.get("stay_in_place", False))
        defaults = {
            "quietinha": (False, False, False, False),
            "companhia": (True, True, False, True),
            "proativa": (True, True, True, True),
        }[self.settings["mode"]]
        self.auto_speech_var = tk.BooleanVar(value=self.settings.get("auto_speech", defaults[0]))
        self.observe_apps_var = tk.BooleanVar(value=self.settings.get("observe_apps", defaults[1]))
        self.peekaboo_var = tk.BooleanVar(value=self.settings.get("peekaboo", defaults[2]))
        self.auto_sit_var = tk.BooleanVar(value=self.settings.get("auto_sit", defaults[3]))
        if self.behind_var.get():
            self.toggle_behind_mode()

        self._context_popup = None

        self.render_and_show()
        self._last_tick_at = time.monotonic()
        self._next_tick_at = self._last_tick_at + TICK_MS / 1000
        self.root.after(TICK_MS, self.tick)
        self.root.after(random.randint(6000, 12000), self.random_speech)
        self.root.after(random.randint(15000, 30000), self.observe_apps)
        self.root.after(random.randint(30000, 60000), self.peekaboo)
        self.root.after(random.randint(20000, 40000), self.maybe_sit)
        self.root.after(15000, self.check_reminders)

    # ---------- geometria ----------
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

    # ---------- reprodução dos movimentos em vídeo ----------
    @staticmethod
    def _load_status_icon(path):
        try:
            return Image.open(path).convert("RGBA")
        except OSError:
            return None

    def _video_for_current_pose(self, now=None):
        if self.state == "sitting":
            return "sleep"
        if self.state == "thinking":
            return "thinking"
        if self.state == "held":
            return "idle"
        if self.state == "walk":
            if self.stay_in_place_var.get():
                return "idle"
            if now is None:
                now = time.monotonic()
            if now < self._irritated_until:
                return "angry"
            if self.busy:
                return "wave"
            walk_velocity_x = getattr(self, "_walk_velocity_x", 0.0)
            direction = walk_velocity_x if abs(walk_velocity_x) > 0.5 else self.walk_dx
            return "walk_left" if direction < 0 else "walk_right"
        return "idle"

    def _current_video_frame(self, now=None):
        if now is None:
            now = time.monotonic()
        video = self._video_for_current_pose(now)
        frames = self.video_frames[video]
        if video == "angry":
            elapsed_ms = (now - self._irritated_started_at) * 1000
        elif video == "thinking":
            elapsed_ms = (now - self._thinking_started_at) * 1000
        else:
            elapsed_ms = self.animation_time_ms
        frame_index = int(elapsed_ms / VIDEO_FRAME_INTERVAL_MS) % len(frames)
        return video, frame_index, frames[frame_index]

    def render_frame(self):
        """Renderiza a personagem com o quadro atual do movimento em vídeo."""
        w, h = WIDTH * SCALE, self.cur_height * SCALE
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        bubble_h = 0
        if self.bubble_text and self.state != "thinking":
            draw = ImageDraw.Draw(img, "RGBA")
            bubble_h = self.draw_bubble(draw, self.bubble_text, w)

        _, _, sprite = self._current_video_frame()
        sprite = sprite.resize(
            (sprite.width * SCALE, sprite.height * SCALE),
            Image.Resampling.NEAREST,
        )
        if self.state == "held" and self.drag_tilt:
            sprite = sprite.rotate(
                self.drag_tilt,
                resample=Image.Resampling.NEAREST,
                center=(sprite.width / 2, sprite.height - 1),
            )
        # Renderiza em alta resolução e volta para o tamanho da janela com
        # NEAREST para conservar os blocos de pixel.
        # Pequeno movimento vertical para dar sensação de vida durante a caminhada.
        bob = 0
        if self.state == "walk" and not self.busy and not self.stay_in_place_var.get():
            bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        elif self.state == "held":
            bob = int(math.sin(self.animation_time_ms / 1000 * 5) * 2 * SCALE)

        x = int((w - sprite.width) / 2)
        y = int(h - sprite.height - 7 * SCALE - bob)
        if y < bubble_h:
            y = int(bubble_h)

        img.alpha_composite(sprite, (x, y))

        # A animação de pensamento já inclui o balão; a lâmpada acompanha
        # temporariamente a resposta da IA.
        status_icon = self.idea_icon if self._show_idea_icon else None
        if status_icon is not None:
            icon_size = 32 * SCALE
            status_icon = status_icon.copy()
            status_icon.thumbnail((icon_size, icon_size), Image.Resampling.LANCZOS)
            icon_x = min(w - status_icon.width - 4 * SCALE, x + sprite.width - status_icon.width // 2)
            icon_y = max(2 * SCALE, y + 8 * SCALE)
            img.alpha_composite(status_icon, (icon_x, icon_y))

        # O vídeo já contém a sombra de chão; o restante do canvas fica transparente.
        img = img.resize((WIDTH, self.cur_height), Image.Resampling.NEAREST)
        return img

    def draw_bubble(self, draw, text, canvas_w):
        max_text_w = canvas_w - 20 * SCALE
        lines = self._wrap_text(text, max_text_w)
        line_h = FONT_BUBBLE.size + 4 * SCALE
        text_h = line_h * len(lines)
        bubble_h = text_h + 20 * SCALE

        draw.rounded_rectangle([4 * SCALE, 2 * SCALE, canvas_w - 4 * SCALE, bubble_h],
                                radius=12 * SCALE, fill=(255, 255, 255, 235),
                                outline=(210, 195, 180, 255), width=int(1.2 * SCALE))
        cx = canvas_w / 2
        draw.polygon([cx - 8 * SCALE, bubble_h - 2, cx + 8 * SCALE, bubble_h - 2, cx, bubble_h + 10 * SCALE],
                     fill=(255, 255, 255, 235))

        y = 10 * SCALE
        for line in lines:
            wtxt = draw.textlength(line, font=FONT_BUBBLE)
            draw.text((cx - wtxt / 2, y), line, font=FONT_BUBBLE, fill=(50, 40, 30, 255))
            y += line_h
        return bubble_h + 10 * SCALE

    def _wrap_text(self, text, max_w):
        words = text.split()
        lines, cur = [], ""
        dummy = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(dummy)
        for word in words:
            trial = (cur + " " + word).strip()
            if d.textlength(trial, font=FONT_BUBBLE) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    def render_and_show(self):
        needed_h = self._needed_height()
        if needed_h != self.cur_height:
            self.set_window_height(needed_h)

        cache_key = self._video_frame_cache_key()
        cached_frame = self._video_frame_cache.get(cache_key) if cache_key is not None else None
        if cached_frame is None:
            frame = self.render_frame()
            self.tk_image = ImageTk.PhotoImage(frame)
            if cache_key is not None:
                self._video_frame_cache[cache_key] = (frame, self.tk_image)
        else:
            frame, self.tk_image = cached_frame
        self.label.configure(image=self.tk_image)
        self._last_render_key = self._render_state_key()

        self.shape_supported = False
        self.root.configure(bg=self._window_background)
        self.label.configure(bg=self._window_background)

    def _render_state_key(self):
        now = time.monotonic()
        video, frame_index, _ = self._current_video_frame(now)
        bob = 0
        if self.state == "walk" and not self.busy and not self.stay_in_place_var.get():
            bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        elif self.state == "held":
            bob = int(math.sin(self.animation_time_ms / 1000 * 5) * 2 * SCALE)
        return (
            self._needed_height(), self.state, self.bubble_text, self.busy,
            self.dragging, video, frame_index, bob, round(self.drag_tilt, 1),
            self._show_idea_icon,
        )

    def _video_frame_cache_key(self):
        if self.state != "walk" or self.busy or self.dragging or self.bubble_text:
            return None
        video, frame_index, _ = self._current_video_frame()
        bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        return video, frame_index, bob

    def _needed_height(self):
        if self.state == "thinking":
            return BASE_HEIGHT + 32
        if not self.bubble_text:
            return BASE_HEIGHT
        dummy = Image.new("RGBA", (WIDTH * SCALE, 10))
        d = ImageDraw.Draw(dummy)
        lines = self._wrap_text(self.bubble_text, WIDTH * SCALE - 20 * SCALE)
        line_h = FONT_BUBBLE.size + 4 * SCALE
        bubble_h = (line_h * len(lines) + 20 * SCALE + 10 * SCALE) / SCALE
        return int(BASE_HEIGHT + bubble_h)

    # ---------- laço principal ----------
    def tick(self):
        now = time.monotonic()
        if hasattr(self, "_ai_results"):
            self._drain_ai_results()
        elapsed = min(now - self._last_tick_at, 0.1)
        self._last_tick_at = now
        self.animation_time_ms += elapsed * 1000
        previous_step = self.step
        self._logic_accumulator += elapsed * 1000
        while self._logic_accumulator >= LOGIC_STEP_MS:
            self.step += 1
            self._logic_accumulator -= LOGIC_STEP_MS
        if self.dragging:
            if time.monotonic() - self._last_drag_motion_at > 0.12:
                self.drag_target_tilt = 0.0
            self.drag_tilt += (self.drag_target_tilt - self.drag_tilt) * 0.24
        else:
            self.drag_tilt = 0.0
            self.drag_target_tilt = 0.0

        can_walk = (
            self.state == "walk"
            and not self.dragging
            and not self.stay_in_place_var.get()
        )
        if can_walk:
            if not self.busy and now >= self._next_walk_direction_change_at:
                self._choose_walk_direction(now)

            target_velocity = 0.0 if self.busy else self.walk_dx * WALK_SPEED
            velocity_change = WALK_ACCELERATION * elapsed
            velocity_delta = target_velocity - self._walk_velocity_x
            self._walk_velocity_x += max(
                -velocity_change, min(velocity_change, velocity_delta)
            )
            next_x = self.x + self._walk_velocity_x * elapsed
            next_y = self.y + self.walk_dy * WALK_SPEED * elapsed
            max_x = max(0, self.screen_w - WIDTH)
            max_y = max(0, self.screen_h - self.cur_height)

            hit_horizontal_boundary = next_x < 0 or next_x > max_x
            if hit_horizontal_boundary:
                self.walk_dx *= -1
                self._walk_velocity_x = 0.0
                next_x = max(0, min(next_x, max_x))
            if next_y < 0 or next_y > max_y:
                self.walk_dy *= -1
                next_y = max(0, min(next_y, max_y))

            self.x = next_x
            self.y = next_y
            window_x = int(round(self.x))
            window_y = int(round(self.y))
            if window_x != self._window_x or window_y != self._window_y:
                self._window_x = window_x
                self._window_y = window_y
                self.root.geometry(f"+{window_x}+{window_y}")
            if hit_horizontal_boundary:
                self._irritated_started_at = now
                self._irritated_until = now + VIDEO_REACTION_SECONDS
        else:
            self._walk_velocity_x = 0.0

        if self.state == "sitting" and self.sit_win_id is not None:
            if not self.x11.window_exists(self.sit_win_id):
                self._stand_up(random.choice(STAND_CLOSED_LINES))

        if self.behind_mode and self.step // 50 > previous_step // 50:
            try:
                self.root.lower()
            except tk.TclError:
                pass

        if hasattr(self, "_last_render_key") and self._render_state_key() != self._last_render_key:
            self.render_and_show()
        self._next_tick_at += TICK_MS / 1000
        schedule_now = time.monotonic()
        while self._next_tick_at <= schedule_now:
            self._next_tick_at += TICK_MS / 1000
        delay = max(1, round((self._next_tick_at - schedule_now) * 1000))
        self.root.after(delay, self.tick)

    def _choose_walk_direction(self, now=None):
        directions = [
            direction
            for direction in WALK_DIRECTION_VECTORS
            if direction != (self.walk_dx, self.walk_dy)
        ]
        self.walk_dx, self.walk_dy = random.choice(directions)
        if now is None:
            now = time.monotonic()
        self._next_walk_direction_change_at = now + random.uniform(
            WALK_DIRECTION_CHANGE_MIN_SECONDS,
            WALK_DIRECTION_CHANGE_MAX_SECONDS,
        )

    def random_speech(self):
        if (self.auto_speech_var.get() and not self._is_quiet_time()
                and not self.busy and not self.is_covered()):
            self.show_bubble(random.choice(SPEECH_LINES), duration=3000)
        interval = (30000, 60000) if self.settings["mode"] == "proativa" else (90000, 150000)
        self.root.after(random.randint(*interval), self.random_speech)

    def _is_quiet_time(self):
        return is_quiet_now(self.settings.get("quiet_start"), self.settings.get("quiet_end"))

    # ---------- observar apps abertos ----------
    def observe_apps(self):
        if (self.observe_apps_var.get() and not self._is_quiet_time() and not self.busy and self.x11.ok
            and self.state != "sitting" and not self.is_covered()):
            info = self.x11.get_active_window_info()
            if info:
                klass, name = info
                haystack = f"{klass} {name}".lower()
                comment = None
                for key, options in APP_COMMENTS.items():
                    if key in haystack:
                        comment = random.choice(options)
                        break
                if comment is None and random.random() < 0.4:
                    comment = random.choice(GENERIC_COMMENTS)
                if comment:
                    self.show_bubble(comment, duration=2800)
        interval = (45000, 90000) if self.settings["mode"] == "proativa" else (90000, 180000)
        self.root.after(random.randint(*interval), self.observe_apps)

    # ---------- modo permanente "atrás das janelas" ----------
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

    # ---------- sumir atrás das janelas (peekaboo temporário) ----------
    def peekaboo(self):
        if (self.peekaboo_var.get() and not self._is_quiet_time() and not self.behind_mode and not self.dragging and not self.busy
                and not self._hidden and self.state != "sitting"):
            self._hidden = True
            try:
                self.root.attributes("-topmost", False)
                self.root.lower()
            except tk.TclError:
                pass
            self.root.after(random.randint(3000, 7000), self._reappear)
        self.root.after(random.randint(40000, 80000), self.peekaboo)

    def _reappear(self):
        self._hidden = False
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except tk.TclError:
            pass
        if self.auto_speech_var.get() and not self.busy and random.random() < 0.5:
            self.show_bubble("Cadê eu? Ah, aqui!", duration=2200)

    # ---------- sentar cansada em cima de uma janela ----------
    def maybe_sit(self):
        if (self.auto_sit_var.get() and not self._is_quiet_time() and not self.stay_in_place_var.get()
                and not self.dragging and not self.busy and self.state == "walk"
                and self.x11.ok and random.random() < 0.7):
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
                self.show_bubble(random.choice(SIT_DOWN_LINES), duration=2500)
                sit_time = random.randint(15000, 35000)
                self.root.after(sit_time, self._sit_timeout)
        self.root.after(random.randint(35000, 70000), self.maybe_sit)

    def _sit_timeout(self):
        if self.state == "sitting":
            self._stand_up(random.choice(STAND_TIMEOUT_LINES))

    def _stand_up(self, line):
        self.state = "walk"
        self.sit_win_id = None
        self.show_bubble(line, duration=2200)

    # ---------- balão de fala ----------
    def show_bubble(self, text, duration=None):
        if self._dismiss_job:
            self.root.after_cancel(self._dismiss_job)
            self._dismiss_job = None
        self.bubble_text = text
        self.busy = True
        if duration is None:
            words = max(len(text.split()), 1)
            duration = min(max(4000, words * 350), 20000)
        if duration < 999999:
            self._dismiss_job = self.root.after(duration, self.hide_bubble)

    def hide_bubble(self):
        self._dismiss_job = None
        self.bubble_text = None
        self.busy = False
        self._show_idea_icon = False
        if self.state == "thinking":
            self.state = "walk"

    # ---------- interação com o mouse ----------
    def start_drag(self, event):
        self.dragging = True
        self.was_drag = False
        self.drag_tilt = 0.0
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = self.root.winfo_pointerx()
        self._last_drag_event_at = time.monotonic()
        self._last_drag_motion_at = self._last_drag_event_at
        if self.state == "sitting":
            self.sit_win_id = None
        self.state = "held"
        self.drag_offset = (event.x, event.y)

    def do_drag(self, event):
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
        self.dragging = False
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = None
        self.state = "walk"
        if not self.was_drag and self.bubble_text:
            self.hide_bubble()

    def say_something(self):
        self.show_bubble(random.choice(SPEECH_LINES), duration=3000)

    def open_chat(self, event=None):
        webbrowser.open("https://claude.ai/new")

    def show_menu(self, event):
        if self._context_popup is not None:
            try:
                self._context_popup.destroy()
            except tk.TclError:
                pass

        popup = tk.Toplevel(self.root)
        self._context_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#D8DEEA")
        popup.bind("<Escape>", lambda _event: popup.destroy())
        popup.bind("<FocusOut>", lambda _event: popup.after_idle(
            lambda: popup.destroy() if popup.winfo_exists() and
            popup.focus_displayof() is None else None
        ))

        panel = tk.Frame(popup, bg="#F5F6FA", padx=8, pady=8,
                         highlightthickness=1, highlightbackground="#D8DEEA")
        panel.pack(fill="both", expand=True)
        title_bar = tk.Frame(panel, bg="#F5F6FA")
        title_bar.pack(fill="x", padx=4, pady=(1, 5))
        title_label = tk.Label(
            title_bar, text="Nova", font=("TkDefaultFont", 10, "bold"),
            fg="#202B45", bg="#F5F6FA", anchor="w", cursor="fleur",
        )
        title_label.pack(side="left", fill="x", expand=True, padx=3, pady=3)
        tk.Button(
            title_bar, text="×", command=lambda: popup.destroy(),
            relief="flat", bd=0, padx=7, pady=1, cursor="hand2",
            font=("TkDefaultFont", 12, "bold"), fg="#68738A",
            bg="#F5F6FA", activebackground="#E7EAF1",
        ).pack(side="right")

        drag_offset = {"x": 0, "y": 0}

        def start_popup_drag(drag_event):
            drag_offset["x"] = drag_event.x_root - popup.winfo_x()
            drag_offset["y"] = drag_event.y_root - popup.winfo_y()

        def move_popup(drag_event):
            screen_width = popup.winfo_screenwidth()
            screen_height = popup.winfo_screenheight()
            x = drag_event.x_root - drag_offset["x"]
            y = drag_event.y_root - drag_offset["y"]
            x = max(0, min(x, screen_width - popup.winfo_width()))
            y = max(0, min(y, screen_height - popup.winfo_height()))
            popup.geometry(f"+{x}+{y}")

        for drag_handle in (title_bar, title_label):
            drag_handle.bind("<ButtonPress-1>", start_popup_drag)
            drag_handle.bind("<B1-Motion>", move_popup)

        def close_popup():
            if popup.winfo_exists():
                popup.destroy()

        def action_button(label, command, primary=False):
            bg = "#5269C8" if primary else "#FFFFFF"
            fg = "#FFFFFF" if primary else "#28334D"
            hover = "#4056B2" if primary else "#E9EDF5"
            button = tk.Button(
                panel, text=label, anchor="w", command=lambda: (close_popup(), command()),
                relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
                bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                font=("TkDefaultFont", 9, "bold" if primary else "normal"),
            )
            button.pack(fill="x", pady=2)
            return button

        action_button("✦  Perguntar", self.ask_menu, primary=True)
        action_button("▦  Calendário", self.show_calendar)
        action_button("⚙  Autonomia e preferências", self.open_autonomy_settings)

        more = tk.Frame(panel, bg="#F5F6FA")
        expanded = {"value": False}

        def toggle_more():
            if expanded["value"]:
                more.pack_forget()
                more_button.configure(text="Mostrar mais  ▾")
            else:
                more.pack(fill="x", pady=(5, 0))
                more_button.configure(text="Mostrar menos  ▴")
            expanded["value"] = not expanded["value"]

        more_button = tk.Button(
            panel, text="Mostrar mais  ▾", command=toggle_more, anchor="w",
            relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
            bg="#E9EDF5", fg="#536078", activebackground="#DDE3EF",
        )
        more_button.pack(fill="x", pady=(5, 0))

        def more_action(label, command):
            tk.Button(
                more, text=label, anchor="w",
                command=lambda: (close_popup(), command()), relief="flat", bd=0,
                padx=10, pady=6, cursor="hand2", bg="#FFFFFF", fg="#28334D",
                activebackground="#E9EDF5",
            ).pack(fill="x", pady=2)

        more_action("Falar algo", self.say_something)
        more_action("Abrir Claude no navegador", self.open_chat)
        tk.Frame(more, height=1, bg="#D8DEEA").pack(fill="x", pady=5)

        def check_option(label, variable, command=None):
            tk.Checkbutton(
                more, text=label, variable=variable, command=command,
                anchor="w", padx=8, pady=4, bg="#F5F6FA", fg="#39445C",
                activebackground="#F5F6FA", selectcolor="#FFFFFF",
                font=("TkDefaultFont", 9),
            ).pack(fill="x")

        check_option("Andar atrás das janelas", self.behind_var, self.toggle_behind_mode)
        check_option("Ficar parada aqui", self.stay_in_place_var, self.persist_preferences)
        check_option("Falas espontâneas", self.auto_speech_var, self.persist_preferences)
        check_option("Comentários sobre apps", self.observe_apps_var, self.persist_preferences)
        check_option("Sumir atrás das janelas", self.peekaboo_var, self.toggle_peekaboo)
        check_option("Sentar em janelas", self.auto_sit_var, self.toggle_auto_sit)
        more_action("Esquecer conversa", self.forget_history)
        more_action("Apagar memórias salvas", self.forget_memories)
        more_action("Fechar Nova", self.close_app)

        popup.update_idletasks()
        screen_w = popup.winfo_screenwidth()
        screen_h = popup.winfo_screenheight()
        x = min(event.x_root, max(0, screen_w - popup.winfo_reqwidth()))
        y = min(event.y_root, max(0, screen_h - popup.winfo_reqheight()))
        popup.geometry(f"+{x}+{y}")
        popup.focus_force()
        try:
            popup.attributes("-alpha", 0.0)

            def fade_in(step=0):
                if not popup.winfo_exists():
                    return
                alpha = min(1.0, (step + 1) / 7)
                try:
                    popup.attributes("-alpha", alpha)
                except tk.TclError:
                    return
                if alpha < 1.0:
                    popup.after(14, lambda: fade_in(step + 1))

            popup.after(14, fade_in)
        except tk.TclError:
            # Alguns gerenciadores de janelas não oferecem transparência gradual.
            pass
        return "break"

    def show_calendar(self):
        open_calendar_window(self.root)

    def persist_preferences(self):
        self.settings.update(
            mode=self.settings.get("mode", "companhia"),
            behind=self.behind_var.get(),
            stay_in_place=self.stay_in_place_var.get(),
            auto_speech=self.auto_speech_var.get(),
            observe_apps=self.observe_apps_var.get(),
            peekaboo=self.peekaboo_var.get(),
            auto_sit=self.auto_sit_var.get(),
        )
        save_settings(self.settings)

    def open_autonomy_settings(self):
        window = tk.Toplevel(self.root)
        window.title("Autonomia da Nova")
        window.transient(self.root)
        window.attributes("-topmost", True)
        window.geometry("620x640")
        window.minsize(560, 580)
        window.configure(bg="#E3E8F0")

        style = ttk.Style(window)
        style.configure("Autonomy.TFrame", background="#E3E8F0")
        style.configure("Card.TFrame", background="#F5F7FA")
        style.configure("Title.TLabel", background="#E3E8F0", foreground="#202B45", font=("TkDefaultFont", 16, "bold"))
        style.configure("Subtitle.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("CardTitle.TLabel", background="#F5F7FA", foreground="#26344A", font=("TkDefaultFont", 10, "bold"))
        style.configure("Hint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("PageHint.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("ModeHint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 8))
        style.configure("Primary.TButton", padding=(14, 8), font=("TkDefaultFont", 9, "bold"))
        style.configure("Secondary.TButton", padding=(12, 8))
        style.configure("Autonomy.TEntry", fieldbackground="#EDF0F5", foreground="#26344A", padding=4)
        style.configure("TNotebook", background="#E3E8F0", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("TkDefaultFont", 9))

        outer = ttk.Frame(window, style="Autonomy.TFrame", padding=(22, 18, 22, 14))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Autonomia da Nova", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Ajuste o ritmo, a rotina e o que ela pode lembrar ou fazer.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 14))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        behavior_tab = ttk.Frame(notebook, style="Autonomy.TFrame", padding=16)
        memory_tab = ttk.Frame(notebook, style="Autonomy.TFrame", padding=16)
        reminder_tab = ttk.Frame(notebook, style="Autonomy.TFrame", padding=16)
        apps_tab = ttk.Frame(notebook, style="Autonomy.TFrame", padding=16)
        notebook.add(behavior_tab, text="Comportamento")
        notebook.add(memory_tab, text="Memórias")
        notebook.add(reminder_tab, text="Lembretes")
        notebook.add(apps_tab, text="Aplicativos")

        mode = tk.StringVar(value=self.settings.get("mode", "companhia"))
        quiet_start = tk.StringVar(value=self.settings.get("quiet_start", "22:00"))
        quiet_end = tk.StringVar(value=self.settings.get("quiet_end", "08:00"))
        speech = tk.BooleanVar(value=self.auto_speech_var.get())
        observe = tk.BooleanVar(value=self.observe_apps_var.get())
        auto_sit = tk.BooleanVar(value=self.auto_sit_var.get())
        peekaboo = tk.BooleanVar(value=self.peekaboo_var.get())
        memory_items = list(self.settings.get("memories", []))
        reminder_items = list(self.settings.get("reminders", []))
        app_items = list(self.settings.get("apps", []))

        def card(parent, title, hint=None):
            frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
            frame.pack(fill="x", pady=(0, 12))
            ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=500).pack(anchor="w", pady=(3, 8))
            return frame

        mode_card = card(behavior_tab, "Como a Nova deve se comportar?", "Você pode personalizar as opções abaixo depois de escolher um modo.")
        mode_row = ttk.Frame(mode_card, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(2, 0))
        modes = (
            ("quietinha", "Quietinha", "Fica mais discreta"),
            ("companhia", "Companhia", "Interage de vez em quando"),
            ("proativa", "Proativa", "Toma mais iniciativas"),
        )
        def choose_mode(value):
            presets = {
                "quietinha": (False, False, False, False),
                "companhia": (True, True, True, False),
                "proativa": (True, True, True, True),
            }
            speech.set(presets[value][0])
            observe.set(presets[value][1])
            auto_sit.set(presets[value][2])
            peekaboo.set(presets[value][3])

        for column, (value, label, description) in enumerate(modes):
            option = ttk.Frame(mode_row, style="Card.TFrame", padding=(0, 2))
            option.grid(row=0, column=column, sticky="w", padx=(0, 18))
            ttk.Radiobutton(
                option, text=label, value=value, variable=mode,
                command=lambda selected=value: choose_mode(selected),
            ).pack(anchor="w")
            ttk.Label(option, text=description, style="ModeHint.TLabel").pack(anchor="w", padx=(22, 0))

        behavior_card = card(behavior_tab, "Iniciativas", "As iniciativas automáticas respeitam o horário de silêncio.")
        ttk.Checkbutton(behavior_card, text="Falas espontâneas", variable=speech).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Comentários sobre o app ativo", variable=observe).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Sentar em janelas", variable=auto_sit).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Brincar de sumir atrás das janelas", variable=peekaboo).pack(anchor="w", pady=3)

        quiet_card = card(behavior_tab, "Horário de silêncio", "A Nova pausa falas, observações e lembretes durante esse período.")
        quiet_row = ttk.Frame(quiet_card, style="Card.TFrame")
        quiet_row.pack(anchor="w")
        ttk.Label(quiet_row, text="Das").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_start, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=(8, 16), ipady=4)
        ttk.Label(quiet_row, text="às").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_end, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=8, ipady=4)
        ttk.Label(quiet_row, text="HH:MM").pack(side="left", padx=(4, 0))

        def setup_list(parent, items, format_item, empty_text):
            ttk.Label(parent, text=empty_text, style="PageHint.TLabel").pack(anchor="w", pady=(0, 8))
            list_frame = ttk.Frame(parent, style="Card.TFrame", padding=1)
            list_frame.pack(fill="both", expand=True)
            listing = tk.Listbox(
                list_frame, height=10, activestyle="none", relief="flat", bd=0,
                highlightthickness=0, selectforeground="#202B45",
                bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 10),
                selectbackground="#C7D2EE", selectmode="browse",
            )
            listing.pack(fill="both", expand=True, padx=8, pady=7)
            def refresh():
                listing.delete(0, "end")
                for item in items:
                    listing.insert("end", format_item(item))
            def remove_selected():
                selected = listing.curselection()
                if selected:
                    del items[selected[0]]
                    refresh()
            refresh()
            return listing, refresh, remove_selected

        memory_card = card(memory_tab, "O que a Nova deve lembrar?", "Só use informações que você queira manter. Elas entram no contexto da IA local.")
        memory_entry = tk.StringVar()
        memory_form = ttk.Frame(memory_card, style="Card.TFrame")
        memory_form.pack(fill="x")
        memory_input = ttk.Entry(memory_form, textvariable=memory_entry, style="Autonomy.TEntry")
        memory_input.pack(side="left", fill="x", expand=True, ipady=5)
        memory_list, refresh_memories, remove_memory = setup_list(
            memory_tab, memory_items, lambda item: item,
            "Suas memórias ficam neste computador e você pode removê-las quando quiser.",
        )
        def add_memory():
            value = memory_entry.get().strip()
            if value:
                memory_items.append(value)
                memory_entry.set("")
                refresh_memories()
        ttk.Button(memory_form, text="Adicionar", style="Primary.TButton", command=add_memory).pack(side="left", padx=(8, 0))
        memory_input.bind("<Return>", lambda _event: add_memory())
        ttk.Button(memory_tab, text="Remover selecionada", style="Secondary.TButton", command=remove_memory).pack(anchor="e", pady=(10, 0))

        reminder_card = card(reminder_tab, "Criar lembrete", "A data e hora seguem o relógio local deste computador.")
        reminder_form = ttk.Frame(reminder_card, style="Card.TFrame")
        reminder_form.pack(fill="x")
        reminder_date = tk.StringVar()
        reminder_time = tk.StringVar()
        reminder_text = tk.StringVar()
        ttk.Label(reminder_form, text="Data").grid(row=0, column=0, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_date, width=14, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Hora").grid(row=0, column=1, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_time, width=9, style="Autonomy.TEntry").grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Lembrete").grid(row=0, column=2, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_text, style="Autonomy.TEntry").grid(row=1, column=2, sticky="ew", pady=(3, 8), ipady=4)
        reminder_form.columnconfigure(2, weight=1)
        reminder_list, refresh_reminders, remove_reminder = setup_list(
            reminder_tab, reminder_items,
            lambda item: f"{item.get('at', '')[:16].replace('T', ' ')}   ·   {item.get('text', '')}",
            "Quando vencer, a Nova mostra o lembrete em um balão.",
        )
        def add_reminder():
            value = f"{reminder_date.get().strip()}T{reminder_time.get().strip()}"
            parsed = valid_reminder_time(value)
            text = reminder_text.get().strip()
            if not parsed or not text:
                messagebox.showerror("Confira o lembrete", "Informe uma data AAAA-MM-DD, horário HH:MM e texto.", parent=window)
                return
            reminder_items.append({"at": parsed.isoformat(timespec="minutes"), "text": text, "done": False})
            reminder_date.set("")
            reminder_time.set("")
            reminder_text.set("")
            refresh_reminders()
        ttk.Button(reminder_form, text="Adicionar", style="Primary.TButton", command=add_reminder).grid(row=2, column=0, columnspan=3, sticky="e")
        ttk.Button(reminder_tab, text="Remover selecionado", style="Secondary.TButton", command=remove_reminder).pack(anchor="e", pady=(10, 0))

        app_card = card(
            apps_tab,
            "Permitir que a Nova abra um app",
            "Cadastre apenas apps que você reconhece. A Nova pede confirmação antes de abrir.",
        )
        picker_row = ttk.Frame(app_card, style="Card.TFrame")
        picker_row.pack(fill="x", pady=(0, 10))
        app_picker_button = ttk.Button(
            picker_row, text="Buscar app instalado…", style="Secondary.TButton"
        )
        app_picker_button.pack(side="left")
        ttk.Label(
            picker_row, text="ou preencha os dados manualmente abaixo",
            style="Hint.TLabel",
        ).pack(side="left", padx=(10, 0))
        app_form = ttk.Frame(app_card, style="Card.TFrame")
        app_form.pack(fill="x")
        app_name = tk.StringVar()
        app_command = tk.StringVar()
        ttk.Label(app_form, text="Nome").grid(row=0, column=0, sticky="w")
        ttk.Entry(app_form, textvariable=app_name, width=18, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 7), ipady=4)
        ttk.Label(app_form, text="Comando executável").grid(row=0, column=1, sticky="w")
        ttk.Entry(app_form, textvariable=app_command, style="Autonomy.TEntry").grid(row=1, column=1, sticky="ew", pady=(3, 7), ipady=4)
        app_form.columnconfigure(1, weight=1)
        ttk.Label(
            app_form,
            text="Exemplos: firefox --new-window  ·  code .  ·  /usr/bin/gimp",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        app_error = tk.StringVar()
        app_error_label = ttk.Label(
            app_form, textvariable=app_error, foreground="#B42318",
            background="#F5F7FA", wraplength=440,
        )
        app_error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))
        app_buttons = ttk.Frame(app_form, style="Card.TFrame")
        app_buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        editing_app = {"index": None}
        app_list, refresh_apps, remove_app = setup_list(
            apps_tab, app_items,
            lambda item: f"{item.get('name', '')}   ·   {item.get('command', '')}",
            "Selecione um app para editar ou remover. Testar comando abre o app imediatamente.",
        )
        def clear_app_form():
            editing_app["index"] = None
            app_name.set("")
            app_command.set("")
            app_error.set("")
            app_error_label.configure(foreground="#B42318")
            save_app_button.configure(text="Adicionar app")
            app_list.selection_clear(0, "end")

        def select_app(_event=None):
            selected = app_list.curselection()
            if not selected:
                return
            index = selected[0]
            editing_app["index"] = index
            app_name.set(app_items[index]["name"])
            app_command.set(app_items[index]["command"])
            app_error.set("")
            save_app_button.configure(text="Salvar edição")

        def open_app_picker():
            picker = tk.Toplevel(window)
            picker.title("Selecionar aplicativo instalado")
            picker.transient(window)
            picker.attributes("-topmost", True)
            picker.geometry("460x500")
            picker.minsize(380, 360)
            picker.configure(bg="#E3E8F0")
            content = ttk.Frame(picker, style="Autonomy.TFrame", padding=18)
            content.pack(fill="both", expand=True)
            ttk.Label(content, text="Selecionar aplicativo", style="Title.TLabel").pack(anchor="w")
            ttk.Label(
                content,
                text="Pesquise entre os aplicativos instalados neste computador.",
                style="Subtitle.TLabel",
            ).pack(anchor="w", pady=(3, 12))
            query = tk.StringVar()
            search_entry = ttk.Entry(content, textvariable=query, style="Autonomy.TEntry")
            search_entry.pack(fill="x", ipady=5, pady=(0, 10))
            result_frame = ttk.Frame(content, style="Card.TFrame", padding=1)
            result_frame.pack(fill="both", expand=True)
            result_list = tk.Listbox(
                result_frame, activestyle="none", relief="flat", bd=0,
                highlightthickness=0, selectforeground="#202B45",
                bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 10),
                selectbackground="#C7D2EE", selectmode="browse",
            )
            scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=result_list.yview)
            result_list.configure(yscrollcommand=scrollbar.set)
            result_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=7)
            scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=7)
            feedback = tk.StringVar()
            ttk.Label(content, textvariable=feedback, style="PageHint.TLabel").pack(anchor="w", pady=(8, 0))
            installed_apps = find_installed_apps()
            visible_apps = []

            def filter_results(*_args):
                needle = query.get().casefold().strip()
                visible_apps.clear()
                visible_apps.extend(
                    item for item in installed_apps
                    if not needle or needle in f"{item['name']} {item['generic_name']}".casefold()
                )
                result_list.delete(0, "end")
                for item in visible_apps:
                    suffix = f"  ·  {item['generic_name']}" if item["generic_name"] else ""
                    result_list.insert("end", item["name"] + suffix)
                if visible_apps:
                    feedback.set(f"{len(visible_apps)} aplicativo(s) encontrado(s).")
                else:
                    feedback.set("Nenhum app encontrado. Você ainda pode preencher o formulário manualmente.")

            def use_selected_app(_event=None):
                selected = result_list.curselection()
                if not selected:
                    feedback.set("Selecione um aplicativo da lista.")
                    return
                app = visible_apps[selected[0]]
                app_name.set(app["name"])
                app_command.set(app["command"])
                app_error.set("")
                editing_app["index"] = None
                save_app_button.configure(text="Adicionar app")
                app_list.selection_clear(0, "end")
                picker.destroy()

            query.trace_add("write", filter_results)
            filter_results()
            result_list.bind("<Double-Button-1>", use_selected_app)
            picker_buttons = ttk.Frame(content, style="Autonomy.TFrame")
            picker_buttons.pack(fill="x", pady=(12, 0))
            ttk.Button(picker_buttons, text="Cancelar", style="Secondary.TButton", command=picker.destroy).pack(side="right")
            ttk.Button(picker_buttons, text="Usar selecionado", style="Primary.TButton", command=use_selected_app).pack(side="right", padx=(0, 8))
            picker.bind("<Return>", use_selected_app)
            picker.bind("<Escape>", lambda _event: picker.destroy())
            picker.grab_set()
            search_entry.focus_set()

        app_picker_button.configure(command=open_app_picker)

        def validate_app_form():
            name = app_name.get().strip()
            command = app_command.get().strip()
            try:
                argv = resolve_app_command(command)
            except ValueError as exc:
                app_error_label.configure(foreground="#B42318")
                app_error.set(str(exc))
                return None
            if not name:
                app_error_label.configure(foreground="#B42318")
                app_error.set("Informe um nome para identificar este aplicativo.")
                return None
            for index, item in enumerate(app_items):
                if index != editing_app["index"] and item["name"].casefold() == name.casefold():
                    app_error_label.configure(foreground="#B42318")
                    app_error.set("Já existe um app com esse nome. Escolha outro nome.")
                    return None
            app_error_label.configure(foreground="#B42318")
            app_error.set("")
            return name, command, argv

        def save_app():
            values = validate_app_form()
            if not values:
                return
            name, command, _argv = values
            index = editing_app["index"]
            if index is None:
                app_items.append({"name": name, "command": command})
            else:
                app_items[index] = {"name": name, "command": command}
            refresh_apps()
            clear_app_form()

        def test_app_command():
            values = validate_app_form()
            if not values:
                return
            name, _command, argv = values
            try:
                subprocess.Popen(argv, close_fds=True)
            except (OSError, ValueError) as exc:
                app_error_label.configure(foreground="#B42318")
                app_error.set(f"Não consegui iniciar {name}: {exc}")
                return
            app_error_label.configure(foreground="#287247")
            app_error.set(f"Comando enviado ao sistema para abrir {name}.")

        def remove_selected_app():
            remove_app()
            clear_app_form()

        app_list.bind("<<ListboxSelect>>", select_app)
        save_app_button = ttk.Button(app_buttons, text="Adicionar app", style="Primary.TButton", command=save_app)
        save_app_button.pack(side="right")
        ttk.Button(app_buttons, text="Testar comando", style="Secondary.TButton", command=test_app_command).pack(side="right", padx=(0, 8))
        ttk.Button(app_buttons, text="Novo app", style="Secondary.TButton", command=clear_app_form).pack(side="left")
        ttk.Button(apps_tab, text="Remover selecionado", style="Secondary.TButton", command=remove_selected_app).pack(anchor="e", pady=(10, 0))

        footer = ttk.Frame(outer, style="Autonomy.TFrame")
        footer.pack(fill="x", pady=(14, 0))

        def save_and_close():
            try:
                for value in (quiet_start.get(), quiet_end.get()):
                    time.strptime(value, "%H:%M")
            except ValueError:
                notebook.select(behavior_tab)
                messagebox.showerror("Horário inválido", "Use HH:MM nos horários de silêncio.", parent=window)
                return
            updated = dict(self.settings)
            updated.update(
                mode=mode.get(), quiet_start=quiet_start.get(), quiet_end=quiet_end.get(),
                memories=memory_items, reminders=reminder_items, apps=app_items,
                auto_speech=speech.get(), observe_apps=observe.get(), auto_sit=auto_sit.get(),
                peekaboo=peekaboo.get(),
            )
            if not save_settings(updated):
                messagebox.showerror("Erro ao salvar", "Não consegui salvar as preferências.", parent=window)
                return
            self.settings = updated
            self.auto_speech_var.set(speech.get())
            self.observe_apps_var.set(observe.get())
            self.auto_sit_var.set(auto_sit.get())
            self.peekaboo_var.set(peekaboo.get())
            window.destroy()
            self.show_bubble("Preferências atualizadas.", duration=2500)

        ttk.Button(footer, text="Cancelar", style="Secondary.TButton", command=window.destroy).pack(side="right")
        ttk.Button(footer, text="Salvar alterações", style="Primary.TButton", command=save_and_close).pack(side="right", padx=(0, 8))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Control-Return>", lambda _event: save_and_close())

    def forget_memories(self):
        if messagebox.askyesno("Apagar memórias", "Apagar todas as memórias que você salvou?", parent=self.root):
            self.settings["memories"] = []
            save_settings(self.settings)
            self.show_bubble("Apaguei as memórias salvas.", duration=2500)

    def check_reminders(self):
        if self._closing:
            return
        now = time.time()
        due = []
        for item in self.settings.get("reminders", []):
            parsed = valid_reminder_time(item.get("at")) if isinstance(item, dict) else None
            if parsed and not item.get("done") and parsed.timestamp() <= now and not self._is_quiet_time():
                item["done"] = True
                due.append(item.get("text", "Você tem um lembrete."))
        if due:
            save_settings(self.settings)
            self.show_bubble("Lembrete: " + "; ".join(due), duration=12000)
        self.root.after(15000, self.check_reminders)

    def _matching_app(self, question):
        normalized = question.lower()
        if not any(token in normalized for token in ("abrir ", "abra ", "abre ", "iniciar ", "inicie ", "executar ")):
            return None
        for app in self.settings.get("apps", []):
            name = app.get("name", "").strip()
            if name and name.lower() in normalized:
                return app
        return None

    def _confirm_open_app(self, question, app):
        confirmation = (
            f"A Nova vai executar este comando:\n\n{app['command']}\n\n"
            f"Abrir {app['name']} agora?"
        )
        if not messagebox.askyesno("Confirmar abertura", confirmation, parent=self.root):
            return
        try:
            argv = resolve_app_command(app["command"])
            subprocess.Popen(argv, close_fds=True)
            answer = f"Abri {app['name']}."
        except (OSError, ValueError) as exc:
            answer = f"Não consegui abrir {app['name']}: {exc}"
        self._record_local_interaction(question, answer)
        self.show_bubble(answer)

    def close_app(self):
        self._closing = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def forget_history(self):
        self.history = []
        if save_history(self.history):
            self.show_bubble("Memória limpa!", duration=2500)
        else:
            self.show_bubble(
                "Memória limpa nesta sessão, mas não consegui salvar.",
                duration=4000,
            )

    # ---------- integração com a IA local ----------
    def ask_menu(self, event=None):
        if self.ai_request_active:
            self.show_bubble("Já estou respondendo sua pergunta!", duration=2500)
            return
        question = self._ask_question()
        if not question:
            return
        date_answer = current_date_answer(question)
        if date_answer:
            answer = self._record_local_interaction(question, date_answer)
            self.show_bubble(answer)
            return
        if is_open_calendar_request(question):
            answer = self._record_local_interaction(
                question, "Abri o calendário para você."
            )
            self.show_calendar()
            self.show_bubble(answer)
            return
        app = self._matching_app(question)
        if app:
            self._confirm_open_app(question, app)
            return
        self.history.append({"role": "user", "content": question})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        request_history = list(self.history)
        self.ai_request_active = True
        self.state = "thinking"
        self._show_idea_icon = False
        self._thinking_started_at = time.monotonic()
        self.show_bubble("pensando...", duration=999999)
        memories = list(self.settings.get("memories", []))
        threading.Thread(target=self._ask_worker, args=(request_history, memories), daemon=True).start()

    def _record_local_interaction(self, question, answer):
        self.history.extend((
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ))
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        if not save_history(self.history):
            return f"{answer}\nNão consegui salvar o histórico."
        return answer

    def _question_dialog_geometry(self, dialog_width=420, dialog_height=230):
        gap = 8
        pet_left = int(round(self.x))
        pet_right = pet_left + WIDTH
        available_left = max(0, pet_left - gap)
        available_right = max(0, self.screen_w - pet_right - gap)
        place_right = available_right >= dialog_width or available_right >= available_left
        available_width = available_right if place_right else available_left
        width = min(dialog_width, max(1, available_width))
        x = pet_right + gap if place_right else pet_left - gap - width

        height = min(dialog_height, self.screen_h)
        y = int(round(self.y + (self.cur_height - height) / 2))
        y = max(0, min(y, self.screen_h - height))
        return x, y, width, height

    def _ask_question(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Perguntar à Nova")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        x, y, width, height = self._question_dialog_geometry()
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        result = {"question": None}
        background = "#F3F5F9"
        content = tk.Frame(dialog, bg=background, padx=18, pady=16)
        content.pack(fill="both", expand=True)
        tk.Label(
            content,
            text="Converse com a Nova",
            font=("TkDefaultFont", 13, "bold"),
            fg="#202B45",
            bg=background,
        ).pack(anchor="w")
        tk.Label(
            content,
            text="Escreva sua pergunta abaixo",
            font=("TkDefaultFont", 9),
            fg="#68738A",
            bg=background,
        ).pack(anchor="w", pady=(3, 10))

        editor_border = tk.Frame(content, bg="#D8DEEA", padx=1, pady=1)
        editor_border.pack(fill="both", expand=True)
        answer = tk.Text(
            editor_border,
            height=4,
            wrap="word",
            undo=True,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=("TkDefaultFont", 10),
            fg="#202B45",
            bg="#FFFFFF",
            insertbackground="#5269C8",
        )
        answer.pack(fill="both", expand=True)

        buttons = tk.Frame(content, bg=background)
        buttons.pack(fill="x", pady=(12, 0))

        def finish():
            question = answer.get("1.0", "end-1c").strip()
            if not question:
                answer.focus_set()
                return
            result["question"] = question
            dialog.destroy()

        def cancel():
            dialog.destroy()

        tk.Button(
            buttons,
            text="Cancelar",
            command=cancel,
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            fg="#536078",
            bg=background,
            activebackground="#E6EAF2",
            cursor="hand2",
        ).pack(side="right")
        tk.Button(
            buttons,
            text="Perguntar",
            command=finish,
            relief="flat",
            bd=0,
            padx=16,
            pady=7,
            fg="#FFFFFF",
            bg="#5269C8",
            activebackground="#4056B2",
            activeforeground="#FFFFFF",
            cursor="hand2",
        ).pack(side="right", padx=(0, 6))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Control-Return>", lambda _event: finish())
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.grab_set()
        answer.focus_set()
        self.root.wait_window(dialog)
        return result["question"]

    def _ask_worker(self, history, memories=None):
        try:
            answer = ask_local_ai(history, memories=memories)
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada ao consultar o Ollama")
            answer = "Tive um problema ao consultar a IA. Tente novamente daqui a pouco."
        self._ai_results.put(answer)

    def _drain_ai_results(self):
        try:
            answer = self._ai_results.get_nowait()
        except queue.Empty:
            return
        if not self._closing:
            self._show_answer(answer)

    def _show_answer(self, answer):
        if self._closing:
            return
        self.ai_request_active = False
        self.history.append({"role": "assistant", "content": answer})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        history_saved = save_history(self.history)
        self.state = "walk"
        self._show_idea_icon = True
        words = max(len(answer.split()), 1)
        duration = min(max(6000, words * 400), 30000)
        if history_saved:
            self.show_bubble(answer, duration=duration)
        else:
            self.show_bubble(
                f"{answer}\n\nNão consegui salvar o histórico.",
                duration=duration,
            )

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        pet = DesktopPet()
        pet.run()
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Erro na Nova", str(exc))
        except Exception:
            pass
        raise
