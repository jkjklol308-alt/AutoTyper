"""Tests for the colour studio (gradient / swatches / shades) and the guide.

The pure colour maths is checked directly, then the Tk widgets are driven
through the miniature ``tkinter`` stub defined in :mod:`test_custom_colours`
so everything runs headlessly, and finally the guide and the tidied-up main
window are exercised on a real ``AutoTyperApp`` object.
"""

import json
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

import auto_typer as at
from test_custom_colours import _StubError, _load_module_with_tk_stub

MODULE_PATH = Path(__file__).resolve().parent / "auto_typer.py"


def _relative_luminance(colour: str) -> float:
    red, green, blue = at.hex_to_rgb(colour)
    return (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0


# ---------------------------------------------------------------------------
# Pure colour model
# ---------------------------------------------------------------------------
class RgbConversionTests(unittest.TestCase):
    def test_hex_to_rgb_reads_the_channels(self):
        self.assertEqual(at.hex_to_rgb("#1E3A8A"), (30, 58, 138))
        self.assertEqual(at.hex_to_rgb("FFF"), (255, 255, 255))

    def test_hex_to_rgb_rejects_rubbish(self):
        for value in ("", "nope", None, 12):
            self.assertIsNone(at.hex_to_rgb(value))

    def test_rgb_to_hex_round_trips_and_clamps(self):
        self.assertEqual(at.rgb_to_hex(30, 58, 138), "#1E3A8A")
        self.assertEqual(at.rgb_to_hex(-20, 300, 12.6), "#00FF0D")
        self.assertEqual(at.rgb_to_hex(255, 255, 255), "#FFFFFF")
        self.assertEqual(at.rgb_to_hex("bad", None, 5), "#000005")

    def test_hsv_from_hex_is_the_inverse_of_hsv_to_hex(self):
        for colour in ("#FF0000", "#00FF00", "#0000FF", "#3B82F6", "#808080", "#FFFFFF"):
            hsv = at.hsv_from_hex(colour)
            self.assertIsNotNone(hsv, colour)
            self.assertEqual(at.hsv_to_hex(*hsv), colour)

    def test_hsv_from_hex_rejects_rubbish(self):
        self.assertIsNone(at.hsv_from_hex("not a colour"))

    def test_format_rgb_is_human_readable(self):
        self.assertEqual(at.format_rgb("#1E3A8A"), "RGB  30  58 138")
        self.assertEqual(at.format_rgb("not a colour"), "RGB —")


class ShadeRampTests(unittest.TestCase):
    def test_ramp_has_the_requested_length(self):
        self.assertEqual(len(at.build_shade_ramp(0.0, 1.0, 1.0)), at.SHADE_STEPS)
        self.assertEqual(len(at.build_shade_ramp(0.0, 1.0, 1.0, steps=5)), 5)

    def test_ramp_runs_from_light_to_dark_through_the_pure_colour(self):
        ramp = at.build_shade_ramp(0.0, 1.0, 1.0)          # red
        self.assertEqual(ramp[len(ramp) // 2], "#FF0000")
        self.assertEqual(ramp[-1], "#000000")
        brightness = [_relative_luminance(colour) for colour in ramp]
        self.assertEqual(brightness, sorted(brightness, reverse=True))
        self.assertTrue(all(colour.startswith("#") and len(colour) == 7 for colour in ramp))

    def test_ramp_stays_in_the_same_hue_family(self):
        ramp = at.build_shade_ramp(0.33, 1.0, 1.0)         # green
        for colour in ramp:
            red, green, blue = at.hex_to_rgb(colour)
            self.assertGreaterEqual(green, red)
            self.assertGreaterEqual(green, blue)

    def test_ramp_survives_degenerate_input(self):
        ramp = at.build_shade_ramp(0.0, 0.0, 0.0)
        self.assertEqual(len(ramp), at.SHADE_STEPS)
        self.assertTrue(all(len(colour) == 7 for colour in ramp))

    def test_brightness_ramp_runs_bright_to_black(self):
        ramp = at.build_brightness_ramp(0.0, 1.0)
        self.assertEqual(len(ramp), at.BRIGHTNESS_STEPS)
        self.assertEqual(ramp[0], "#FF0000")
        self.assertEqual(ramp[-1], "#000000")


class PaintSwatchBoardTests(unittest.TestCase):
    def test_board_has_four_rows_of_twelve(self):
        colours = at.build_paint_basic_palette()
        self.assertEqual(len(colours), at.PAINT_SWATCH_COLUMNS * at.PAINT_SWATCH_ROWS)

    def test_board_contains_the_classic_anchor_colours(self):
        colours = at.build_paint_basic_palette()
        self.assertIn("#FF0000", colours)                  # vivid hues
        self.assertIn("#FFFFFF", colours)                  # neutral ramp
        self.assertIn("#000000", colours)

    def test_rows_are_hues_tints_shades_then_neutrals(self):
        columns = at.PAINT_SWATCH_COLUMNS
        colours = at.build_paint_basic_palette()
        vivid, tints, shades, neutrals = (colours[index * columns:(index + 1) * columns]
                                          for index in range(4))
        self.assertEqual(vivid[0], "#FF0000")
        self.assertGreater(_relative_luminance(tints[0]), _relative_luminance(vivid[0]))
        self.assertLess(_relative_luminance(shades[0]), _relative_luminance(vivid[0]))
        self.assertEqual(neutrals[0], "#FFFFFF")
        self.assertEqual(neutrals[-1], "#000000")


# ---------------------------------------------------------------------------
# Widgets, driven through the tkinter stub
# ---------------------------------------------------------------------------
class ColourStudioWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.messagebox.calls.clear()
        self.root = self.mod.tk.Frame(None)

    def _colours(self):
        return self.mod._palette_colours(self.mod.DEFAULT_PALETTE)

    # -- shades --------------------------------------------------------
    def test_shade_strip_draws_every_step(self):
        picked = []
        strip = self.mod.ColourShadeStrip(self.root, on_pick=picked.append)
        self.assertEqual(len(strip.swatch_colours()), self.mod.SHADE_STEPS)
        self.assertEqual(len(strip.canvas.items), self.mod.SHADE_STEPS)
        strip.canvas.click(sorted(strip.canvas.items)[-1])
        self.assertEqual(picked, ["#000000"])

    def test_shade_strip_rebuilds_around_a_new_base_colour(self):
        strip = self.mod.ColourShadeStrip(self.root)
        strip.set_base_colour("#00FF00")
        ramp = strip.swatch_colours()
        self.assertEqual(ramp[len(ramp) // 2], "#00FF00")
        self.assertEqual(len(strip.canvas.items), self.mod.SHADE_STEPS)

    def test_shade_strip_rejects_nonsense_base_colours(self):
        strip = self.mod.ColourShadeStrip(self.root)
        strip.set_base_colour("not a colour")
        self.assertEqual(len(strip.swatch_colours()), self.mod.SHADE_STEPS)

    def test_shade_strip_highlights_the_selected_swatch(self):
        strip = self.mod.ColourShadeStrip(self.root)
        strip.set_selected("#000000")
        item = sorted(strip.canvas.items)[-1]
        self.assertEqual(strip.canvas.items[item]["width"], 3)
        strip.set_selected("#123456")                     # not on the ramp
        self.assertEqual(strip.canvas.items[item]["width"], 1)
        self.assertEqual(strip.selected_colour, "#123456")

    # -- basic colour board -------------------------------------------
    def test_swatch_board_draws_forty_eight_colours(self):
        board = self.mod.ColourSwatchBoard(self.root)
        self.assertEqual(len(board.swatch_colours()), 48)
        self.assertEqual(len(board.canvas.items), 48)

    def test_swatch_board_reports_clicks(self):
        picked = []
        board = self.mod.ColourSwatchBoard(self.root, on_pick=picked.append)
        first = sorted(board.canvas.items)[0]
        board.canvas.click(first)
        self.assertEqual(picked, [board.canvas.items[first]["fill"]])
        self.assertEqual(board.selected_colour, picked[0])

    def test_swatch_board_hit_testing_maps_pixels_to_swatches(self):
        board = self.mod.ColourSwatchBoard(self.root, swatch=(20, 17), gap=3)
        self.assertEqual(board._item_at(1, 1), sorted(board.canvas.items)[0])
        self.assertEqual(board._item_at(1000, 1), None)
        self.assertEqual(board._item_at(1, 1000), None)
        second = sorted(board.canvas.items)[1]
        self.assertEqual(board._item_at(24, 1), second)

    def test_swatch_board_hover_does_not_pick(self):
        picked = []
        board = self.mod.ColourSwatchBoard(self.root, on_pick=picked.append)
        board._motion(types.SimpleNamespace(x=1, y=1))
        self.assertEqual(picked, [])
        board._leave()
        self.assertIsNone(board._hover_item)

    # -- Paint gradient field -----------------------------------------
    def test_gradient_field_is_a_full_hue_by_saturation_grid(self):
        picker = self.mod.ColourGradientPicker(self.root)
        self.assertEqual(len(picker._field_items), picker.columns * picker.rows)
        self.assertEqual(len(picker._bar_items), picker.brightness_steps)
        colours = set()
        for item, (hue, saturation) in picker._field_items.items():
            colours.add(picker.canvas.items[item]["fill"])
            self.assertTrue(0.0 <= hue <= 1.0 and 0.0 <= saturation <= 1.0)
        self.assertGreater(len(colours), 400)

    def test_clicking_the_field_sets_hue_and_saturation(self):
        picked = []
        picker = self.mod.ColourGradientPicker(self.root, on_pick=picked.append)
        picker._pressed(types.SimpleNamespace(x=0, y=0))
        self.assertEqual((picker.hue, picker.saturation), (0.0, 0.0))
        self.assertEqual(picked[-1], picker.current_colour())
        half = picker.field_width / 2.0
        picker._pressed(types.SimpleNamespace(x=half, y=picker.field_height))
        self.assertAlmostEqual(picker.hue, 0.5, places=2)
        self.assertEqual(picker.saturation, 1.0)
        self.assertEqual(picked[-1], picker.current_colour())

    def test_dragging_the_brightness_bar_repaints_the_field(self):
        picker = self.mod.ColourGradientPicker(self.root)
        picker._pressed(types.SimpleNamespace(x=picker._bar_origin + 4, y=0))
        self.assertEqual(picker.value, 1.0)
        self.assertTrue(picker._redraw_pending)
        # the repaint itself is coalesced onto the main loop
        self.assertEqual(picker.pending_after[0][0], 25)
        picker._flush_redraw()
        self.assertFalse(picker._redraw_pending)
        red_corner = [item for item, hsv in picker._field_items.items() if hsv == (0.0, 1.0)]
        self.assertEqual(picker.canvas.items[red_corner[0]]["fill"], "#FF0000")
        picker._pressed(types.SimpleNamespace(x=picker._bar_origin + 4,
                                              y=picker.field_height))
        picker._flush_redraw()
        self.assertEqual(picker.value, 0.0)
        black_corner = [item for item, hsv in picker._field_items.items() if hsv == (0.0, 1.0)]
        self.assertEqual(picker.canvas.items[black_corner[0]]["fill"], "#000000")

    def test_set_selected_moves_the_marker_without_notifying(self):
        picked = []
        picker = self.mod.ColourGradientPicker(self.root, on_pick=picked.append)
        picker.set_selected("#123456")
        self.assertEqual(picked, [])
        self.assertEqual(picker.selected_colour, "#123456")
        hue, saturation, value = self.mod.hsv_from_hex("#123456")
        self.assertAlmostEqual(picker.hue, hue, places=6)
        self.assertAlmostEqual(picker.saturation, saturation, places=6)
        self.assertAlmostEqual(picker.value, value, places=6)
        marker = picker._marker_items[0]
        cx = (picker.canvas.items[marker]["points"][0] + picker.canvas.items[marker]["points"][2]) / 2
        self.assertAlmostEqual(cx, picker._field_marker_centre()[0], places=3)

    def test_set_selected_ignores_rubbish(self):
        picker = self.mod.ColourGradientPicker(self.root)
        before = (picker.hue, picker.saturation, picker.value)
        picker.set_selected("nope")
        self.assertEqual((picker.hue, picker.saturation, picker.value), before)

    def test_redraw_is_skipped_once_the_canvas_is_gone(self):
        picker = self.mod.ColourGradientPicker(self.root)
        picker.canvas.destroy()
        picker._flush_redraw()          # must not raise


class PaletteBinderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, _ = _load_module_with_tk_stub()

    def setUp(self):
        self.colours = self.mod._palette_colours(self.mod.DEFAULT_PALETTE)
        self.binder = self.mod.PaletteBinder(self.colours)
        self.root = self.mod.tk.Frame(None)

    def test_registers_and_counts_widgets(self):
        self.binder.register(self.root, "body")
        self.assertEqual(self.binder.count(), 1)

    def test_registration_paints_immediately(self):
        frame = self.mod.tk.Label(self.root)
        self.binder.register(frame, "heading")
        self.assertEqual(frame.cget("bg"), self.colours["background"])
        self.assertEqual(frame.cget("fg"), self.colours["primary"])

    def test_apply_repaints_every_slot(self):
        label = self.mod.tk.Label(self.root)
        entry = self.mod.tk.Entry(self.root)
        self.binder.register(label, "muted")
        self.binder.register(entry, "field")
        dark = self.mod._palette_colours("Cyberpunk Neon")
        self.binder.apply(dark)
        self.assertEqual(label.cget("fg"), dark["muted"])
        self.assertEqual(entry.cget("bg"), dark["surface"])

    def test_roles_use_sensible_palette_colours(self):
        frame = self.mod.tk.Frame(self.root)
        self.binder.register(frame, "card")
        self.assertEqual(frame.cget("highlightbackground"), self.colours["surface"])
        self.assertEqual(frame.cget("bg"), self.colours["background"])

    def test_forget_drops_a_closed_window(self):
        frame = self.mod.tk.Label(self.root)
        self.binder.register(frame, "body", window="settings")
        self.binder.register(self.root, "body", window="main")
        self.assertEqual(self.binder.forget("settings"), 1)
        self.assertEqual(self.binder.count(), 1)

    def test_unknown_roles_fall_back_to_body(self):
        frame = self.mod.tk.Label(self.root)
        self.binder.register(frame, "not-a-role")
        self.assertEqual(frame.cget("fg"), self.colours["foreground"])

    def test_widgets_that_reject_options_do_not_break_the_binder(self):
        class Picky:
            def configure(self, **kwargs):
                raise _StubError("unknown option")

        picky = Picky()
        self.binder.register(picky, "field")
        self.binder.apply(self.colours)
        self.assertEqual(self.binder.count(), 1)

    def test_apply_without_colours_is_a_no_op(self):
        empty = self.mod.PaletteBinder()
        empty.apply()
        self.assertEqual(empty.count(), 0)


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------
class GuideContentTests(unittest.TestCase):
    def test_sections_are_populated_and_well_formed(self):
        self.assertGreaterEqual(len(at.GUIDE_SECTIONS), 8)
        for section in at.GUIDE_SECTIONS:
            self.assertTrue(section.title.strip())
            self.assertTrue(section.blurb.strip())
            self.assertTrue(section.items)
            for item in section.items:
                self.assertTrue(item.name.strip())
                self.assertTrue(item.text.strip())
                self.assertGreater(len(item.text), 25)

    def test_titles_are_unique(self):
        titles = [section.title for section in at.GUIDE_SECTIONS]
        self.assertEqual(len(titles), len(set(titles)))

    def test_item_count_matches_the_sections(self):
        self.assertEqual(at.guide_item_count(),
                         sum(len(section.items) for section in at.GUIDE_SECTIONS))

    def test_every_control_of_the_interface_is_documented(self):
        text = " ".join(
            f"{section.title} {section.blurb} " +
            " ".join(f"{item.name} {item.text}" for item in section.items)
            for section in at.GUIDE_SECTIONS).lower()
        for phrase in ("wpm", "typo", "speed definition", "countdown", "editor indentation",
                       "indent width", "coding mode", "verify and repair", "deterministic seed",
                       "paste clipboard", "clear", "benchmark", "status", "progress",
                       "start autotyper", "stop", "palette", "always on top" if False else "above other",
                       "check for updates", "autoTyper.exe".lower(), "gradient", "brightness",
                       "tints & shades", "swatches", "hexagon", "rgb", "primary", "accent",
                       "background", "palette name", "save colours", "f1", "ctrl+enter",
                       "esc", "troubleshoot"):
            self.assertIn(phrase, text, f"the guide never explains {phrase!r}")

    def test_shortcuts_are_documented_and_implemented(self):
        text = " ".join(item.name for section in at.GUIDE_SECTIONS for item in section.items)
        for shortcut in ("Ctrl+Enter", "Esc", "F1", "Ctrl+A"):
            self.assertIn(shortcut, text)
        for name in ("_shortcut_start", "_shortcut_stop", "_shortcut_guide"):
            self.assertTrue(hasattr(at.AutoTyperApp, name), name)


class GuideFilterTests(unittest.TestCase):
    def test_empty_query_returns_every_section(self):
        self.assertEqual(at.filter_guide(at.GUIDE_SECTIONS, ""), list(at.GUIDE_SECTIONS))
        self.assertEqual(at.filter_guide(at.GUIDE_SECTIONS, "   "), list(at.GUIDE_SECTIONS))

    def test_matching_keeps_only_the_relevant_entries(self):
        results = at.filter_guide(at.GUIDE_SECTIONS, "wpm")
        self.assertTrue(results)
        names = [item.name for section in results for item in section.items]
        self.assertTrue(any("WPM" in name for name in names))
        for item in [item for section in results for item in section.items]:
            haystack = f"{item.name} {item.text}".lower()
            self.assertIn("wpm", haystack)

    def test_section_titles_match_wholesale(self):
        results = at.filter_guide(at.GUIDE_SECTIONS, "troubleshooting")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Troubleshooting")

    def test_query_is_case_insensitive(self):
        lower = at.filter_guide(at.GUIDE_SECTIONS, "hex")
        upper = at.filter_guide(at.GUIDE_SECTIONS, "HEX")
        self.assertEqual([section.title for section in lower],
                         [section.title for section in upper])

    def test_no_match_returns_nothing(self):
        self.assertEqual(at.filter_guide(at.GUIDE_SECTIONS, "zzz-not-a-topic"), [])


class GuideWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        colours = self.mod._palette_colours(self.mod.DEFAULT_PALETTE)
        self.window = self.mod.GuideWindow(self.mod.tk.Frame(None), colours)

    def _rendered_text(self):
        return " ".join(label.cget("text") or "" for label in self.window._text_labels)

    def test_renders_every_topic(self):
        self.assertEqual(len(self.window._text_labels),
                         self.mod.guide_item_count())
        self.assertIn("WPM", self._rendered_text())

    def test_filter_narrows_the_rendered_topics(self):
        self.window.filter_var.set("hexagon")
        self.window.render()
        self.assertTrue(self.window._text_labels)
        self.assertLess(len(self.window._text_labels), self.mod.guide_item_count())
        self.assertIn("hexagon", self._rendered_text().lower())

    def test_clear_filter_restores_everything(self):
        self.window.filter_var.set("wpm")
        self.window.render()
        self.window._clear_filter()
        self.assertEqual(self.window.filter_var.get(), "")
        self.assertEqual(len(self.window._text_labels), self.mod.guide_item_count())

    def test_empty_result_shows_a_message(self):
        self.window.filter_var.set("zzz-not-a-topic")
        self.window.render()
        self.assertEqual(self.window._text_labels, [])
        self.assertIn("0 topics", self.window._count_label.cget("text"))

    def test_apply_palette_repaints_the_guide(self):
        dark = self.mod._palette_colours("Cyberpunk Neon")
        self.window.apply_palette(dark)
        self.assertEqual(self.window.colours["background"], "#0B0F19")
        self.assertEqual(self.window._heading.cget("bg"), "#0B0F19")

    def test_close_reports_back_and_destroys(self):
        closed = []
        window = self.mod.GuideWindow(self.mod.tk.Frame(None),
                                      self.mod._palette_colours(self.mod.DEFAULT_PALETTE),
                                      on_close=lambda: closed.append(True))
        window.close()
        self.assertEqual(closed, [True])
        self.assertTrue(window.destroyed)


# ---------------------------------------------------------------------------
# Application integration: guide button, shortcuts, tidied-up window
# ---------------------------------------------------------------------------
class GuideIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.messagebox.calls.clear()
        self.tmp = Path(tempfile.mkdtemp()) / "settings.json"
        mod = self.mod
        patches = [
            unittest.mock.patch.object(mod.AutoTyperApp, "_start_update_check", lambda self: None),
            unittest.mock.patch.object(mod.AutoTyperApp, "_ui_settings_path",
                                       staticmethod(lambda path=self.tmp: path)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.app = mod.AutoTyperApp()

    def test_window_has_the_new_header_buttons(self):
        self.assertTrue(hasattr(self.app, "guide_btn"))
        self.assertEqual(self.app.guide_btn.cget("text"), "❓ Guide")
        self.assertTrue(hasattr(self.app, "settings_btn"))
        self.assertTrue(hasattr(self.app, "download_btn"))

    def test_the_guide_opens_on_first_launch(self):
        self.app._open_guide()      # what the queued after() callback does
        self.assertIsNotNone(self.app._guide_window)
        self.assertTrue(self.app.guide_seen)

    def test_opening_the_guide_marks_it_seen_and_persists(self):
        self.app._open_guide()
        self.assertIsNotNone(self.app._guide_window)
        self.assertTrue(self.app.guide_seen)
        saved = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertTrue(saved["guide_seen"])

    def test_the_guide_is_only_opened_automatically_once(self):
        self.tmp.write_text(json.dumps({"guide_seen": True}), encoding="utf-8")
        reopened = self.mod.AutoTyperApp()
        self.assertTrue(reopened.guide_seen)
        self.assertIsNone(reopened._guide_window)

    def test_opening_the_guide_twice_reuses_the_window(self):
        self.app._open_guide()
        first = self.app._guide_window
        self.app._open_guide()
        self.assertIs(self.app._guide_window, first)

    def test_closing_the_guide_forgets_it(self):
        self.app._open_guide()
        self.app._close_guide()
        self.assertIsNone(self.app._guide_window)
        # Reopening after a close must build a fresh window.
        self.app._open_guide()
        self.assertIsNotNone(self.app._guide_window)

    def test_switching_palette_repaints_the_open_guide(self):
        self.app._open_guide()
        guide = self.app._guide_window
        self.app._choose_palette("Cyberpunk Neon")
        self.assertEqual(guide.colours["background"], "#0B0F19")

    def test_shortcuts_start_stop_and_open_the_guide(self):
        started, stopped = [], []
        self.app.start_process = lambda: started.append(True)
        self.app.stop_process = lambda: stopped.append(True)
        self.app.is_running = False
        self.app._shortcut_start()
        self.app._shortcut_stop()            # idle: does nothing
        self.assertEqual(started, [True])
        self.assertEqual(stopped, [])
        self.app.is_running = True
        self.app._shortcut_stop()
        self.assertEqual(stopped, [True])
        self.app._shortcut_guide()
        self.assertIsNotNone(self.app._guide_window)


class MainWindowTests(unittest.TestCase):
    """The tidied-up main window: cards, counters and palette switches."""

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.messagebox.calls.clear()
        self.tmp = Path(tempfile.mkdtemp()) / "settings.json"
        mod = self.mod
        patches = [
            unittest.mock.patch.object(mod.AutoTyperApp, "_start_update_check", lambda self: None),
            unittest.mock.patch.object(mod.AutoTyperApp, "_ui_settings_path",
                                       staticmethod(lambda path=self.tmp: path)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.app = mod.AutoTyperApp()

    def test_every_control_still_exists(self):
        for name in ("wpm_var", "typo_var", "mode_var", "delay_var", "indent_mode_var",
                     "indent_var", "coding_mode_var", "verify_var", "det_var", "seed_var",
                     "text_box", "status_label", "progress", "start_btn", "stop_btn",
                     "count_var", "wpm_scale", "typo_scale", "mode_combo", "indent_combo"):
            self.assertTrue(hasattr(self.app, name), name)

    def test_character_counter_tracks_the_text_box(self):
        self.app._update_count_label()
        self.assertIn("Empty", self.app.count_var.get())
        self.app.text_box.get = lambda *args, **kwargs: "one\ntwo\nthree"
        self.app._update_count_label()
        self.assertIn("3 lines", self.app.count_var.get())
        self.assertIn("13 characters", self.app.count_var.get())

    def test_switching_palette_repaints_main_window_widgets(self):
        self.app._choose_palette("Cyberpunk Neon")
        dark = self.app.colors
        self.assertEqual(self.app.status_label.cget("bg"), dark["background"])
        self.assertEqual(self.app.wpm_scale.cget("troughcolor"), dark["surface"])
        self.assertEqual(self.app.text_box.cget("background"), dark["surface"])
        self.assertEqual(self.app.count_var.get() is not None, True)

    def test_main_window_widgets_are_registered_with_the_binder(self):
        self.assertGreater(self.app._binder.count(), 30)

    def test_popup_windows_forget_their_widgets_when_closed(self):
        self.app._open_settings()
        self.assertGreater(self.app._settings_binder.count(), 0)
        self.app._close_settings()
        self.assertEqual(self.app._settings_binder.count(), 0)

    def test_tooltips_are_attached_to_the_help_widgets(self):
        self.app._open_settings()
        self.assertIsNotNone(getattr(self.app.guide_btn, "bindings", None))
        # The settings window must be able to reach the guide too.
        self.assertTrue(self.app._settings_window is not None)

    def test_settings_window_opens_the_colour_studio(self):
        self.app._open_settings()
        self.app._open_custom_editor(None)
        editor = self.app._custom_editor
        self.assertIsNotNone(editor)
        self.assertIsNotNone(editor.gradient)
        self.assertIsNotNone(editor.swatches)
        self.assertIsNotNone(editor.shades)
        self.assertIn("Custom UI Colour", editor._title.cget("text"))

    def test_preview_updates_when_picking_a_shade(self):
        self.app._open_custom_editor(None)
        editor = self.app._custom_editor
        editor.role_var.set("accent")
        editor._role_changed()
        editor._shade_picked("#000000")
        self.assertEqual(editor.triple()[1], "#000000")
        self.assertEqual(editor.hex_var.get(), "#000000")
        self.assertIn("RGB", editor.rgb_label.cget("text"))

    def test_picking_keeps_all_three_pickers_in_sync(self):
        self.app._open_custom_editor(None)
        editor = self.app._custom_editor
        editor._picked("#7F00FF", "hexagon")
        self.assertEqual(editor.triple()[0], "#7F00FF")
        self.assertEqual(editor.gradient.selected_colour, "#7F00FF")
        self.assertEqual(editor.swatches.selected_colour, "#7F00FF")
        # ... and the tints/shades ramp follows the new colour.
        ramp = editor.shades.swatch_colours()
        self.assertEqual(ramp[len(ramp) // 2], "#7F00FF")
        # A pick from the gradient field updates the other two pickers.
        editor._picked("#00FF00", "gradient")
        self.assertEqual(editor.picker.selected_colour, "#00FF00")
        self.assertEqual(editor.swatches.selected_colour, "#00FF00")

    def test_editing_a_palette_restyles_the_studio_when_the_palette_changes(self):
        self.app._open_custom_editor(None)
        editor = self.app._custom_editor
        self.app._choose_palette("Cyberpunk Neon")
        self.assertEqual(editor.colours["background"], "#0B0F19")


if __name__ == "__main__":
    unittest.main()
