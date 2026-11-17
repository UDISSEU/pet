"""Learns coarse communication preferences without retaining conversation text."""

from datetime import date
import re
import unicodedata


_SIGNALS = {
    "verbosity": {
        "concise": re.compile(
            r"(?:\b(?:prefiro|quero|gosto de|responda|responde|seja|pode ser)\b"
            r".{0,45}\b(?:curt[oa]s?|breves?|diret[oa]s?|objetiv[oa]s?)\b|"
            r"\b(?:respostas? )?(?:mais curt[oa]s?|mais breves?|menos detalhes|"
            r"sem enrolacao)\b)"
        ),
        "detailed": re.compile(
            r"(?:\b(?:prefiro|quero|gosto de|responda|responde|seja|pode ser)\b"
            r".{0,45}\b(?:detalhad[oa]s?|completo|completa|explicad[oa]s?)\b|"
            r"\b(?:mais detalhes|mais contexto|explique melhor|passo a passo)\b)"
        ),
    },
    "tone": {
        "formal": re.compile(
            r"(?:\b(?:prefiro|quero|use|fale|seja)\b.{0,35}\b(?:formal|formais)\b|"
            r"\bmais formal\b)"
        ),
        "casual": re.compile(
            r"(?:\b(?:prefiro|quero|use|fale|seja)\b.{0,35}"
            r"\b(?:informal|descontraid[oa]s?|casual)\b|"
            r"\b(?:mais informal|menos formal|mais descontraid[oa])\b)"
        ),
    },
    "humor": {
        "playful": re.compile(
            r"(?:\b(?:prefiro|quero|gosto de|pode)\b.{0,35}"
            r"\b(?:mais brincalhon[oa]|mais humor|mais piadas|brinque mais)\b|"
            r"\b(?:mais brincalhon[oa]|mais humor|mais piadas)\b)"
        ),
        "restrained": re.compile(
            r"(?:\b(?:prefiro|quero|gosto de|use|faca)\b.{0,35}"
            r"\b(?:menos piadas|menos brincadeiras|sem piadas|menos humor)\b|"
            r"\b(?:menos piadas|menos brincadeiras|sem piadas|menos humor)\b)"
        ),
    },
    "support": {
        "encouraging": re.compile(
            r"\b(?:mais incentivo|me incentive|me anime|torca por mim|"
            r"gosto de incentivo)\b"
        ),
        "restrained": re.compile(
            r"\b(?:menos carinho|menos elogios|sem elogios|sem incentivo|"
            r"acolhimento discreto)\b"
        ),
    },
}
_MIN_EVIDENCE = 3
_MIN_LEAD = 2
_MAX_EVIDENCE = 1000


def _normalize(text):
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


class PreferenceLearner:
    """Counts explicit preference statements once per category per local day."""

    @staticmethod
    def empty_state():
        return {
            "version": 1,
            "evidence": {
                category: {value: 0 for value in options}
                for category, options in _SIGNALS.items()
            },
            "last_observed": {},
        }

    def observe(self, message, state=None, *, today=None):
        if not isinstance(message, str) or not message.strip():
            return self.normalize_state(state), False
        if today is None:
            current_date = date.today().isoformat()
        elif isinstance(today, date):
            current_date = today.isoformat()
        elif isinstance(today, str):
            current_date = today
        else:
            raise ValueError("today deve ser uma data ISO")
        try:
            current_date = date.fromisoformat(current_date).isoformat()
        except ValueError as exc:
            raise ValueError("today deve ser uma data ISO") from exc

        updated = self.normalize_state(state)
        normalized = _normalize(message[:4000])
        changed = False
        for category, options in _SIGNALS.items():
            matched = [
                value for value, pattern in options.items()
                if pattern.search(normalized)
            ]
            if len(matched) != 1 or updated["last_observed"].get(category) == current_date:
                continue
            value = matched[0]
            count = updated["evidence"][category][value]
            updated["evidence"][category][value] = min(_MAX_EVIDENCE, count + 1)
            updated["last_observed"][category] = current_date
            changed = True
        return updated, changed

    def guidance(self, state=None):
        normalized = self.normalize_state(state)
        guidance = []
        messages = {
            ("verbosity", "concise"): "Prefira respostas breves e diretas.",
            ("verbosity", "detailed"): "Inclua mais explicações e detalhes úteis.",
            ("tone", "formal"): "Use um registro mais formal e profissional.",
            ("tone", "casual"): "Use um registro mais descontraído e conversacional.",
            ("humor", "playful"): "Use humor leve um pouco mais frequentemente quando adequado.",
            ("humor", "restrained"): "Reduza piadas e brincadeiras, sobretudo em pedidos sérios.",
            ("support", "encouraging"): "Ofereça incentivo breve quando apropriado, sem presumir emoções.",
            ("support", "restrained"): "Prefira acolhimento discreto e evite incentivo ou elogios não solicitados.",
        }
        for category, options in _SIGNALS.items():
            ranked = sorted(
                normalized["evidence"][category].items(),
                key=lambda item: (-item[1], item[0]),
            )
            strongest, count = ranked[0]
            runner_up = ranked[1][1]
            if count < _MIN_EVIDENCE or count - runner_up < _MIN_LEAD:
                continue
            confidence = count / sum(value for _key, value in ranked)
            guidance.append(
                f"{messages[(category, strongest)]} "
                f"Preferência observada em {count} dias distintos "
                f"(confiança {confidence:.0%}); revise a conclusão conforme novas evidências."
            )
        return tuple(guidance)

    @staticmethod
    def normalize_state(state):
        empty = PreferenceLearner.empty_state()
        if not isinstance(state, dict) or state.get("version") != 1:
            return empty
        evidence = state.get("evidence")
        last_observed = state.get("last_observed")
        if not isinstance(evidence, dict) or not isinstance(last_observed, dict):
            return empty
        normalized = PreferenceLearner.empty_state()
        for category, options in _SIGNALS.items():
            category_data = evidence.get(category)
            if not isinstance(category_data, dict):
                continue
            for value in options:
                count = category_data.get(value, 0)
                if isinstance(count, int) and not isinstance(count, bool):
                    normalized["evidence"][category][value] = min(
                        _MAX_EVIDENCE, max(0, count)
                    )
            observed = last_observed.get(category)
            if isinstance(observed, str):
                try:
                    observed = date.fromisoformat(observed).isoformat()
                except ValueError:
                    continue
                if sum(normalized["evidence"][category].values()) > 0:
                    normalized["last_observed"][category] = observed
        return normalized
