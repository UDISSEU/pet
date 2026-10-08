#!/usr/bin/env python3
"""
Bichinho de Desktop em pixel art + IA local (Ollama)
----------------------------------------------------
Personagem animada com ciclos de caminhada, balanço ao arrastar e piscada.

Ela observa (sem mexer em nada) os apps que você tem aberto, comenta
quando percebe que você tá no YouTube, senta cansada em cima de
janelas abertas de vez em quando, balança feito num carro em
movimento quando você arrasta ela com o mouse, e levanta se a janela
em que estava sentada for fechada.

DEPENDÊNCIAS:
    pip install --break-system-packages Pillow python-xlib
    sudo apt install python3-tk

- Pillow: obrigatório.
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

import json
import math
import os
import random
import re
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from io import BytesIO
from pathlib import Path
from tkinter import messagebox, simpledialog

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:
    import sys
    print("Falta a biblioteca Pillow. Instale com:\n"
          "    pip install --break-system-packages Pillow", file=sys.stderr)
    sys.exit(1)

try:
    from Xlib import X, display as xlib_display
    from Xlib.ext import shape as xlib_shape
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
WIDTH = 140
BASE_HEIGHT = 190
SCREEN_MARGIN = 40
SCALE = 3
TICK_MS = 16
LOGIC_STEP_MS = 40
ANIMATION_FRAME_MS = 96
WALK_SPEED = 24.0

# ---------------------------------------------------------------------------
# Personagem em pixel art
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOVEMENTS_DIR = PROJECT_ROOT.parent / "movimento 2.0"
SPRITE_MAX_W = 124
SPRITE_MAX_H = 176
SPRITE_RESAMPLE = Image.Resampling.NEAREST

SPEECH_LINES = [
    "Oi!",
    "Precisa de algo?",
    "Bora codar?",
    "Estudando hoje?",
    "Clica com o botão direito pra me perguntar algo",
    "Analista de dados on!",
    ":)",
]

APP_COMMENTS = {
    "youtube": [
        "Rindo do vídeo ou é sério isso?",
        "Mais um vídeo pra 'só um rapidinho', né?",
        "O algoritmo te pegou de novo",
        "Assistindo ou trabalhando? 👀",
    ],
    "firefox": ["Navegando por aí?", "Achou algo legal?"],
    "chrome": ["Navegando por aí?", "Muitas abas hein"],
    "chromium": ["Navegando por aí?"],
    "code": ["Bora codar!", "Código novo?"],
    "sublime": ["Editando código?"],
    "terminal": ["Modo terminal ativado", "Linha de comando é vida"],
    "xterm": ["Modo terminal ativado"],
    "thunar": ["Organizando arquivos?"],
    "nautilus": ["Organizando arquivos?"],
    "files": ["Vendo seus arquivos?"],
    "libreoffice": ["Trabalhando em documento?"],
    "gimp": ["Editando imagem, bonito!"],
    "spotify": ["Boa música?"],
}
GENERIC_COMMENTS = ["Vendo o que você tá fazendo", "Te acompanhando por aqui", ":)"]
SIT_DOWN_LINES = ["Ufa... só um descansinho", "Cansei de andar por aí", "Cadeira improvisada, hihi"]
STAND_CLOSED_LINES = ["Ei, sumiu minha cadeira!", "A janela fechou, levantando!"]
STAND_TIMEOUT_LINES = ["Descanso acabou, vamo lá de novo"]

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:1b"

HISTORY_PATH = Path.home() / ".desktop_pet_history.json"
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = (
    "Você é a companheira de desktop do Ulisses. Responda de forma curta, "
    "calorosa e direta, sem enrolação. Se não souber algo, diga isso "
    "abertamente em vez de inventar. Respostas de no máximo 3 ou 4 frases."
)

# Paleta anime/cartoon (personagem original, estilo "boneca pixel art" com
# sombreado em camadas, inspirada em cabelo longo ondulado + jaqueta oversized)
COL_HAIR = (94, 62, 45, 255)            # castanho
COL_HAIR_LIGHT = (128, 88, 62, 255)     # mecha clara (volume)
COL_HAIR_DARK = (64, 40, 28, 255)       # sombra do cabelo
COL_SKIN = (255, 219, 191, 255)
COL_SKIN_SHADOW = (232, 190, 160, 255)
COL_JACKET = (40, 38, 46, 255)          # jaqueta preta oversized
COL_JACKET_DARK = (24, 22, 28, 255)
COL_SHIRT = (215, 215, 220, 255)        # blusa cinza-clara por baixo
COL_JEANS = (150, 176, 205, 255)        # calça jeans larga
COL_JEANS_DARK = (110, 135, 165, 255)
COL_BLUSH = (255, 150, 170, 170)
COL_EYE = (35, 28, 24, 255)             # olhos bem escuros
COL_SHOE = (35, 33, 38, 255)            # tênis preto


def get_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_BUBBLE = get_font(13 * SCALE)
FONT_SMALL = get_font(9 * SCALE)


# ---------------------------------------------------------------------------
# IA local (Ollama)
# ---------------------------------------------------------------------------
def load_history():
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history):
    try:
        HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ask_local_ai(history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    payload = json.dumps({"model": OLLAMA_MODEL, "messages": messages, "stream": False}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return f"Erro {e.code} do Ollama: {e.read().decode('utf-8', errors='ignore')[:200]}"
    except urllib.error.URLError:
        return ("Não consegui falar com o Ollama. Confirme que ele está rodando "
                f"e que o modelo '{OLLAMA_MODEL}' foi baixado (ollama pull {OLLAMA_MODEL}).")
    return data.get("message", {}).get("content", "").strip() or "(resposta vazia)"


# ---------------------------------------------------------------------------
# Integração opcional com X11
# ---------------------------------------------------------------------------
class X11Helper:
    def __init__(self):
        self.ok = False
        self.last_shape_error = None
        self.dpy = None
        self.root_win = None
        if not XLIB_AVAILABLE:
            return
        try:
            self.dpy = xlib_display.Display()
            self.root_win = self.dpy.screen().root
            self.ok = True
        except Exception:
            self.ok = False

    def get_active_window_info(self):
        if not self.ok:
            return None
        try:
            NET_ACTIVE = self.dpy.intern_atom("_NET_ACTIVE_WINDOW")
            prop = self.root_win.get_full_property(NET_ACTIVE, X.AnyPropertyType)
            if not prop or not prop.value or not prop.value[0]:
                return None
            win = self.dpy.create_resource_object("window", prop.value[0])
            wm_class = win.get_wm_class()
            klass = wm_class[1].lower() if wm_class else ""
            name = (win.get_wm_name() or "")
            return klass, name
        except Exception:
            return None

    def get_open_windows(self, exclude_win_id=None):
        """Lista janelas 'de verdade' abertas, com posição/tamanho na tela."""
        if not self.ok:
            return []
        try:
            NET_LIST = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = self.root_win.get_full_property(NET_LIST, X.AnyPropertyType)
            if not prop or not prop.value:
                return []
            results = []
            for win_id in prop.value:
                if win_id == exclude_win_id:
                    continue
                try:
                    win = self.dpy.create_resource_object("window", win_id)
                    geom = win.get_geometry()
                    coords = win.translate_coords(self.root_win, 0, 0)
                    rx = -coords.x
                    ry = -coords.y
                    w, h = geom.width, geom.height
                    if w < 200 or h < 150:
                        continue  # ignora painéis, docks, coisas pequenas
                    results.append({"id": win_id, "x": rx, "y": ry, "w": w, "h": h})
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def window_exists(self, win_id):
        if not self.ok:
            return False
        try:
            NET_LIST = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = self.root_win.get_full_property(NET_LIST, X.AnyPropertyType)
            return bool(prop and prop.value and win_id in list(prop.value))
        except Exception:
            return False

    def apply_shape_mask(self, tk_window_id, pil_rgba_image):
        if not self.ok:
            return False
        try:
            bit_order = self.dpy.info.bitmap_format_bit_order

            alpha = pil_rgba_image.split()[3]
            mask_img = alpha.point(lambda p: 255 if p > 20 else 0).convert("1")

            buf = BytesIO()
            mask_img.save(buf, format="XBM")  # XBM já usa ordem LSBFirst por padrão
            xbm_text = buf.getvalue().decode("ascii", errors="ignore")
            hex_bytes = re.findall(r"0x([0-9a-fA-F]{2})", xbm_text)
            if not hex_bytes:
                return False
            raw = [int(h, 16) for h in hex_bytes]
            if bit_order != X.LSBFirst:
                raw = [int(f"{b:08b}"[::-1], 2) for b in raw]  # servidor usa MSBFirst
            data = bytes(raw)

            width, height = mask_img.size
            win = self.dpy.create_resource_object("window", tk_window_id)
            pixmap = win.create_pixmap(width, height, 1)
            gc = pixmap.create_gc(foreground=1, background=0)
            pixmap.put_image(gc, 0, 0, width, height, X.XYBitmap, 1, 0, data)

            xlib_shape.combine(win, xlib_shape.SO.Set, xlib_shape.SK.Bounding, 0, 0, pixmap)
            xlib_shape.combine(win, xlib_shape.SO.Set, xlib_shape.SK.Input, 0, 0, pixmap)

            gc.free()
            pixmap.free()
            self.dpy.sync()
            return True
        except Exception as exc:
            self.last_shape_error = f"{type(exc).__name__}: {exc}"
            return False


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
        self.root.geometry(f"{WIDTH}x{self.cur_height}+{self._window_x}+{int(self.y)}")

        self.tk_image = None

        self.direction = random.choice([-1, 1])
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

        self.walk_frames = self._load_sprite_sheet_frames(
            "Folha de sprites_ caminhada em pixel art.png",
            4, 2, row_end_fractions=(0.86, 0.81),
        )
        self.balance_frames = self._load_sprite_sheet_frames(
            "Folha de sprites_ garota balançando.png",
            4, 2, row_end_fractions=(0.86, 0.81),
        )
        self.blink_frames = self._load_sprite_sheet_frames(
            "Folha de Sprites_ Animação de Piscada.png",
            3, 3, row_end_fractions=(0.87, 0.84, 0.82),
            cells=((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2)),
        )
        self.scaled_walk_frames = self._scale_frames(self.walk_frames)
        self.scaled_balance_frames = self._scale_frames(self.balance_frames)
        self.scaled_blink_frames = self._scale_frames(self.blink_frames)
        self._walk_frame_cache = {}
        self.drag_tilt = 0.0
        self.drag_target_tilt = 0.0
        self._last_drag_pointer_x = None
        self._last_drag_event_at = 0.0
        self._last_drag_motion_at = 0.0
        self.balance_tilt_frames = self._build_balance_tilt_frames()
        self.blink_frame_index = None
        self._blink_frame_step = 0
        self.next_blink_step = random.randint(30, 100)

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
        self.y = old_bottom - new_height
        self.root.geometry(f"{WIDTH}x{new_height}+{int(self.x)}+{int(self.y)}")

    # ---------- sprites pixel art ----------
    def _load_sprite_sheet_frames(
        self, filename, columns, rows, row_end_fractions, cells=None
    ):
        """Recorta quadros de uma folha e remove o fundo claro conectado às bordas."""
        sheet_path = MOVEMENTS_DIR / filename
        with Image.open(sheet_path) as source:
            sheet = source.convert("RGBA")
        cell_width = sheet.width / columns
        cell_height = sheet.height / rows
        frames = []
        frame_cells = cells or tuple(
            (column, row)
            for row in range(rows)
            for column in range(columns)
        )

        for column, row in frame_cells:
            left = round(column * cell_width)
            right = round((column + 1) * cell_width)
            top = round(row * cell_height)
            bottom = top + round(cell_height * row_end_fractions[row])
            frame = sheet.crop((left, top, right, bottom))
            frame = self._remove_sheet_background(frame)
            bounds = frame.getchannel("A").getbbox()
            if bounds is None:
                raise ValueError(
                    f"Nenhum personagem encontrado no quadro {filename} "
                    f"(coluna {column + 1}, linha {row + 1})."
                )
            frame = frame.crop(bounds)
            frame.thumbnail((SPRITE_MAX_W, SPRITE_MAX_H), SPRITE_RESAMPLE)
            canvas = Image.new("RGBA", (SPRITE_MAX_W, SPRITE_MAX_H), (0, 0, 0, 0))
            position = ((SPRITE_MAX_W - frame.width) // 2, SPRITE_MAX_H - frame.height)
            canvas.alpha_composite(frame, position)
            frames.append(canvas)
        return frames

    @staticmethod
    def _remove_sheet_background(frame):
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

    @staticmethod
    def _scale_frames(frames):
        return [
            frame.resize((frame.width * SCALE, frame.height * SCALE), Image.Resampling.NEAREST)
            for frame in frames
        ]

    def _build_balance_tilt_frames(self):
        """Precalcula inclinações suaves, girando ao redor dos pés."""
        sprite = self.scaled_balance_frames[0]
        max_angle = 18
        padding = math.ceil(sprite.height * math.sin(math.radians(max_angle))) + 4
        canvas = Image.new("RGBA", (sprite.width + padding * 2, sprite.height), (0, 0, 0, 0))
        canvas.alpha_composite(sprite, (padding, 0))
        center = (padding + sprite.width / 2, sprite.height - 1)
        frames = {0: sprite}

        for angle in range(-max_angle, max_angle + 1):
            if angle == 0:
                continue
            rotated = canvas.rotate(
                angle, resample=Image.Resampling.NEAREST, expand=False, center=center
            )
            frames[angle] = rotated.crop((padding, 0, padding + sprite.width, sprite.height))
        return frames

    def _advance_blink(self):
        is_idle = self.state != "held" and (self.state != "walk" or self.busy)
        if not is_idle:
            self.blink_frame_index = None
            return

        if self.blink_frame_index is None:
            if self.step >= self.next_blink_step:
                self.blink_frame_index = 0
                self._blink_frame_step = self.step
        elif self.step - self._blink_frame_step >= 1:
            self.blink_frame_index += 1
            self._blink_frame_step = self.step
            if self.blink_frame_index >= len(self.scaled_blink_frames):
                self.blink_frame_index = None
                self.next_blink_step = self.step + random.randint(75, 150)

    def _sprite_for_current_pose(self):
        if self.state == "held":
            angle = max(-18, min(18, int(round(self.drag_tilt))))
            if angle:
                return self.balance_tilt_frames[angle]
            frame_index = int(self.animation_time_ms // ANIMATION_FRAME_MS) % len(
                self.scaled_balance_frames
            )
            return self.scaled_balance_frames[frame_index]

        if self.state == "walk" and not self.busy:
            frame_index = int(self.animation_time_ms // ANIMATION_FRAME_MS) % len(
                self.scaled_walk_frames
            )
            sprite = self.scaled_walk_frames[frame_index]
            if self.direction < 0:
                sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            return sprite

        if self.blink_frame_index is not None:
            return self.scaled_blink_frames[self.blink_frame_index]
        return self.scaled_blink_frames[0]

    def render_frame(self):
        """Renderiza a personagem usando os sprites pixel art gerados para ela."""
        w, h = WIDTH * SCALE, self.cur_height * SCALE
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        bubble_h = 0
        if self.bubble_text:
            draw = ImageDraw.Draw(img, "RGBA")
            bubble_h = self.draw_bubble(draw, self.bubble_text, w)

        sprite = self._sprite_for_current_pose()
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

        # O sprite já contém a sombra de chão; o restante do canvas fica transparente.
        img = img.resize((WIDTH, self.cur_height), Image.Resampling.NEAREST)
        return img

    def capsule_line(self, draw, x1, y1, x2, y2, width, fill):
        r = width / 2
        draw.line([x1, y1, x2, y2], fill=fill, width=int(width))
        draw.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=fill)
        draw.ellipse([x2 - r, y2 - r, x2 + r, y2 + r], fill=fill)

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

        cache_key = self._walk_frame_cache_key()
        cached_frame = self._walk_frame_cache.get(cache_key) if cache_key is not None else None
        if cached_frame is None:
            frame = self.render_frame()
            self.tk_image = ImageTk.PhotoImage(frame)
            if cache_key is not None:
                self._walk_frame_cache[cache_key] = (frame, self.tk_image)
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

    def _walk_frame_cache_key(self):
        if self.state != "walk" or self.busy or self.dragging or self.bubble_text:
            return None
        frame_index = int(self.animation_time_ms // ANIMATION_FRAME_MS) % len(
            self.scaled_walk_frames
        )
        bob = int(abs(math.sin(self.animation_time_ms / 1000 * 3.75)) * 2 * SCALE)
        return frame_index, self.direction, bob

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
        self._advance_blink()

        if self.dragging:
            if time.monotonic() - self._last_drag_motion_at > 0.12:
                self.drag_target_tilt = 0.0
            self.drag_tilt += (self.drag_target_tilt - self.drag_tilt) * 0.24
        else:
            self.drag_tilt = 0.0
            self.drag_target_tilt = 0.0

        if self.state == "walk" and not self.dragging and not self.busy:
            self.x += self.direction * WALK_SPEED * elapsed
            if self.x < 0 or self.x > self.screen_w - WIDTH:
                self.direction *= -1
                self.x = max(0, min(self.x, self.screen_w - WIDTH))
            window_x = int(round(self.x))
            if window_x != self._window_x:
                self._window_x = window_x
                self.root.geometry(f"+{window_x}+{int(self.y)}")

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
