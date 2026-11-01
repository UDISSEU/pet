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
    Clique simples (sem arrastar) -> acena
    Duplo clique             -> dança
    Clique direito             -> menu (perguntar / falar algo / esquecer conversa / fechar)
"""

import logging
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox
from tkinter import ttk

try:
    from animation_loader import AnimationLoader
    from PIL import Image, ImageDraw, ImageTk
except ImportError as exc:
    if exc.name in ("PIL", "cv2", "numpy"):
        dependency = {"PIL": "Pillow", "cv2": "OpenCV", "numpy": "NumPy"}[exc.name]
        print(
            f"Falta a dependência {dependency}. Instale as dependências com ./install.sh.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise
from autonomy import (
    is_quiet_now,
    find_installed_apps,
    load_settings,
    resolve_app_command,
    save_settings,
    valid_reminder_time,
)
from assistant_actions import (
    current_date_answer,
    is_open_calendar_request,
    local_personality_intent,
)
from app_intents import (
    app_open_target as parse_app_open_target,
    is_app_open_request as parse_app_open_request,
    looks_like_app_target as parse_app_target,
    match_registered_app,
)
from calendar_view import open_calendar_window
from config import (
    APP_COMMENTS,
    BASE_HEIGHT,
    FONT_BUBBLE,
    GENERIC_COMMENTS,
    ICONS_DIR,
    LOGIC_STEP_MS,
    MAX_HISTORY_MESSAGES,
    ONE_SHOT_VIDEOS,
    REMINDER_ANIMATION_SECONDS,
    SCALE,
    SCREEN_MARGIN,
    STARTUP_IDLE_SECONDS,
    TICK_MS,
    THUMBS_UP_ANIMATION_SECONDS,
    VIDEO_FRAME_INTERVAL_MS,
    VIDEO_FALLBACKS,
    VIDEO_REACTION_SECONDS,
    VANISHING_ANIMATION_SECONDS,
    MOVEMENT_VIDEOS,
    VIDEO_LOOP_WINDOWS,
    PROJECT_ROOT,
    resolve_movement_path,
    WALK_ACCELERATION,
    WALK_DIRECTION_VECTORS,
    WALK_SPEED,
    WALK_DIRECTION_CHANGE_MAX_SECONDS,
    WALK_DIRECTION_CHANGE_MIN_SECONDS,
    WIDTH,
)
from animation import frame_index_at_elapsed
from ollama_client import load_history, save_history
from personality import (
    can_speak_spontaneously,
    pick_line,
    record_spontaneous_speech,
    reset_personality_state,
)
from ai.request_handler import PROVIDER_FAILURE_MESSAGE, answer_request
from providers.base_provider import ProviderError
from providers.provider_factory import create_provider
from x11_helper import X11Helper

# ---------------------------------------------------------------------------
# Personagem
# ---------------------------------------------------------------------------
class DesktopPet:
    @property
    def state(self):
        return getattr(self, "_state", "idle")

    @state.setter
    def state(self, value):
        self._state = value
        self._state_generation = getattr(self, "_state_generation", 0) + 1
        self._state_started_at = time.monotonic()

    def __init__(self):
        self.history = load_history()
        self.settings = load_settings()
        reset_personality_state()
        self._speech_history = []
        self._click_timestamps = []
        self._pending_click_job = None
        self._ignore_next_click = False
        self._pickup_until = 0.0
        self._pickup_spoken = False
        self._last_dance_at = time.monotonic()
        self._last_break_tip_at = time.monotonic()
        self._focus_routine_started_at = None
        self._focus_mid_job = None
        self._miss_you_pending = False
        self._update_visit_metadata()
        self._user_name_dialog = None
        self._installed_apps_cache = None
        self.x11 = X11Helper()
        self.shape_supported = None

        self.root = tk.Tk()
        self._window_icon = None
        try:
            with Image.open(PROJECT_ROOT / "launchers" / "nova-icon.png") as icon:
                icon = icon.convert("RGBA")
                icon.thumbnail((128, 128), Image.Resampling.LANCZOS)
                self._window_icon = ImageTk.PhotoImage(icon)
            self.root.iconphoto(True, self._window_icon)
        except (tk.TclError, OSError, ValueError):
            pass
        self._closing = False
        self._ai_results = queue.Queue()
        self._provider_test_results = queue.Queue()
        self._app_launch_results = queue.Queue()
        self.app_launch_active = False
        self.system_maintenance_active = False
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
        self._drag_focus_widget = None
        self.state = "idle"
        self.busy = False
        self.focus_mode = "idle"  # idle | focus | break
        self.focus_goal = ""
        self.focus_minutes = 25
        self.break_minutes = 5
        self._focus_job = None
        self._routine_greeted = False
        self._last_user_activity_at = time.monotonic()
        self.sit_win_id = None
        self.behind_mode = False  # true = ela fica sempre atrás das janelas
        self.ai_request_active = False
        self._dismiss_job = None
        self._hidden = False
        self._animation_loader = AnimationLoader(MOVEMENT_VIDEOS)
        idle_preview = self._animation_loader.preview("idle")
        self.video_frames = {
            name: [idle_preview] for name in MOVEMENT_VIDEOS
        }
        self._video_frame_cache = {}
        self.drag_tilt = 0.0
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = None
        self._last_drag_event_at = 0.0
        self._last_drag_motion_at = 0.0
        self._irritated_until = 0.0
        self._irritated_started_at = 0.0
        self._reminder_started_at = 0.0
        self._reminder_animation_until = 0.0
        self._thumbs_up_started_at = 0.0
        self._vanishing_started_at = 0.0

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
        self._animation_loader.start()
        self._last_tick_at = time.monotonic()
        self._next_tick_at = self._last_tick_at + TICK_MS / 1000
        self.root.after(TICK_MS, self.tick)
        self.root.after(
            round(STARTUP_IDLE_SECONDS * 1000), self._finish_startup_idle
        )
        self.root.after(random.randint(6000, 12000), self.random_speech)
        self.root.after(random.randint(15000, 30000), self.observe_apps)
        self.root.after(random.randint(30000, 60000), self.peekaboo)
        self.root.after(random.randint(20000, 40000), self.maybe_sit)
        self.root.after(15000, self.check_reminders)
        self.root.after(30000, self.check_daily_routine)
        self.root.after(300000, self.check_daily_surprise)
        self.root.after(300000, self.check_idle_yawn)
        self.root.after(300000, self.check_occasional_note)
        self.root.after(60000, self.check_idle_dance)
        self.root.after(300000, self.check_healthy_break)
        if not self.settings.get("user_name"):
            self.root.after(1200, self.ask_user_name)
        if self.settings.get("routine_greeting"):
            self.root.after(
                round((STARTUP_IDLE_SECONDS + 1) * 1000),
                self.show_start_greeting,
            )
        if self.settings.get("routine_context"):
            self.root.after(7000, self.show_context_greeting)
        self.root.after(random.randint(30000, 60000), self.maybe_curious)

    # ---------- geometria ----------
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

    # ---------- reprodução dos movimentos em vídeo ----------
    @staticmethod
    def _load_status_icon(path):
        try:
            return Image.open(path).convert("RGBA")
        except OSError:
            return None

    def _video_for_current_pose(self, now=None):
        if now is None:
            now = time.monotonic()
        if self.state == "focused":
            video = "focused"
        elif now < getattr(self, "_reminder_animation_until", 0.0):
            video = "reminder"
        elif self.state == "celebrating":
            video = "celebrate"
        elif self.state == "cheering":
            video = "cheering"
        elif self.state == "greeting":
            video = "wave"
        elif self.state == "thumbs_up":
            video = "thumbs_up"
        elif self.state == "vanishing":
            video = "vanishing"
        elif self.state == "resting":
            video = "rest"
        elif getattr(self, "focus_mode", "idle") == "break":
            video = "rest"
        elif self.state == "curious":
            video = "curious"
        elif self.state == "yawning":
            video = "yawn"
        elif self.state == "sitting":
            video = "sleep"
        elif self.state == "thinking":
            video = "thinking"
        elif self.state == "held":
            video = "idle"
        elif self.state == "walk":
            if self.stay_in_place_var.get():
                video = "idle"
            elif now < self._irritated_until:
                video = "angry"
            elif self.busy:
                video = "wave"
            else:
                walk_velocity_x = getattr(self, "_walk_velocity_x", 0.0)
                direction = walk_velocity_x if abs(walk_velocity_x) > 0.5 else self.walk_dx
                video = "walk_left" if direction < 0 else "walk_right"
        else:
            video = self.state
        return self._video_with_fallback(video)

    @staticmethod
    def _video_with_fallback(video):
        seen = set()
        while video not in seen:
            seen.add(video)
            filename = MOVEMENT_VIDEOS.get(video)
            if filename and resolve_movement_path(filename).is_file():
                return video
            video = VIDEO_FALLBACKS.get(video, "idle")
        return "idle"

    def _current_video_frame(self, now=None):
        if now is None:
            now = time.monotonic()
        video = self._video_for_current_pose(now)
        frames = self.video_frames[video]
        if not frames:
            raise ValueError(f"A animação {video} está sem quadros.")
        if video == "angry":
            elapsed_ms = (now - self._irritated_started_at) * 1000
        elif video in ONE_SHOT_VIDEOS or video == "thinking":
            started_at = {
                "thinking": self._thinking_started_at,
                "focused": getattr(self, "_focused_started_at", now),
                "reminder": self._reminder_started_at,
                "thumbs_up": self._thumbs_up_started_at,
                "vanishing": self._vanishing_started_at,
            }[video]
            elapsed_ms = (now - started_at) * 1000
        elif self.state != "walk":
            elapsed_ms = (now - self._state_started_at) * 1000
        else:
            elapsed_ms = self.animation_time_ms
        frame_index = frame_index_at_elapsed(
            elapsed_ms,
            len(frames),
            loop_window=VIDEO_LOOP_WINDOWS.get(video),
            one_shot=video in ONE_SHOT_VIDEOS,
            fps=1000 / VIDEO_FRAME_INTERVAL_MS,
        )
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
        self._drain_animation_results()
        if hasattr(self, "_ai_results"):
            self._drain_ai_results()
        if hasattr(self, "_provider_test_results"):
            self._drain_provider_test_results()
        if hasattr(self, "_app_launch_results"):
            self._drain_app_launch_results()
        raw_elapsed = max(0.0, now - self._last_tick_at)
        elapsed = min(raw_elapsed, 0.1)
        self._last_tick_at = now
        # O relógio da animação acompanha tempo real para que
        # os vídeos não fiquem para trás quando um quadro demora a renderizar.
        self.animation_time_ms += raw_elapsed * 1000
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
                self._stand_up("stand_closed")

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

    def _drain_animation_results(self):
        loader = getattr(self, "_animation_loader", None)
        if loader is None:
            return
        changed = False
        for name, frames, error in loader.drain():
            if error is not None:
                # Keep the already-renderable preview if a video is damaged.
                continue
            self.video_frames[name] = frames
            changed = True
        if changed and not self._closing:
            self._video_frame_cache.clear()
            self.render_and_show()

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

    def _finish_startup_idle(self):
        if not self._closing and self.state == "idle":
            self.state = "walk"

    def random_speech(self):
        if (self.auto_speech_var.get() and self.state == "walk"
                and self._can_speak_spontaneously()):
            self._show_personality_line("idle_chatter", duration=3500, spontaneous=True)
        interval = (30000, 60000) if self.settings["mode"] == "proativa" else (90000, 150000)
        self.root.after(random.randint(*interval), self.random_speech)

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
        if not save_settings(self.settings):
            logging.getLogger(__name__).warning(
                "Não foi possível salvar a data da última visita da Nova."
            )

    def _record_interaction(self):
        self.settings["interaction_count"] = self.settings.get("interaction_count", 0) + 1
        self.settings["last_seen_date"] = datetime.now().astimezone().date().isoformat()
        if not save_settings(self.settings):
            logging.getLogger(__name__).warning(
                "Não foi possível salvar os metadados da interação da Nova."
            )

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
            and not self.ai_request_active
            and not self.is_covered()
        )

    def _show_personality_line(
        self, category, duration=5000, spontaneous=False, allow_focus=False
    ):
        if spontaneous:
            if (not self._can_speak_spontaneously(allow_focus=allow_focus)
                    or not can_speak_spontaneously()):
                return False
        elif self._closing:
            return False
        line = pick_line(
            category,
            name=self.settings.get("user_name", ""),
            rng=random,
            history=self._speech_history,
        )
        if spontaneous:
            record_spontaneous_speech()
        self.show_bubble(line, duration=duration)
        return True

    def _show_spontaneous_pose(self, category, state, duration=5000):
        if not self._can_speak_spontaneously() or not can_speak_spontaneously():
            return False
        self.state = state
        if not self._show_personality_line(category, duration, spontaneous=True):
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
        if available and random.random() < 0.2 and can_speak_spontaneously():
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

    # ---------- observar apps abertos ----------
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
                        if self._can_speak_spontaneously() and can_speak_spontaneously():
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
                and self._can_speak_spontaneously() and can_speak_spontaneously()):
            self._show_personality_line(
                "peekaboo", duration=2500, spontaneous=True
            )

    # ---------- sentar cansada em cima de uma janela ----------
    def maybe_sit(self):
        if (self.auto_sit_var.get() and self._can_speak_spontaneously()
                and not self.stay_in_place_var.get()
                and self.state == "walk" and self.x11.ok
                and can_speak_spontaneously() and random.random() < 0.7):
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

    def say_something(self):
        self._show_personality_line("idle_chatter", duration=3500)

    def show_menu(self, event):
        self._last_user_activity_at = time.monotonic()
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

        action_button("✦  Conversar", self.ask_menu, primary=True)
        action_button("▦  Calendário", self.show_calendar)
        action_button("⏱  Foco e rotina", lambda: self.open_autonomy_settings("routine"))
        action_button("⚙  Preferências", self.open_autonomy_settings)

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

        def section_label(parent, label):
            tk.Label(
                parent, text=label.upper(), anchor="w", padx=7, pady=5,
                bg="#F5F6FA", fg="#758099",
                font=("TkDefaultFont", 8, "bold"),
            ).pack(fill="x", pady=(4, 0))

        def more_action(label, command):
            tk.Button(
                more, text=label, anchor="w",
                command=lambda: (close_popup(), command()), relief="flat", bd=0,
                padx=10, pady=6, cursor="hand2", bg="#FFFFFF", fg="#28334D",
                activebackground="#E9EDF5",
            ).pack(fill="x", pady=2)

        section_label(more, "Interação")
        more_action("Falar algo", self.say_something)

        behavior_group = tk.Frame(more, bg="#F5F6FA")
        behavior_group.pack(fill="x", pady=(5, 0))
        behavior_section = tk.Frame(behavior_group, bg="#F5F6FA")
        behavior_expanded = {"value": False}

        def toggle_behavior():
            if behavior_expanded["value"]:
                behavior_section.pack_forget()
                behavior_button.configure(text="Comportamento  ▾")
            else:
                behavior_section.pack(fill="x", pady=(1, 2))
                behavior_button.configure(text="Comportamento  ▴")
            behavior_expanded["value"] = not behavior_expanded["value"]

        behavior_button = tk.Button(
            behavior_group, text="Comportamento  ▾", command=toggle_behavior, anchor="w",
            relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
            bg="#E9EDF5", fg="#536078", activebackground="#DDE3EF",
        )
        behavior_button.pack(fill="x")

        def check_option(label, variable, command=None):
            tk.Checkbutton(
                behavior_section, text=label, variable=variable, command=command,
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
        section_label(more, "Manutenção")
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

    def open_autonomy_settings(self, selected_tab="behavior"):
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        window.title("Preferências da Nova")
        window.transient(self.root)
        window.attributes("-topmost", True)
        window.geometry("560x600")
        window.minsize(520, 550)
        window.configure(bg="#E3E8F0")

        style = ttk.Style(window)
        style.configure("Autonomy.TFrame", background="#E3E8F0")
        style.configure("Card.TFrame", background="#F5F7FA")
        style.configure("Title.TLabel", background="#E3E8F0", foreground="#202B45", font=("TkDefaultFont", 14, "bold"))
        style.configure("Subtitle.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("CardTitle.TLabel", background="#F5F7FA", foreground="#26344A", font=("TkDefaultFont", 10, "bold"))
        style.configure("Hint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("PageHint.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("ComputerStatus.TLabel", background="#F5F7FA", foreground="#26344A", font=("TkDefaultFont", 10, "bold"))
        style.configure("ComputerStatusError.TLabel", background="#F5F7FA", foreground="#B42318", font=("TkDefaultFont", 10, "bold"))
        style.configure("ModeHint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 8))
        style.configure("Primary.TButton", padding=(14, 8), font=("TkDefaultFont", 9, "bold"))
        style.configure("Secondary.TButton", padding=(12, 8))
        style.configure("Nav.TButton", padding=(4, 2))
        style.configure(
            "TabNav.TLabel", background="#E3E8F0", foreground="#202B45",
            font=("TkDefaultFont", 11, "bold"),
        )
        style.configure(
            "Maintenance.Treeview", background="#F5F7FA", fieldbackground="#F5F7FA",
            foreground="#26344A", rowheight=28, borderwidth=0,
        )
        style.configure(
            "Maintenance.Treeview.Heading", background="#E3E8F0",
            foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        style.configure(
            "History.Treeview", background="#F5F7FA", fieldbackground="#F5F7FA",
            foreground="#26344A", rowheight=27, borderwidth=0,
        )
        style.configure(
            "History.Treeview.Heading", background="#E3E8F0",
            foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        style.configure("Autonomy.TEntry", fieldbackground="#EDF0F5", foreground="#26344A", padding=4)

        outer = ttk.Frame(window, style="Autonomy.TFrame", padding=(22, 18, 22, 14))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Preferências da Nova", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Ajuste o ritmo, a rotina e o que ela pode lembrar ou fazer.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 14))

        notebook = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation.pack(fill="x", pady=(0, 6))
        tab_pages = []
        history_refresh_callback = {"callback": None}
        active_tab_index = 0
        active_tab_name = tk.StringVar(value="Comportamento")

        def select_tab(target):
            nonlocal active_tab_index
            if isinstance(target, int):
                index = target % len(tab_pages)
            else:
                index = next(i for i, (_name, page) in enumerate(tab_pages) if page is target)
            active_tab_index = index
            for i, (name, page) in enumerate(tab_pages):
                if i == index:
                    page.pack(fill="both", expand=True)
                    active_tab_name.set(name)
                    if name == "Histórico" and history_refresh_callback["callback"]:
                        history_refresh_callback["callback"]()
                else:
                    page.pack_forget()

        def register_tab(page, name):
            tab_pages.append((name, page))
            if len(tab_pages) == 1:
                select_tab(0)

        def move_tab(direction):
            select_tab(active_tab_index + direction)

        ttk.Button(
            tab_navigation, text="◀", width=2, style="Nav.TButton",
            command=lambda: move_tab(-1),
        ).pack(side="left")
        ttk.Label(
            tab_navigation, textvariable=active_tab_name, style="TabNav.TLabel",
        ).pack(side="left", expand=True, padx=8)
        ttk.Button(
            tab_navigation, text="▶", width=2, style="Nav.TButton",
            command=lambda: move_tab(1),
        ).pack(side="right")
        notebook.pack(fill="both", expand=True)
        def scrollable_tab():
            tab = ttk.Frame(notebook, style="Autonomy.TFrame")
            canvas = tk.Canvas(
                tab, bg="#E3E8F0", bd=0, highlightthickness=0,
                yscrollincrement=24,
            )
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            content = ttk.Frame(canvas, style="Autonomy.TFrame", padding=14)
            content_window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind(
                "<Configure>",
                lambda _event, target=canvas: target.configure(scrollregion=target.bbox("all")),
            )
            canvas.bind(
                "<Configure>",
                lambda event, target=canvas, item=content_window:
                    target.itemconfigure(item, width=event.width),
            )

            def scroll_wheel(event, target=canvas):
                widget = event.widget
                while widget is not None:
                    if widget is target:
                        if getattr(event, "num", None) == 4:
                            target.yview_scroll(-3, "units")
                        elif getattr(event, "num", None) == 5:
                            target.yview_scroll(3, "units")
                        else:
                            delta = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                            if delta:
                                target.yview_scroll(delta * 3, "units")
                        return "break"
                    widget = getattr(widget, "master", None)
                return None

            canvas.bind_all("<MouseWheel>", scroll_wheel, add="+")
            canvas.bind_all("<Button-4>", scroll_wheel, add="+")
            canvas.bind_all("<Button-5>", scroll_wheel, add="+")
            return tab, content

        behavior_tab, behavior_content = scrollable_tab()
        routine_tab, routine_content = scrollable_tab()
        memory_tab, memory_content = scrollable_tab()
        history_tab, history_content = scrollable_tab()
        reminder_tab, reminder_content = scrollable_tab()
        apps_tab, apps_content = scrollable_tab()
        computer_tab, computer_content = scrollable_tab()
        ai_tab, ai_content = scrollable_tab()
        register_tab(behavior_tab, "Comportamento")
        register_tab(routine_tab, "Foco e rotina")
        register_tab(memory_tab, "Memórias")
        register_tab(history_tab, "Histórico")
        register_tab(reminder_tab, "Lembretes")
        register_tab(apps_tab, "Aplicativos")
        register_tab(computer_tab, "Meu Computador")
        register_tab(ai_tab, "Inteligência artificial")

        mode = tk.StringVar(value=self.settings.get("mode", "companhia"))
        quiet_start = tk.StringVar(value=self.settings.get("quiet_start", "22:00"))
        quiet_end = tk.StringVar(value=self.settings.get("quiet_end", "08:00"))
        focus_goal = tk.StringVar()
        focus_minutes = tk.StringVar(value=str(self.settings.get("focus_minutes", 25)))
        break_minutes = tk.StringVar(value=str(self.settings.get("break_minutes", 5)))
        routine_greeting = tk.BooleanVar(value=self.settings.get("routine_greeting", True))
        routine_context = tk.BooleanVar(value=self.settings.get("routine_context", True))
        routine_idle_yawn = tk.BooleanVar(value=self.settings.get("routine_idle_yawn", True))
        routine_focus_celebration = tk.BooleanVar(value=self.settings.get("routine_focus_celebration", True))
        routine_note = tk.BooleanVar(value=self.settings.get("routine_note", True))
        routine_surprise = tk.BooleanVar(value=self.settings.get("routine_surprise", True))
        routine_evening = tk.BooleanVar(value=self.settings.get("routine_evening", True))
        routine_dance = tk.BooleanVar(value=self.settings.get("routine_dance", True))
        routine_break_tip = tk.BooleanVar(value=self.settings.get("routine_break_tip", True))
        evening_time = tk.StringVar(value=self.settings.get("evening_time", "20:30"))
        speech = tk.BooleanVar(value=self.auto_speech_var.get())
        observe = tk.BooleanVar(value=self.observe_apps_var.get())
        auto_sit = tk.BooleanVar(value=self.auto_sit_var.get())
        peekaboo = tk.BooleanVar(value=self.peekaboo_var.get())
        confirm_app_launch = tk.BooleanVar(
            value=self.settings.get("confirm_app_launch", False)
        )
        ai_provider = tk.StringVar(value=self.settings.get("ai_provider", "ollama"))
        online_ai_enabled = tk.BooleanVar(value=self.settings.get("online_ai_enabled", False))
        allow_online_data = tk.BooleanVar(value=self.settings.get("allow_online_data", False))
        confirm_free_tier = tk.BooleanVar(value=self.settings.get("confirm_free_tier", False))
        ai_timeout = tk.StringVar(value=str(self.settings.get("ai_timeout", 30)))
        ollama_model = tk.StringVar(value=self.settings.get("ollama_model", "llama3.2:1b"))
        gemini_model = tk.StringVar(value=self.settings.get("gemini_model", "gemini-3.8-flash"))
        groq_model = tk.StringVar(value=self.settings.get("groq_model", "openai/gpt-oss-20b"))
        mistral_model = tk.StringVar(value=self.settings.get("mistral_model", "mistral-small-latest"))
        memory_items = list(self.settings.get("memories", []))
        reminder_items = list(self.settings.get("reminders", []))
        app_items = list(self.settings.get("apps", []))

        def card(parent, title, hint=None):
            frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
            frame.pack(fill="x", pady=(0, 12))
            ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
            return frame

        ai_provider_card = card(
            ai_content, "Provedor de conversa",
            "A Nova começa usando o Ollama local. Provedores online só recebem o histórico recente e memórias relacionadas depois que você habilitar o uso e autorizar o envio.",
        )
        ttk.Label(ai_provider_card, text="Provedor", style="Hint.TLabel").pack(anchor="w")
        ttk.Combobox(
            ai_provider_card, textvariable=ai_provider,
            values=("ollama", "gemini", "groq", "mistral"), state="readonly",
        ).pack(fill="x", pady=(3, 8))
        ttk.Checkbutton(
            ai_provider_card, text="Ativar provedor online selecionado",
            variable=online_ai_enabled,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Autorizo enviar histórico recente e memórias relacionadas\nà pergunta ao provedor online",
            variable=allow_online_data,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Confirmei no painel que minha chave usa modalidade gratuita\ne que a cobrança está desabilitada",
            variable=confirm_free_tier,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            ai_provider_card,
            text="O teste verifica a chave e a disponibilidade do modelo sem enviar conversas. Chaves (nunca gravadas nas preferências): GEMINI_API_KEY, GROQ_API_KEY ou MISTRAL_API_KEY; o lançador também lê as três do cofre do sistema. Confira privacidade, limites e cobrança no painel do provedor.",
            style="Hint.TLabel", wraplength=400,
        ).pack(anchor="w", pady=(5, 8))
        test_row = ttk.Frame(ai_provider_card, style="Card.TFrame")
        test_row.pack(fill="x", pady=(0, 8))
        test_status = tk.StringVar(value="")
        test_button_state = {"running": False}
        test_button = ttk.Button(
            test_row, text="Testar conexão", style="Secondary.TButton",
        )
        test_button.pack(side="left")
        ttk.Label(test_row, textvariable=test_status, style="Hint.TLabel", wraplength=265).pack(
            side="left", fill="x", expand=True, padx=(8, 0),
        )

        def test_selected_provider():
            if test_button_state["running"]:
                return
            try:
                timeout_value = int(ai_timeout.get())
            except ValueError:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            if not 5 <= timeout_value <= 30:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            provider_name = ai_provider.get()
            provider_settings = dict(self.settings)
            provider_settings.update(
                ai_provider=provider_name,
                ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                gemini_model=gemini_model.get().strip(),
                groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
            )
            test_button_state["running"] = True
            test_button.configure(state="disabled")
            test_status.set("Testando…")
            threading.Thread(
                target=self._provider_test_worker,
                args=(provider_name, provider_settings, window, test_status, test_button, test_button_state),
                daemon=True,
            ).start()

        test_button.configure(command=test_selected_provider)
        ttk.Label(ai_provider_card, text="Modelo Ollama", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Gemini", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=gemini_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Groq", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=groq_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Mistral", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=mistral_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Timeout (5–30 segundos)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ai_timeout, style="Autonomy.TEntry").pack(fill="x", pady=(2, 0))

        mode_card = card(behavior_content, "Como a Nova deve se comportar?", "Você pode personalizar as opções abaixo depois de escolher um modo.")
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

        behavior_card = card(behavior_content, "Iniciativas", "As iniciativas automáticas respeitam o horário de silêncio.")
        ttk.Checkbutton(behavior_card, text="Falas espontâneas", variable=speech).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Comentários sobre o app ativo", variable=observe).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Sentar em janelas", variable=auto_sit).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Brincar de sumir atrás das janelas", variable=peekaboo).pack(anchor="w", pady=3)

        quiet_card = card(behavior_content, "Horário de silêncio", "A Nova pausa falas, observações e lembretes durante esse período.")
        quiet_row = ttk.Frame(quiet_card, style="Card.TFrame")
        quiet_row.pack(anchor="w")
        ttk.Label(quiet_row, text="Das").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_start, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=(8, 16), ipady=4)
        ttk.Label(quiet_row, text="às").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_end, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=8, ipady=4)
        ttk.Label(quiet_row, text="HH:MM").pack(side="left", padx=(4, 0))

        focus_card = card(
            routine_content,
            "Sessão de foco",
            "Escolha no que vai trabalhar. A Nova fica quieta até a pausa e usa a animação de descanso.",
        )
        ttk.Label(focus_card, text="Sua prioridade", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Entry(focus_card, textvariable=focus_goal, style="Autonomy.TEntry").pack(fill="x", ipady=5)
        duration_row = ttk.Frame(focus_card, style="Card.TFrame")
        duration_row.pack(fill="x", pady=(12, 4))
        ttk.Label(duration_row, text="Foco (min)").pack(side="left")
        ttk.Spinbox(duration_row, from_=5, to=180, increment=5, textvariable=focus_minutes, width=7).pack(side="left", padx=(8, 18), ipady=3)
        ttk.Label(duration_row, text="Pausa (min)").pack(side="left")
        ttk.Spinbox(duration_row, from_=1, to=60, increment=1, textvariable=break_minutes, width=7).pack(side="left", padx=8, ipady=3)
        if self.focus_mode == "focus":
            focus_status_text = f"Foco em andamento: {self.focus_goal}"
        elif self.focus_mode == "break":
            focus_status_text = "Você está no intervalo. A Nova também está descansando."
        else:
            focus_status_text = "Ao terminar, ela avisa para você fazer uma pausa."
        focus_status = tk.StringVar(value=focus_status_text)
        ttk.Label(focus_card, textvariable=focus_status, style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(6, 8))
        focus_actions = ttk.Frame(focus_card, style="Card.TFrame")
        focus_actions.pack(fill="x")
        ttk.Button(
            focus_actions, text="Iniciar foco", style="Primary.TButton",
            command=lambda: start_focus_from_settings(),
        ).pack(side="left")
        ttk.Button(
            focus_actions, text="Encerrar sessão", style="Secondary.TButton",
            command=self.stop_focus,
        ).pack(side="left", padx=(8, 0))

        routine_card = card(
            routine_content,
            "Pequenas rotinas",
            "As mensagens aparecem apenas enquanto a Nova estiver aberta e fora do horário de silêncio.",
        )
        ttk.Checkbutton(
            routine_card, text="Dar boas-vindas quando eu iniciar a Nova",
            variable=routine_greeting,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Comentário de bom dia, boa tarde ou boa noite",
            variable=routine_context,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Bocejar depois de 5 minutos sem interação",
            variable=routine_idle_yawn,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Comemorar ao concluir uma sessão de foco",
            variable=routine_focus_celebration,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Recadinho ocasional (intervalo mínimo de 30 minutos)",
            variable=routine_note,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Uma surpresa aleatória por dia (fala e aceno)",
            variable=routine_surprise,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Dancinha espontânea (somente companhia/proativa)",
            variable=routine_dance,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Lembrete de pausa saudável a cada 50 minutos",
            variable=routine_break_tip,
        ).pack(anchor="w", pady=4)
        evening_row = ttk.Frame(routine_card, style="Card.TFrame")
        evening_row.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(
            evening_row, text="Lembrar de encerrar o dia às",
            variable=routine_evening,
        ).pack(side="left")
        ttk.Entry(evening_row, textvariable=evening_time, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=8, ipady=3)
        ttk.Label(evening_row, text="(HH:MM)", style="Hint.TLabel").pack(side="left")

        computer_intro = card(
            computer_content, "Cuidados com o sistema",
            "Atualizações e limpezas usam o APT. O Linux solicitará autenticação quando necessário.",
        )
        ttk.Label(
            computer_intro, text="Escolha uma ação para começar.", style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        progress_card = ttk.Frame(computer_content, style="Card.TFrame", padding=14)
        progress_card.pack(fill="x", pady=(0, 12))
        computer_status = tk.StringVar(value="Tudo pronto.")
        computer_status_label = ttk.Label(
            progress_card, textvariable=computer_status, style="ComputerStatus.TLabel",
            wraplength=360,
        )
        computer_status_label.pack(anchor="w")
        computer_progress = ttk.Progressbar(progress_card, mode="indeterminate", length=380)
        computer_progress.pack(fill="x", pady=(10, 0))
        computer_progress.stop()
        computer_progress.pack_forget()
        maintenance_buttons = []
        maintenance_details = {"text": ""}

        def show_maintenance_details():
            if not maintenance_details["text"]:
                return
            details_window = self._set_nova_window_icon(tk.Toplevel(window))
            details_window.title("Detalhes da operação")
            details_window.transient(window)
            details_window.geometry("620x380")
            details_window.configure(bg="#E3E8F0")
            frame = ttk.Frame(details_window, style="Autonomy.TFrame", padding=14)
            frame.pack(fill="both", expand=True)
            output = tk.Text(frame, wrap="word", height=18, relief="flat", bd=0,
                             bg="#F5F7FA", fg="#344054", font=("TkFixedFont", 9))
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=output.yview)
            output.configure(yscrollcommand=scrollbar.set)
            output.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            output.insert("1.0", maintenance_details["text"])
            output.configure(state="disabled")

        details_button = ttk.Button(
            progress_card, text="Ver detalhes", style="Secondary.TButton",
            command=show_maintenance_details, state="disabled",
        )
        details_button.pack(anchor="e", pady=(8, 0))

        def show_maintenance_confirmation(title, description, confirm_label, on_confirm):
            dialog = self._set_nova_window_icon(tk.Toplevel(window))
            dialog.title(title)
            dialog.transient(window)
            dialog.resizable(False, False)
            dialog.configure(bg="#E3E8F0")
            frame = ttk.Frame(dialog, style="Autonomy.TFrame", padding=20)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(frame, text=description, style="Subtitle.TLabel", wraplength=420).pack(anchor="w", pady=(8, 18))
            actions = ttk.Frame(frame, style="Autonomy.TFrame")
            actions.pack(fill="x")
            ttk.Button(actions, text="Cancelar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")

            def confirm():
                dialog.destroy()
                on_confirm()

            ttk.Button(
                actions, text=confirm_label, style="Primary.TButton", command=confirm,
            ).pack(side="right", padx=(0, 8))
            dialog.geometry("500x220")
            dialog.grab_set()
            dialog.focus_set()

        def show_package_review(title, description, packages, action_label=None, on_action=None):
            dialog = self._set_nova_window_icon(tk.Toplevel(window))
            dialog.title(title)
            dialog.transient(window)
            dialog.geometry("620x440")
            dialog.minsize(500, 350)
            dialog.configure(bg="#E3E8F0")
            frame = ttk.Frame(dialog, style="Autonomy.TFrame", padding=16)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
            count = len(packages)
            count_text = f"{count} pacote(s)" if count else "Nenhum pacote"
            ttk.Label(
                frame, text=f"{description}  {count_text}.", style="Subtitle.TLabel",
                wraplength=440,
            ).pack(anchor="w", pady=(4, 12))
            table_frame = ttk.Frame(frame, style="Card.TFrame", padding=4)
            table_frame.pack(fill="both", expand=True)
            columns = ("package", "current", "action")
            table = ttk.Treeview(
                table_frame, columns=columns, show="headings", height=12,
                style="Maintenance.Treeview",
            )
            table.heading("package", text="Pacote")
            table.heading("current", text="Versão instalada")
            table.heading("action", text="Ação / nova versão")
            table.column("package", width=200, minwidth=120, anchor="w")
            table.column("current", width=130, minwidth=90, anchor="w")
            table.column("action", width=200, minwidth=100, anchor="w")
            scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
            horizontal_scrollbar = ttk.Scrollbar(
                table_frame, orient="horizontal", command=table.xview,
            )
            table.configure(
                yscrollcommand=scrollbar.set,
                xscrollcommand=horizontal_scrollbar.set,
            )
            table.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            horizontal_scrollbar.pack(side="bottom", fill="x")
            for package in packages:
                table.insert("", "end", values=package)
            if not packages:
                ttk.Label(
                    frame, text="Não há pacotes para mostrar.", style="Hint.TLabel",
                ).pack(anchor="w", pady=(8, 0))
            buttons = ttk.Frame(frame, style="Autonomy.TFrame")
            buttons.pack(fill="x", pady=(12, 0))
            ttk.Button(buttons, text="Fechar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")
            if packages and action_label and on_action:
                def do_action():
                    dialog.destroy()
                    on_action()

                ttk.Button(
                    buttons, text=action_label, style="Primary.TButton", command=do_action,
                ).pack(side="right", padx=(0, 8))
            dialog.grab_set()
            dialog.focus_set()

        def parse_upgradable_packages(output):
            packages = []
            for line in output.splitlines():
                if "upgradable" not in line.lower() or "/" not in line:
                    continue
                fields = line.split()
                if len(fields) < 2:
                    continue
                name = fields[0].split("/", 1)[0]
                candidate = fields[1]
                installed = ""
                match = re.search(r"\[upgradable from: ([^\]]+)\]", line)
                if match:
                    installed = match.group(1)
                packages.append((name, installed, candidate))
            return packages

        def parse_removable_packages(output):
            packages = []
            for line in output.splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[0] in ("Remv", "Purg"):
                    version = fields[2].strip("[]") if len(fields) >= 3 else ""
                    packages.append((fields[1], version, "Será removido"))
            return packages

        def finish_maintenance(title, result, error, on_success=None):
            if not window.winfo_exists():
                return
            computer_progress.stop()
            computer_progress.pack_forget()
            for button in maintenance_buttons:
                button.configure(state="normal")
            maintenance_details["text"] = (result or error or "").strip()
            details_button.configure(state="normal" if maintenance_details["text"] else "disabled")
            if error:
                computer_status_label.configure(style="ComputerStatusError.TLabel")
                computer_status.set(f"{title}: não foi concluído. Veja os detalhes para entender o erro.")
                return
            computer_status_label.configure(style="ComputerStatus.TLabel")
            if title == "Verificar atualizações":
                packages = parse_upgradable_packages(result)
                if packages:
                    summary = f"Há {len(packages)} atualização(ões) disponível(is)."
                else:
                    summary = "Seu sistema está atualizado."
            elif title == "Atualizar sistema":
                summary = "Atualização concluída."
            elif title == "Limpar cache do APT":
                summary = "Cache de pacotes limpo."
            else:
                summary = "Limpeza concluída."
            computer_status.set(summary)
            if title == "Verificar atualizações":
                action = on_success or None
                show_package_review(
                    "Atualizações disponíveis", "Veja as versões encontradas pelo APT.",
                    packages, "Atualizar pacotes" if action else None, action,
                )
            elif on_success:
                on_success()

        def run_maintenance(title, commands, on_success=None):
            if self.system_maintenance_active:
                messagebox.showinfo("Manutenção em andamento", "Aguarde a ação atual terminar.", parent=window)
                return
            self.system_maintenance_active = True
            maintenance_details["text"] = ""
            details_button.configure(state="disabled")
            computer_status_label.configure(style="ComputerStatus.TLabel")
            computer_status.set(f"{title} em andamento. O Linux pode solicitar autenticação.")
            for button in maintenance_buttons:
                button.configure(state="disabled")
            computer_progress.pack(fill="x", pady=(10, 0), before=details_button)
            computer_progress.start(12)

            def worker():
                output = []
                error = None
                try:
                    for command in commands:
                        completed = subprocess.run(
                            command, capture_output=True, text=True, timeout=600,
                            check=False, env=self._child_process_env(),
                        )
                        details = (completed.stdout or "") + (completed.stderr or "")
                        if details.strip():
                            output.append(details.strip())
                        if completed.returncode != 0:
                            error = details.strip() or f"O comando terminou com código {completed.returncode}."
                            break
                except subprocess.TimeoutExpired:
                    error = "A operação demorou demais e foi interrompida."
                except OSError as exc:
                    error = f"Não consegui iniciar a ação: {exc}"
                finally:
                    self.system_maintenance_active = False
                self.root.after(0, lambda: finish_maintenance(
                    title, "\n\n".join(output), error, on_success,
                ))

            threading.Thread(target=worker, daemon=True).start()

        def check_system_updates(for_upgrade=False):
            followup = None
            if for_upgrade:
                followup = lambda: run_maintenance(
                    "Atualizar sistema", [["pkexec", "apt-get", "upgrade", "-y"]],
                )
            run_maintenance("Verificar atualizações", [
                ["pkexec", "apt-get", "update"],
                ["apt", "list", "--upgradable"],
            ], on_success=followup)

        def add_maintenance_button(parent, text, style_name, command):
            button = ttk.Button(parent, text=text, style=style_name, command=command)
            button.pack(side="right", padx=(12, 0))
            maintenance_buttons.append(button)
            return button

        def action_card(title, description):
            action = ttk.Frame(computer_content, style="Card.TFrame", padding=(14, 11))
            action.pack(fill="x", pady=(0, 9))
            text_frame = ttk.Frame(action, style="Card.TFrame")
            text_frame.pack(side="left", fill="x", expand=True)
            ttk.Label(text_frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(text_frame, text=description, style="Hint.TLabel", wraplength=280).pack(anchor="w", pady=(3, 0))
            return action

        def preview_autoremove():
            if self.system_maintenance_active:
                messagebox.showinfo("Manutenção em andamento", "Aguarde a ação atual terminar.", parent=window)
                return
            self.system_maintenance_active = True
            computer_status.set("Conferindo a prévia de remoção…")
            details_button.configure(state="disabled")
            for button in maintenance_buttons:
                button.configure(state="disabled")
            computer_progress.pack(fill="x", pady=(10, 0), before=details_button)
            computer_progress.start(12)

            def worker():
                try:
                    result = subprocess.run(
                        ["apt-get", "-s", "autoremove"], capture_output=True,
                        text=True, timeout=120, check=False,
                        env=self._child_process_env(),
                    )
                    details = (result.stdout or "") + (result.stderr or "")
                    error = details.strip() if result.returncode else None
                except (OSError, subprocess.TimeoutExpired) as exc:
                    details = ""
                    error = f"Não consegui verificar a lista: {exc}"
                self.system_maintenance_active = False

                def show_preview():
                    if not window.winfo_exists():
                        return
                    computer_progress.stop()
                    computer_progress.pack_forget()
                    for button in maintenance_buttons:
                        button.configure(state="normal")
                    if error:
                        maintenance_details["text"] = error
                        details_button.configure(state="normal")
                        computer_status_label.configure(style="ComputerStatusError.TLabel")
                        computer_status.set("Não consegui preparar a prévia. Veja os detalhes.")
                        return
                    preview_text = details.strip() or "O APT não listou pacotes para remover."
                    maintenance_details["text"] = preview_text
                    details_button.configure(state="normal")
                    packages = parse_removable_packages(preview_text)
                    computer_status.set(f"Prévia pronta: {len(packages)} pacote(s) para revisar.")
                    show_package_review(
                        "Pacotes não utilizados", "O APT marcou estes pacotes para remoção.",
                        packages, "Remover pacotes" if packages else None,
                        lambda: run_maintenance(
                            "Remover pacotes não utilizados",
                            [["pkexec", "apt-get", "autoremove", "-y"]],
                        ),
                    )

                self.root.after(0, show_preview)

            threading.Thread(target=worker, daemon=True).start()

        action = action_card("Atualizações disponíveis", "Atualiza a lista do APT e informa quais pacotes têm versões novas.")
        add_maintenance_button(action, "Verificar", "Secondary.TButton", check_system_updates)
        action = action_card("Atualizar programas", "Instala atualizações disponíveis sem remover pacotes.")
        add_maintenance_button(
            action, "Atualizar", "Primary.TButton",
            lambda: check_system_updates(for_upgrade=True),
        )
        action = action_card("Pacotes não utilizados", "Mostra primeiro a prévia do que o APT pretende remover.")
        add_maintenance_button(action, "Revisar", "Secondary.TButton", preview_autoremove)
        action = action_card("Cache de downloads", "Apaga arquivos de instalação .deb já baixados pelo APT.")
        add_maintenance_button(
            action, "Limpar cache", "Secondary.TButton",
            lambda: show_maintenance_confirmation(
                "Limpar cache de downloads",
                "Serão apagados os arquivos .deb já baixados pelo APT. Isso não remove programas instalados.",
                "Limpar cache",
                lambda: run_maintenance("Limpar cache do APT", [["pkexec", "apt-get", "clean"]]),
            ),
        )

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
            list_scrollbar = ttk.Scrollbar(
                list_frame, orient="horizontal", command=listing.xview,
            )
            listing.configure(xscrollcommand=list_scrollbar.set)
            listing.pack(fill="both", expand=True, padx=8, pady=(7, 0))
            list_scrollbar.pack(fill="x", padx=8, pady=(0, 7))
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

        protected_memory_card = card(
            memory_content, "Memórias essenciais protegidas",
            "Essas informações são controladas pelo código e não podem ser removidas pela lista de memórias.",
        )
        ttk.Label(
            protected_memory_card, text="Nome da assistente: Nova · protegido",
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(2, 4))
        user_name_display = tk.StringVar(
            value=(f"Seu nome: {self.settings['user_name']} · protegido"
                   if self.settings.get("user_name") else "Seu nome ainda não foi informado.")
        )
        self._user_name_display_var = user_name_display
        ttk.Label(
            protected_memory_card, textvariable=user_name_display, style="CardTitle.TLabel",
        ).pack(anchor="w")
        if not self.settings.get("user_name"):
            ttk.Button(
                protected_memory_card, text="Informar meu nome", style="Secondary.TButton",
                command=self.ask_user_name,
            ).pack(anchor="w", pady=(8, 0))

        memory_card = card(memory_content, "O que a Nova deve lembrar?", "Só use informações que você queira manter. Elas entram no contexto da IA local.")
        memory_entry = tk.StringVar()
        memory_form = ttk.Frame(memory_card, style="Card.TFrame")
        memory_form.pack(fill="x")
        memory_input = ttk.Entry(memory_form, textvariable=memory_entry, style="Autonomy.TEntry")
        memory_input.pack(side="left", fill="x", expand=True, ipady=5)
        memory_list, refresh_memories, remove_memory = setup_list(
            memory_content, memory_items, lambda item: item,
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
        ttk.Button(memory_content, text="Remover selecionada", style="Secondary.TButton", command=remove_memory).pack(anchor="e", pady=(10, 0))

        history_card = card(
            history_content, "Histórico de conversa",
            "Veja as mensagens salvas, quando foram registradas e apague uma mensagem ou todo o histórico.",
        )
        history_status = tk.StringVar(value="")
        ttk.Label(history_card, textvariable=history_status, style="Hint.TLabel").pack(anchor="w")
        history_list_frame = ttk.Frame(history_content, style="Card.TFrame", padding=4)
        history_list_frame.pack(fill="both", expand=True, pady=(0, 10))
        history_view = tk.Text(
            history_list_frame, height=10, wrap="word", relief="flat", bd=0,
            padx=10, pady=8, spacing1=2, spacing3=5,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
            cursor="arrow", takefocus=True,
        )
        history_scrollbar = ttk.Scrollbar(
            history_list_frame, orient="vertical", command=history_view.yview,
        )
        history_view.configure(yscrollcommand=history_scrollbar.set)
        history_view.pack(side="left", fill="both", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        history_view.tag_configure(
            "history_header", foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        history_view.tag_configure("history_selected", background="#DFE6FA")
        history_entries = []
        selected_history = {"index": None}

        def scroll_history(event):
            if getattr(event, "num", None) == 4:
                history_view.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                history_view.yview_scroll(3, "units")
            elif event.delta:
                amount = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                if amount:
                    history_view.yview_scroll(amount * 3, "units")
            return "break"

        history_view.bind("<MouseWheel>", scroll_history)
        history_view.bind("<Button-4>", scroll_history)
        history_view.bind("<Button-5>", scroll_history)

        ttk.Label(history_content, text="Mensagem selecionada", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 5))
        history_detail_frame = ttk.Frame(history_content, style="Card.TFrame", padding=1)
        history_detail_frame.pack(fill="x", pady=(0, 10))
        history_detail = tk.Text(
            history_detail_frame, height=5, wrap="word", relief="flat", bd=0,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
        )
        history_detail_scrollbar = ttk.Scrollbar(
            history_detail_frame, orient="vertical", command=history_detail.yview,
        )
        history_detail.configure(yscrollcommand=history_detail_scrollbar.set)
        history_detail.pack(side="left", fill="both", expand=True)
        history_detail_scrollbar.pack(side="right", fill="y")
        history_detail.configure(state="disabled")

        def show_selected_history_message(index=None):
            if index is not None:
                selected_history["index"] = index
            index = selected_history["index"]
            content = ""
            if index is not None:
                try:
                    item = self.history[index]
                    stamp = item.get("timestamp")
                    if isinstance(stamp, str):
                        try:
                            local_time = datetime.fromisoformat(stamp).astimezone()
                            when = local_time.strftime("%d/%m/%Y às %H:%M:%S")
                        except ValueError:
                            when = "Data/hora não registrada"
                    else:
                        when = "Data/hora não registrada"
                    who = "Você" if item.get("role") == "user" else "Nova"
                    content = f"{who} · {when}\n\n{item.get('content', '')}"
                except (IndexError, ValueError):
                    pass
            history_detail.configure(state="normal")
            history_detail.delete("1.0", "end")
            history_detail.insert("1.0", content)
            history_detail.configure(state="disabled")

        def select_history_message(event):
            line = int(history_view.index(f"@{event.x},{event.y}").split(".")[0])
            for first_line, last_line, index, start, end in history_entries:
                if first_line <= line <= last_line:
                    selected_history["index"] = index
                    history_view.tag_remove("history_selected", "1.0", "end")
                    history_view.tag_add("history_selected", start, end)
                    show_selected_history_message(index)
                    break
            return "break"

        history_view.bind("<Button-1>", select_history_message)

        def refresh_history():
            history_view.configure(state="normal")
            history_view.delete("1.0", "end")
            history_entries.clear()
            for index in range(len(self.history) - 1, -1, -1):
                item = self.history[index]
                if not isinstance(item, dict):
                    continue
                stamp = item.get("timestamp")
                try:
                    when = datetime.fromisoformat(stamp).astimezone().strftime("%d/%m/%Y %H:%M")
                except (TypeError, ValueError):
                    when = "Sem data/hora"
                who = "Você" if item.get("role") == "user" else "Nova"
                message = item.get("content", "")
                if not isinstance(message, str):
                    message = str(message)
                message = message.strip() or "(mensagem vazia)"
                start = history_view.index("end-1c")
                first_line = int(start.split(".")[0])
                history_view.insert("end", f"{who} · {when}\n", "history_header")
                history_view.insert("end", f"{message}\n\n")
                end = history_view.index("end-1c")
                last_line = int(end.split(".")[0])
                history_entries.append((first_line, last_line, index, start, end))
            history_view.configure(state="disabled")
            selected_history["index"] = None
            history_status.set(f"{len(self.history)} mensagem(ns) salvas neste computador.")
            show_selected_history_message()

        def delete_history_message():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar mensagens.", parent=window)
                return
            index = selected_history["index"]
            if index is None:
                messagebox.showinfo("Selecione uma mensagem", "Escolha uma mensagem na lista para apagá-la.", parent=window)
                return
            removed = self.history.pop(index)
            if not save_history(self.history):
                self.history.insert(index, removed)
                messagebox.showerror("Erro ao salvar", "Não consegui apagar a mensagem do arquivo de histórico.", parent=window)
                return
            refresh_history()

        def clear_conversation_history():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar o histórico.", parent=window)
                return
            if not self.history:
                return
            if not messagebox.askyesno("Apagar histórico", "Apagar todas as mensagens salvas?", parent=window):
                return
            previous = self.history
            self.history = []
            if not save_history(self.history):
                self.history = previous
                messagebox.showerror("Erro ao salvar", "Não consegui apagar o arquivo de histórico.", parent=window)
            else:
                refresh_history()

        history_actions = ttk.Frame(history_content, style="Autonomy.TFrame")
        history_actions.pack(fill="x")
        ttk.Button(
            history_actions, text="Apagar mensagem selecionada", style="Secondary.TButton",
            command=delete_history_message,
        ).pack(side="left")
        ttk.Button(
            history_actions, text="Apagar todo o histórico", style="Secondary.TButton",
            command=clear_conversation_history,
        ).pack(side="right")
        history_refresh_callback["callback"] = refresh_history
        refresh_history()

        reminder_card = card(reminder_content, "Criar lembrete", "A data e hora seguem o relógio local deste computador.")
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
            reminder_content, reminder_items,
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
        ttk.Button(reminder_content, text="Remover selecionado", style="Secondary.TButton", command=remove_reminder).pack(anchor="e", pady=(10, 0))

        app_card = card(
            apps_content,
            "Permitir que a Nova abra um app",
            "Cadastre apenas apps que você reconhece. Você pode escolher se a Nova confirma cada abertura.",
        )
        ttk.Checkbutton(
            app_card,
            text="Perguntar antes de abrir um app",
            variable=confirm_app_launch,
        ).pack(anchor="w", pady=(0, 10))
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
        app_desktop_file = tk.StringVar()
        ttk.Label(app_form, text="Nome").grid(row=0, column=0, sticky="w")
        ttk.Entry(app_form, textvariable=app_name, width=18, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 7), ipady=4)
        ttk.Label(app_form, text="Comando executável").grid(row=0, column=1, sticky="w")
        app_command_input = ttk.Entry(app_form, textvariable=app_command, style="Autonomy.TEntry")
        app_command_input.grid(row=1, column=1, sticky="ew", pady=(3, 7), ipady=4)
        app_command_input.bind("<KeyRelease>", lambda _event: app_desktop_file.set(""))
        app_form.columnconfigure(1, weight=1)
        ttk.Label(
            app_form,
            text="Exemplos: firefox --new-window  ·  code .  ·  /usr/bin/gimp",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        app_error = tk.StringVar()
        app_error_label = ttk.Label(
            app_form, textvariable=app_error, foreground="#B42318",
            background="#F5F7FA", wraplength=360,
        )
        app_error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))
        app_buttons = ttk.Frame(app_form, style="Card.TFrame")
        app_buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        editing_app = {"index": None}
        app_list, refresh_apps, remove_app = setup_list(
            apps_content, app_items,
            lambda item: f"{item.get('name', '')}   ·   {item.get('command', '')}",
            "Selecione um app para editar ou remover. As alterações são salvas na hora.",
        )
        def clear_app_form():
            editing_app["index"] = None
            app_name.set("")
            app_command.set("")
            app_desktop_file.set("")
            app_error.set("")
            app_error_label.configure(foreground="#B42318")
            save_app_button.configure(text="Adicionar app")
            remove_app_button.configure(state="disabled")
            app_list.selection_clear(0, "end")

        def select_app(_event=None):
            selected = app_list.curselection()
            if not selected:
                return
            index = selected[0]
            editing_app["index"] = index
            app_name.set(app_items[index]["name"])
            app_command.set(app_items[index]["command"])
            app_desktop_file.set(app_items[index].get("desktop_file", ""))
            app_error.set("")
            save_app_button.configure(text="Salvar edição")
            remove_app_button.configure(state="normal")

        def open_app_picker():
            picker = self._set_nova_window_icon(tk.Toplevel(window))
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
            horizontal_scrollbar = ttk.Scrollbar(
                result_frame, orient="horizontal", command=result_list.xview,
            )
            result_list.configure(
                yscrollcommand=scrollbar.set,
                xscrollcommand=horizontal_scrollbar.set,
            )
            result_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=7)
            scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=7)
            horizontal_scrollbar.pack(side="bottom", fill="x", padx=8, pady=(0, 7))
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
                app_desktop_file.set(app.get("desktop_file", ""))
                app_error.set("")
                editing_app["index"] = None
                save_app_button.configure(text="Adicionar app")
                remove_app_button.configure(state="disabled")
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
            return name, command, argv, app_desktop_file.get().strip()

        def persist_app_items():
            updated = dict(self.settings)
            updated["apps"] = [dict(item) for item in app_items]
            if not save_settings(updated):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui salvar os apps. Confira as permissões e tente novamente.")
                return False
            self.settings = updated
            return True

        def save_app():
            values = validate_app_form()
            if not values:
                return
            name, command, _argv, desktop_file = values
            index = editing_app["index"]
            previous_items = [dict(item) for item in app_items]
            saved_app = {"name": name, "command": command}
            if desktop_file:
                saved_app["desktop_file"] = desktop_file
            if index is None:
                app_items.append(saved_app)
            else:
                app_items[index] = saved_app
            refresh_apps()
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        def test_app_command():
            values = validate_app_form()
            if not values:
                return
            name, command, argv, desktop_file = values
            try:
                self._launch_app(
                    {"name": name, "command": command, "desktop_file": desktop_file},
                    question="",
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui iniciar esse aplicativo agora.")
                self._show_oops()
                return
            app_error_label.configure(foreground="#287247")
            app_error.set(f"Comando enviado ao sistema para abrir {name}.")

        def remove_selected_app():
            previous_items = [dict(item) for item in app_items]
            remove_app()
            if previous_items == app_items:
                return
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        app_list.bind("<<ListboxSelect>>", select_app)
        save_app_button = ttk.Button(app_buttons, text="Adicionar app", style="Primary.TButton", command=save_app)
        save_app_button.pack(side="right")
        ttk.Button(app_buttons, text="Testar comando", style="Secondary.TButton", command=test_app_command).pack(side="right", padx=(0, 8))
        ttk.Button(app_buttons, text="Novo app", style="Secondary.TButton", command=clear_app_form).pack(side="left")
        remove_app_button = ttk.Button(
            app_buttons,
            text="Remover app",
            style="Secondary.TButton",
            command=remove_selected_app,
            state="disabled",
        )
        remove_app_button.pack(side="left", padx=(8, 0))

        def start_focus_from_settings():
            if self.focus_mode != "idle" or self.ai_request_active or self.dragging:
                focus_status.set("Não consigo iniciar outra sessão enquanto estou ocupada.")
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Informe durações em minutos.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            save_and_close((focus_goal.get(), duration, pause))

        footer = ttk.Frame(outer, style="Autonomy.TFrame")
        footer.pack(fill="x", pady=(14, 0))

        def save_and_close(focus_params=None):
            try:
                for value in (quiet_start.get(), quiet_end.get()):
                    time.strptime(value, "%H:%M")
            except ValueError:
                select_tab(behavior_tab)
                messagebox.showerror("Horário inválido", "Use HH:MM nos horários de silêncio.", parent=window)
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
                time.strptime(evening_time.get(), "%H:%M")
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Valor inválido", "Confira as durações e use HH:MM no horário de encerramento.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            try:
                timeout_value = int(ai_timeout.get())
            except ValueError:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            if not 5 <= timeout_value <= 30:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            updated = dict(self.settings)
            updated.update(
                mode=mode.get(), quiet_start=quiet_start.get(), quiet_end=quiet_end.get(),
                memories=memory_items, reminders=reminder_items, apps=app_items,
                confirm_app_launch=confirm_app_launch.get(),
                auto_speech=speech.get(), observe_apps=observe.get(), auto_sit=auto_sit.get(),
                peekaboo=peekaboo.get(),
                focus_minutes=duration, break_minutes=pause,
                routine_greeting=routine_greeting.get(),
                routine_context=routine_context.get(),
                routine_idle_yawn=routine_idle_yawn.get(),
                routine_focus_celebration=routine_focus_celebration.get(),
                routine_note=routine_note.get(),
                routine_surprise=routine_surprise.get(),
                routine_evening=routine_evening.get(), evening_time=evening_time.get(),
                routine_dance=routine_dance.get(),
                routine_break_tip=routine_break_tip.get(),
                ai_provider=ai_provider.get(), online_ai_enabled=online_ai_enabled.get(),
                allow_online_data=allow_online_data.get(),
                confirm_free_tier=confirm_free_tier.get(), ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                gemini_model=gemini_model.get().strip(), groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
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
            if routine_greeting.get() and not self._routine_greeted:
                self.root.after(500, self.show_start_greeting)
            if routine_context.get():
                self.root.after(1000, self.show_context_greeting)
            if focus_params:
                self.start_focus(*focus_params)
            else:
                self.show_bubble("Preferências atualizadas.", duration=2500)

        ttk.Button(footer, text="Cancelar", style="Secondary.TButton", command=window.destroy).pack(side="right")
        ttk.Button(footer, text="Salvar alterações", style="Primary.TButton", command=save_and_close).pack(side="right", padx=(0, 8))
        if selected_tab == "routine":
            select_tab(routine_tab)
        elif selected_tab == "memory":
            select_tab(memory_tab)
        elif selected_tab == "reminder":
            select_tab(reminder_tab)
        elif selected_tab == "apps":
            select_tab(apps_tab)
        elif selected_tab == "computer":
            select_tab(computer_tab)
        elif selected_tab == "ai":
            select_tab(ai_tab)
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
        available = (
            self.state == "walk"
            and self._can_speak_spontaneously()
            and can_speak_spontaneously()
        )
        due = []
        for item in self.settings.get("reminders", []):
            parsed = valid_reminder_time(item.get("at")) if isinstance(item, dict) else None
            if (available and parsed and not item.get("done")
                    and parsed.timestamp() <= now):
                item["done"] = True
                due.append(item.get("text", "Você tem um lembrete."))
        if due:
            save_settings(self.settings)
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
        if not self._show_spontaneous_pose(category, "greeting", duration=6500):
            self.root.after(60000, self.show_start_greeting)
            return
        self._routine_greeted = True
        self._miss_you_pending = False
        self.settings["last_context_date"] = datetime.now().astimezone().date().isoformat()
        save_settings(self.settings)
        self._schedule_pose_callback(
            round(VIDEO_REACTION_SECONDS * 1000),
            "greeting",
            self.finish_greeting,
        )

    def finish_greeting(self):
        if not self._closing and self.state == "greeting":
            self.state = "walk"

    def show_context_greeting(self):
        if self._closing or not self.settings.get("routine_context"):
            return
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        if self.settings.get("last_context_date") == today:
            return
        if self._routine_greeted:
            self.settings["last_context_date"] = today
            save_settings(self.settings)
            return
        category = "miss_you" if self._miss_you_pending else "greeting"
        if not self._show_spontaneous_pose(category, "greeting", duration=6500):
            self.root.after(60000, self.show_context_greeting)
            return
        self._routine_greeted = True
        self._miss_you_pending = False
        self.settings["last_context_date"] = today
        save_settings(self.settings)
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
            save_settings(self.settings)
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
            and can_speak_spontaneously()
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
            and now - self._last_break_tip_at >= 50 * 60
            and self.state == "walk"
            and self._can_speak_spontaneously()
            and can_speak_spontaneously()
        )
        if available and self._show_spontaneous_pose(
            "break_tip", "thumbs_up", duration=6500
        ):
            self._last_break_tip_at = now
            self._thumbs_up_started_at = now
            self._schedule_pose_return(
                round(THUMBS_UP_ANIMATION_SECONDS * 1000), "thumbs_up"
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
                and can_speak_spontaneously()):
            self.settings["last_evening_date"] = today
            save_settings(self.settings)
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
            and can_speak_spontaneously()
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
                save_settings(self.settings)
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
        if not self._can_speak_spontaneously(allow_focus=True) or not can_speak_spontaneously():
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

    def _matching_app(self, question):
        def get_installed_apps():
            if getattr(self, "_installed_apps_cache", None) is None:
                try:
                    self._installed_apps_cache = find_installed_apps()
                except OSError:
                    self._installed_apps_cache = []
            return self._installed_apps_cache

        return match_registered_app(
            question,
            self.settings.get("apps", []),
            get_installed_apps,
        )

    @staticmethod
    def _app_open_target(question):
        return parse_app_open_target(question)

    @classmethod
    def _is_app_open_request(cls, question):
        return parse_app_open_request(question)

    def _looks_like_app_target(self, question):
        return parse_app_target(question)

    def _confirm_open_app(self, question, app):
        if getattr(self, "app_launch_active", False):
            self.show_bubble("Já estou abrindo um aplicativo.", duration=2500)
            return
        if self.settings.get("confirm_app_launch", True):
            confirmation = (
                f"A Nova vai executar este comando:\n\n{app['command']}\n\n"
                f"Abrir {app['name']} agora?"
            )
            if not messagebox.askyesno("Confirmar abertura", confirmation, parent=self.root):
                return
        self.app_launch_active = True
        self.show_bubble(f"Abrindo {app['name']}…", duration=999999)
        threading.Thread(
            target=self._app_launch_worker,
            args=(question, app),
            daemon=True,
        ).start()

    def _app_launch_worker(self, question, app):
        try:
            self._launch_app(app, question)
            success = True
        except subprocess.TimeoutExpired:
            self._app_launch_results.put((
                question,
                f"A abertura de {app.get('name', 'app')} ainda está em andamento.",
            ))
            return
        except (OSError, ValueError, subprocess.SubprocessError):
            success = False
        self._app_launch_results.put((question, success))

    def _drain_app_launch_results(self):
        try:
            question, success = self._app_launch_results.get_nowait()
        except queue.Empty:
            return
        self.app_launch_active = False
        if not self._closing:
            if getattr(self, "busy", False):
                self.hide_bubble()
            if self._interaction_speech_allowed():
                if isinstance(success, str):
                    answer = success
                else:
                    category = "app_launch_ok" if success else "oops"
                    answer = pick_line(
                        category, name=self.settings.get("user_name", ""),
                        rng=random, history=getattr(self, "_speech_history", []),
                    )
                    self.state = "thumbs_up" if success else "curious"
                    if success:
                        self._thumbs_up_started_at = time.monotonic()
                    self._schedule_pose_return(
                        round(THUMBS_UP_ANIMATION_SECONDS * 1000)
                        if success else 3000,
                        "thumbs_up" if success else "curious",
                    )
                answer = self._record_local_interaction(question, answer)
                self.show_bubble(answer)

    @staticmethod
    def _child_process_env():
        return {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}

    @staticmethod
    def _launch_app(app, question=""):
        desktop_file = app.get("desktop_file")
        if desktop_file:
            argv = ["gio", "launch", desktop_file]
            app_name = app.get("name", "").casefold()
            lowered_question = question.casefold()
            if (
                "google chrome" in app_name
                and re.search(r"\bgoogle\b", lowered_question)
                and not re.search(r"\bchrome\b", lowered_question)
            ):
                argv.append("https://www.google.com")
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=DesktopPet._child_process_env(),
            )
            if result.returncode:
                details = (result.stderr or result.stdout or "").strip()
                raise OSError(details or f"gio launch terminou com código {result.returncode}")
            return

        argv = resolve_app_command(app["command"])
        subprocess.Popen(argv, close_fds=True, env=DesktopPet._child_process_env())

    def close_app(self):
        self._closing = True
        loader = getattr(self, "_animation_loader", None)
        if loader is not None:
            loader.close()
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

    def ask_user_name(self):
        if self._closing or self.settings.get("user_name") or self._user_name_dialog:
            return
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._user_name_dialog = dialog
        dialog.title("Como devo chamar você?")
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg="#E3E8F0")
        style = ttk.Style(dialog)
        style.configure("Autonomy.TFrame", background="#E3E8F0")
        style.configure("Title.TLabel", background="#E3E8F0", foreground="#202B45", font=("TkDefaultFont", 14, "bold"))
        style.configure("Subtitle.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("Autonomy.TEntry", fieldbackground="#EDF0F5", foreground="#26344A", padding=4)
        style.configure("Primary.TButton", padding=(14, 8), font=("TkDefaultFont", 9, "bold"))
        style.configure("Secondary.TButton", padding=(12, 8))
        frame = ttk.Frame(dialog, style="Autonomy.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Oi! Eu sou a Nova", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame, text="Como você gostaria que eu te chamasse? Vou guardar seu nome para nossas próximas conversas.",
            style="Subtitle.TLabel", wraplength=360,
        ).pack(anchor="w", pady=(6, 14))
        name = tk.StringVar()
        name_entry = ttk.Entry(frame, textvariable=name, style="Autonomy.TEntry", width=36)
        name_entry.pack(fill="x", ipady=5)
        error = tk.StringVar()
        ttk.Label(frame, textvariable=error, style="Hint.TLabel", foreground="#B42318").pack(anchor="w", pady=(5, 0))
        buttons = ttk.Frame(frame, style="Autonomy.TFrame")
        buttons.pack(fill="x", pady=(14, 0))

        def close_dialog():
            self._user_name_dialog = None
            try:
                dialog.destroy()
            except tk.TclError:
                pass

        def save_name():
            value = name.get().strip()
            if not value:
                error.set("Escreva seu nome para eu poder guardá-lo.")
                name_entry.focus_set()
                return
            updated = dict(self.settings)
            updated["user_name"] = value[:60]
            if not save_settings(updated):
                error.set("Não consegui salvar agora. Confira as permissões e tente novamente.")
                return
            self.settings = updated
            close_dialog()
            if hasattr(self, "_user_name_display_var"):
                self._user_name_display_var.set(f"Seu nome: {updated['user_name']} · protegido")
            self.show_bubble(f"Prazer em conhecer você, {updated['user_name']}! Vou lembrar do seu nome.", duration=7000)
            if self.settings.get("routine_greeting") and not self._routine_greeted:
                self.root.after(7500, self.show_start_greeting)
            if self.settings.get("routine_context"):
                self.root.after(8000, self.show_context_greeting)

        ttk.Button(buttons, text="Agora não", style="Secondary.TButton", command=close_dialog).pack(side="right")
        ttk.Button(buttons, text="Guardar nome", style="Primary.TButton", command=save_name).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.bind("<Return>", lambda _event: save_name())
        dialog.bind("<Escape>", lambda _event: close_dialog())
        dialog.update_idletasks()
        x = max(0, (self.screen_w - dialog.winfo_reqwidth()) // 2)
        y = max(0, (self.screen_h - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        name_entry.focus_set()

    # ---------- integração com a IA local ----------
    def ask_menu(self, event=None):
        self._last_user_activity_at = time.monotonic()
        if event is not None:
            self._handle_double_click()
            return "break"
        if self.ai_request_active:
            self.show_bubble("Já estou respondendo sua pergunta!", duration=2500)
            return
        question = self._ask_question()
        if not question:
            return
        self._record_interaction()
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
        local_intent = local_personality_intent(question)
        if local_intent:
            category, animation = local_intent
            self._handle_local_personality(category, animation)
            return
        app = self._matching_app(question)
        if app:
            self._confirm_open_app(question, app)
            return
        if self._is_app_open_request(question) and self._looks_like_app_target(question):
            answer = pick_line(
                "oops", name=self.settings.get("user_name", ""),
                rng=random, history=self._speech_history,
            )
            self._record_local_interaction(question, answer)
            if self._interaction_speech_allowed():
                self.state = "curious"
                self._schedule_pose_callback(
                    3500, "curious", self.finish_curious
                )
                self.show_bubble(answer)
            return
        self.history.append({
            "role": "user", "content": question,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        request_history = list(self.history)
        self.ai_request_active = True
        self.state = "thinking"
        self._show_idea_icon = False
        self._thinking_started_at = time.monotonic()
        self.show_bubble("pensando...", duration=999999)
        memories = list(self.settings.get("memories", []))
        user_name = self.settings.get("user_name", "").strip()[:60]
        threading.Thread(
            target=self._ask_worker,
            args=(request_history, memories, dict(self.settings), user_name),
            daemon=True,
        ).start()

    def _record_local_interaction(self, question, answer):
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.history.extend((
            {"role": "user", "content": question, "timestamp": timestamp},
            {"role": "assistant", "content": answer, "timestamp": timestamp},
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
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
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
        answer.focus_set()
        self.root.wait_window(dialog)
        return result["question"]

    def _ask_worker(self, history, memories=None, settings=None, user_name=""):
        self._ai_results.put(answer_request(
            history, memories=memories, settings=settings or self.settings,
            user_name=user_name,
        ))

    def _provider_test_worker(self, provider_name, settings, window, status_var, button, button_state):
        try:
            provider = create_provider(provider_name, settings)
            result = provider.test_connection(timeout=min(15, settings.get("ai_timeout", 10)))
        except ProviderError as exc:
            result = str(exc)
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no teste do provedor de IA")
            result = "O teste de conexão falhou por um erro inesperado."
        self._provider_test_results.put((window, status_var, button, result, button_state))

    def _drain_provider_test_results(self):
        try:
            window, status_var, button, result, button_state = self._provider_test_results.get_nowait()
        except queue.Empty:
            return
        button_state["running"] = False
        try:
            if window.winfo_exists():
                status_var.set(result)
                button.configure(state="normal")
        except tk.TclError:
            pass

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
        self.history.append({
            "role": "assistant", "content": answer,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        history_saved = save_history(self.history)
        failed = answer == PROVIDER_FAILURE_MESSAGE
        self.state = "curious" if failed else "walk"
        self._show_idea_icon = True
        if failed:
            answer = pick_line(
                "oops", name=self.settings.get("user_name", ""),
                rng=random, history=self._speech_history,
            )
            self._schedule_pose_callback(3500, "curious", self.finish_curious)
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
    log_dir = Path.home() / ".local" / "state" / "desktop_pet"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler(log_dir / "nova.log", encoding="utf-8"), logging.StreamHandler()],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
