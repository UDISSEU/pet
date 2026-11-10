import queue
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_pet_ai import DesktopPetAIMixin


class _Pet(DesktopPetAIMixin):
    def __init__(self, settings):
        self.settings = settings
        self.history = [
            {"role": "user", "content": "pergunta anterior"},
            {"role": "assistant", "content": "resposta anterior"},
            {"role": "user", "content": "pergunta atual"},
        ]
        self.history_path = Path("unused-history.json")
        self._ai_results = queue.Queue()
        self._closing = False
        self.show_bubble = mock.Mock()
        self._speech_history = []


class TestDesktopPetAI(unittest.TestCase):
    def test_worker_sends_only_current_question_without_context_opt_in(self):
        pet = _Pet({})
        with mock.patch("desktop_pet_ai.answer_request", return_value="resposta") as request:
            pet._ask_worker(pet.history)

        self.assertEqual(
            request.call_args.args[0],
            [{"role": "user", "content": "pergunta atual"}],
        )
        self.assertEqual(pet._ai_results.get_nowait(), "resposta")

    def test_worker_sends_history_after_context_opt_in(self):
        pet = _Pet({"conversation_context_enabled": True})
        with mock.patch("desktop_pet_ai.answer_request", return_value="resposta") as request:
            pet._ask_worker(pet.history)

        self.assertEqual(request.call_args.args[0], pet.history)

    def test_answer_is_not_persisted_by_default(self):
        pet = _Pet({})
        with mock.patch("desktop_pet_ai.save_history") as save:
            pet._show_answer("resposta")

        save.assert_not_called()
        pet.show_bubble.assert_called_once_with("resposta", duration=6000)

    def test_answer_is_persisted_only_when_enabled(self):
        pet = _Pet({"conversation_history_enabled": True})
        with mock.patch("desktop_pet_ai.save_history", return_value=True) as save:
            pet._show_answer("resposta")

        save.assert_called_once_with(pet.history, pet.history_path)
        pet.show_bubble.assert_called_once_with("resposta", duration=6000)

    def test_save_failure_is_reported_in_the_conversation(self):
        pet = _Pet({"conversation_history_enabled": True})
        with mock.patch("desktop_pet_ai.save_history", return_value=False):
            pet._show_answer("resposta")

        pet.show_bubble.assert_called_once_with(
            "resposta\n\nNão consegui salvar o histórico.", duration=6000
        )


if __name__ == "__main__":
    unittest.main()
