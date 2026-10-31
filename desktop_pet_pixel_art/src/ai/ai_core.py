"""Orquestra contexto, personalidade e roteamento de geração de texto."""

from ai.context_manager import ContextManager
from ai.model_router import ModelRouter
from ai.prompts import build_system_prompt


class AICore:
    def __init__(self, settings=None, router=None, context_manager=None):
        self.settings = dict(settings or {})
        self.router = router or ModelRouter(self.settings)
        self.context_manager = context_manager or ContextManager()

    def process_message(self, history, memories=None, user_name=""):
        messages, selected_memories = self.context_manager.build(history, memories)
        if selected_memories:
            instruction = "Memórias escolhidas pela pessoa usuária; use apenas se forem pertinentes:\n- "
            instruction += "\n- ".join(selected_memories)
            prompt = f"{build_system_prompt()}\n\n{instruction}"
        else:
            prompt = build_system_prompt()
        if user_name.strip():
            prompt += f"\n\nO nome da pessoa usuária é {user_name.strip()[:60]}. Use-o naturalmente ao conversar."
        return self.router.generate(messages, prompt)
