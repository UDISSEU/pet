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
from nova_ai.desktop_routing import route_user_request
from x11_helper import X11Helper
from animation_controller import AnimationControllerMixin
from interaction_controller import InteractionControllerMixin
from routine_controller import RoutineControllerMixin
from device_controller import DeviceControllerMixin
from speech_controller import SpeechControllerMixin
from window_controller import WindowControllerMixin
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
from nova_ai.desktop_integration import DesktopNovaIntegration
from nova_ai.profiles import UserProfileManager
from nova_ai.actions import CancellationToken

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Personagem
# ---------------------------------------------------------------------------
class DesktopPet(
    AnimationControllerMixin, InteractionControllerMixin, RoutineControllerMixin,
    DeviceControllerMixin, SpeechControllerMixin, WindowControllerMixin,
    DesktopPetUIMixin,
):
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
        integration = getattr(self, "nova_integration", None)
        if integration is not None:
            integration.sync_visual_state(value)

    def __init__(self):
        self.profile_manager = UserProfileManager()
        self.settings_path = self.profile_manager.settings_path()
        self.settings = load_settings(self.settings_path)
        self.history_path = self.profile_manager.history_path()
        self.history = load_history(self.history_path)
        self._recent_errors = deque(maxlen=20)
        self.event_bus = EventBus()
        self.state_manager = StateManager()
        self.permission_manager = PermissionManager()
        self.nova_integration = None
        try:
            self.nova_integration = DesktopNovaIntegration(
                permission_manager=self.permission_manager,
                profile_manager=self.profile_manager,
            )
        except Exception:
            logger.exception("Núcleo Nova indisponível; mantendo a aplicação legado")
        self._cognitive_cancel_token = None
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
        self._ai_cancel = threading.Event()
        self._ai_inference_lock = threading.Lock()
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
        self._resolved_animations = set()
        self._startup_idle_elapsed = False
        self._startup_walk_enabled = False
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


    # ---------- reprodução dos movimentos em vídeo ----------











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
            and getattr(self, "_startup_walk_enabled", True)
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
























    # ---------- observar apps abertos ----------

    # ---------- modo permanente "atrás das janelas" ----------




    # ---------- sumir atrás das janelas (peekaboo temporário) ----------



    # ---------- sentar cansada em cima de uma janela ----------



    # ---------- balão de fala ----------


    # ---------- interação com o mouse ----------














    def forget_memories(self):
        if messagebox.askyesno("Apagar memórias", "Apagar todas as memórias que você salvou?", parent=self.root):
            self.settings["memories"] = []
            save_settings(self.settings, getattr(self, "settings_path", None))
            self.show_bubble("Apaguei as memórias salvas.", duration=2500)
































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
        if automation["id"] == "organize_downloads":
            enabled = self.settings.get("automations", {}).get("enabled", {}).get(
                automation["id"], True
            )
            if not enabled:
                self.show_bubble("Essa automação está desativada nas preferências.", duration=3000)
                return
            if getattr(self, "nova_integration", None) is None:
                self.show_bubble(
                    "A organização segura de Downloads está indisponível no momento.", duration=4000
                )
                return
            self._start_cognitive_request("Organize Downloads")
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
        confirmed_plan = None
        preview_messages = {
            "organize_downloads": "Estou conferindo os arquivos de Downloads…",
            "organize_screenshots": "Estou procurando capturas de tela…",
            "trash_duplicates": "Estou comparando os arquivos…",
            "empty_trash": "Estou conferindo a Lixeira…",
        }
        if automation["id"] in preview_messages:
            self.automation_active = True
            for button in getattr(self, "_automation_action_buttons", {}).values():
                button.configure(state="disabled")
            self.state = "thinking"
            self.show_bubble(preview_messages[automation["id"]], duration=999999)
            threading.Thread(target=self._automation_preview_worker, args=(automation["id"],), daemon=True).start()
            return
        self.automation_active = True
        for button in getattr(self, "_automation_action_buttons", {}).values():
            button.configure(state="disabled")
        self.state = "thinking"
        self._thinking_started_at = time.monotonic()
        self.show_bubble("Estou cuidando disso…", duration=999999)
        threading.Thread(target=self._automation_worker, args=(automation, confirmed_plan), daemon=True).start()

    def _automation_preview_worker(self, automation_id):
        try:
            previewers = {
                "organize_downloads": (preview_downloads, "Prévia de Downloads"),
                "organize_screenshots": (preview_screenshots, "Prévia de capturas de tela"),
                "trash_duplicates": (preview_duplicate_removals, "Prévia de cópias"),
                "empty_trash": (preview_empty_trash, "Prévia da Lixeira"),
            }
            previewer, title = previewers[automation_id]
            operations = previewer()
            result = {"title": title, "lines": [], "status": "preview", "plan": operations}
        except Exception as exc:
            logging.warning("Prévia da automação %s falhou (%s)", automation_id, type(exc).__name__)
            result = {"title": "Não consegui preparar a prévia", "lines": [f"Ocorreu um erro ({type(exc).__name__})."], "status": "error"}
        event_type = EventType.TASK_FINISHED if result.get("status") == "preview" else EventType.TASK_FAILED
        self.event_bus.post(Event(event_type, {"automation_id": automation_id, "result": result}))

    def _confirm_automation_plan(self, operations, *, title="Prévia · Organizar Downloads"):
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
        dialog.title(title)
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
            if result.get("status") == "preview" and automation_id in (
                "organize_downloads", "organize_screenshots", "trash_duplicates", "empty_trash",
            ):
                operations = result.get("plan", [])
                if not operations:
                    empty_titles = {
                        "organize_downloads": "Downloads já está em ordem",
                        "organize_screenshots": "Nenhuma captura para organizar",
                        "trash_duplicates": "Nenhuma cópia duplicada encontrada",
                        "empty_trash": "A Lixeira já está vazia",
                    }
                    title = empty_titles[automation_id]
                    self._finish_automation(automation_id, {"title": title, "lines": ["Não encontrei itens para esta ação."], "status": "ok"})
                    return
                if not self._confirm_automation_plan(operations, title=result.get("title", "Prévia da automação")):
                    self.state = "walk"
                    self.show_bubble("Tudo bem, mantive os arquivos como estavam.", duration=3500)
                    return
                automation = next(item for item in AUTOMATIONS if item["id"] == automation_id)
                self.automation_active = True
                for button in getattr(self, "_automation_action_buttons", {}).values():
                    button.configure(state="disabled")
                self.state = "thinking"
                progress_messages = {
                    "organize_downloads": "Estou organizando Downloads…",
                    "organize_screenshots": "Estou organizando as capturas…",
                    "trash_duplicates": "Estou movendo as cópias para a Lixeira…",
                    "empty_trash": "Estou esvaziando a Lixeira…",
                }
                self.show_bubble(progress_messages[automation_id], duration=999999)
                threading.Thread(target=self._automation_worker, args=(automation, tuple(operations)), daemon=True).start()
                return
            self._finish_automation(automation_id, result)

    def _start_cognitive_request(self, question):
        if self.automation_active or self.ai_request_active:
            self.show_bubble("Termino a tarefa atual antes de começar outra.", duration=3000)
            return
        self.automation_active = True
        self.state = "thinking"
        self.show_bubble("Vou conferir a pasta Downloads e preparar uma prévia…", duration=999999)
        threading.Thread(
            target=self._cognitive_prepare_worker,
            args=(question,), name="nova-cognitive-prepare", daemon=True,
        ).start()

    def _cognitive_prepare_worker(self, question):
        try:
            prepared = self.nova_integration.prepare_task(question)
            error = None
        except Exception as exc:
            prepared, error = None, type(exc).__name__
            logging.getLogger(__name__).exception("Falha ao preparar tarefa cognitiva")
        self.post_ui_callback(self._handle_cognitive_prepared, question, prepared, error)

    def _handle_cognitive_prepared(self, question, prepared, error):
        if self._closing:
            return
        if error:
            self._finish_cognitive_request(question, f"Não consegui preparar a tarefa ({error}).")
            return
        inspection = prepared.inspection
        if inspection is not None and inspection.data.get("limit_reached"):
            self._finish_cognitive_request(
                question,
                "Downloads contém mais de 500 arquivos para organizar. "
                "A prévia está incompleta, então não alterei nenhum arquivo. "
                "Reduza a quantidade e tente novamente.",
            )
            return
        decision = prepared.decision
        if decision.kind.value == "request_permission":
            permission = next(iter(decision.permissions_required), None)
            if permission is None:
                self._finish_cognitive_request(question, "A tarefa requer uma permissão que não identifiquei.")
                return
            accepted = messagebox.askyesno(
                "Permissão necessária",
                f"Para preparar a prévia, a Nova precisa da permissão {permission}.\n\n"
                "Conceder esta permissão não confirma a movimentação dos arquivos. Deseja concedê-la?",
                parent=self.root,
            )
            if not accepted:
                self._finish_cognitive_request(question, "Sem essa permissão, não alterei nenhum arquivo.")
                return
            try:
                self.permission_manager.authorize("nova.core", permission, confirmed=True)
                self.permission_manager.require("nova.core", permission, confirmed=True)
            except (PermissionError, OSError, ValueError):
                self._finish_cognitive_request(question, "Não consegui registrar essa permissão.")
                return
            self.state = "thinking"
            self.show_bubble("Permissão registrada. Estou atualizando a prévia…", duration=999999)
            threading.Thread(
                target=self._cognitive_prepare_worker,
                args=(question,), name="nova-cognitive-prepare", daemon=True,
            ).start()
            return
        if decision.kind.value == "ask_clarification":
            self._finish_cognitive_request(
                question, prepared.task.clarification_question or "Pode explicar o que deseja organizar?"
            )
            return
        if decision.kind.value != "require_confirmation" or not prepared.files_checked:
            self._finish_cognitive_request(question, decision.reason or "Não posso executar essa tarefa agora.")
            return
        rows = prepared.inspection.data.get("plan", []) if prepared.inspection else []
        if not rows:
            self._finish_cognitive_request(question, "Não encontrei arquivos para organizar; nada foi alterado.")
            return
        operations = [(Path(row["source"]), Path(row["destination"])) for row in rows]
        if not self._confirm_automation_plan(operations):
            self._finish_cognitive_request(question, "Tudo bem. Cancelei a organização e mantive os arquivos no lugar.")
            return
        self._cognitive_cancel_token = CancellationToken()
        self.state = "thinking"
        self.show_bubble("Organizando os arquivos aprovados…", duration=999999)
        self._show_cognitive_progress(self._cognitive_cancel_token)
        threading.Thread(
            target=self._cognitive_execute_worker,
            args=(question, prepared, self._cognitive_cancel_token),
            name="nova-cognitive-execute", daemon=True,
        ).start()

    def _cognitive_execute_worker(self, question, prepared, cancellation):
        try:
            result = self.nova_integration.execute_task(
                prepared, approved=True, cancellation=cancellation
            )
            self.post_ui_callback(self._handle_cognitive_execution, question, result, None)
        except Exception as exc:
            if cancellation.cancelled:
                logging.getLogger(__name__).warning(
                    "Worker cognitivo encerrou após cancelamento (%s)", type(exc).__name__
                )
                error_name = "cancelada"
            else:
                logging.getLogger(__name__).exception(
                    "Falha inesperada no worker de execução cognitiva"
                )
                error_name = type(exc).__name__
            # Keep exception details in logs only; the UI receives a safe status label.
            self.post_ui_callback(
                self._handle_cognitive_execution, question, None, error_name
            )

    def _show_cognitive_progress(self, cancellation):
        dialog = self._set_nova_window_icon(tk.Toplevel(self.root))
        dialog.title("Nova · Organização")
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        ttk.Label(dialog, text="Organizando os arquivos aprovados…", padding=14).pack(fill="x")
        button = ttk.Button(
            dialog, text="Cancelar tarefa",
            command=lambda: (cancellation.cancel(), button.configure(state="disabled", text="Cancelando…")),
        )
        button.pack(anchor="e", padx=12, pady=(0, 12))
        dialog.protocol("WM_DELETE_WINDOW", cancellation.cancel)
        self._cognitive_progress_dialog = dialog

    def _handle_cognitive_execution(self, question, result, error=None):
        self._cognitive_cancel_token = None
        self._finish_cognitive_controls()
        if self._closing:
            return
        if error is not None or result is None:
            error_name = error if isinstance(error, str) else "erro inesperado"
            if error_name == "cancelada":
                message = "Cancelei a tarefa. Os arquivos permaneceram no lugar ou foram restaurados."
            else:
                message = f"Não consegui concluir a organização ({error_name}). Você pode tentar novamente."
            self.state = "curious"
            self._record_local_interaction(question, message)
            self.show_bubble(message, duration=6000)
            return
        self.state = "thumbs_up" if result.verified else "curious"
        self.show_bubble(result.message, duration=6000)
        if result.verified and self.nova_integration.last_undo_mapping:
            if messagebox.askyesno(
                    "Organização concluída",
                    "A organização foi verificada. Deseja desfazer e restaurar os arquivos?",
                    parent=self.root):
                self._request_cognitive_undo(question)
        else:
            self._record_local_interaction(question, result.message)

    def _request_cognitive_undo(self, question):
        for permission in ("file.read", "file.move"):
            if self.permission_manager.allowed("nova.core", permission):
                continue
            if not messagebox.askyesno(
                    "Permissão para restaurar",
                    f"Desfazer requer {permission}. Conceder a permissão não executa a restauração; "
                    "a solicitação de desfazer já foi confirmada separadamente. Deseja conceder?",
                    parent=self.root):
                self.show_bubble("Restauração cancelada; os arquivos continuam organizados.", duration=5000)
                return
            try:
                self.permission_manager.authorize("nova.core", permission, confirmed=True)
            except (OSError, ValueError):
                self.show_bubble("Não consegui registrar a permissão de restauração.", duration=5000)
                return
        self.automation_active = True
        self.show_bubble("Restaurando os arquivos…", duration=999999)
        threading.Thread(
            target=self._cognitive_undo_worker,
            args=(question,), name="nova-cognitive-undo", daemon=True,
        ).start()

    def _cognitive_undo_worker(self, question):
        try:
            result = self.nova_integration.undo_last_organization(approved=True)
            message = result.summary if result is not None else "Não há uma organização disponível para desfazer."
        except Exception as exc:
            logging.getLogger(__name__).exception("Falha ao desfazer organização")
            message = f"Não consegui restaurar os arquivos ({type(exc).__name__})."
        self.post_ui_callback(self._handle_cognitive_undo, question, message)

    def _handle_cognitive_undo(self, question, message):
        self._finish_cognitive_controls()
        if not self._closing:
            self._record_local_interaction(question, message)
            self.show_bubble(message, duration=6000)

    def _finish_cognitive_controls(self):
        self.automation_active = False
        self.state = "walk"
        dialog = getattr(self, "_cognitive_progress_dialog", None)
        self._cognitive_progress_dialog = None
        if dialog is not None:
            try:
                dialog.destroy()
            except tk.TclError:
                pass

    def _finish_cognitive_request(self, question, message):
        self._finish_cognitive_controls()
        self._record_local_interaction(question, message)
        self.show_bubble(message, duration=6000)

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
        save_settings(self.settings, getattr(self, "settings_path", None))
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
        if self._closing:
            return
        self._closing = True
        cancel_ai = getattr(self, "_ai_cancel", None)
        if cancel_ai is not None:
            cancel_ai.set()
        cognitive_cancel = getattr(self, "_cognitive_cancel_token", None)
        if cognitive_cancel is not None:
            cognitive_cancel.cancel()
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
        monitor_thread = getattr(self, "_device_monitor_thread", None)
        if (monitor_thread is not None and monitor_thread is not threading.current_thread()
                and monitor_thread.is_alive()):
            monitor_thread.join(timeout=1.0)
        pending_callbacks = getattr(self, "_ui_callbacks", None)
        if pending_callbacks is not None:
            while True:
                try:
                    pending_callbacks.get_nowait()
                except queue.Empty:
                    break
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
        if save_history(self.history, self.history_path):
            self.show_bubble("Memória limpa!", duration=2500)
        else:
            self.show_bubble(
                "Memória limpa nesta sessão, mas não consegui salvar.",
                duration=4000,
            )

    def switch_user_profile(self, profile_id):
        if self.ai_request_active:
            raise RuntimeError("Aguarde a conversa terminar antes de trocar de perfil")
        integration = getattr(self, "nova_integration", None)
        if integration is None:
            raise RuntimeError("A troca de perfil está indisponível")
        profile = integration.select_profile(profile_id)
        self.profile_manager = integration.profile_manager
        self.settings_path = self.profile_manager.settings_path(profile.profile_id)
        self.settings = load_settings(self.settings_path)
        self.history_path = self.profile_manager.history_path(profile.profile_id)
        self.history = load_history(self.history_path)
        defaults = {
            "quietinha": (False, False, False, False),
            "companhia": (True, True, False, True),
            "proativa": (True, True, True, True),
        }[self.settings["mode"]]
        self.auto_speech_var.set(self.settings.get("auto_speech", defaults[0]))
        self.observe_apps_var.set(self.settings.get("observe_apps", defaults[1]))
        self.peekaboo_var.set(self.settings.get("peekaboo", defaults[2]))
        self.auto_sit_var.set(self.settings.get("auto_sit", defaults[3]))
        return profile

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
            if not save_settings(updated, getattr(self, "settings_path", None)):
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
        integration = getattr(self, "nova_integration", None)
        route, routed_task = route_user_request(
            question,
            cognitive_classifier=(integration.classify_task if integration is not None else None),
            legacy_recognizer=recognize_automation,
        )
        if route == "cognitive":
            self._start_cognitive_request(question)
            return
        if route == "unavailable":
            self.show_bubble("A organização segura de Downloads está indisponível no momento.", duration=4000)
            return
        if route == "legacy" and self.settings.get("automations", {}).get("enabled", {}).get(routed_task["id"], True):
            self._request_automation(routed_task)
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
        memories = (
            list(self.settings.get("memories", []))
            if self.profile_manager.active_profile.profile_id == "legacy"
            else []
        )
        user_name = (
            self.settings.get("user_name", "").strip()[:60]
            if self.profile_manager.active_profile.profile_id == "legacy"
            else self.profile_manager.active_profile.name
        )
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
        if not save_history(self.history, self.history_path):
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
        cancel_event = getattr(self, "_ai_cancel", None)
        inference_lock = getattr(self, "_ai_inference_lock", None)
        if cancel_event is not None and cancel_event.is_set():
            return
        acquired = inference_lock.acquire(blocking=False) if inference_lock is not None else True
        if not acquired:
            self.post_ui_callback(
                self._show_answer,
                "Já estou respondendo a outra pergunta. Tente novamente em instantes.",
            )
            return
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
            integration = getattr(self, "nova_integration", None)
            if integration is not None:
                question = next((item.get("content", "") for item in reversed(history)
                                 if item.get("role") == "user"), "")
                memories = integration.build_context(question, memories)
                request_settings["nova_personality_instructions"] = (
                    integration.personality_instructions()
                )
            answer = answer_request(
                history, memories=memories, settings=request_settings,
                user_name=user_name,
            )
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no serviço de IA")
            answer = PROVIDER_FAILURE_MESSAGE
        finally:
            if inference_lock is not None:
                inference_lock.release()
        if cancel_event is not None and cancel_event.is_set():
            return
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
        history_saved = save_history(self.history, self.history_path)
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
