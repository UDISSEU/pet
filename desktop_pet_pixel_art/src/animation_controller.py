import math
import random
import time
from PIL import Image, ImageDraw, ImageTk
from config import BASE_HEIGHT, FONT_BUBBLE, ONE_SHOT_VIDEOS, SCALE, VIDEO_FRAME_INTERVAL_MS, VIDEO_FALLBACKS, MOVEMENT_VIDEOS, VIDEO_LOOP_WINDOWS, resolve_movement_path, WALK_DIRECTION_VECTORS, WALK_DIRECTION_CHANGE_MAX_SECONDS, WALK_DIRECTION_CHANGE_MIN_SECONDS, WIDTH
from animation import frame_index_at_elapsed
from event_bus import Event, EventType


class AnimationControllerMixin:
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
            if not getattr(self, "_startup_walk_enabled", True):
                video = "idle"
            elif self.stay_in_place_var.get():
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
            self._resolved_animations.add(name)
            self.video_frames[name] = frames
            changed = True
        self._maybe_enable_startup_walk()
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
        if self._closing:
            return
        self._startup_idle_elapsed = True
        self._maybe_enable_startup_walk()

    def _maybe_enable_startup_walk(self):
        if self._closing or not getattr(self, "_startup_idle_elapsed", False):
            return
        direction = "walk_left" if getattr(self, "walk_dx", 1) < 0 else "walk_right"
        if direction not in getattr(self, "_resolved_animations", set()):
            return
        self._startup_walk_enabled = True
        if self.state == "idle":
            self.state = "walk"
