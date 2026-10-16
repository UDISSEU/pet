#!/usr/bin/env python3
"""
Bichinho de Desktop em pixel art + IA local (Ollama)
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

import math
import os
import random
import threading
import time
import tkinter as tk
import webbrowser
from collections import deque
from tkinter import messagebox, simpledialog

from config import (
    APP_COMMENTS,
    BASE_HEIGHT,
    FONT_BUBBLE,
    FONT_SMALL,
    GENERIC_COMMENTS,
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
    VIDEO_FRAME_RATE,
    VIDEO_MAX_H,
    VIDEO_MAX_W,
    VIDEO_REACTION_SECONDS,
    MOVEMENT_VIDEOS,
    resolve_movement_path,
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
        self.x11 = X11Helper()
        self.shape_supported = None

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        try:
            self.root.wm_attributes("-type", "splash")
        except tk.TclError:
            pass

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self.x = float(random.randint(100, max(101, self.screen_w - 200)))
        self.y = float(self.screen_h - BASE_HEIGHT - SCREEN_MARGIN)
        self.cur_height = BASE_HEIGHT
        self.label = tk.Label(self.root, bd=0, highlightthickness=0, bg="#1c1830")
        self.label.pack(fill="both", expand=True)
        self._window_x = int(round(self.x))
        self._window_y = int(round(self.y))
        self.root.geometry(f"{WIDTH}x{self.cur_height}+{self._window_x}+{int(self.y)}")

        self.tk_image = None

        self.walk_dx, self.walk_dy = random.choice(WALK_DIRECTION_VECTORS)
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
        self._shape_counter = 0
        self._last_shape_update = 0
        self._hidden = False
        self.video_frames = {
            name: self._load_video_frames(filename)
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

        self.behind_var = tk.BooleanVar(value=False)
        self.auto_speech_var = tk.BooleanVar(value=True)
        self.observe_apps_var = tk.BooleanVar(value=True)
        self.peekaboo_var = tk.BooleanVar(value=True)
        self.auto_sit_var = tk.BooleanVar(value=True)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Perguntar", command=self.ask_menu)
        self.menu.add_command(label="Falar algo", command=self.say_something)
        self.menu.add_command(label="Abrir Claude no navegador", command=self.open_chat)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Andar atrás das janelas", variable=self.behind_var,
                                   command=self.toggle_behind_mode)
        self.menu.add_checkbutton(label="Falas espontâneas", variable=self.auto_speech_var)
        self.menu.add_checkbutton(label="Comentários sobre apps", variable=self.observe_apps_var)
        self.menu.add_checkbutton(label="Sumir atrás das janelas", variable=self.peekaboo_var,
                      command=self.toggle_peekaboo)
        self.menu.add_checkbutton(label="Sentar em janelas", variable=self.auto_sit_var,
                      command=self.toggle_auto_sit)
        self.menu.add_command(label="Esquecer conversa", command=self.forget_history)
        self.menu.add_command(label="Fechar", command=self.root.destroy)

        self.render_and_show()
        self._last_tick_at = time.monotonic()
        self._next_tick_at = self._last_tick_at + TICK_MS / 1000
        self.root.after(TICK_MS, self.tick)
        self.root.after(random.randint(6000, 12000), self.random_speech)
        self.root.after(random.randint(15000, 30000), self.observe_apps)
        self.root.after(random.randint(30000, 60000), self.peekaboo)
        self.root.after(random.randint(20000, 40000), self.maybe_sit)

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
    def _load_video_frames(self, filename):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "Falta o OpenCV para reproduzir os movimentos em vídeo. "
                "Instale as dependências com: pip install -r requirements.txt"
            ) from exc

        path = resolve_movement_path(filename)
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise OSError(f"Não foi possível abrir o vídeo de movimento: {path}")

        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = VIDEO_FRAME_RATE
        frames = []
        source_frame = 0
        next_sample_at_ms = 0.0
        try:
            while True:
                success, frame = capture.read()
                if not success:
                    break
                source_frame_at_ms = source_frame * 1000 / fps
                if source_frame_at_ms >= next_sample_at_ms:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(rgb)
                    frames.append(self._prepare_video_frame(image, path.name))
                    next_sample_at_ms += VIDEO_FRAME_INTERVAL_MS
                source_frame += 1
        finally:
            capture.release()

        if not frames:
            raise ValueError(f"O vídeo de movimento não contém quadros: {path}")
        return frames

    def _prepare_video_frame(self, frame, description):
        frame.thumbnail(
            (VIDEO_MAX_W, VIDEO_MAX_H),
            Image.Resampling.LANCZOS,
        )
        frame = self._remove_video_background(frame.convert("RGBA"))
        bounds = frame.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"Nenhum personagem encontrado no vídeo {description}.")
        frame = frame.crop(bounds)
        canvas = Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
        position = ((VIDEO_MAX_W - frame.width) // 2, VIDEO_MAX_H - frame.height)
        canvas.alpha_composite(frame, position)
        return canvas

    @staticmethod
    def _remove_video_background(frame):
        width, height = frame.size
        pixels = list(frame.getdata())
        background = bytearray(
            int(
                min(red, green, blue) >= 220
                and max(red, green, blue) - min(red, green, blue) <= 24
            )
            for red, green, blue, _ in pixels
        )
        transparent = bytearray(width * height)
        pending = deque()

        def enqueue(index):
            if background[index] and not transparent[index]:
                transparent[index] = 1
                pending.append(index)

        for x in range(width):
            enqueue(x)
            enqueue((height - 1) * width + x)
        for y in range(1, height - 1):
            enqueue(y * width)
            enqueue(y * width + width - 1)

        while pending:
            index = pending.popleft()
            x = index % width
            if x:
                enqueue(index - 1)
            if x + 1 < width:
                enqueue(index + 1)
            if index >= width:
                enqueue(index - width)
            if index + width < width * height:
                enqueue(index + width)

        alpha = Image.new("L", frame.size)
        alpha.putdata([
            0 if is_background else pixel[3]
            for is_background, pixel in zip(transparent, pixels)
        ])
        frame.putalpha(alpha)
        return frame

    def _video_for_current_pose(self, now=None):
        if self.state == "sitting":
            return "sleep"
        if self.state in ("held", "thinking"):
            return "idle"
        if self.state == "walk":
            if now is None:
                now = time.monotonic()
            if now < self._irritated_until:
                return "angry"
            if self.busy:
                return "wave"
            return "walk_left" if self.walk_dx < 0 else "walk_right"
        return "idle"

    def _current_video_frame(self, now=None):
        if now is None:
            now = time.monotonic()
        video = self._video_for_current_pose(now)
        frames = self.video_frames[video]
        if video == "angry":
            elapsed_ms = (now - self._irritated_started_at) * 1000
        else:
            elapsed_ms = self.animation_time_ms
        frame_index = int(elapsed_ms / VIDEO_FRAME_INTERVAL_MS) % len(frames)
        return video, frame_index, frames[frame_index]

    def render_frame(self):
        """Renderiza a personagem com o quadro atual do movimento em vídeo."""
        w, h = WIDTH * SCALE, self.cur_height * SCALE
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        bubble_h = 0
        if self.bubble_text:
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
        if self.state == "walk" and not self.busy:
            bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        elif self.state == "held":
            bob = int(math.sin(self.animation_time_ms / 1000 * 5) * 2 * SCALE)

        x = int((w - sprite.width) / 2)
        y = int(h - sprite.height - 7 * SCALE - bob)
        if y < bubble_h:
            y = int(bubble_h)

        img.alpha_composite(sprite, (x, y))

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

        self._shape_counter += 1
        if self._shape_counter % 15 == 0:
            self.root.update_idletasks()
            win_id = self.root.winfo_id()
            ok = self.x11.apply_shape_mask(win_id, frame)
            if self.shape_supported is None:
                self.shape_supported = ok
                if ok:
                    print("[bichinho] transparência real ativada — fundo recortado com sucesso.")
                else:
                    if not self.x11.ok:
                        reason = "python-xlib indisponível"
                    else:
                        reason = self.x11.last_shape_error or "motivo desconhecido"
                    print(f"[bichinho] transparência real NÃO disponível ({reason}); "
                          "usando fundo sólido como alternativa.")
                    self.label.configure(bg="#f4f4f4")

    def _video_frame_cache_key(self):
        if self.state != "walk" or self.busy or self.dragging or self.bubble_text:
            return None
        video, frame_index, _ = self._current_video_frame()
        bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        return video, frame_index, bob

    def _needed_height(self):
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

        if self.state == "walk" and not self.dragging and not self.busy:
            if now >= self._next_walk_direction_change_at:
                self._choose_walk_direction(now)

            speed = WALK_SPEED
            if self.walk_dx and self.walk_dy:
                speed /= math.sqrt(2)
            next_x = self.x + self.walk_dx * speed * elapsed
            next_y = self.y + self.walk_dy * speed * elapsed
            max_x = max(0, self.screen_w - WIDTH)
            max_y = max(0, self.screen_h - self.cur_height)

            hit_horizontal_boundary = next_x < 0 or next_x > max_x
            if hit_horizontal_boundary:
                self.walk_dx *= -1
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

        if self.state == "sitting" and self.sit_win_id is not None:
            if not self.x11.window_exists(self.sit_win_id):
                self._stand_up(random.choice(STAND_CLOSED_LINES))

        if self.behind_mode and self.step // 50 > previous_step // 50:
            try:
                self.root.lower()
            except tk.TclError:
                pass

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
        if self.auto_speech_var.get() and not self.busy and not self.is_covered():
            self.show_bubble(random.choice(SPEECH_LINES), duration=3000)
        self.root.after(random.randint(15000, 30000), self.random_speech)

    # ---------- observar apps abertos ----------
    def observe_apps(self):
        if (self.observe_apps_var.get() and not self.busy and self.x11.ok
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
        self.root.after(random.randint(25000, 50000), self.observe_apps)

    # ---------- modo permanente "atrás das janelas" ----------
    def toggle_behind_mode(self):
        self.behind_mode = self.behind_var.get()
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
        if not self.peekaboo_var.get() and self._hidden:
            self._reappear()

    def toggle_auto_sit(self):
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
        if (self.peekaboo_var.get() and not self.behind_mode and not self.dragging and not self.busy
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
        if (self.auto_sit_var.get() and not self.dragging and not self.busy and self.state == "walk"
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
        self.menu.tk_popup(event.x_root, event.y_root)

    def forget_history(self):
        self.history = []
        save_history(self.history)
        self.show_bubble("Memória limpa!", duration=2500)

    # ---------- integração com a IA local ----------
    def ask_menu(self, event=None):
        if self.ai_request_active:
            self.show_bubble("Já estou respondendo sua pergunta!", duration=2500)
            return
        question = simpledialog.askstring("Perguntar", "O que você quer perguntar?", parent=self.root)
        if not question:
            return
        self.history.append({"role": "user", "content": question})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        request_history = list(self.history)
        self.ai_request_active = True
        self.state = "thinking"
        self.show_bubble("pensando...", duration=999999)
        threading.Thread(target=self._ask_worker, args=(request_history,), daemon=True).start()

    def _ask_worker(self, history):
        answer = ask_local_ai(history)
        self.root.after(0, self._show_answer, answer)

    def _show_answer(self, answer):
        self.ai_request_active = False
        self.history.append({"role": "assistant", "content": answer})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        save_history(self.history)
        self.state = "walk"
        words = max(len(answer.split()), 1)
        duration = min(max(6000, words * 400), 30000)
        self.show_bubble(answer, duration=duration)

    def _safe_call_later(self, callback, delay_ms, *args):
        try:
            self.root.after(delay_ms, callback, *args)
        except tk.TclError:
            pass

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
            messagebox.showerror("Erro no bichinho", str(exc))
        except Exception:
            pass
        raise
