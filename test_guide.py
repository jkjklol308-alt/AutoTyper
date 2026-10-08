"""Tests for the built-in guide (v1.2.0).

Two layers, the same split the colour picker tests use:

  1. The wording itself (`GUIDE_SECTIONS` / `GUIDE_INTRO`), which is plain
     data and can be checked with no display at all.
  2. The `GuideWindow` form, exercised against the miniature ``tkinter`` stub
     from `test_custom_colours.py`, plus the settings-menu wiring that opens
     it — including the check that the old "Live preview" panel is gone.
"""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

import auto_typer as at
from test_custom_colours import _load_module_with_tk_stub


# ---------------------------------------------------------------------------
# The words (no Tk needed)
# ---------------------------------------------------------------------------
class GuideContentTests(unittest.TestCase):
    """The guide is only useful if it is complete and readable."""

    def test_intro_is_a_sentence(self):
        self.assertIsInstance(at.GUIDE_INTRO, str)
        self.assertGreater(len(at.GUIDE_INTRO.strip()), 40)
        self.assertTrue(at.GUIDE_INTRO.strip().endswith("."))

    def test_every_section_is_headed_and_filled(self):
        self.assertGreaterEqual(len(at.GUIDE_SECTIONS), 4)
        for heading, entries in at.GUIDE_SECTIONS:
            self.assertIsInstance(heading, str)
            self.assertTrue(heading.strip())
            self.assertGreater(len(entries), 0)

    def test_every_entry_names_a_control_and_says_what_it_does(self):
        for _heading, entries in at.GUIDE_SECTIONS:
            for entry in entries:
                self.assertEqual(len(entry), 2)
                name, description = entry
                self.assertTrue(name.strip(), "every entry needs a name")
                self.assertTrue(description.strip(), "every entry needs a description")
                # A description that just repeats the name explains nothing.
                self.assertNotEqual(name.strip(), description.strip())
                self.assertGreaterEqual(len(description.split()), 3)

    def test_controls_are_only_explained_once(self):
        names = [name for _heading, entries in at.GUIDE_SECTIONS
                 for name, _description in entries]
        self.assertEqual(len(names), len(set(names)))

    def test_the_main_controls_are_all_covered(self):
        documented = {name for _heading, entries in at.GUIDE_SECTIONS
                      for name, _description in entries}
        expected = (
            "Target speed (WPM)",
            "Base typo rate (%)",
            "Speed definition",
            "Countdown (seconds)",
            "Editor indentation",
            "Fixed indent width",
            "Pascal coding mode",
            "Verify and repair target editor",
            "Deterministic seed",
            "Clear",
            "Paste clipboard",
            "Benchmark",
            "Start AutoTyper",
            "Stop",
            "⚙ Settings",
            "🎨 New colours…",
            "Edit selected",
            "Delete selected",
            "Check for updates now",
            "🗒 Open update log",
        )
        for control in expected:
            self.assertIn(control, documented)

    def test_descriptions_avoid_jargon_that_needs_explaining(self):
        """The guide is for a first-time reader: no raw trace vocabulary."""
        banned = ("IKI", "Ornstein-Uhlenbeck", "Fitts", "gammavariate", "dwell")
        for _heading, entries in at.GUIDE_SECTIONS:
            for _name, description in entries:
                for word in banned:
                    self.assertNotIn(word, description)


# ---------------------------------------------------------------------------
# The window and its wiring (Tk stub)
# ---------------------------------------------------------------------------
def _walk(widget, found=None):
    """Collect every widget under `widget`, breadth first."""
    found = [] if found is None else found
    for child in widget.winfo_children():
        found.append(child)
        _walk(child, found)
    return found


class GuideWindowTests(unittest.TestCase):
    """Build the guide against the Tk stub and drive it."""

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "settings.json"
        patches = [
            unittest.mock.patch.object(self.mod.AutoTyperApp, "_start_update_check",
                                       lambda self: None),
            unittest.mock.patch.object(self.mod.AutoTyperApp, "_ui_settings_path",
                                       staticmethod(lambda path=self.tmp: path)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.app = self.mod.AutoTyperApp()

    def test_settings_menu_offers_the_guide(self):
        self.app._open_settings()
        self.assertIsNotNone(self.app._guide_button)
        self.assertIn("guide", self.app._guide_button.cget("text").lower())

    def test_live_preview_panel_is_gone(self):
        self.app._open_settings()
        texts = [str(widget.cget("text")) for widget in _walk(self.app._settings_window)]
        self.assertIn(" Guide ", texts)
        self.assertNotIn(" Live preview ", texts)
        self.assertFalse(hasattr(self.app, "_preview_widgets"))

    def test_the_guide_opens_as_its_own_form(self):
        self.app._open_settings()
        self.app._open_guide()
        guide = self.app._guide_window
        self.assertIsNotNone(guide)
        self.assertIsInstance(guide, self.mod.GuideWindow)
        # A separate top-level window, not another panel inside Settings.
        self.assertNotIn(guide, _walk(self.app._settings_window))
        self.assertIn("guide", guide.title_text.lower())

    def test_reopening_raises_the_same_window(self):
        self.app._open_guide()
        first = self.app._guide_window
        self.app._open_guide()
        self.assertIs(self.app._guide_window, first)

    def test_every_control_and_description_is_shown(self):
        self.app._open_guide()
        shown = [str(widget.cget("text")) for widget in _walk(self.app._guide_window)]
        self.assertIn(at.GUIDE_INTRO, shown)
        entries = [(name, description)
                   for _heading, entries in at.GUIDE_SECTIONS
                   for name, description in entries]
        self.assertGreater(len(entries), 10)
        for name, description in entries:
            self.assertIn(name, shown)
            self.assertIn(description, shown)
        for heading, _entries in at.GUIDE_SECTIONS:
            self.assertIn(heading, shown)

    def test_the_guide_follows_the_palette(self):
        self.app._open_guide()
        guide = self.app._guide_window
        self.app._choose_palette("Cyberpunk Neon")     # a dark palette
        accent = guide._accent_button
        painted = 0
        for widget in _walk(guide):
            if widget is accent:
                self.assertEqual(widget.cget("bg"), self.app.colors["accent"])
            elif widget.cget("bg") is not None:
                painted += 1
                self.assertEqual(widget.cget("bg"), "#0B0F19")
        self.assertGreater(painted, 10)

    def test_a_closed_guide_is_forgotten_rather_than_repainted(self):
        self.app._open_guide()
        guide = self.app._guide_window
        guide.destroy()
        self.app._choose_palette("Cyberpunk Neon")     # must not explode
        self.app._open_guide()
        self.assertIsNot(self.app._guide_window, guide)

    def test_closing_settings_clears_its_guide_widgets(self):
        self.app._open_settings()
        self.app._open_guide()
        self.app._close_settings()
        self.assertIsNone(self.app._guide_hint)
        self.assertIsNone(self.app._guide_button)
        # The guide is a separate form: Settings closing must not take it too.
        self.assertIsNotNone(self.app._guide_window)


if __name__ == "__main__":
    unittest.main()
