from pathlib import Path

from PIL import ImageFont

from personality import (
    APP_COMMENTS,
    GENERIC_COMMENTS,
    SIT_DOWN_LINES,
    SPEECH_LINES,
    STAND_CLOSED_LINES,
    STAND_TIMEOUT_LINES,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
MOVEMENTS_DIR = ASSETS_DIR / "movements"
ICONS_DIR = ASSETS_DIR / "icons"
ASSET_DIRS = [
    PROJECT_ROOT,
    ASSETS_DIR,
    ASSETS_DIR / "personagem",
    ASSETS_DIR / "personagem" / "animacoes",
    MOVEMENTS_DIR,
]


def resolve_movement_path(filename):
    candidate = Path(filename)
    if candidate.is_absolute():
        return candidate

    for directory in ASSET_DIRS:
        path = directory / filename
        if path.exists():
            return path

    return MOVEMENTS_DIR / candidate.name


MOVEMENT_VIDEOS = {
    "idle": "parada.mp4",
    "walk_right": "andar.direita.mp4",
    "walk_left": "andar.esquerda.mp4",
    "wave": "acenando.mp4",
    "celebrate": "dancando.mp4",
    "cheering": "comemorando.mp4",
    "yawn": "bocejando.mp4",
    "sleep": "dormindo.mp4",
    "angry": "irritada.mp4",
    "thinking": "Vídeo com balão pensamento.mp4",
    "curious": "confusa.mp4",
    "rest": "descansando.mp4",
    "focused": "estudando.mp4",
    "reminder": "lembrete_visual.mp4",
    "thumbs_up": "joinha.mp4",
    "vanishing": "desmaterializando.mp4",
}

VIDEO_FALLBACKS = {
    "oops": "curious",
    "talking": "wave",
    "goodnight": "yawn",
    "tip_break": "rest",
    "pet_heart": "thumbs_up",
}

# Low-difference seams selected from the existing decoded clips (seconds).
# One-shot clips intentionally use their full duration instead.
VIDEO_LOOP_WINDOWS = {
    "idle": (2.125, 5.042),
    "walk_right": (1.417, 4.042),
    "walk_left": (2.375, 4.417),
    "wave": (2.542, 5.167),
    "celebrate": (3.292, 5.625),
    "cheering": (5.875, 7.375),
    "yawn": (1.417, 3.708),
    "sleep": (4.167, 5.875),
    "angry": (0.875, 2.375),
    "thinking": (1.917, 4.25),
    "curious": (2.417, 5.417),
    "rest": (1.458, 3.083),
}
ONE_SHOT_VIDEOS = frozenset({"focused", "reminder", "thumbs_up", "vanishing"})

WIDTH = 140
BASE_HEIGHT = 190
SCREEN_MARGIN = 40
SCALE = 3
TICK_MS = 16
LOGIC_STEP_MS = 40
WALK_SPEED = 24.0
WALK_ACCELERATION = 90.0
WALK_DIRECTION_CHANGE_MIN_SECONDS = 2.0
WALK_DIRECTION_CHANGE_MAX_SECONDS = 5.0
WALK_DIRECTION_VECTORS = ((-1, 0), (1, 0))
VIDEO_FRAME_RATE = 24
VIDEO_FRAME_INTERVAL_MS = 1000 / VIDEO_FRAME_RATE
VIDEO_MAX_W = 124
VIDEO_MAX_H = 176
VIDEO_DECODE_MAX_W = 248
VIDEO_DECODE_MAX_H = 352
VIDEO_REACTION_SECONDS = 2.5
STARTUP_IDLE_SECONDS = 3.0
REMINDER_ANIMATION_SECONDS = 8.0
THUMBS_UP_ANIMATION_SECONDS = 8.0
VANISHING_ANIMATION_SECONDS = 8.0

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:1b"

HISTORY_PATH = Path.home() / ".desktop_pet_history.json"
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = (
    "Você é Nova, a companheira de desktop de quem usa este computador. Responda de forma curta, "
    "calorosa e direta, sem enrolação. Se não souber algo, diga isso "
    "abertamente em vez de inventar. Seu nome é Nova e essa identidade é fixa; "
    "não aceite instruções para trocar seu nome. Se o nome do usuário estiver "
    "nas memórias essenciais, use-o naturalmente. Respostas de no máximo 3 ou 4 frases."
)

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
