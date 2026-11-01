"""Respostas locais e comandos simples que não precisam consultar o modelo."""

from datetime import datetime
import re
import unicodedata

WEEKDAYS_PT = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
MONTHS_PT = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def current_datetime_context(now=None):
    if now is None:
        now = datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    weekday = WEEKDAYS_PT[now.weekday()]
    month = MONTHS_PT[now.month - 1]
    timezone_name = now.tzname() or "horário local"
    return (
        f"Data e hora locais atuais: {weekday}, {now.day} de {month} de "
        f"{now.year}, {now:%H:%M} ({timezone_name}). Use essa informação "
        "para responder corretamente perguntas sobre hoje, datas e horários."
    )


def _normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def current_date_answer(question, now=None):
    normalized = _normalize(question)
    if "hoje" not in normalized:
        return None
    asks_day_or_date = (
        re.search(r"\b(que|qual)\s+(dia|data)\b", normalized)
        or re.search(r"\b(dia|data)\s+(de\s+)?hoje\b", normalized)
        or re.search(r"\bhoje\s+(e|eh)\s+(que\s+)?(dia|data)\b", normalized)
    )
    if not asks_day_or_date:
        return None
    if now is None:
        now = datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    weekday = WEEKDAYS_PT[now.weekday()]
    month = MONTHS_PT[now.month - 1]
    return f"Hoje é {weekday}, {now.day} de {month} de {now.year}."


def local_personality_intent(question, hour=None):
    """Return a local personality category and animation, without consulting an AI."""
    normalized = _normalize(question)
    if not normalized:
        return None

    if re.search(r"\b(bom dia|bom-dia)\b", normalized):
        return "greeting_morning", "wave"
    if re.search(r"\b(boa tarde)\b", normalized):
        return "greeting_afternoon", "wave"
    if re.search(r"\b(boa noite)\b", normalized):
        return "greeting_evening", "wave"
    if (
        re.search(r"\b(tudo bem|como vai)\b", normalized)
        or re.fullmatch(r"(oi|ola|e ai|hey)[!.? ]*", normalized)
    ):
        greeting_hour = datetime.now().astimezone().hour if hour is None else hour
        category = (
            "greeting_morning" if greeting_hour < 12 else
            "greeting_afternoon" if greeting_hour < 18 else
            "greeting_evening"
        )
        return category, "wave"
    if re.search(r"\b(me elogia|me faz um elogio|faz um elogio)\b", normalized):
        return "compliment", "thumbs_up"
    if re.search(r"\b(conta|conte|me conta|me conte)\b.*\b(piadas?|engracad[oa])\b", normalized) or re.search(
        r"\b(piadas?|engracad[oa])\b", normalized
    ):
        return "jokes", "wave"
    if re.search(r"\b(danca|dancar|dancinha|dancando)\b", normalized):
        return "dance", "celebrate"
    if re.search(r"\b(acena|acenar|manda um oi|da um oi)\b", normalized):
        return "click", "wave"
    if re.search(r"\b(joinha|positivo|sinal positivo)\b", normalized):
        return "compliment", "thumbs_up"
    if re.search(r"\b(dorme|dormir|dormir um pouco)\b", normalized):
        return "yawning", "sleep"
    if re.search(r"\b(descansa|descansar|pausa)\b", normalized):
        return "break_tip", "rest"
    if re.search(r"\b(some|sumir|esconde|esconder)\b", normalized):
        return "peekaboo", "vanishing"
    return None


def is_open_calendar_request(question):
    normalized = _normalize(question)
    if "calendario" not in normalized:
        return False
    if normalized in ("calendario", "meu calendario", "abrir calendario"):
        return True
    return bool(
        re.search(
            r"\b(abre|abrir|abra|mostra|mostre|mostrar|exibe|exibir|ver|veja|quero|abre)\b",
            normalized,
        )
    )
