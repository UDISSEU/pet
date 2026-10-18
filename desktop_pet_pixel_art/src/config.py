from pathlib import Path

from PIL import ImageFont

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
        if candidate.exists():
            return candidate
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
    "sleep": "dormindo.mp4",
    "angry": "irritada.mp4",
    "thinking": "Vídeo com balão pensamento.mp4",
}

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
VIDEO_REACTION_SECONDS = 2.5

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
    "Você é Nova, a companheira de desktop do Ulisses. Responda de forma curta, "
    "calorosa e direta, sem enrolação. Se não souber algo, diga isso "
    "abertamente em vez de inventar. Respostas de no máximo 3 ou 4 frases."
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
