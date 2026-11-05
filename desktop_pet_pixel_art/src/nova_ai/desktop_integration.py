"""Composição local e opcional entre o núcleo Nova e o desktop legado."""

from nova_ai.core import NovaAI, NovaAIConfig
from nova_ai.memory import MemoryManager, PreferenceMemory
from nova_ai.personality import PersonalityEngine

class DesktopNovaIntegration:
    """Adapta memória e personalidade sem criar UI, filas ou workers próprios."""

    def __init__(self, *, config=None, memory_manager=None, personality=None):
        self.core = NovaAI(config=config or NovaAIConfig()).initialize()
        self.memory = memory_manager or MemoryManager()
        self.personality = personality or PersonalityEngine(
            preference_memory=PreferenceMemory(self.memory)
        )
        self._visual_behavior = None

    def build_context(self, question, legacy_memories=(), *, limit=8):
        memories = list(legacy_memories or ())[:limit]
        try:
            records = self.memory.search(question, limit=limit)
        except Exception:
            return memories
        seen = {str(item).casefold() for item in memories}
        for record in records:
            if record.content.casefold() not in seen and len(memories) < limit:
                memories.append(record.content)
                seen.add(record.content.casefold())
        return memories

    def personality_instructions(self):
        if (self._visual_behavior
                and self.personality.get_behavior_state() != self._visual_behavior):
            self.personality.set_behavior_state(self._visual_behavior)
        return self.personality.build_personality_instructions()

    def sync_visual_state(self, visual_state):
        mapping = {"thinking": "THINKING", "curious": "THINKING", "walk": "IDLE",
                   "idle": "IDLE", "sleep": "SLEEPING", "sleeping": "SLEEPING",
                   "error": "ERROR", "working": "WORKING", "happy": "HAPPY"}
        behavior = mapping.get(str(visual_state).lower())
        if behavior:
            # Setter is called from Tk's main thread; only retain a volatile
            # snapshot here. Persistence is applied later by the AI worker.
            self._visual_behavior = behavior
