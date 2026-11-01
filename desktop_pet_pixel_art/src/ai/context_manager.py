"""Monta contexto curto para respeitar privacidade e limites de recursos."""

import re


_TRUNCATION_MARKER = "[… início omitido …]\n"


def _keep_tail(text, limit):
    """Trim old text without making the retained fragment look complete."""
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return text[-limit:] if limit else ""
    return _TRUNCATION_MARKER + text[-(limit - len(_TRUNCATION_MARKER)):]


class ContextManager:
    max_messages = 12
    max_message_chars = 4000
    max_memories = 8
    max_context_chars = 16000
    max_memory_chars = 3000

    def build(self, history, memories=None):
        valid_history = []
        for message in history or []:
            if not isinstance(message, dict):
                continue
            role, content = message.get("role"), message.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            valid_history.append({
                "role": role,
                "content": _keep_tail(content, self.max_message_chars),
            })
        # Walk backwards so a large old conversation cannot crowd out the latest turn.
        messages = []
        used_chars = 0
        for message in reversed(valid_history[-self.max_messages:]):
            remaining = self.max_context_chars - used_chars
            if remaining <= len(_TRUNCATION_MARKER):
                break
            content = _keep_tail(message["content"], remaining)
            messages.append({"role": message["role"], "content": content})
            used_chars += len(content)
        messages.reverse()
        chosen = []
        latest_question = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        query_terms = {
            term for term in re.findall(r"[\wÀ-ÿ]{3,}", latest_question.casefold())
            if term not in {"que", "com", "para", "por", "uma", "uns", "das", "dos", "the", "and"}
        }
        ranked = []
        seen_memories = set()
        candidates = list(memories or [])
        for memory in candidates:
            if not isinstance(memory, str) or not memory.strip():
                continue
            memory = memory.strip()[:500]
            canonical = " ".join(memory.split()).casefold()
            if canonical in seen_memories:
                continue
            seen_memories.add(canonical)
            memory_terms = set(re.findall(r"[\wÀ-ÿ]{3,}", canonical))
            overlap = query_terms & memory_terms
            if overlap:
                ranked.append((len(overlap), memory))
        for _score, memory in sorted(ranked, key=lambda item: (-item[0], item[1].casefold())):
            if len(chosen) >= self.max_memories:
                break
            remaining = self.max_memory_chars - sum(map(len, chosen))
            if remaining <= 0:
                break
            chosen.append(memory[:remaining])
        return messages, chosen
