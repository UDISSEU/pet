import json
import random
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autonomy import DEFAULT_SETTINGS, load_settings
from assistant_actions import local_personality_intent
from personality import (
    APP_COMMENTS,
    SPEECH_POOLS,
    can_speak_spontaneously,
    pick_line,
    record_spontaneous_speech,
    reset_personality_state,
)


class TestPersonality(unittest.TestCase):
    def tearDown(self):
        reset_personality_state()

    def test_seeded_line_selection_is_deterministic(self):
        first_history = []
        second_history = []
        first = [
            pick_line("idle_chatter", rng=random.Random(23), history=first_history)
            for _ in range(5)
        ]
        second = [
            pick_line("idle_chatter", rng=random.Random(23), history=second_history)
            for _ in range(5)
        ]
        self.assertEqual(first, second)

    def test_line_selection_avoids_the_last_three_lines(self):
        history = []
        for seed in range(15):
            line = pick_line("click", rng=random.Random(seed), history=history)
            self.assertNotIn(line, history[-4:-1])
            self.assertEqual(len(history), min(seed + 1, 3))

    def test_empty_name_does_not_leave_template_or_orphan_punctuation(self):
        for seed in range(30):
            line = pick_line(
                "greeting", name="", hour=9, rng=random.Random(seed), history=[]
            )
            self.assertNotIn("{nome}", line)
            self.assertNotRegex(line, r",\s*[.!?]")
            self.assertFalse(line.endswith(","))

    def test_every_personality_category_has_six_or_more_lines(self):
        self.assertGreaterEqual(len(SPEECH_POOLS["jokes"]), 10)
        for category, lines in SPEECH_POOLS.items():
            with self.subTest(category=category):
                self.assertGreaterEqual(len(lines), 6)

    def test_empty_or_unknown_categories_use_a_safe_fallback(self):
        with mock.patch.dict(SPEECH_POOLS, {"empty": ()}):
            line = pick_line("empty", history=[], rng=random.Random(2))
        self.assertTrue(line)
        self.assertNotIn("{nome}", line)
        self.assertEqual(pick_line("unknown", history=[], rng=random.Random(2)), line)

    def test_spontaneous_speech_uses_a_global_minimum_cooldown(self):
        reset_personality_state()
        self.assertTrue(can_speak_spontaneously(now=100))
        record_spontaneous_speech(now=100)
        self.assertFalse(can_speak_spontaneously(now=119.99, cooldown=1))
        self.assertTrue(can_speak_spontaneously(now=120, cooldown=1))

    def test_code_specific_comments_are_not_in_generic_chatter(self):
        self.assertNotIn("Bora codar!", SPEECH_POOLS["idle_chatter"])
        self.assertNotIn("Analista de dados on!", SPEECH_POOLS["idle_chatter"])
        self.assertTrue(any("Bora codar!" in line for line in APP_COMMENTS["code"]))
        self.assertTrue(any("Analista de dados on!" in line for line in APP_COMMENTS["terminal"]))

    def test_new_settings_are_defaulted_and_validated(self):
        self.assertTrue(DEFAULT_SETTINGS["routine_dance"])
        self.assertTrue(DEFAULT_SETTINGS["routine_break_tip"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(json.dumps({
                "routine_dance": "yes",
                "routine_break_tip": False,
                "last_seen_date": "not-a-date",
                "interaction_count": -8,
            }), encoding="utf-8")
            settings = load_settings(path)
        self.assertFalse(settings["routine_dance"])
        self.assertFalse(settings["routine_break_tip"])
        self.assertEqual(settings["last_seen_date"], "")
        self.assertEqual(settings["interaction_count"], 0)

    def test_valid_visit_metadata_is_preserved_and_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(json.dumps({
                "last_seen_date": "2026-10-30",
                "interaction_count": "7",
            }), encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings["last_seen_date"], "2026-10-30")
        self.assertEqual(settings["interaction_count"], 7)

    def test_local_personality_intents_map_to_animations_without_ai(self):
        cases = {
            "oi": ("greeting_morning", "wave"),
            "bom dia": ("greeting_morning", "wave"),
            "boa tarde": ("greeting_afternoon", "wave"),
            "boa noite": ("greeting_evening", "wave"),
            "tudo bem?": ("greeting_evening", "wave"),
            "me elogia": ("compliment", "thumbs_up"),
            "conta uma piada": ("jokes", "wave"),
            "dança": ("dance", "celebrate"),
            "acena": ("click", "wave"),
            "joinha": ("compliment", "thumbs_up"),
            "dorme": ("yawning", "sleep"),
            "descansa": ("break_tip", "rest"),
            "some": ("peekaboo", "vanishing"),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                result = local_personality_intent(question, hour=20)
                if question == "oi":
                    expected = ("greeting_evening", "wave")
                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
