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
from collections import deque
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
from automations import AUTOMATIONS, preview_downloads, preview_duplicate_removals, preview_empty_trash, preview_screenshots, recognize_automation
from config import (
    APP_COMMENTS,
    BASE_HEIGHT,
    FONT_BUBBLE,
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
from desktop_pet_ui import DesktopPetUIMixin
from event_bus import Event, EventBus, EventType
from state_manager import StateManager
from plugin_manager import PluginManager
from permissions import PermissionManager
from notifications import NotificationManager, NotificationCategory
from system_monitor import SystemMonitor
from spotify_control import (
    SpotifyError,
    connect_spotify as spotify_connect,
    execute_spotify_action,
    parse_spotify_command,
    playlist_uri_from_input,
    spotify_connected as spotify_token_connected,
)

# ---------------------------------------------------------------------------
# Personagem
# ---------------------------------------------------------------------------
class DesktopPet(DesktopPetUIMixin):
    @property
    def state(self):
        return getattr(self, "_state", "idle")

    @state.setter
    def state(self, value):
        previous = getattr(self, "_state", None)
        self._state = value
        self._state_generation = getattr(self, "_state_generation", 0) + 1
        self._state_started_at = time.monotonic()
        manager = getattr(self, "state_manager", None)
        if manager is not None:
            manager.transition(value, force=True)
        bus = getattr(self, "event_bus", None)
        if bus is not None and previous != value:
            bus.post(Event(EventType.PET_STATE_CHANGED, {"previous": previous, "current": value}))

    def __init__(self):
        self.history = load_history()
        self.settings = load_settings()
        self._recent_errors = deque(maxlen=20)
        self.event_bus = EventBus()
        self.state_manager = StateManager()
        self.permission_manager = PermissionManager()
        self.plugin_manager = PluginManager(context={"event_bus": self.event_bus,
                                                     "permissions": self.permission_manager},
                                            event_bus=self.event_bus)
        self.notification_manager = NotificationManager(event_bus=self.event_bus)
        self.system_monitor = SystemMonitor()
        self.event_bus.subscribe(EventType.AI_RESPONSE_RECEIVED, self._on_ai_response_event)
        self.event_bus.subscribe(EventType.APP_LAUNCH_RESULT, self._on_app_launch_event)
        self.event_bus.subscribe(EventType.TASK_FINISHED, self._on_automation_event)
        self.event_bus.subscribe(EventType.TASK_FAILED, self._on_automation_event)
        self.event_bus.subscribe(EventType.AI_REQUEST_FAILED, self._on_ai_failure_event)
        self.event_bus.subscribe(EventType.AI_REQUEST_STARTED, self._on_ai_started_event)
        self.event_bus.subscribe(EventType.PLUGIN_FAILED, self._on_plugin_failure_event)
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
        self._ui_callbacks = queue.Queue()
        self._provider_test_results = queue.Queue()
        self._app_launch_results = queue.Queue()
        self.automation_active = False
        self._battery_check_results = queue.Queue()
        self._device_event_results = queue.Queue()
        self._pending_device_announcements = []
        self._device_monitor_stop = threading.Event()
        self._device_monitor_thread = None
        self._device_announcement_retry_job = None
        self._spotify_results = queue.Queue()
        self._spotify_action_active = False
        self._battery_check_active = False
        self._low_battery_alerted = False
        self._low_battery_pending = False
        self._low_battery_percent = None
        self._low_battery_retry_job = None
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
        self._last_character_sprite = None
        self._active_video_name = None
        self._transition_from_sprite = None
        self._transition_started_at = 0.0
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
        first_speech_delay = (
            random.randint(90000, 150000)
            if self.settings["mode"] == "proativa"
            else random.randint(180000, 300000)
        )
        self.root.after(first_speech_delay, self.random_speech)
        self.root.after(random.randint(15000, 30000), self.observe_apps)
        self.root.after(random.randint(30000, 60000), self.peekaboo)
        self.root.after(random.randint(20000, 40000), self.maybe_sit)
        self.root.after(15000, self.check_reminders)
        self.root.after(10000, self.check_low_battery)
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

        video, _, sprite = self._current_video_frame()
        now = time.monotonic()
        if video != self._active_video_name:
            if self._last_character_sprite is not None:
                self._transition_from_sprite = self._last_character_sprite.copy()
                self._transition_started_at = now
            self._active_video_name = video
        sprite = sprite.resize(
            (sprite.width * SCALE, sprite.height * SCALE),
            Image.Resampling.NEAREST,
        )
        # Cruzamento curto entre o último quadro e o novo clipe evita cortes
        # secos quando a personagem muda de ação.
        transition_progress = min(
            1.0, max(0.0, (now - self._transition_started_at) / 0.14)
        )
        if self._transition_from_sprite is not None:
            if transition_progress < 1.0:
                previous = self._transition_from_sprite
                if previous.size != sprite.size:
                    previous = previous.resize(sprite.size, Image.Resampling.NEAREST)
                sprite = Image.blend(previous, sprite, transition_progress)
            else:
                self._transition_from_sprite = None
        self._last_character_sprite = sprite.copy()
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
        sway = 0
        if self.state == "walk" and not self.busy and not self.stay_in_place_var.get():
            bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        elif self.state == "idle":
            # Respiração lenta e pequena, para o idle não ficar visualmente
            # congelado entre os movimentos já presentes no clipe.
            phase = self.animation_time_ms / 1000 * 1.7
            bob = int((0.5 + 0.5 * math.sin(phase)) * SCALE)
            sway = int(math.sin(phase * 0.5) * SCALE)
        elif self.state == "held":
            bob = int(math.sin(self.animation_time_ms / 1000 * 5) * 2 * SCALE)

        x = int((w - sprite.width) / 2 + sway)
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
        sway = 0
        if self.state == "walk" and not self.busy and not self.stay_in_place_var.get():
            bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        elif self.state == "idle":
            phase = self.animation_time_ms / 1000 * 1.7
            bob = int((0.5 + 0.5 * math.sin(phase)) * SCALE)
            sway = int(math.sin(phase * 0.5) * SCALE)
        elif self.state == "held":
            bob = int(math.sin(self.animation_time_ms / 1000 * 5) * 2 * SCALE)
        transition_step = (
            min(14, max(0, int((now - self._transition_started_at) * 100)))
            if self._transition_from_sprite is not None else 14
        )
        return (
            self._needed_height(), self.state, self.bubble_text, self.busy,
            self.dragging, video, frame_index, bob, sway, transition_step,
            round(self.drag_tilt, 1),
            self._show_idea_icon,
        )

    def _video_frame_cache_key(self):
        if self.state != "walk" or self.busy or self.dragging or self.bubble_text:
            return None
        if self._transition_from_sprite is not None:
            return None
        video, frame_index, _ = self._current_video_frame()
        if video != self._active_video_name:
            return None
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
    def post_ui_callback(self, callback, *args, **kwargs):
        """Schedule a UI callback from any worker for execution by ``tick``."""
        if self._closing or not callable(callback):
            return False
        self._ui_callbacks.put((callback, args, kwargs))
        return True

    def _drain_ui_callbacks(self):
        callbacks = getattr(self, "_ui_callbacks", None)
        if callbacks is None or getattr(self, "_closing", False):
            return
        while True:
            try:
                callback, args, kwargs = callbacks.get_nowait()
            except queue.Empty:
                return
            try:
                callback(*args, **kwargs)
            except Exception:
                logger.exception("Falha ao processar retorno de worker na thread Tkinter")

    def tick(self):
        now = time.monotonic()
        self._drain_ui_callbacks()
        event_bus = getattr(self, "event_bus", None)
        if event_bus is not None:
            event_bus.drain()
        self._drain_animation_results()
        if hasattr(self, "_provider_test_results"):
            self._drain_provider_test_results()
        if hasattr(self, "_app_launch_results"):
            self._drain_app_launch_results()
        if hasattr(self, "_battery_check_results"):
            self._drain_low_battery_results()
        if hasattr(self, "_device_event_results"):
            self._drain_device_event_results()
        if hasattr(self, "_spotify_results"):
            self._drain_spotify_results()
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

        if event_bus is not None:
            animation_name = self._video_for_current_pose(now)
            previous_animation = getattr(self, "_last_event_animation", None)
            if animation_name != previous_animation:
                if previous_animation is not None:
                    finished = previous_animation in ONE_SHOT_VIDEOS
                    event_bus.publish(Event(
                        EventType.ANIMATION_FINISHED if finished else EventType.ANIMATION_CANCELLED,
                        {"animation": previous_animation},
                    ))
                event_bus.publish(Event(EventType.ANIMATION_STARTED,
                                        {"animation": animation_name, "state": self.state}))
                self._last_event_animation = animation_name

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
                event_bus = getattr(self, "event_bus", None)
                if event_bus is not None:
                    event_bus.publish(Event(EventType.ANIMATION_LOAD_FAILED,
                                            {"animation": name, "error": error}))
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
        interval = (90000, 150000) if self.settings["mode"] == "proativa" else (180000, 300000)
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
                and self._can_speak_spontaneously() and self._spontaneous_ready()):
            self._show_personality_line(
                "peekaboo", duration=2500, spontaneous=True
            )

    # ---------- sentar cansada em cima de uma janela ----------
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

    # ---------- balão de fala ----------
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
            and self._spontaneous_ready()
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
        save_settings(self.settings)
        if label is not None:
            try:
                label.configure(text=message)
            except tk.TclError:
                pass
        if self.state == "curious":
            self._schedule_pose_return(3500, "curious")

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
        if self.settings.get("confirm_app_launch", False):
            confirmation = (
                f"A Nova vai executar este comando:\n\n{app['command']}\n\n"
                f"Abrir {app['name']} agora?"
            )
            if not messagebox.askyesno("Confirmar abertura", confirmation, parent=self.root):
                return
        try:
            self._authorize_core_action("system.app.launch", confirmed=True)
        except (PermissionError, OSError) as exc:
            self.show_bubble(f"Não posso abrir esse aplicativo: {exc}", duration=4000)
            return
        self.app_launch_active = True
        self.show_bubble(f"Abrindo {app['name']}…", duration=999999)
        threading.Thread(
            target=self._app_launch_worker,
            args=(question, app),
            daemon=True,
        ).start()

    def _app_launch_worker(self, question, app):
        def deliver(success, detail=""):
            event_bus = getattr(self, "event_bus", None)
            if event_bus is not None:
                event_bus.post(Event(EventType.APP_LAUNCH_RESULT, {
                    "question": question, "success": success, "detail": detail,
                }))
            elif hasattr(self, "_app_launch_results"):
                self._app_launch_results.put((question, success, detail))
        try:
            permissions = getattr(self, "permission_manager", None)
            if permissions is not None:
                permissions.require("nova.core", "system.app.launch", confirmed=True)
            self._launch_app(app, question)
            deliver(True)
        except subprocess.TimeoutExpired:
            deliver(False, f"O sistema demorou demais para abrir {app.get('name', 'o aplicativo')}. Tente novamente.")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            detail = str(exc).strip() or type(exc).__name__
            deliver(False, f"Não consegui abrir {app.get('name', 'o aplicativo')}: {detail[:350]}")

    def _drain_app_launch_results(self):
        if getattr(self, "event_bus", None) is not None:
            return
        try:
            question, success, detail = self._app_launch_results.get_nowait()
        except queue.Empty:
            return
        self._handle_app_launch_result(question, success, detail)

    def _on_app_launch_event(self, event):
        self._handle_app_launch_result(event.payload.get("question", ""),
                                       bool(event.payload.get("success")),
                                       str(event.payload.get("detail", "")))

    def _handle_app_launch_result(self, question, success, detail):
        self.app_launch_active = False
        if self._closing:
            return
        if getattr(self, "busy", False):
            self.hide_bubble()
        if not self._interaction_speech_allowed():
            return
        if detail:
            answer = detail
        else:
            category = "app_launch_ok" if success else "oops"
            answer = pick_line(
                category, name=self.settings.get("user_name", ""),
                rng=random, history=getattr(self, "_speech_history", []),
            )
        if not success:
            errors = getattr(self, "_recent_errors", None)
            if errors is not None:
                errors.append({"source": "app_launch", "error": detail[:200], "timestamp": time.time()})
        self.state = "thumbs_up" if success else "curious"
        if success:
            self._thumbs_up_started_at = time.monotonic()
        self._schedule_pose_return(
            round(THUMBS_UP_ANIMATION_SECONDS * 1000) if success else 3000,
            "thumbs_up" if success else "curious",
        )
        answer = self._record_local_interaction(question, answer)
        self.show_bubble(answer)

    @staticmethod
    def _child_process_env():
        secret_suffixes = ("_API_KEY", "_KEY", "_SECRET", "_TOKEN", "_PASSWORD")
        return {
            key: value
            for key, value in os.environ.items()
            if not any(key.upper().endswith(suffix) for suffix in secret_suffixes)
        }

    def _request_automation(self, automation):
        if not any(automation is allowed for allowed in AUTOMATIONS):
            return
        if getattr(self, "ai_request_active", False) or getattr(self, "app_launch_active", False):
            self.show_bubble("Termino o que estou fazendo e já cuido disso.", duration=2500)
            return
        enabled = self.settings.get("automations", {}).get("enabled", {}).get(automation["id"], True)
        if not enabled:
            self.show_bubble("Essa automação está desativada nas preferências.", duration=3000)
            return
        read_permission = "system.cpu.read" if automation.get("read_only") and automation["id"] == "laptop_status" else "file.read"
        try:
            self._authorize_core_action(read_permission, confirmed=False)
            self.permission_manager.require("nova.core", read_permission, confirmed=False)
        except (PermissionError, OSError) as exc:
            self.show_bubble(f"Permissão necessária para essa automação: {exc}", duration=4000)
            return
        if self.automation_active:
            self.show_bubble("Já estou cuidando de uma automação.", duration=2500)
            return
        if automation["id"] in ("trash_duplicates", "empty_trash"):
            self.automation_active = True
            for button in getattr(self, "_automation_action_buttons", {}).values():
                button.configure(state="disabled")
            self.state = "thinking"
            message = "Estou comparando os arquivos…" if automation["id"] == "trash_duplicates" else "Estou conferindo a Lixeira…"
            self.show_bubble(message, duration=999999)
            threading.Thread(target=self._automation_preview_worker, args=(automation["id"],), daemon=True).start()
            return
        if automation["id"] in ("organize_downloads", "organize_screenshots", "empty_trash"):
            try:
                operations = (
                    preview_downloads() if automation["id"] == "organize_downloads" else
                    preview_screenshots() if automation["id"] == "organize_screenshots" else
                    preview_empty_trash()
                )
            except (OSError, ValueError) as exc:
                self._finish_automation(automation["id"], {"title": "Não consegui ler os arquivos", "lines": [str(exc)], "status": "error"})
                return
            if not operations:
                empty_titles = {"organize_downloads": "Downloads já está em ordem", "organize_screenshots": "Nenhuma captura para organizar", "empty_trash": "A Lixeira já está vazia"}
                self._finish_automation(automation["id"], {"title": empty_titles[automation["id"]], "lines": ["Não encontrei itens para esta ação."], "status": "ok"})
                return
            if not self._confirm_automation_plan(operations):
                return
            confirmed_plan = tuple(operations)
        else:
            confirmed_plan = None
        self.automation_active = True
        for button in getattr(self, "_automation_action_buttons", {}).values():
            button.configure(state="disabled")
        self.state = "thinking"
        self._thinking_started_at = time.monotonic()
        self.show_bubble("Estou cuidando disso…", duration=999999)
        threading.Thread(target=self._automation_worker, args=(automation, confirmed_plan), daemon=True).start()

    def _automation_preview_worker(self, automation_id):
        try:
            operations = preview_duplicate_removals() if automation_id == "trash_duplicates" else preview_empty_trash()
            result = {"title": "Prévia de cópias", "lines": [], "status": "preview", "plan": operations}
        except Exception as exc:
            logging.warning("Prévia da automação %s falhou (%s)", automation_id, type(exc).__name__)
            result = {"title": "Não consegui preparar a prévia", "lines": [f"Ocorreu um erro ({type(exc).__name__})."], "status": "error"}
        event_type = EventType.TASK_FINISHED if result.get("status") == "preview" else EventType.TASK_FAILED
        self.event_bus.post(Event(event_type, {"automation_id": automation_id, "result": result}))

    def _confirm_automation_plan(self, operations):
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
        dialog.title("Prévia · Organizar Downloads")
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.resizable(True, True)
        x, y, width, height = self._question_dialog_geometry(460, 420)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        accepted = {"value": False}
        outer = ttk.Frame(dialog, style="Autonomy.TFrame", padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Confira antes de organizar", style="Title.TLabel").pack(anchor="w")
        irreversible = any(isinstance(target, str) and target.startswith("apagar definitivamente") for _source, target in operations)
        moving_to_trash = any(isinstance(target, str) and target.startswith("Mover para a Lixeira") for _source, target in operations)
        description = f"{len(operations)} item(ns) serão removidos definitivamente da Lixeira." if irreversible else f"{len(operations)} cópia(s) serão movidas para a Lixeira. Você poderá restaurá-las." if moving_to_trash else f"{len(operations)} arquivo(s) serão movidos. Nenhum arquivo será substituído."
        ttk.Label(outer, text=description, style="Subtitle.TLabel", wraplength=max(240, width - 40)).pack(anchor="w", pady=(4, 9))
        list_card = ttk.Frame(outer, style="Card.TFrame", padding=5)
        list_card.pack(fill="both", expand=True)
        listing = tk.Text(list_card, height=12, wrap="word", relief="flat", bd=0, padx=8, pady=7, bg="#F5F7FA", fg="#26344A", insertbackground="#26344A", font="TkDefaultFont", state="normal")
        scrollbar = ttk.Scrollbar(list_card, orient="vertical", command=listing.yview)
        listing.configure(yscrollcommand=scrollbar.set)
        listing.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for source, target in operations:
            destination = target if isinstance(target, str) else f"{target.parent.name}/{target.name}"
            listing.insert("end", f"{source.name}\n    → {destination}\n")
        listing.configure(state="disabled")
        button_row = ttk.Frame(outer, style="Autonomy.TFrame")
        button_row.pack(fill="x", pady=(10, 0))
        def decide(value):
            accepted["value"] = value
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
        ttk.Button(button_row, text="Cancelar", style="Secondary.TButton", command=lambda: decide(False)).pack(side="right")
        confirm_text = "Esvaziar a Lixeira" if irreversible else "Mover cópias para a Lixeira" if moving_to_trash else "Confirmar organização"
        ttk.Button(button_row, text=confirm_text, style="Primary.TButton", command=lambda: decide(True)).pack(side="right", padx=(0, 7))
        dialog.protocol("WM_DELETE_WINDOW", lambda: decide(False))
        dialog.grab_set()
        dialog.wait_window()
        return accepted["value"]

    def _request_automation_undo(self):
        automation = next(item for item in AUTOMATIONS if item["id"] == "undo_downloads")
        self._request_automation(automation)

    def _automation_worker(self, automation, confirmed_plan=None):
        self.event_bus.post(Event(EventType.TASK_STARTED, {"automation_id": automation["id"]}))
        try:
            permission = self._automation_permission(automation["id"])
            destructive = automation["id"] in ("trash_duplicates", "empty_trash")
            self._authorize_core_action(permission, confirmed=True)
            self.permission_manager.require("nova.core", permission,
                                            confirmed=bool(confirmed_plan is not None or destructive))
            result = automation["executor"](plan=confirmed_plan) if confirmed_plan is not None else automation["executor"]()
        except Exception as exc:
            logging.warning("Automação %s falhou (%s)", automation["id"], type(exc).__name__)
            result = {"title": "Não consegui concluir", "lines": [f"Ocorreu um erro ({type(exc).__name__})."], "status": "error"}
        event_type = EventType.TASK_FINISHED if result.get("status") == "ok" else EventType.TASK_FAILED
        self.event_bus.post(Event(event_type, {"automation_id": automation["id"], "result": result}))

    @staticmethod
    def _automation_permission(automation_id):
        if automation_id in ("organize_downloads", "organize_screenshots"):
            return "file.organize"
        if automation_id == "undo_downloads":
            return "file.move"
        if automation_id in ("trash_duplicates", "empty_trash"):
            return "file.delete"
        if automation_id == "laptop_status":
            return "system.cpu.read"
        if automation_id == "disk_summary":
            return "system.disk.read"
        if automation_id == "large_files" or automation_id == "duplicates":
            return "file.read"
        return "system.memory.read"

    def _authorize_core_action(self, permission, *, confirmed=False):
        """Record a scoped grant following the corresponding explicit UI action."""
        manager = getattr(self, "permission_manager", None)
        if manager is None:  # Compatibility for lightweight legacy/test instances.
            return True
        if not manager.allowed("nova.core", permission):
            if manager.has_decision("nova.core", permission):
                raise PermissionError(f"Permissão revogada: {permission}")
            if not manager.authorize("nova.core", permission, confirmed=True):
                raise PermissionError(f"Permissão não concedida: {permission}")
        return manager.require("nova.core", permission, confirmed=confirmed)

    def _on_automation_event(self, event):
        automation_id = event.payload.get("automation_id")
        result = event.payload.get("result")
        if not automation_id or not isinstance(result, dict):
            return
        self.automation_active = False
        for button in getattr(self, "_automation_action_buttons", {}).values():
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass
        if not self._closing:
            if result.get("status") == "preview" and automation_id in ("trash_duplicates", "empty_trash"):
                operations = result.get("plan", [])
                if not operations:
                    title = "Nenhuma cópia duplicada encontrada" if automation_id == "trash_duplicates" else "A Lixeira já está vazia"
                    self._finish_automation(automation_id, {"title": title, "lines": ["Não encontrei itens para esta ação."], "status": "ok"})
                    return
                if not self._confirm_automation_plan(operations):
                    self.state = "walk"
                    self.show_bubble("Tudo bem, mantive os arquivos como estavam.", duration=3500)
                    return
                automation = next(item for item in AUTOMATIONS if item["id"] == automation_id)
                self.automation_active = True
                for button in getattr(self, "_automation_action_buttons", {}).values():
                    button.configure(state="disabled")
                self.state = "thinking"
                self.show_bubble("Estou movendo as cópias para a Lixeira…", duration=999999)
                threading.Thread(target=self._automation_worker, args=(automation, tuple(operations)), daemon=True).start()
                return
            self._finish_automation(automation_id, result)

    def _on_ai_response_event(self, event):
        answer = event.payload.get("answer")
        if isinstance(answer, str) and not self._closing:
            self._ai_status = "respondida"
            self._ai_last_response_at = time.time()
            self._show_answer(answer)

    def _on_ai_failure_event(self, event):
        self._ai_status = "falha"
        details = str(event.payload.get("error", "Falha ao consultar a IA."))[:300]
        self._recent_errors.append({"source": "ai", "error": details, "timestamp": time.time()})
        self.notification_manager.create("Falha na IA", details,
                                         NotificationCategory.ERROR, priority=70)

    def _on_ai_started_event(self, _event):
        self._ai_status = "consultando"
        self._ai_last_request_at = time.time()

    def _on_plugin_failure_event(self, event):
        plugin_id = str(event.payload.get("plugin_id", "Plugin"))[:80]
        error = str(event.payload.get("error", "Falha"))[:100]
        self._recent_errors.append({"source": plugin_id, "error": error, "timestamp": time.time()})
        self.notification_manager.create("Falha em habilidade", f"{plugin_id}: {error}",
                                         NotificationCategory.ERROR, priority=75)

    def _dashboard_snapshot(self):
        return {
            "pet_state": str(self.state),
            "animation": getattr(self, "_last_event_animation", "idle"),
            "ai_provider": self.settings.get("ai_provider", "ollama"),
            "ai_status": getattr(self, "_ai_status", "idle"),
            "integrations": {"spotify": bool(self.settings.get("spotify_client_id")
                                                and spotify_token_connected(self.settings.get("spotify_client_id")))},
            "plugins": self.plugin_manager.counts,
            "tasks_running": int(bool(getattr(self, "automation_active", False)))
                             + int(bool(getattr(self, "ai_request_active", False)))
                             + int(bool(getattr(self, "app_launch_active", False))),
            "recent_errors": [*list(self._recent_errors)[-5:], *list(self.plugin_manager.errors[-5:])][-10:],
        }

    def _finish_automation(self, automation_id, result):
        now = datetime.now().astimezone().strftime("%H:%M")
        summary = f"{result.get('title', 'Automação')} · {'concluída' if result.get('status') == 'ok' else 'erro'} às {now}"
        auto_settings = self.settings.setdefault("automations", {"enabled": {}, "last_run": {}, "activity": []})
        auto_settings.setdefault("last_run", {})[automation_id] = summary
        timestamp = datetime.now().astimezone().isoformat(timespec="minutes")
        auto_settings.setdefault("activity", []).insert(0, {"id": automation_id, "summary": summary, "timestamp": timestamp})
        auto_settings["activity"] = auto_settings["activity"][:10]
        save_settings(self.settings)
        label = getattr(self, "_automation_status_labels", {}).get(automation_id)
        if label is not None:
            try:
                label.configure(text=summary)
            except tk.TclError:
                pass
        self._refresh_automation_activity()
        metrics = result.get("metrics")
        if isinstance(metrics, dict):
            self._update_automation_metrics(metrics)
        success = result.get("status") == "ok"
        if not success and hasattr(self, "_recent_errors"):
            self._recent_errors.append({"source": automation_id,
                                        "error": str(result.get("title", "falha"))[:200],
                                        "timestamp": time.time()})
        self.notification_manager.create(
            "Automação concluída" if success else "Falha na automação",
            str(result.get("title", automation_id)),
            NotificationCategory.SUCCESS if success else NotificationCategory.ERROR,
            priority=35 if success else 65,
        )
        category = "automation_ok" if success else "automation_error"
        line = pick_line(category, name=self.settings.get("user_name", ""), rng=random, history=self._speech_history)
        result_lines = result.get("lines", [])
        balloon_lines = result_lines[:4] if automation_id == "laptop_status" else result_lines[:3]
        details = "\n".join(balloon_lines)
        if len(result_lines) > len(balloon_lines):
            details += f"\nMais {len(result_lines) - len(balloon_lines)} detalhe(s) na janela de resultados."
            self._show_automation_details(result)
        self.state = "thumbs_up" if success else "curious"
        if success:
            self._thumbs_up_started_at = time.monotonic()
        self._schedule_pose_return(round(THUMBS_UP_ANIMATION_SECONDS * 1000) if success else 3000, self.state)
        self.show_bubble(f"{line}\n{details}", duration=8000)

    def _show_automation_details(self, result):
        previous = getattr(self, "_automation_detail_window", None)
        if previous is not None:
            try:
                if previous.winfo_exists():
                    previous.destroy()
            except tk.TclError:
                pass
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._automation_detail_window = dialog
        dialog.title(result.get("title", "Resultado da automação"))
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.resizable(True, True)
        x, y, width, height = self._question_dialog_geometry(460, 390)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        outer = ttk.Frame(dialog, style="Autonomy.TFrame", padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=result.get("title", "Resultado"), style="Title.TLabel", wraplength=max(240, width - 36)).pack(anchor="w", pady=(0, 8))
        card = ttk.Frame(outer, style="Card.TFrame", padding=5)
        card.pack(fill="both", expand=True)
        content = tk.Text(card, height=12, wrap="word", relief="flat", bd=0, padx=8, pady=7, bg="#F5F7FA", fg="#26344A", font="TkDefaultFont")
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=content.yview)
        content.configure(yscrollcommand=scrollbar.set)
        content.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        content.insert("end", "\n".join(result.get("lines", [])))
        content.configure(state="disabled")
        ttk.Button(outer, text="Fechar", style="Primary.TButton", command=dialog.destroy).pack(anchor="e", pady=(8, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _update_automation_metrics(self, metrics):
        for key in ("cpu", "memory", "disk", "battery"):
            value = metrics.get(key)
            variable = getattr(self, "_automation_metric_vars", {}).get(key)
            bar = getattr(self, "_automation_metric_bars", {}).get(key)
            if variable is None:
                continue
            if value is None:
                variable.set("Sem bateria" if key == "battery" else "Indisponível")
                if bar is not None:
                    bar.set(0)
                continue
            number = max(0.0, min(100.0, float(value)))
            suffix = f" · {metrics.get('memory_label')}" if key == "memory" else f" · {metrics.get('disk_label')}" if key == "disk" else ""
            if key == "battery" and metrics.get("charging"):
                suffix = " · carregando"
            variable.set(f"{number:.0f}%{suffix}")
            if bar is not None:
                bar.set(number)
        lines = [metrics.get("uptime", "")]
        processes = metrics.get("processes", [])
        if processes:
            lines.append("Maior uso de memória: " + " · ".join(f"{item['name']} ({item['memory_mb']} MB)" for item in processes))
        info = getattr(self, "_automation_device_info_var", None)
        if info is not None:
            info.set("\n".join(item for item in lines if item))

    def _refresh_automation_activity(self):
        variable = getattr(self, "_automation_activity_var", None)
        if variable is None:
            return
        entries = self.settings.get("automations", {}).get("activity", [])
        if not entries:
            variable.set("Nenhuma automação executada ainda.")
            return
        names = {item["id"]: item["name"] for item in AUTOMATIONS}
        variable.set("\n".join(f"{item.get('timestamp', '')}  ·  {names.get(item.get('id'), 'Automação')}  ·  {item.get('summary', '')}" for item in entries[:5]))

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
        event_bus = getattr(self, "event_bus", None)
        if event_bus is not None:
            event_bus.publish(Event(EventType.APPLICATION_SHUTDOWN, {}))
        plugin_manager = getattr(self, "plugin_manager", None)
        if plugin_manager is not None:
            plugin_manager.shutdown()
        if event_bus is not None:
            event_bus.close()
        stop_event = getattr(self, "_device_monitor_stop", None)
        if stop_event is not None:
            stop_event.set()
        retry_job = getattr(self, "_device_announcement_retry_job", None)
        if retry_job is not None:
            try:
                self.root.after_cancel(retry_job)
            except tk.TclError:
                pass
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
    def _spotify_connect_worker(self, client_id):
        try:
            permissions = getattr(self, "permission_manager", None)
            if permissions is not None:
                self._authorize_core_action("network.access", confirmed=True)
                permissions.require("nova.core", "network.access", confirmed=True)
            spotify_connect(client_id)
            self._spotify_results.put(("connect", True, "Conta Spotify conectada."))
        except Exception as exc:
            self._spotify_results.put(("connect", False, str(exc)))

    def _drain_spotify_results(self):
        while True:
            try:
                kind, success, message, *extra = self._spotify_results.get_nowait()
            except queue.Empty:
                return
            if kind == "connect":
                status = getattr(self, "_spotify_status_var", None)
                button = getattr(self, "_spotify_connect_button", None)
                if status is not None:
                    try:
                        status.set(message)
                    except tk.TclError:
                        pass
                if button is not None:
                    try:
                        button.configure(state="normal")
                    except tk.TclError:
                        pass
                continue
            question = extra[0] if extra else ""
            self._spotify_action_active = False
            if self._closing:
                continue
            if self.busy:
                self.hide_bubble()
            answer = self._record_local_interaction(question, message)
            self.show_bubble(answer, duration=7000 if success else 8000)

    def _start_spotify_request(self, question, request):
        if self._spotify_action_active:
            self.show_bubble("Já estou cuidando de um pedido do Spotify.", duration=3000)
            return
        playlist = request.get("playlist", "").strip()
        track = request.get("track", "").strip()
        if request["operation"] == "play_track" and not track:
            self._spotify_pending_track_at = time.monotonic()
            self.show_bubble(
                "Qual música você quer ouvir? Diga o nome da faixa e, se souber, o artista.",
                duration=7000,
            )
            return
        if request["operation"] == "play_track":
            self._spotify_pending_track_at = None
        if not playlist:
            if request["operation"] != "play_track":
                self.show_bubble(
                    "Qual é o nome da playlist? Pode dizer: ‘toca a playlist Favoritas no Spotify’.",
                    duration=6500,
                )
                return
        if request["operation"] == "add" and not request.get("track", "").strip():
            self.show_bubble(
                "Qual música você quer adicionar? Pode dizer: ‘adiciona Blinding Lights na playlist Favoritas do Spotify’.",
                duration=7500,
            )
            return
        client_id = self.settings.get("spotify_client_id", "").strip()
        connected = bool(client_id and spotify_token_connected(client_id))
        if request["operation"] == "play" and playlist_uri_from_input(playlist):
            connected = True
            client_id = ""
        if not connected:
            if request["operation"] == "play":
                self.show_bubble(
                    "Para tocar sem vincular a API, mande o link da playlist do Spotify. Exemplo: ‘toca https://open.spotify.com/playlist/…’.",
                    duration=8000,
                )
                return
            if request["operation"] == "play_track":
                self.show_bubble(
                    "Para procurar uma música pelo nome, conecte sua conta Spotify em Preferências > Inteligência artificial. Depois diga, por exemplo: ‘toca Evidências do Chitãozinho e Xororó’.",
                    duration=9000,
                )
                return
            self.show_bubble(
                "Para a Nova adicionar a faixa automaticamente, a API exige um app Developer Mode cujo dono tenha Premium. Sem ele, você ainda pode tocar pelo link e adicionar a música manualmente no Spotify Free.",
                duration=9000,
            )
            return
        self._spotify_action_active = True
        message = (
            "Estou procurando essa música no Spotify…"
            if request["operation"] == "play_track"
            else "Estou abrindo o Spotify e procurando sua playlist…"
        )
        self.show_bubble(message, duration=999999)
        threading.Thread(
            target=self._spotify_action_worker,
            args=(question, request, client_id),
            name="nova-spotify-action",
            daemon=True,
        ).start()

    def _spotify_action_worker(self, question, request, client_id):
        try:
            permissions = getattr(self, "permission_manager", None)
            if permissions is not None:
                self._authorize_core_action("spotify.control", confirmed=True)
                self._authorize_core_action("network.access", confirmed=True)
                permissions.require("nova.core", "spotify.control", confirmed=True)
                permissions.require("nova.core", "network.access", confirmed=True)
            message = execute_spotify_action(
                client_id,
                request["operation"],
                request.get("playlist", ""),
                request.get("track", ""),
            )
            self._spotify_results.put(("action", True, message, question))
        except (SpotifyError, OSError, ValueError) as exc:
            self._spotify_results.put(("action", False, str(exc), question))

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
        pending_track_at = getattr(self, "_spotify_pending_track_at", None)
        if pending_track_at is not None:
            self._spotify_pending_track_at = None
            if time.monotonic() - pending_track_at <= 90:
                if question.casefold().strip(" .!?") in (
                    "cancela", "cancelar", "deixa", "deixa pra la", "deixa para la",
                    "deixa pra lá", "deixa para lá",
                    "esquece",
                ):
                    answer = self._record_local_interaction(
                        question, "Tudo bem, cancelei o pedido de música."
                    )
                    self.show_bubble(answer)
                    return
                request = parse_spotify_command(question) or {
                    "operation": "play_track",
                    "track": question.strip(),
                }
                self._start_spotify_request(question, request)
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
        automation = recognize_automation(question)
        if automation and self.settings.get("automations", {}).get("enabled", {}).get(automation["id"], True):
            self._request_automation(automation)
            return
        local_intent = local_personality_intent(question)
        if local_intent:
            category, animation = local_intent
            self._handle_local_personality(category, animation)
            return
        spotify_request = parse_spotify_command(question)
        if spotify_request:
            self._start_spotify_request(question, spotify_request)
            return
        app = self._matching_app(question)
        if app:
            self._confirm_open_app(question, app)
            return
        if self._is_app_open_request(question) and self._looks_like_app_target(question):
            target = self._app_open_target(question).strip(" .!?\t")
            answer = (
                f"Não encontrei ‘{target}’ entre os aplicativos disponíveis. "
                "Confira o nome ou cadastre o aplicativo em Preferências > Aplicativos."
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
        event_bus = getattr(self, "event_bus", None)
        permissions = getattr(self, "permission_manager", None)
        request_settings = settings or self.settings
        if event_bus is not None:
            event_bus.post(Event(EventType.AI_REQUEST_STARTED, {}))
        try:
            if permissions is not None:
                self._authorize_core_action("ai.use")
                permissions.require("nova.core", "ai.use")
                if (request_settings.get("ai_provider") in ("gemini", "groq", "mistral")
                        and request_settings.get("online_ai_enabled")
                        and request_settings.get("allow_online_data")
                        and request_settings.get("confirm_free_tier")):
                    self._authorize_core_action("network.access", confirmed=True)
                    permissions.require("nova.core", "network.access", confirmed=True)
            answer = answer_request(
                history, memories=memories, settings=request_settings,
                user_name=user_name,
            )
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no serviço de IA")
            answer = PROVIDER_FAILURE_MESSAGE
        if event_bus is not None:
            if answer == PROVIDER_FAILURE_MESSAGE:
                event_bus.post(Event(EventType.AI_REQUEST_FAILED, {"error": answer}))
            event_bus.post(Event(EventType.AI_RESPONSE_RECEIVED, {"answer": answer}))
        elif hasattr(self, "_ai_results"):
            self._ai_results.put(answer)

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
        """Compatibility hook; worker responses arrive through EventBus."""

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
        if self._device_monitor_thread is None:
            self._device_monitor_thread = threading.Thread(
                target=self._device_monitor_worker,
                name="nova-device-monitor",
                daemon=True,
            )
            self._device_monitor_thread.start()
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
