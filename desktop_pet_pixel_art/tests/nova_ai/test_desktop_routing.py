import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from automations import recognize_automation
from nova_ai.cognition.intent_classifier import IntentClassifier
from nova_ai.desktop_routing import route_user_request


class DesktopRoutingTests(unittest.TestCase):
    def setUp(self):
        self.classifier = IntentClassifier()

    def test_download_organization_variants_are_routed_to_cognition_first(self):
        for phrase in (
            "Organize meus Downloads.",
            "Organiza Downloads",
            "Organizar pasta Downloads",
        ):
            with self.subTest(phrase=phrase), mock.patch(
                "automations.recognize_automation", wraps=recognize_automation
            ) as legacy:
                route, task = route_user_request(
                    phrase,
                    cognitive_classifier=lambda text: self.classifier.classify(text).name.value
                    == "organize_downloads",
                    legacy_recognizer=legacy,
                )
                self.assertEqual(route, "cognitive")
                self.assertIsNone(task)
                legacy.assert_not_called()

    def test_ambiguous_organization_routes_for_clarification_without_implicit_target(self):
        route, task = route_user_request(
            "Separe meus arquivos por tipo.",
            cognitive_classifier=lambda text: self.classifier.classify(text).name.value
            == "organize_downloads",
            legacy_recognizer=recognize_automation,
        )
        self.assertEqual(route, "cognitive")
        self.assertIsNone(task)
        self.assertIsNone(recognize_automation("Separe meus arquivos por tipo."))

    def test_legacy_automation_still_handles_non_migrated_task(self):
        route, task = route_user_request(
            "Status do notebook",
            cognitive_classifier=lambda _text: False,
            legacy_recognizer=recognize_automation,
        )
        self.assertEqual(route, "legacy")
        self.assertEqual(task["id"], "laptop_status")

    def test_cognitive_failure_cannot_fall_back_to_legacy_file_mover(self):
        route, task = route_user_request(
            "Organizar Downloads",
            cognitive_classifier=mock.Mock(side_effect=RuntimeError("internal details")),
            legacy_recognizer=recognize_automation,
        )
        self.assertEqual(route, "cognitive")
        self.assertIsNone(task)

    def test_download_organization_is_blocked_when_cognition_is_unavailable(self):
        route, task = route_user_request(
            "Organiza Downloads",
            cognitive_classifier=None,
            legacy_recognizer=recognize_automation,
        )
        self.assertEqual(route, "unavailable")
        self.assertIsNone(task)


if __name__ == "__main__":
    unittest.main()
