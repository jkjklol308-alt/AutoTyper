"""Tests for the custom UI colour feature.

Two layers are covered:

  1. The pure model behind the Microsoft-Paint style gradient colour picker
     (shade-square geometry, the rainbow hue strip, saved-palette validation).
  2. The Tk widgets themselves, exercised against a miniature stub of
     ``tkinter`` so the picker and the editor dialog are smoke-tested on
     machines (CI included) that have no display or no Tk at all.
"""

import importlib.util
import json
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

import auto_typer as v2

MODULE_PATH = Path(__file__).resolve().parent / "auto_typer.py"


# ---------------------------------------------------------------------------
# Pure model
# ---------------------------------------------------------------------------
class VersionTests(unittest.TestCase):
    def test_version_is_1_1_2(self):
        self.assertEqual(v2.APP_VERSION, "1.1.2")

    def test_warm_terracotta_removed_and_order_shifted(self):
        names = list(v2.PALETTE_DEFINITIONS)
        self.assertNotIn("Warm Terracotta", v2.PALETTE_DEFINITIONS)
        # Everything that used to sit after Warm Terracotta now shifts one
        # slot earlier: Sage Wellness takes the vacated position.
        self.assertEqual(names[names.index("Berry Modern") + 1], "Sage Wellness")
        self.assertEqual(len(names), 19)

    def test_default_palette_still_present(self):
        self.assertIn(v2.DEFAULT_PALETTE, v2.PALETTE_DEFINITIONS)


class HexColourTests(unittest.TestCase):
    def test_accepts_common_spellings(self):
        for text in ("#aabbcc", "aabbcc", "#AABBCC", "  #AaBbCc  "):
            self.assertEqual(v2.normalise_hex_colour(text), "#AABBCC")

    def test_expands_shorthand(self):
        self.assertEqual(v2.normalise_hex_colour("#abc"), "#AABBCC")
        self.assertEqual(v2.normalise_hex_colour("f00"), "#FF0000")

    def test_rejects_rubbish(self):
        for text in ("", "#12345", "#gggggg", "red", None, 42, ["#fff"]):
            self.assertIsNone(v2.normalise_hex_colour(text))

    def test_hsv_to_hex_round_trips_primaries(self):
        self.assertEqual(v2.hsv_to_hex(0.0, 1.0, 1.0), "#FF0000")
        self.assertEqual(v2.hsv_to_hex(1.0 / 3.0, 1.0, 1.0), "#00FF00")
        self.assertEqual(v2.hsv_to_hex(0.0, 0.0, 1.0), "#FFFFFF")
        self.assertEqual(v2.hsv_to_hex(0.0, 0.0, 0.0), "#000000")

    def test_hsv_clamps_out_of_range_input(self):
        self.assertEqual(v2.hsv_to_hex(2.0, 5.0, 5.0), "#FF0000")
        self.assertEqual(v2.hsv_to_hex(0.0, -3.0, -3.0), "#000000")


class HexToHsvTests(unittest.TestCase):
    def test_primaries_land_where_expected(self):
        self.assertEqual(v2.hex_to_hsv("#FF0000"), (0.0, 1.0, 1.0))
        self.assertEqual(v2.hex_to_hsv("#FFFFFF"), (0.0, 0.0, 1.0))
        self.assertEqual(v2.hex_to_hsv("#000000"), (0.0, 0.0, 0.0))
        h, s, v = v2.hex_to_hsv("#00FF00")
        self.assertAlmostEqual(h, 1.0 / 3.0)
        self.assertEqual((s, v), (1.0, 1.0))

    def test_accepts_every_hex_spelling(self):
        self.assertEqual(v2.hex_to_hsv("abc"), v2.hex_to_hsv("#AABBCC"))

    def test_rejects_rubbish(self):
        for value in ("", "red", "#12345", None, 42):
            self.assertIsNone(v2.hex_to_hsv(value))

    def test_round_trips_through_hsv_to_hex(self):
        for colour in ("#3B82F6", "#123456", "#F97316", "#808080", "#010203"):
            self.assertEqual(v2.hsv_to_hex(*v2.hex_to_hsv(colour)), colour)


