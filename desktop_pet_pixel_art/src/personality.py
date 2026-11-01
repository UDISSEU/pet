"""Reusable, UI-independent personality lines and selection rules for Nova."""

from datetime import datetime
import random
import re
import time


_FALLBACK_LINES = (
    "Estou aqui com você.",
    "Um passinho de cada vez, tá?",
    "Pode contar comigo.",
    "Que bom dividir esse momento com você.",
    "Respira: não precisa resolver tudo de uma vez.",
    "Tô por aqui, no seu ritmo.",
)

SPEECH_POOLS = {
    "idle_chatter": (
        "Oi! Como está indo por aí?",
        "Passando para fazer companhia.",
        "Espero que seu dia esteja leve.",
        "Se precisar, é só me chamar.",
        "Estou aqui torcendo por você.",
        "Um carinho em forma de companhia.",
        "Já bebeu uma aguinha hoje?",
        "Vai no seu tempo; cada passo conta.",
    ),
    "greeting_morning": (
        "Bom dia, {nome}! Que seu começo seja gentil.",
        "Bom dia, {nome}! Um passo de cada vez.",
        "Que bom te ver nesta manhã, {nome}!",
        "Bom dia! Espero que você tenha descansado.",
        "Uma manhã novinha para começar com calma.",
        "Bom dia, {nome}! Estou aqui com você.",
    ),
    "greeting_afternoon": (
        "Boa tarde, {nome}! Como está seu ritmo?",
        "Que bom te ver por aqui, {nome}!",
        "Boa tarde! Espero que esteja tudo bem.",
        "Uma pausa carinhosa no meio da tarde.",
        "Boa tarde, {nome}! Vamos com calma.",
        "Oi, {nome}! Que a tarde seja leve.",
    ),
    "greeting_evening": (
        "Boa noite, {nome}! Espero que seu dia tenha sido bom.",
        "Que bom te ver, {nome}. Vamos desacelerar?",
        "Boa noite! Você merece um descanso tranquilo.",
        "O dia está terminando; pega leve com você.",
        "Boa noite, {nome}! Estou aqui pertinho.",
        "Que sua noite tenha um pouco de sossego.",
    ),
    "click": (
        "Oi! Você me chamou?",
        "Opa, estou aqui!",
        "Um aceno só para você!",
        "Oi, que bom receber sua visita.",
        "Pode falar comigo quando quiser.",
        "Acenei de volta! Tudo bem por aí?",
    ),
    "rapid_click": (
        "Calma, meu bem! Um clique de cada vez.",
        "Opa, estou ouvindo! Pode ir com calma.",
        "Hehe, assim eu fico tonta!",
        "Recebi o recado, vamos devagarinho?",
        "Ui! Minha cabecinha pixelada!",
        "Tô aqui! Respira comigo um instantinho.",
    ),
    "pickup": (
        "Eba, passeio no colo!",
        "Segurou firme? Lá vamos nós!",
        "Adoro uma carona com você.",
        "Estou segura aí, né?",
        "Passeio de Nova, que divertido!",
        "Pode me levar, vou com cuidado.",
    ),
    "drop": (
        "Pouso macio! Obrigada.",
        "Prontinho, voltei para o meu cantinho.",
        "Valeu pelo passeio!",
        "Cheguei inteirinha, obrigada pelo cuidado.",
        "Aterrissagem perfeita!",
        "Já estou de volta por aqui.",
    ),
    "focus_start": (
        "Boa sessão! Vou ficar na torcida.",
        "Você cuida da tarefa; eu cuido da torcida.",
        "Um passo de cada vez. Você consegue.",
        "Hora de focar com gentileza.",
        "Estou aqui quietinha enquanto você trabalha.",
        "Que bom que você reservou esse tempo.",
    ),
    "focus_mid": (
        "Você já chegou até aqui. Continue no seu ritmo.",
        "Só passando para lembrar: está indo bem.",
        "Respira fundo e volta para uma coisa de cada vez.",
        "Seu esforço de agora também conta.",
        "Foco gentil, sem precisar ser perfeito.",
        "Mais um pouquinho; estou torcendo por você.",
    ),
    "focus_done": (
        "Você conseguiu! Estou muito orgulhosa.",
        "Mandou bem; seu esforço valeu.",
        "Tarefa concluída, coração mais leve!",
        "Parabéns por cuidar da sua prioridade.",
        "Você chegou ao fim dessa etapa. Boa!",
        "Que conquista bonita. Celebra um pouquinho!",
    ),
    "break_tip": (
        "Solta os ombros e faz um alongamento leve.",
        "Uma aguinha pode fazer bem. Vamos beber?",
        "Olha para longe por alguns segundos.",
        "Levanta com calma e dá uma esticadinha.",
        "Descansa os olhos; eles trabalharam bastante.",
        "Respira fundo e dá um carinho no seu corpo.",
    ),
    "break_end": (
        "Pausa feita! Quando quiser, seguimos.",
        "Espero que esse respiro tenha ajudado.",
        "Prontinha para a próxima etapa, sem pressa.",
        "Obrigada por cuidar de você um pouquinho.",
        "Que bom que você fez essa pausa.",
        "Voltamos no seu ritmo. Você decide.",
    ),
    "reminder_due": (
        "Um lembrete chegou para você.",
        "Psiu, tem uma coisinha para lembrar.",
        "Passando com um lembrete carinhoso.",
        "Seu lembrete está aqui; confira quando puder.",
        "Não deixa passar: chegou a hora do lembrete.",
        "Um recadinho importante está esperando.",
    ),
    "evening_wrap": (
        "O dia já rendeu bastante. Pode descansar.",
        "Se puder, encerra por hoje com carinho.",
        "Seu descanso também faz parte do caminho.",
        "Hora de desacelerar e cuidar de você.",
        "O que ficou pode esperar um pouquinho.",
        "Que tal fechar o dia com uma respiração tranquila?",
    ),
    "app_launch_ok": (
        "Prontinho, abri para você!",
        "Aplicativo aberto. Bom proveito!",
        "Tudo certo por aqui; pode começar.",
        "Consegui! Já deixei o app prontinho.",
        "Abriu direitinho. Vamos nessa?",
        "Missão cumprida, o app está aberto!",
    ),
    "oops": (
        "Ops, não deu certo desta vez. Quer tentar de novo?",
        "Encontrei um tropeço, mas estou aqui com você.",
        "Não consegui completar isso agora. Vamos com calma?",
        "Algo não funcionou; podemos tentar outro caminho.",
        "Foi mal, encontrei uma dificuldade por aqui.",
        "Não saiu como esperado. Quer tentar mais uma vez?",
    ),
    "compliment": (
        "Você merece reconhecimento pelo que está tentando.",
        "Seu jeito de persistir é muito especial.",
        "Você tem valor, inclusive nos dias difíceis.",
        "Gosto da sua coragem de continuar aprendendo.",
        "Você merece falar consigo com carinho.",
        "Tem muita coisa bonita no jeito que você segue.",
    ),
    "dance": (
        "Pista aberta! Essa dancinha é para você!",
        "Balança comigo? Só vale se divertir!",
        "Dancinha pixelada para alegrar o momento!",
        "Uma música imaginária e um passinho feliz!",
        "Bora mexer os pixels um pouquinho?",
        "Essa dança vai no seu ritmo!",
    ),
    "miss_you": (
        "Que saudade! Fico feliz que você voltou.",
        "Fazia um tempinho, {nome}. Que bom te ver!",
        "Senti falta da sua companhia por aqui.",
        "Olha quem voltou! Meu dia ficou mais alegre.",
        "Que bom ter você de volta, {nome}!",
        "A casa ficou mais feliz com sua visita.",
    ),
    "sit_down": (
        "Ufa... só um descansinho.",
        "Cansei de andar por aí.",
        "Cadeira improvisada, hihi.",
        "Vou sentar um pouquinho, tudo bem?",
        "Minhas perninhas pediram uma pausa.",
        "Um minutinho de descanso por aqui.",
    ),
    "stand_closed": (
        "Ei, sumiu minha cadeira!",
        "A janela fechou, levantando!",
        "Pronto, achei outro cantinho.",
        "Levantei para continuar por aqui.",
        "Tudo bem, fico de pé mais um pouco.",
        "Voltei para o passeio!",
    ),
    "stand_timeout": (
        "Descanso acabou, vamo lá de novo.",
        "Pausa feita! Vou dar mais uma voltinha.",
        "Obrigada pela cadeira emprestada.",
        "Já descansei; hora de caminhar.",
        "Pronto, minhas pernas agradecem!",
        "Voltei renovada para o passeio.",
    ),
    "yawning": (
        "Haaam... hora de espreguiçar.",
        "Um bocejo e já volto!",
        "Acho que meu soninho está chegando.",
        "Vou bocejar bem baixinho.",
        "Pisquei devagar, quase cochilei.",
        "Uma espreguiçada para renovar as energias.",
    ),
    "surprise": (
        "Passei só para deixar um oi para você!",
        "Uma pausa pequena também conta.",
        "Surpresinha: você está indo muito bem!",
        "Trouxe um aceno e um pouquinho de companhia.",
        "Só queria lembrar que estou torcendo por você.",
        "Uma visita surpresa para alegrar o cantinho!",
    ),
    "peekaboo": (
        "Cadê eu? Ah, aqui!",
        "Voltei! Sentiu minha falta?",
        "Tcharam, apareci de novo!",
        "Escondi e já voltei para perto.",
        "Achou a Nova!",
        "Prontinho, estou de volta.",
    ),
}

