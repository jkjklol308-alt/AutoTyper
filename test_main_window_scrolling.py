"""Tests for the scrolling main menu and the window that fits the screen.

The request behind these tests: on some monitors the main menu was taller
than the usable part of the screen, so the bottom of the window — where the
Start button lives — was out of reach and a run could not be started.

Two behaviours answer it, and both are checked here against the miniature
``tkinter`` stub from `test_custom_colours.py`:

  * the menu scrolls (`AutoTyperApp._build_scrolling_body`), while the footer
    with the Start button is packed outside the scrolling area;
  * the window never opens larger than the screen allows and its minimum size
    is small enough for a scaled-down laptop screen
    (`AutoTyperApp._fit_window_to_screen`).
"""

import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

from test_custom_colours import _load_module_with_tk_stub


def _walk(widget, found=None):
    """Collect every widget under ``widget``, breadth first."""
    found = [] if found is None else found
    for child in widget.winfo_children():
        found.append(child)
        _walk(child, found)
    return found


def _texts(widget):
    return [str(child.cget("text")) for child in _walk(widget)]


class _MainWindowTestCase(unittest.TestCase):
    """Build the real app against the Tk stub."""

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

    def wheel(self, widget, num="??", delta=-120):
        """A wheel event as Tk delivers it (``num`` is "??" for MouseWheel)."""
        return types.SimpleNamespace(widget=widget, num=num, delta=delta)


# ---------------------------------------------------------------------------
# The scrolling menu
# ---------------------------------------------------------------------------
class ScrollingMenuTests(_MainWindowTestCase):
    def test_the_menu_scrolls_in_a_canvas_with_a_vertical_scrollbar(self):
        scroller = self.app._body_scroller
        self.assertIsInstance(scroller, self.mod.tk.Canvas)
        self.assertIsNotNone(scroller.cget("yscrollcommand"))
        scrollbar = self.app._body_scrollbar
        self.assertEqual(scrollbar.cget("orient"), "vertical")
        self.assertIs(scrollbar.cget("command").__self__, scroller)

    def test_the_header_and_panels_live_inside_the_scrolling_frame(self):
        inner = self.app._body_inner
        self.assertIs(inner.master, self.app._body_scroller)
        texts = _texts(inner)
        self.assertIn("AutoTyper", texts)
        self.assertIn(" Typing settings ", texts)
        self.assertIn(" Source code / text input ", texts)

    def test_the_start_button_is_pinned_outside_the_scrolling_area(self):
        """It must never be able to scroll away above the bottom edge."""
        scrolled = _walk(self.app._body_scroller)
        for pinned in (self.app.start_btn, self.app.stop_btn,
                       self.app.status_label, self.app.progress):
            self.assertNotIn(pinned, scrolled)
            self.assertIn(pinned, _walk(self.app))

    def test_a_tall_window_is_filled_instead_of_left_short(self):
        """Nothing changes for a window that is taller than the menu."""
        self.app._body_scroller.width = 780
        self.app._body_scroller.height = 860
        self.app._body_inner.reqheight = 700
        self.app._body_inner.reqwidth = 760
        self.app._sync_body_scroll()
        item = self.app._body_scroller.items[self.app._body_window_id]
        self.assertEqual(item["width"], 780)
        self.assertEqual(item["height"], 860)      # the viewport, not 700
        self.assertIsNotNone(self.app._body_scroller.cget("scrollregion"))

    def test_a_short_window_keeps_the_menu_height_and_scrolls(self):
        self.app._body_scroller.width = 560
        self.app._body_scroller.height = 400
        self.app._body_inner.reqheight = 900
        self.app._body_inner.reqwidth = 540
        self.app._sync_body_scroll()
        item = self.app._body_scroller.items[self.app._body_window_id]
        self.assertEqual(item["height"], 900)      # taller than the viewport
        self.assertEqual(item["width"], 560)

    def test_the_menu_is_not_squashed_before_the_canvas_is_mapped(self):
        """Tk reports a width of 1 until the window is on screen."""
        self.app._body_scroller.width = 1
        self.app._body_scroller.height = 1
        self.app._body_inner.reqheight = 700
        self.app._body_inner.reqwidth = 640
        self.app._sync_body_scroll()
        item = self.app._body_scroller.items[self.app._body_window_id]
        self.assertEqual(item["width"], 640)
        self.assertEqual(item["height"], 700)

    def test_resizing_again_reuses_the_last_real_width(self):
        self.app._body_scroller.width = 1
        self.app._body_scroller.height = 1
        self.app._body_inner.reqheight = 700
        self.app._body_inner.reqwidth = 640
        self.app._sync_body_scroll()
        self.app._body_inner.reqwidth = 200          # a shrink request
        self.app._sync_body_scroll()
        item = self.app._body_scroller.items[self.app._body_window_id]
        self.assertEqual(item["width"], 640)         # the width it really had