class GradientModelTests(unittest.TestCase):
    """The pure model behind the Paint-style colour field + shade strip."""

    def test_point_to_hs_maps_corners_like_paint(self):
        w, h = v2.GRADIENT_WIDTH, v2.GRADIENT_HEIGHT
        self.assertEqual(v2.point_to_hs(0, 0, w, h), (0.0, 1.0))        # pure red
        self.assertEqual(v2.point_to_hs(w - 1, 0, w, h), (1.0, 1.0))    # rainbow wraps
        self.assertEqual(v2.point_to_hs(0, h - 1, w, h), (0.0, 0.0))    # greyscale
        self.assertEqual(v2.point_to_hs(w - 1, h - 1, w, h), (1.0, 0.0))

    def test_point_to_hs_clamps_outside_the_square(self):
        w, h = v2.GRADIENT_WIDTH, v2.GRADIENT_HEIGHT
        self.assertEqual(v2.point_to_hs(-50, -50, w, h), (0.0, 1.0))
        self.assertEqual(v2.point_to_hs(w + 50, h + 50, w, h), (1.0, 0.0))

    def test_hs_to_point_is_the_inverse(self):
        w, h = 11, 9
        for x in range(w):
            for y in range(h):
                px, py = v2.hs_to_point(*v2.point_to_hs(x, y, w, h), width=w, height=h)
                self.assertAlmostEqual(px, x)
                self.assertAlmostEqual(py, y)

    def test_value_at_and_value_to_y_are_inverses(self):
        for y in range(v2.GRADIENT_HEIGHT):
            self.assertAlmostEqual(v2.value_to_y(v2.value_at(y), v2.GRADIENT_HEIGHT), y)
        self.assertEqual(v2.value_at(-10), 1.0)          # light end
        self.assertEqual(v2.value_at(10_000), 0.0)       # dark end

    def test_field_corners_are_red_white_and_black(self):
        w, h = v2.GRADIENT_WIDTH, v2.GRADIENT_HEIGHT
        self.assertEqual(v2.gradient_square_colour(0, 0, 1.0, w, h), "#FF0000")
        self.assertEqual(v2.gradient_square_colour(w - 1, 0, 1.0, w, h), "#FF0000")
        self.assertEqual(v2.gradient_square_colour(0, h - 1, 1.0, w, h), "#FFFFFF")
        self.assertEqual(v2.gradient_square_colour(0, h - 1, 0.5, w, h), "#808080")
        self.assertEqual(v2.gradient_square_colour(123, 45, 0.0, w, h), "#000000")

    def test_top_row_of_the_field_is_the_rainbow(self):
        w, h = 7, 3
        rows = v2.gradient_square_rows(1.0, w, h)
        top = rows[0][1:-1].split(" ")
        self.assertEqual(top, ["#FF0000", "#FFFF00", "#00FF00", "#00FFFF",
                               "#0000FF", "#FF00FF", "#FF0000"])

    def test_bottom_edge_of_the_square_is_greyscale(self):
        for value in (1.0, 0.6, 0.2):
            for x in (0, 60, 120, v2.GRADIENT_WIDTH - 1):
                colour = v2.gradient_square_colour(x, v2.GRADIENT_HEIGHT - 1, value)
                r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
                self.assertEqual(r, g)
                self.assertEqual(g, b)

    def test_square_rows_match_the_per_pixel_function_exactly(self):
        # Dyadic sizes, hues and values keep every float operation exact, so
        # the fast row builder must agree with gradient_square_colour bit for bit.
        w, h = 9, 5
        for value in (1.0, 0.75, 0.5, 0.25, 0.0):
            rows = v2.gradient_square_rows(value, w, h)
            self.assertEqual(len(rows), h)
            for y, row in enumerate(rows):
                cells = row[1:-1].split(" ")
                self.assertEqual(len(cells), w)
                for x, cell in enumerate(cells):
                    self.assertEqual(cell, v2.gradient_square_colour(x, y, value, w, h),
                                     f"value={value} x={x} y={y}")

    def test_square_rows_are_valid_photo_image_data(self):
        rows = v2.gradient_square_rows(0.6, 16, 8)
        for row in rows:
            self.assertTrue(row.startswith("{") and row.endswith("}"))
            for colour in row[1:-1].split(" "):
                self.assertEqual(v2.normalise_hex_colour(colour), colour)

    def test_square_rows_cover_the_full_size(self):
        rows = v2.gradient_square_rows(0.6)
        self.assertEqual(len(rows), v2.GRADIENT_HEIGHT)
        self.assertEqual(len(rows[0][1:-1].split(" ")), v2.GRADIENT_WIDTH)

    def test_shade_strip_runs_white_to_black(self):
        h = 5
        rows = v2.shade_strip_rows(4, h)
        self.assertEqual(len(rows), h)
        colours = [row[1:-1].split(" ") for row in rows]
        for row in colours:
            self.assertEqual(len(set(row)), 1)          # each row is one shade
            self.assertEqual(len(row), 4)
        self.assertEqual(colours[0][0], "#FFFFFF")
        self.assertEqual(colours[1][0], "#BFBFBF")
        self.assertEqual(colours[2][0], "#808080")
        self.assertEqual(colours[3][0], "#404040")
        self.assertEqual(colours[4][0], "#000000")

    def test_shade_strip_colour_matches_the_rows(self):
        for y in (0, 13, 79, v2.GRADIENT_HEIGHT - 1):
            row = v2.shade_strip_rows(v2.HUE_STRIP_WIDTH, v2.GRADIENT_HEIGHT)[y]
            self.assertEqual(row[1:-1].split(" ")[0], v2.shade_strip_colour(y))