JOKES = (
    "Por que o computador foi ao médico? Estava com um vírus!",
    "Qual é o café favorito do computador? O Java.",
    "O que o zero disse para o oito? Que cinto bonito!",
    "Por que o livro de matemática ficou triste? Tinha muitos problemas.",
    "O que uma parede disse para a outra? A gente se encontra na esquina.",
    "Por que a plantinha não foi ao médico? Porque estava com tosse de folha.",
    "Qual é o animal mais antigo? A zebra, porque está em preto e branco.",
    "O que o lápis falou para o papel? Você me completa!",
    "Por que o tomate foi ao banco? Para tirar extrato.",
    "O que a nuvem falou para a outra? Está tudo tão carregado hoje!",
)
SPEECH_POOLS["jokes"] = JOKES

APP_COMMENTS = {
    "youtube": (
        "Rindo do vídeo ou é sério isso?",
        "Mais um vídeo pra 'só um rapidinho', né?",
        "O algoritmo te pegou de novo.",
        "Assistindo ou trabalhando? 👀",
        "Esse vídeo parece interessante!",
        "Pausa para um vídeo também vale.",
    ),
    "firefox": ("Navegando por aí?", "Achou algo legal?", "A internet está cheia de caminhos.", "Muitas abas abertas?", "Boa pesquisa!", "Descobrindo novidades?"),
    "chrome": ("Navegando por aí?", "Muitas abas, hein?", "Encontrou o que procurava?", "Boa pesquisa!", "A internet está cheia de caminhos.", "Só mais uma aba?"),
    "chromium": ("Navegando por aí?", "Encontrou algo interessante?", "Boa pesquisa!", "Muitas abas abertas?", "Descobrindo novidades?", "A internet está cheia de caminhos."),
    "code": ("Bora codar!", "Código novo?", "Analista de dados on!", "Uma linha por vez.", "Debugando com carinho?", "Que projeto está tomando forma?"),
    "sublime": ("Editando código?", "Uma linha por vez.", "Código novo?", "Debugando com carinho?", "Que projeto está tomando forma?", "Bora codar!"),
    "terminal": ("Modo terminal ativado.", "Linha de comando é vida!", "Um comando por vez.", "O terminal está sob controle?", "Bora codar!", "Analista de dados on!"),
    "xterm": ("Modo terminal ativado.", "Um comando por vez.", "O terminal está sob controle?", "Linha de comando é vida!", "Bora codar!", "Analista de dados on!"),
    "thunar": ("Organizando arquivos?", "Tudo no seu lugar?", "Faxina digital em andamento?", "Que pastas bonitas!", "Seu cantinho está organizado.", "Encontrou o arquivo?"),
    "nautilus": ("Organizando arquivos?", "Tudo no seu lugar?", "Faxina digital em andamento?", "Que pastas bonitas!", "Seu cantinho está organizado.", "Encontrou o arquivo?"),
    "files": ("Vendo seus arquivos?", "Tudo no seu lugar?", "Encontrou o que procurava?", "Seu cantinho está organizado.", "Faxina digital em andamento?", "Que pastas bonitas!"),
    "libreoffice": ("Trabalhando em documento?", "Uma frase de cada vez.", "Esse texto está tomando forma.", "Boa escrita!", "Pausa para salvar?", "Seu trabalho está avançando."),
    "gimp": ("Editando imagem, que bonito!", "Criatividade em pixels!", "Essa arte está tomando forma.", "Que cores lindas!", "Hora de criar!", "Seu olhar artístico está on."),
    "spotify": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
    "music": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
    "rhythmbox": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
}
GENERIC_COMMENTS = (
    "Vendo o que você está fazendo.",
    "Te acompanhando por aqui.",
    "Estou por perto.",
    "Como vai esse cantinho?",
    "Espero que esteja tudo bem.",
    "Um oi da sua Nova!",
)

