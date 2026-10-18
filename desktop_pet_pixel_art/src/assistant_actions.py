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