class CustomPaletteStorageTests(unittest.TestCase):
    def test_round_trips_valid_entries(self):
        saved = v2.sanitise_custom_palettes({"Mine": ["#123456", "abc", "#FFFFFF"]})
        self.assertEqual(saved, {"Mine": ("#123456", "#AABBCC", "#FFFFFF")})

    def test_accepts_role_dictionaries(self):
        saved = v2.sanitise_custom_palettes(
            {"Mine": {"primary": "#000", "accent": "#0F0", "background": "#FFF"}})
        self.assertEqual(saved, {"Mine": ("#000000", "#00FF00", "#FFFFFF")})

    def test_drops_broken_entries(self):
        self.assertEqual(v2.sanitise_custom_palettes(None), {})
        self.assertEqual(v2.sanitise_custom_palettes("nope"), {})
        self.assertEqual(v2.sanitise_custom_palettes({"X": ["#fff", "#fff"]}), {})
        self.assertEqual(v2.sanitise_custom_palettes({"X": ["#fff", "nope", "#000"]}), {})
        self.assertEqual(v2.sanitise_custom_palettes({"  ": ["#fff", "#fff", "#fff"]}), {})
        self.assertEqual(v2.sanitise_custom_palettes({7: ["#fff", "#fff", "#fff"]}), {})

    def test_cannot_shadow_a_builtin_palette(self):
        saved = v2.sanitise_custom_palettes({v2.DEFAULT_PALETTE: ["#fff", "#fff", "#fff"]})
        self.assertEqual(saved, {})

    def test_respects_the_maximum(self):
        raw = {f"P{i}": ["#000000", "#111111", "#222222"] for i in range(v2.MAX_CUSTOM_PALETTES + 5)}
        self.assertEqual(len(v2.sanitise_custom_palettes(raw)), v2.MAX_CUSTOM_PALETTES)

    def test_merged_palettes_appends_custom_entries(self):
        custom = {"Mine": ("#101010", "#202020", "#303030")}
        merged = v2.merged_palettes(custom)
        self.assertEqual(list(merged)[:len(v2.PALETTE_DEFINITIONS)], list(v2.PALETTE_DEFINITIONS))
        self.assertEqual(list(merged)[-1], "Mine")
        self.assertEqual(merged["Mine"], custom["Mine"])
        self.assertEqual(v2.merged_palettes(None), dict(v2.PALETTE_DEFINITIONS))

    def test_merged_palettes_never_overrides_builtins(self):
        merged = v2.merged_palettes({v2.DEFAULT_PALETTE: ("#000", "#000", "#000")})
        self.assertEqual(merged[v2.DEFAULT_PALETTE], v2.PALETTE_DEFINITIONS[v2.DEFAULT_PALETTE])

    def test_unique_palette_name(self):
        self.assertEqual(v2.unique_palette_name("Mine", []), "Mine")
        self.assertEqual(v2.unique_palette_name("Mine", ["Mine"]), "Mine 2")
        self.assertEqual(v2.unique_palette_name("Mine", ["Mine", "Mine 2"]), "Mine 3")
        self.assertEqual(v2.unique_palette_name("   ", []), "My Colours")

    def test_palette_colours_accepts_custom_definitions(self):
        table = v2.merged_palettes({"Mine": ("#111111", "#EEEEEE", "#000000")})
        colours = v2._palette_colours("Mine", table)
        self.assertEqual(colours["primary"], "#111111")
        self.assertEqual(colours["accent"], "#EEEEEE")
        self.assertEqual(colours["background"], "#000000")
        self.assertEqual(colours["foreground"], "#F8FAFC")       # dark background
        self.assertEqual(colours["accent_foreground"], "#111827")  # light accent
        self.assertEqual(v2._palette_colours(v2.DEFAULT_PALETTE)["primary"], "#1E3A8A")


# ---------------------------------------------------------------------------
# Miniature Tk stub so the widgets can be built headlessly
# ---------------------------------------------------------------------------
class _StubError(Exception):
    pass


class _StubInterp:
    """Stands in for ``widget.tk``; native calls simply report unavailable."""

    def call(self, *args):
        raise _StubError("no interpreter in the stub")