SPEECH_LINES = SPEECH_POOLS["idle_chatter"]
SIT_DOWN_LINES = SPEECH_POOLS["sit_down"][:3]
STAND_CLOSED_LINES = SPEECH_POOLS["stand_closed"][:2]
STAND_TIMEOUT_LINES = SPEECH_POOLS["stand_timeout"][:1]

_recent_lines = []
_last_spontaneous_speech_at = None


def _greeting_category(hour):
    if hour is None:
        hour = datetime.now().astimezone().hour
    if hour < 12:
        return "greeting_morning"
    if hour < 18:
        return "greeting_afternoon"
    return "greeting_evening"


def pick_line(category, name="", hour=None, rng=random, history=None):
    """Choose a short line, avoiding the last three selections in its history."""
    if category == "greeting":
        category = _greeting_category(hour)
    lines = SPEECH_POOLS.get(category, ())
    recent = _recent_lines if history is None else history
    candidates = lines or _FALLBACK_LINES
    available = [line for line in candidates if line not in recent[-3:]]
    if not available:
        available = [line for line in _FALLBACK_LINES if line not in recent[-3:]]
    line = rng.choice(available or _FALLBACK_LINES)
    clean_name = name.strip() if isinstance(name, str) else ""
    line = line.replace("{nome}", clean_name)
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\s+([,.!?])", r"\1", line)
    line = re.sub(r",\s*([.!?])", r"\1", line)
    line = re.sub(r"\s*,\s*$", "", line)
    if history is not None:
        history.append(line)
        del history[:-3]
    else:
        _recent_lines.append(line)
        del _recent_lines[:-3]
    return line


def can_speak_spontaneously(now=None, cooldown=20):
    """Return whether the shared spontaneous-speech cooldown has elapsed."""
    if now is None:
        now = time.monotonic()
    required_cooldown = max(20.0, float(cooldown))
    return (
        _last_spontaneous_speech_at is None
        or now - _last_spontaneous_speech_at >= required_cooldown
    )


def record_spontaneous_speech(now=None):
    """Start the shared cooldown after a spontaneous line is shown."""
    global _last_spontaneous_speech_at
    _last_spontaneous_speech_at = time.monotonic() if now is None else now


def reset_personality_state():
    """Reset shared selection state for tests and a newly started mascot."""
    global _last_spontaneous_speech_at
    _recent_lines.clear()
    _last_spontaneous_speech_at = None
