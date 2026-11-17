import unittest

from ui_theme import COLORS, FONTS, SPACING, apply_theme


class FakeStyle:
    def __init__(self):
        self.configured = {}
        self.maps = {}
        self.theme = None

    def theme_names(self):
        return ("default", "clam")

    def theme_use(self, name):
        self.theme = name

    def configure(self, name, **options):
        self.configured[name] = options

    def map(self, name, **options):
        self.maps[name] = options


class AurovaAuroraThemeTests(unittest.TestCase):
    def test_palette_and_layout_tokens_are_centralized(self):
        self.assertEqual(COLORS["background"], "#111827")
        self.assertEqual(COLORS["surface"], "#1B273A")
        self.assertEqual(COLORS["purple"], "#A78BFA")
        self.assertEqual(COLORS["cyan"], "#72D6CE")
        self.assertEqual(COLORS["gold"], "#F2BC75")
        self.assertEqual(SPACING["md"], 12)
        self.assertIn("title", FONTS)

    def test_theme_installs_reusable_styles_without_a_tk_display(self):
        style = FakeStyle()
        self.assertIs(apply_theme(object(), style=style), style)
        self.assertEqual(style.theme, "clam")
        self.assertIn("Primary.TButton", style.configured)
        self.assertIn("Nav.Active.TButton", style.configured)
        self.assertIn("Destructive.TButton", style.configured)
        self.assertIn("Treeview", style.configured)
        self.assertIn("TNotebook.Tab", style.configured)
        self.assertIn("Horizontal.TProgressbar", style.configured)
        self.assertIn("Primary.TButton", style.maps)
        self.assertIn(("disabled", COLORS["background_secondary"]),
                      style.maps["Secondary.TButton"]["background"])
        self.assertIn(("disabled", COLORS["disabled"]),
                      style.maps["Secondary.TButton"]["foreground"])
        self.assertIn(("focus", COLORS["focus"]),
                      style.maps["TEntry"]["bordercolor"])
        self.assertIn("Nav.Active.TButton", style.maps)


if __name__ == "__main__":
    unittest.main()
