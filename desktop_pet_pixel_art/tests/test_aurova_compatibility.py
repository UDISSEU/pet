"""Compatibility checks for established package imports."""

import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class AurovaCompatibilityTests(unittest.TestCase):
    def test_old_package_name_exports_the_new_public_types(self):
        from aurova_ai import AurovaAI
        from aurova_ai.actions.reminders import ReminderStore
        from nova_ai import NovaAI
        from nova_ai.actions.reminders import ReminderStore as LegacyReminderStore
        from nova_ai.core.application import NovaAI as LegacyModuleAI

        self.assertIs(NovaAI, AurovaAI)
        self.assertIs(LegacyModuleAI, AurovaAI)
        self.assertIs(LegacyReminderStore, ReminderStore)


if __name__ == "__main__":
    unittest.main()
