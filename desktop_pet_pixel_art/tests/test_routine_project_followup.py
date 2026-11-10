from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from routine_controller import RoutineControllerMixin


class RoutineProjectFollowupTests(unittest.TestCase):
    def setUp(self):
        self.controller = object.__new__(RoutineControllerMixin)
        self.controller.settings = {
            "routine_context": True,
            "proactive_project_followups": {},
        }
        self.controller.nova_integration = mock.Mock()
        self.record = SimpleNamespace(
            memory_id="a" * 32,
            content="Projeto Aurora: painel de estudos",
        )
        self.controller.nova_integration.project_memories.return_value = [self.record]
        self.now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    def test_explicit_project_memory_is_used_once_and_cooldown_persisted(self):
        with (
            mock.patch.object(
                self.controller, "_show_spontaneous_pose", return_value=True,
                create=True,
            ) as show,
            mock.patch("routine_controller.save_settings", return_value=True) as save,
        ):
            shown = self.controller._show_greeting_pose("greeting", self.now)

        self.assertTrue(shown)
        show.assert_called_once_with(
            "project_followup", "greeting", duration=6500,
            topic="Projeto Aurora: painel de estudos",
        )
        self.assertEqual(
            self.controller.settings["proactive_project_followups"][self.record.memory_id],
            self.now.isoformat(),
        )
        save.assert_called_once()

    def test_project_is_not_repeated_within_seven_days(self):
        self.controller.settings["proactive_project_followups"] = {
            self.record.memory_id: (self.now - timedelta(days=6)).isoformat()
        }
        with mock.patch.object(
            self.controller, "_show_spontaneous_pose", return_value=True,
            create=True,
        ) as show:
            shown = self.controller._show_greeting_pose("greeting", self.now)
        self.assertTrue(shown)
        show.assert_called_once_with("greeting", "greeting", duration=6500)

    def test_user_configured_interval_controls_project_followup(self):
        self.controller.settings["project_followup_days"] = 2
        self.controller.settings["proactive_project_followups"] = {
            self.record.memory_id: (self.now - timedelta(days=2)).isoformat()
        }
        with mock.patch.object(
            self.controller, "_show_spontaneous_pose", return_value=True,
            create=True,
        ) as show:
            self.controller._show_greeting_pose("greeting", self.now)
        self.assertEqual(show.call_args.args[0], "project_followup")

    def test_context_opt_out_prevents_project_lookup(self):
        self.controller.settings["routine_context"] = False
        with mock.patch.object(
            self.controller, "_show_spontaneous_pose", return_value=True,
            create=True,
        ) as show:
            self.controller._show_greeting_pose("greeting", self.now)
        self.controller.nova_integration.project_memories.assert_not_called()
        show.assert_called_once_with("greeting", "greeting", duration=6500)

    def test_memory_opt_out_prevents_project_lookup(self):
        self.controller.settings["memory_enabled"] = False
        with mock.patch.object(
            self.controller, "_show_spontaneous_pose", return_value=True,
            create=True,
        ) as show:
            self.controller._show_greeting_pose("greeting", self.now)
        self.controller.nova_integration.project_memories.assert_not_called()
        show.assert_called_once_with("greeting", "greeting", duration=6500)

    def test_missing_project_memory_preserves_the_regular_greeting(self):
        self.controller.nova_integration.project_memories.return_value = []
        with mock.patch.object(
            self.controller, "_show_spontaneous_pose", return_value=True,
            create=True,
        ) as show:
            self.controller._show_greeting_pose("miss_you", self.now)
        show.assert_called_once_with("miss_you", "greeting", duration=6500)


if __name__ == "__main__":
    unittest.main()
