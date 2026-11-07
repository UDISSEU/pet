import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autonomy import DEFAULT_SETTINGS, load_settings
from nova_ai.personality import PreferenceLearner


class PreferenceLearnerTests(unittest.TestCase):
    def setUp(self):
        self.learner = PreferenceLearner()

    def test_explicit_preferences_require_repeated_distinct_days(self):
        state = self.learner.empty_state()
        for day in ("2026-03-01", "2026-03-02"):
            state, changed = self.learner.observe(
                "Prefiro respostas curtas, por favor.", state, today=day
            )
            self.assertTrue(changed)
            self.assertEqual(self.learner.guidance(state), ())
        state, changed = self.learner.observe(
            "Prefiro respostas curtas, por favor.", state, today="2026-03-03"
        )
        self.assertTrue(changed)
        guidance = self.learner.guidance(state)
        self.assertEqual(len(guidance), 1)
        self.assertIn("breves e diretas", guidance[0])
        self.assertIn("3 dias distintos", guidance[0])
        self.assertIn("confiança 100%", guidance[0])

    def test_duplicate_signal_on_same_day_is_counted_once(self):
        state, first_changed = self.learner.observe(
            "Prefiro respostas curtas.", today="2026-03-01"
        )
        state, second_changed = self.learner.observe(
            "Prefiro respostas curtas.", state, today="2026-03-01"
        )
        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(state["evidence"]["verbosity"]["concise"], 1)

    def test_explicit_tone_humor_and_support_preferences_are_adaptive(self):
        state = self.learner.empty_state()
        messages = (
            "Mais informal.",
            "Mais piadas, por favor.",
            "Me incentive quando eu estiver trabalhando.",
        )
        for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
            for message in messages:
                state, changed = self.learner.observe(message, state, today=day)
                self.assertTrue(changed)
        guidance = "\n".join(self.learner.guidance(state))
        self.assertIn("descontraído", guidance)
        self.assertIn("humor leve", guidance)
        self.assertIn("incentivo breve", guidance)

    def test_learning_state_contains_no_conversation_content(self):
        message = "Prefiro respostas curtas sobre o projeto secreto Aurora."
        state, _changed = self.learner.observe(message, today="2026-03-01")
        serialized = json.dumps(state)
        self.assertNotIn(message, serialized)
        self.assertNotIn("Aurora", serialized)

    def test_profiles_with_separate_states_do_not_share_preferences(self):
        first_profile, _ = self.learner.observe(
            "Prefiro respostas curtas.", today="2026-03-01"
        )
        second_profile = self.learner.empty_state()
        self.assertEqual(first_profile["evidence"]["verbosity"]["concise"], 1)
        self.assertEqual(second_profile["evidence"]["verbosity"]["concise"], 0)
        self.assertEqual(self.learner.guidance(second_profile), ())

    def test_ambiguous_or_empty_input_does_not_create_evidence(self):
        state, changed = self.learner.observe(
            "Prefiro respostas curtas e detalhadas.", today="2026-03-01"
        )
        state, empty_changed = self.learner.observe("", state, today="2026-03-02")
        self.assertFalse(changed)
        self.assertFalse(empty_changed)
        self.assertEqual(self.learner.guidance(state), ())

    def test_learning_is_opt_in_and_loaded_state_is_sanitized(self):
        self.assertFalse(DEFAULT_SETTINGS["adaptive_learning_enabled"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({
                "adaptive_learning_enabled": True,
                "project_followup_days": 31,
                "adaptive_learning_state": {
                    "version": 1,
                    "evidence": {
                        "verbosity": {"concise": 3, "detailed": -5, "extra": 8},
                        "tone": {"formal": True},
                    },
                    "last_observed": {"verbosity": "2026-03-01"},
                },
            }), encoding="utf-8")
            settings = load_settings(path)
        self.assertTrue(settings["adaptive_learning_enabled"])
        self.assertEqual(settings["project_followup_days"], 30)
        state = settings["adaptive_learning_state"]
        self.assertEqual(state["evidence"]["verbosity"]["concise"], 3)
        self.assertEqual(state["evidence"]["verbosity"]["detailed"], 0)
        self.assertEqual(state["evidence"]["tone"]["formal"], 0)
        self.assertEqual(set(state["evidence"]), {"verbosity", "tone", "humor", "support"})

    def test_invalid_learning_opt_in_defaults_to_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({"adaptive_learning_enabled": "yes"}), encoding="utf-8")
            settings = load_settings(path)
        self.assertFalse(settings["adaptive_learning_enabled"])

    def test_invalid_project_followup_interval_uses_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({"project_followup_days": "invalid"}), encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings["project_followup_days"], 7)


if __name__ == "__main__":
    unittest.main()
