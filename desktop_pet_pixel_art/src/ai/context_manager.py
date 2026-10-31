"""Monta contexto curto para respeitar privacidade e limites de recursos."""

import re


class ContextManager:
    max_messages = 12
    max_message_chars = 4000
    max_memories = 8

    def build(self, history, memories=None, user_name=""):
        messages = []
        valid_history = []
        for message in history or []:
            if not isinstance(message, dict):
                continue
            role, content = message.get("role"), message.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            valid_history.append({"role": role, "content": content[-self.max_message_chars:]})
        messages = valid_history[-self.max_messages:]
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
        candidates = list(memories or [])
        for memory in candidates:
            if not isinstance(memory, str) or not memory.strip():
                continue
            memory_terms = set(re.findall(r"[\wÀ-ÿ]{3,}", memory.casefold()))
            overlap = query_terms & memory_terms
            if overlap:
                ranked.append((len(overlap), memory.strip()[:500]))
        chosen.extend(memory for _score, memory in sorted(ranked, reverse=True)[:self.max_memories])
        return messages, chosen