class _StubWidget:
    tk = _StubInterp()

    def __init__(self, master=None, **kwargs):
        self.master = master
        self.kw = dict(kwargs)
        self.children = []
        self.bindings = {}
        self.destroyed = False
        if isinstance(master, _StubWidget):
            master.children.append(self)

    # configuration -----------------------------------------------------
    def configure(self, cnf=None, **kwargs):
        self.kw.update(kwargs)
    config = configure

    def cget(self, key):
        return self.kw.get(key)

    def __getitem__(self, key):
        return self.kw.get(key)

    # geometry managers --------------------------------------------------
    def pack(self, **kwargs):
        pass
    grid = place = pack

    def pack_propagate(self, flag=None):
        pass

    def columnconfigure(self, *args, **kwargs):
        pass
    rowconfigure = columnconfigure

    # events -------------------------------------------------------------
    def bind(self, sequence, func=None, add=None):
        self.bindings.setdefault(sequence, []).append(func)
    bind_all = bind

    def unbind_all(self, sequence):
        self.bindings.pop(sequence, None)

    # window / misc -------------------------------------------------------
    def winfo_children(self):
        return list(self.children)

    def winfo_exists(self):
        return 0 if self.destroyed else 1

    def destroy(self):
        self.destroyed = True

    def title(self, *args):
        pass

    def geometry(self, *args):
        pass

    minsize = resizable = deiconify = lift = transient = geometry

    def protocol(self, *args):
        pass

    def wm_attributes(self, *args):
        pass

    def after(self, delay, func=None, *args):
        return "after#1"

    def after_cancel(self, identifier):
        pass

    def update_idletasks(self):
        pass

    def focus_set(self):
        pass

    def clipboard_get(self):
        raise _StubError("no clipboard")

    # text / scrollbar surface used by the main window
    def insert(self, *args, **kwargs):
        pass

    def delete(self, *args, **kwargs):
        pass

    def tag_add(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return ""

    def set(self, *args, **kwargs):
        pass

    def yview(self, *args):
        pass

    def xview(self, *args):
        pass

    def state(self, *args):
        pass


class _StubCanvas(_StubWidget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.items = {}
        self.item_bindings = {}
        self._next_id = 1

    def _new_item(self, **record):
        item = self._next_id
        self._next_id += 1
        self.items[item] = record
        return item

    def create_polygon(self, points, **kwargs):
        return self._new_item(points=list(points), **kwargs)

    def create_window(self, *args, **kwargs):
        return self._new_item(embedded=True, **kwargs)

    def create_image(self, x, y, **kwargs):
        return self._new_item(image_at=(x, y), **kwargs)

    def create_rectangle(self, *points, **kwargs):
        return self._new_item(rectangle=list(points), **kwargs)

    def create_oval(self, *points, **kwargs):
        return self._new_item(oval=list(points), **kwargs)

    def coords(self, item, *points):
        record = self.items.setdefault(item, {})
        if points:
            record["coords"] = list(points)
            return None
        return record.get("coords", [])

    def delete(self, *items):
        for item in items:
            self.items.pop(item, None)

    def tag_bind(self, item, sequence, func=None, add=None):
        self.item_bindings.setdefault((item, sequence), []).append(func)

    def itemconfigure(self, item, **kwargs):
        self.items.setdefault(item, {}).update(kwargs)
    itemconfig = itemconfigure

    def tag_raise(self, item):
        pass

    def bbox(self, *args):
        return (0, 0, 10, 10)

    def yview(self, *args):
        pass

    def yview_scroll(self, *args):
        pass

    def click(self, item):
        for callback in self.item_bindings.get((item, "<Button-1>"), []):
            callback(types.SimpleNamespace(x=0, y=0))

    # pointer events on the canvas itself, as the gradient picker uses them
    def press(self, x, y):
        self._dispatch("<Button-1>", x, y)

    def drag(self, x, y):
        self._dispatch("<B1-Motion>", x, y)

    def _dispatch(self, sequence, x, y):
        for callback in self.bindings.get(sequence, []):
            callback(types.SimpleNamespace(x=x, y=y))


class _StubPhotoImage:
    """Stands in for ``tk.PhotoImage``; records the pixel data it is fed."""

    def __init__(self, master=None, **kwargs):
        self.master = master
        self.kw = dict(kwargs)
        self.puts = []

    def put(self, data, *args, **kwargs):
        self.puts.append(data)

    def blank(self):
        self.puts.clear()

    def width(self):
        return self.kw.get("width", 1)

    def height(self):
        return self.kw.get("height", 1)


class _StubStyle:
    def __init__(self, master=None):
        self.configured = {}

    def theme_use(self, name=None):
        return "clam"

    def configure(self, style, **kwargs):
        self.configured.setdefault(style, {}).update(kwargs)

    def map(self, style, **kwargs):
        pass

    def lookup(self, *args, **kwargs):
        return ""

    def layout(self, *args, **kwargs):
        return []


class _StubVariable:
    def __init__(self, master=None, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _make_tk_stub():
    tk_module = types.ModuleType("tkinter")
    tk_module.TclError = _StubError
    tk_module.Tk = _StubWidget
    tk_module.Toplevel = _StubWidget
    tk_module.Frame = _StubWidget
    tk_module.LabelFrame = _StubWidget
    tk_module.Label = _StubWidget
    tk_module.Button = _StubWidget
    tk_module.Entry = _StubWidget
    tk_module.Radiobutton = _StubWidget
    tk_module.Checkbutton = _StubWidget
    tk_module.Scale = _StubWidget
    tk_module.Text = _StubWidget
    tk_module.Canvas = _StubCanvas
    tk_module.PhotoImage = _StubPhotoImage
    tk_module.StringVar = _StubVariable
    tk_module.BooleanVar = _StubVariable
    tk_module.IntVar = _StubVariable
    tk_module.DoubleVar = _StubVariable
    tk_module.END = "end"
    tk_module.W = "w"

    ttk_module = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Combobox", "Spinbox",
                 "Progressbar", "Scrollbar", "Notebook", "Labelframe", "LabelFrame",
                 "Checkbutton", "Radiobutton", "Separator"):
        setattr(ttk_module, name, _StubWidget)
    ttk_module.Style = _StubStyle

    messagebox_module = types.ModuleType("tkinter.messagebox")
    messagebox_module.calls = []
    for name in ("showinfo", "showwarning", "showerror"):
        def _record(title=None, message=None, _name=name, **kwargs):
            messagebox_module.calls.append((_name, title, message))
        setattr(messagebox_module, name, _record)
    messagebox_module.askyesno = lambda *args, **kwargs: True

    tk_module.ttk = ttk_module
    tk_module.messagebox = messagebox_module
    return tk_module, ttk_module, messagebox_module


def _load_module_with_tk_stub():
    """Import a private copy of auto_typer that believes Tk is available."""
    tk_module, ttk_module, messagebox_module = _make_tk_stub()
    saved = {name: sys.modules.get(name)
             for name in ("tkinter", "tkinter.ttk", "tkinter.messagebox")}
    sys.modules["tkinter"] = tk_module
    sys.modules["tkinter.ttk"] = ttk_module
    sys.modules["tkinter.messagebox"] = messagebox_module
    try:
        spec = importlib.util.spec_from_file_location("auto_typer_tkstub", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module, messagebox_module


class WidgetTests(unittest.TestCase):
    """Smoke tests for the gradient picker and the custom palette editor."""

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.messagebox.calls.clear()
        self.root = self.mod.tk.Frame(None)

    # -- picker ---------------------------------------------------------
    def _picker(self, **kwargs):
        kwargs.setdefault("width", 11)
        kwargs.setdefault("height", 11)
        kwargs.setdefault("hue_width", 3)
        return self.mod.ColourGradientPicker(self.root, **kwargs)

    def test_picker_paints_the_colour_field_and_the_shade_strip(self):
        picker = self._picker()
        expected_square = "{" + " ".join(self.mod.gradient_square_rows(1.0, 11, 11)) + "}"
        expected_strip = "{" + " ".join(self.mod.shade_strip_rows(3, 11)) + "}"
        self.assertEqual(picker._square_image.puts, [expected_square])
        self.assertEqual(picker._strip_image.puts, [expected_strip])

    def test_clicking_the_square_reports_the_colour_under_the_pointer(self):
        picked = []
        picker = self._picker(on_pick=picked.append)
        sx0, sy0, sx1, sy1 = picker.square_box
        picker.canvas.press(sx0, sy0)                # top-left: pure red
        self.assertEqual(picked[-1], "#FF0000")
        picker.canvas.press(sx1, sy0)                # top-right: rainbow wraps
        self.assertEqual(picked[-1], "#FF0000")
        picker.canvas.press(sx0 + 5, sy0 + 5)        # middle: half saturated
        self.assertEqual(picked[-1],
                         self.mod.gradient_square_colour(5, 5, 1.0, 11, 11))
        picker.canvas.press(sx0, sy1)                # bottom: greyscale at v=1
        self.assertEqual(picked[-1], "#FFFFFF")
        self.assertEqual(picker.selected_colour, "#FFFFFF")

    def test_dragging_inside_the_square_streams_colours(self):
        picked = []
        picker = self._picker(on_pick=picked.append)
        sx0, sy0 = picker.square_box[0], picker.square_box[1]
        picker.canvas.press(sx0 + 5, sy0)
        picker.canvas.drag(sx0 + 5, sy0 + 10)
        self.assertEqual(len(picked), 2)
        self.assertEqual(picked[-1], picker.selected_colour)

    def test_dragging_the_shade_strip_darkens_the_whole_field(self):
        picked = []
        picker = self._picker(width=11, height=13, on_pick=picked.append)
        hx0, hy0 = picker.hue_box[0], picker.hue_box[1]
        renders_before = len(picker._square_image.puts)
        picker.canvas.press(hx0 + 1, hy0 + 4)        # value = 1 - 4/12
        shade = self.mod.value_at(4, 13)
        self.assertEqual(picked[-1], "#AA0000")      # hue/sat kept, darker red
        self.assertEqual(len(picker._square_image.puts), renders_before + 1)
        expected = "{" + " ".join(self.mod.gradient_square_rows(shade, 11, 13)) + "}"
        self.assertEqual(picker._square_image.puts[-1], expected)
        # ...and the field's top-left corner now reports the darker red too.
        sx0, sy0 = picker.square_box[0], picker.square_box[1]
        picker.canvas.press(sx0, sy0)
        self.assertEqual(picked[-1], "#AA0000")

    def test_clicks_in_the_margin_are_ignored(self):
        picked = []
        picker = self._picker(on_pick=picked.append)
        picker.canvas.press(1, 1)                    # outside both areas
        self.assertEqual(picked, [])
        self.assertIsNone(picker.selected_colour)

    def test_set_selected_moves_the_markers_without_a_callback(self):
        picked = []
        picker = self._picker(on_pick=picked.append)
        picker.set_selected("#00FF00")
        self.assertEqual(picked, [])                 # programmatic: no callback
        self.assertEqual(picker.selected_colour, "#00FF00")
        hue, saturation, value = picker.hsv
        self.assertAlmostEqual(hue, 1 / 3)
        self.assertEqual((saturation, value), (1.0, 1.0))
        sx0, sy0 = picker.square_box[0], picker.square_box[1]
        coords = picker.canvas.items[picker._shade_marker_outer]["coords"]
        mx, my = self.mod.hs_to_point(1 / 3, 1.0, 11, 11)
        self.assertAlmostEqual(coords[0], sx0 + mx - picker.MARKER_R)
        self.assertAlmostEqual(coords[1], sy0 + my - picker.MARKER_R)
        strip_coords = picker.canvas.items[picker._hue_marker_outer]["coords"]
        self.assertAlmostEqual((strip_coords[1] + strip_coords[3]) / 2,
                               sy0 + self.mod.value_to_y(1.0, 11))

    def test_set_selected_echoes_the_exact_colour(self):
        picker = self._picker()
        picker.set_selected("#123456")               # reachable only via hex
        self.assertEqual(picker.selected_colour, "#123456")
        picker.set_selected("banana")
        self.assertIsNone(picker.selected_colour)
        picker.set_selected(None)
        self.assertIsNone(picker.selected_colour)

    def test_greys_keep_the_field_position_already_shown(self):
        picker = self._picker()
        sx0, sy0 = picker.square_box[0], picker.square_box[1]
        picker.canvas.press(sx0 + 5, sy0 + 5)        # cyan-ish, half saturated
        picker.set_selected("#808080")
        self.assertEqual(picker.selected_colour, "#808080")
        self.assertAlmostEqual(picker.hsv[0], 0.5)   # field keeps its place
        self.assertAlmostEqual(picker.hsv[1], 0.5)

    # -- editor ---------------------------------------------------------
    def _editor(self, **kwargs):
        colours = self.mod._palette_colours(self.mod.DEFAULT_PALETTE)
        saved = []
        editor = self.mod.CustomPaletteEditor(
            self.root, colours,
            on_save=lambda *args: saved.append(args),
            **kwargs)
        return editor, saved

    def test_editor_starts_from_the_supplied_colours(self):
        editor, _ = self._editor(initial=("#102030", "#405060", "#708090"),
                                 initial_name="Mine")
        self.assertEqual(editor.triple(), ("#102030", "#405060", "#708090"))
        self.assertEqual(editor.name_var.get(), "Mine")
        self.assertEqual(editor.hex_var.get(), "#102030")   # primary selected first

    def test_picking_fills_the_selected_role(self):
        editor, _ = self._editor(initial=("#102030", "#405060", "#708090"))
        editor.role_var.set("accent")
        editor._role_changed()
        self.assertEqual(editor.hex_var.get(), "#405060")
        editor._picked("#00FF00")
        self.assertEqual(editor.triple(), ("#102030", "#00FF00", "#708090"))

    def test_typed_hex_is_validated(self):
        editor, _ = self._editor(initial=("#102030", "#405060", "#708090"))
        editor.hex_var.set("not a colour")
        editor._apply_typed_hex()
        self.assertEqual(editor.triple()[0], "#102030")
        self.assertEqual(editor._hex_hint.cget("text"), "use #RRGGBB")
        editor.hex_var.set("0f0")
        editor._apply_typed_hex()
        self.assertEqual(editor.triple()[0], "#00FF00")
        self.assertEqual(editor._hex_hint.cget("text"), "")

    def test_save_passes_name_triple_and_edit_target(self):
        editor, saved = self._editor(initial=("#102030", "#405060", "#708090"),
                                     initial_name="Mine", editing="Mine")
        editor._save()
        self.assertEqual(saved, [("Mine", ("#102030", "#405060", "#708090"), "Mine")])
        self.assertTrue(editor.destroyed)

    def test_save_requires_a_name(self):
        editor, saved = self._editor()
        editor.name_var.set("   ")
        editor._save()
        self.assertEqual(saved, [])
        self.assertFalse(editor.destroyed)
        self.assertEqual(self.messagebox.calls[-1][0], "showwarning")

    # -- app-level palette bookkeeping (no window is created) ------------
    def _app_shell(self):
        app = self.mod.AutoTyperApp.__new__(self.mod.AutoTyperApp)
        app.custom_palettes = {}
        app.palette_name = self.mod.DEFAULT_PALETTE
        app.palette_var = self.mod.tk.StringVar(value=self.mod.DEFAULT_PALETTE)
        app._palette_grid = None
        app._custom_hint = None
        app._settings_window = None
        app.applied = []
        app._apply_palette = app.applied.append
        app._save_ui_settings = lambda: None
        return app

    def test_saving_a_custom_palette_selects_it(self):
        app = self._app_shell()
        self.mod.AutoTyperApp._save_custom_palette(app, "Mine", ("#101010", "#f0f", "#fff"))
        self.assertEqual(app.custom_palettes, {"Mine": ("#101010", "#FF00FF", "#FFFFFF")})
        self.assertEqual(app.applied, ["Mine"])
        self.assertIn("Mine", app.available_palettes())
        self.assertTrue(app.is_custom_palette("Mine"))

    def test_saving_twice_does_not_overwrite(self):
        app = self._app_shell()
        save = self.mod.AutoTyperApp._save_custom_palette
        save(app, "Mine", ("#101010", "#202020", "#303030"))
        save(app, "Mine", ("#404040", "#505050", "#606060"))
        self.assertEqual(list(app.custom_palettes), ["Mine", "Mine 2"])

    def test_editing_renames_in_place(self):
        app = self._app_shell()
        save = self.mod.AutoTyperApp._save_custom_palette
        save(app, "A", ("#101010", "#202020", "#303030"))
        save(app, "B", ("#404040", "#505050", "#606060"))
        save(app, "A renamed", ("#111111", "#222222", "#333333"), "A")
        self.assertEqual(list(app.custom_palettes), ["A renamed", "B"])
        self.assertEqual(app.custom_palettes["A renamed"], ("#111111", "#222222", "#333333"))

    def test_deleting_falls_back_to_the_default_palette(self):
        app = self._app_shell()
        self.mod.AutoTyperApp._save_custom_palette(app, "Mine", ("#101010", "#202020", "#303030"))
        app.palette_name = "Mine"
        self.mod.AutoTyperApp._delete_custom_palette(app)
        self.assertEqual(app.custom_palettes, {})
        self.assertEqual(app.applied[-1], self.mod.DEFAULT_PALETTE)

    def test_deleting_a_builtin_is_refused(self):
        app = self._app_shell()
        app.palette_name = self.mod.DEFAULT_PALETTE
        self.mod.AutoTyperApp._delete_custom_palette(app)
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")


class AppIntegrationTests(unittest.TestCase):
    """Build the real window (against the Tk stub) and drive the settings UI."""

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

    def _cards(self):
        return [name for _, _, _, name in self.app._settings_cards]

    def test_window_builds_with_the_default_palette(self):
        self.assertEqual(self.app.palette_name, self.mod.DEFAULT_PALETTE)
        self.assertEqual(self.app.colors["primary"], "#1E3A8A")
        self.assertEqual(self.app.custom_palettes, {})

    def test_settings_window_lists_every_palette(self):
        self.app._open_settings()
        self.assertEqual(self._cards(), list(self.mod.PALETTE_DEFINITIONS))
        self.assertNotIn("Warm Terracotta", self._cards())

    def test_saving_from_the_editor_adds_a_card_and_persists(self):
        self.app._open_settings()
        self.app._open_custom_editor(None)
        editor = self.app._custom_editor
        editor.role_var.set("accent")
        editor._role_changed()
        editor._picked("#00FF00")
        editor.name_var.set("Gradient Green")
        editor._save()

        self.assertEqual(self.app.palette_name, "Gradient Green")
        self.assertEqual(self.app.custom_palettes["Gradient Green"][1], "#00FF00")
        self.assertIn("★ Gradient Green", [radio.cget("text")
                                           for _, radio, _, _ in self.app._settings_cards])
        self.assertEqual(self._cards()[-1], "Gradient Green")

        saved = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(saved["palette"], "Gradient Green")
        self.assertEqual(saved["custom_palettes"]["Gradient Green"][1], "#00FF00")

    def test_saved_palettes_reload_on_the_next_start(self):
        self.app._save_custom_palette("Gradient Green", ("#101010", "#00FF00", "#FFFFFF"))
        reopened = self.mod.AutoTyperApp()
        self.assertEqual(reopened.custom_palettes,
                         {"Gradient Green": ("#101010", "#00FF00", "#FFFFFF")})
        self.assertEqual(reopened.palette_name, "Gradient Green")
        self.assertEqual(reopened.colors["accent"], "#00FF00")

    def test_a_missing_palette_falls_back_to_the_default(self):
        self.tmp.write_text(json.dumps({"palette": "Warm Terracotta"}), encoding="utf-8")
        reopened = self.mod.AutoTyperApp()
        self.assertEqual(reopened.palette_name, self.mod.DEFAULT_PALETTE)

    def test_deleting_through_the_settings_window_rebuilds_the_grid(self):
        self.app._open_settings()
        self.app._save_custom_palette("Temp", ("#101010", "#202020", "#303030"))
        self.assertIn("Temp", self._cards())
        self.app._delete_custom_palette()
        self.assertNotIn("Temp", self._cards())
        self.assertEqual(self.app.palette_name, self.mod.DEFAULT_PALETTE)

    def test_editing_requires_a_custom_selection(self):
        self.app._open_settings()
        self.app._edit_selected_custom_palette()
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")
        self.assertIsNone(self.app._custom_editor)

    def test_switching_palette_restyles_the_open_settings_window(self):
        self.app._open_settings()
        self.app._choose_palette("Cyberpunk Neon")
        self.assertEqual(self.app.colors["background"], "#0B0F19")
        for card, _, _, name in self.app._settings_cards:
            self.assertEqual(card.cget("bg"), "#0B0F19")
        selected = [card for card, _, _, name in self.app._settings_cards
                    if name == "Cyberpunk Neon"][0]
        self.assertEqual(selected.cget("highlightbackground"), self.app.colors["accent"])

    def test_closing_settings_clears_its_state(self):
        self.app._open_settings()
        self.app._close_settings()
        self.assertIsNone(self.app._settings_window)
        self.assertIsNone(self.app._palette_grid)
        self.assertIsNone(self.app._download_exe_button)
        self.assertIsNone(self.app._update_hint)
        self.assertEqual(self.app._settings_cards, [])
        # Rebuilding the cards with no window must not explode.
        self.app._refresh_palette_cards()
        self.app._set_download_button_state("disabled")
        self.app._refresh_update_controls()

    # -- tidied header & the settings-hosted update controls --------------
    def test_header_keeps_only_the_settings_button(self):
        self.assertTrue(hasattr(self.app, "settings_btn"))
        self.assertFalse(hasattr(self.app, "download_btn"))
        self.assertFalse(hasattr(self.app, "update_btn"))

    def test_settings_window_hosts_the_exe_download(self):
        self.app._open_settings()
        self.assertIsNotNone(self.app._download_exe_button)
        self.assertIn("AutoTyper.exe", self.app._download_exe_button.cget("text"))
        self.assertIn(str(self.mod.APP_VERSION), self.app._update_hint.cget("text"))

    def _announce(self, version="9.9.9"):
        """Feed the app an available update, declining the download prompt."""
        release = self.mod.ReleaseInfo(
            version=version,
            assets=(self.mod.UpdateAsset(self.mod.EXE_ASSET_NAME,
                                         "https://example.invalid/AutoTyper.exe"),))
        previous = self.messagebox.askyesno
        self.messagebox.askyesno = lambda *args, **kwargs: False
        try:
            self.app._on_update_available(release)
        finally:
            self.messagebox.askyesno = previous

    def test_an_available_update_relabels_the_settings_button(self):
        self.app._open_settings()
        self._announce("9.9.9")
        self.assertEqual(self.app._available_version, "9.9.9")
        self.assertIn("v9.9.9", self.app._download_exe_button.cget("text"))
        self.assertIn("9.9.9", self.app._update_hint.cget("text"))
        self.assertIn("9.9.9", self.app.status_label.cget("text"))

    def test_reopening_settings_remembers_the_available_version(self):
        self._announce("9.9.9")                      # settings window closed
        self.app._open_settings()
        self.assertIn("v9.9.9", self.app._download_exe_button.cget("text"))

    def test_custom_palette_limit_is_reported(self):
        for index in range(self.mod.MAX_CUSTOM_PALETTES):
            self.app._save_custom_palette(f"P{index}", ("#101010", "#202020", "#303030"))
        self.app._open_custom_editor(None)
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")
        self.assertIsNone(self.app._custom_editor)


if __name__ == "__main__":
    unittest.main()