# ---------------------------------------------------------------------------
# The window that fits the screen
# ---------------------------------------------------------------------------
class WindowFitsScreenTests(_MainWindowTestCase):
    def test_a_large_screen_keeps_the_design_size(self):
        self.app.screen_size = (1920, 1080)
        self.assertEqual(self.app._fit_window_to_screen(), (780, 980))
        self.assertEqual(self.app.geometry_requested, "780x980+570+10")

    def test_a_short_screen_gets_a_shorter_window(self):
        """1366x768 — the screen that made the Start button unreachable."""
        self.app.screen_size = (1366, 768)
        width, height = self.app._fit_window_to_screen()
        self.assertEqual(width, 780)
        self.assertLess(height, 768)
        self.assertEqual(height, 768 - self.mod.SCREEN_MARGIN[1])
        self.assertIn(f"{width}x{height}+293+0", self.app.geometry_requested)

    def test_the_window_never_exceeds_the_screen(self):
        for screen in ((1920, 1080), (1366, 768), (1280, 720), (1024, 600), (800, 480)):
            self.app.screen_size = screen
            width, height = self.app._fit_window_to_screen()
            self.assertLessEqual(width, screen[0], screen)
            self.assertLessEqual(height, screen[1], screen)

    def test_the_minimum_size_fits_inside_the_window(self):
        self.app.screen_size = (1024, 600)
        width, height = self.app._fit_window_to_screen()
        min_width, min_height = self.app.minimum_size
        self.assertLessEqual(min_width, width)
        self.assertLessEqual(min_height, height)
        self.assertLessEqual(min_height, 600)

    def test_a_very_small_screen_still_gets_a_positive_window(self):
        self.app.screen_size = (320, 200)
        width, height = self.app._fit_window_to_screen()
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)


# ---------------------------------------------------------------------------
# The mouse wheel
# ---------------------------------------------------------------------------
class WheelDispatchTests(_MainWindowTestCase):
    def test_the_wheel_scrolls_the_menu(self):
        self.app._on_mousewheel(self.wheel(self.app.status_label))
        self.assertEqual(self.app._body_scroller.scrolled[-1], (1, "units"))

    def test_wheel_up_scrolls_the_other_way(self):
        self.app._on_mousewheel(self.wheel(self.app.status_label, delta=120))
        self.assertEqual(self.app._body_scroller.scrolled[-1], (-1, "units"))
        # X11 reports buttons 4 and 5 instead of a delta.
        self.app._on_mousewheel(self.wheel(self.app.status_label, num=5))
        self.assertEqual(self.app._body_scroller.scrolled[-1], (1, "units"))
        self.app._on_mousewheel(self.wheel(self.app.status_label, num=4))
        self.assertEqual(self.app._body_scroller.scrolled[-1], (-1, "units"))

    def test_the_text_box_keeps_scrolling_its_own_text(self):
        self.app._on_mousewheel(self.wheel(self.app.text_box))
        self.assertFalse(hasattr(self.app._body_scroller, "scrolled"))

    def test_the_wheel_over_settings_scrolls_settings_only(self):
        self.app._open_settings()
        self.app._on_mousewheel(self.wheel(self.app._guide_button))
        self.assertEqual(self.app._settings_scroller.scrolled[-1], (1, "units"))
        self.assertFalse(hasattr(self.app._body_scroller, "scrolled"))

    def test_the_guide_scrolls_itself(self):
        """The guide binds the wheel on its own widgets, so nothing else may."""
        self.app._open_guide()
        widget = _walk(self.app._guide_window)[0]
        self.assertIs(widget.winfo_toplevel(), self.app._guide_window)
        self.app._on_mousewheel(self.wheel(widget))
        self.assertFalse(hasattr(self.app._body_scroller, "scrolled"))

    def test_closing_settings_keeps_the_menu_scrollable(self):
        """Regression: ``unbind_all`` used to remove the main menu's binding."""
        self.app._open_settings()
        self.app._close_settings()
        self.assertIn(self.app._on_mousewheel, self.app.bindings["<MouseWheel>"])
        self.app._on_mousewheel(self.wheel(self.app.status_label))
        self.assertEqual(self.app._body_scroller.scrolled[-1], (1, "units"))

    def test_the_wheel_is_bound_for_every_platform(self):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.assertIn(self.app._on_mousewheel, self.app.bindings[sequence])


if __name__ == "__main__":
    unittest.main()
