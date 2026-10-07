"""Tests for the custom UI colour feature.

Two layers are covered:

  1. The pure model behind the Microsoft-Paint style colour hexagon
     (honeycomb geometry, colour ramps, saved-palette validation).
  2. The Tk widgets themselves, exercised against a miniature stub of
     ``tkinter`` so the picker and the editor dialog are smoke-tested on
     machines (CI included) that have no display or no Tk at all.
"""

import importlib.util
import json
import math
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
    def test_version_is_1_1_0(self):
        self.assertEqual(v2.APP_VERSION, "1.1.0")

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


class HoneycombTests(unittest.TestCase):
    def test_cell_count_matches_hex_number(self):
        for rings in (1, 3, v2.HEXAGON_RINGS):
            cells = v2.build_colour_hexagon(rings)
            self.assertEqual(len(cells), 1 + 3 * rings * (rings + 1))

    def test_centre_cell_is_white(self):
        cells = v2.build_colour_hexagon()
        self.assertEqual(cells[0].colour, "#FFFFFF")
        self.assertEqual((cells[0].q, cells[0].r, cells[0].ring), (0, 0, 0))

    def test_every_cell_has_a_unique_axial_position(self):
        cells = v2.build_colour_hexagon()
        positions = {(cell.q, cell.r) for cell in cells}
        self.assertEqual(len(positions), len(cells))

    def test_axial_distance_equals_ring_index(self):
        for cell in v2.build_colour_hexagon():
            distance = (abs(cell.q) + abs(cell.q + cell.r) + abs(cell.r)) // 2
            self.assertEqual(distance, cell.ring)

    def test_colours_are_valid_hex(self):
        for cell in v2.build_colour_hexagon():
            self.assertEqual(v2.normalise_hex_colour(cell.colour), cell.colour)

    def test_rim_ring_is_darker_than_inner_tints(self):
        cells = v2.build_colour_hexagon()
        rim = [c for c in cells if c.ring == v2.HEXAGON_RINGS]
        inner = [c for c in cells if 0 < c.ring < v2.HEXAGON_RINGS]

        def brightness(colour):
            value = colour.lstrip("#")
            return max(int(value[i:i + 2], 16) for i in (0, 2, 4))

        self.assertTrue(all(brightness(c.colour) < 200 for c in rim))
        self.assertTrue(all(brightness(c.colour) == 255 for c in inner))

    def test_saturation_grows_outwards(self):
        cells = {(c.q, c.r): c.colour for c in v2.build_colour_hexagon()}
        # Straight line of cells away from the centre: white -> saturated.
        previous = None
        for step in range(0, v2.HEXAGON_RINGS):
            colour = cells[(step, 0)]
            value = colour.lstrip("#")
            r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
            spread = max(r, g, b) - min(r, g, b)
            if previous is not None:
                self.assertGreater(spread, previous)
            previous = spread

    def test_greyscale_strip_runs_black_to_white(self):
        strip = v2.build_greyscale_strip()
        self.assertEqual(strip[0], "#000000")
        self.assertEqual(strip[-1], "#FFFFFF")
        self.assertEqual(len(strip), v2.GREYSCALE_STEPS)
        self.assertEqual(len(set(strip)), len(strip))

    def test_geometry_tiles_without_overlapping(self):
        size = 10.0
        centres = [v2.hexagon_centre(c.q, c.r, size) for c in v2.build_colour_hexagon(2)]
        spacing = math.sqrt(3.0) * size
        for index, (x1, y1) in enumerate(centres):
            for x2, y2 in centres[index + 1:]:
                distance = math.hypot(x1 - x2, y1 - y2)
                self.assertGreater(distance, spacing - 1e-6)

    def test_hexagon_points_are_pointy_top(self):
        points = v2.hexagon_points(0.0, 0.0, 10.0)
        self.assertEqual(len(points), 12)
        xs = points[0::2]
        ys = points[1::2]
        self.assertAlmostEqual(min(ys), -10.0)        # a vertex straight up
        self.assertAlmostEqual(max(xs) - min(xs), math.sqrt(3.0) * 10.0)


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
    """Stands in for ``tkinter.TclError``."""


class _StubInterp:
    """Stands in for ``widget.tk``; native calls simply report unavailable."""

    def call(self, *args):
        raise _StubError("no interpreter in the stub")


# ---------------------------------------------------------------------------
# Tk option tables. The stub validates every option name against these, so a
# widget that is configured with something real Tk would reject (a ``bg`` on a
# ttk widget, an ``fg`` on a Frame, a Button-only option on a Label...) raises
# here exactly as it would on a desktop.
# ---------------------------------------------------------------------------
_COMMON_WIDGET_OPTIONS = {
    "class", "cursor", "name", "takefocus", "highlightbackground", "highlightcolor",
    "highlightthickness", "relief", "borderwidth", "background", "width", "height",
    "padx", "pady", "bd",
}
_FRAME_OPTIONS = _COMMON_WIDGET_OPTIONS | {"colormap", "container", "visual"}
_LABEL_OPTIONS = (_COMMON_WIDGET_OPTIONS | {
    "anchor", "bitmap", "compound", "disabledforeground", "font", "foreground",
    "image", "justify", "state", "text", "textvariable", "underline", "wraplength",
})
_LABELFRAME_OPTIONS = _FRAME_OPTIONS | {
    "foreground", "font", "labelanchor", "labelwidget", "text",
}
_BUTTON_OPTIONS = {
    "activebackground", "activeforeground", "anchor", "background", "bd", "bitmap",
    "borderwidth", "command", "compound", "cursor", "default", "disabledforeground",
    "font", "foreground", "height", "highlightbackground", "highlightcolor",
    "highlightthickness", "image", "justify", "name", "overrelief", "padx", "pady",
    "relief", "repeatdelay", "repeatinterval", "state", "takefocus", "text",
    "textvariable", "underline", "width", "wraplength", "class",
}
_TOGGLE_OPTIONS = _BUTTON_OPTIONS | {
    "indicatoron", "offvalue", "onvalue", "selectcolor", "selectimage", "variable",
    "value",
}
_ENTRY_OPTIONS = {
    "background", "bd", "borderwidth", "class", "cursor", "disabledbackground",
    "disabledforeground", "exportselection", "font", "foreground", "highlightbackground",
    "highlightcolor", "highlightthickness", "insertbackground", "insertborderwidth",
    "insertofftime", "insertontime", "insertwidth", "invalidcommand", "justify", "name",
    "readonlybackground", "relief", "selectbackground", "selectborderwidth",
    "selectforeground", "show", "state", "takefocus", "textvariable", "validate",
    "validatecommand", "width", "xscrollcommand",
}
_SCALE_OPTIONS = {
    "activebackground", "background", "bd", "bigincrement", "borderwidth", "class",
    "command", "cursor", "digits", "font", "foreground", "from", "highlightbackground",
    "highlightcolor", "highlightthickness", "label", "length", "name", "orient", "relief",
    "repeatdelay", "repeatinterval", "resolution", "showvalue", "sliderlength",
    "sliderrelief", "state", "takefocus", "tickinterval", "to", "troughcolor", "variable",
    "width",
}
_TEXT_OPTIONS = {
    "autoseparators", "background", "bd", "blockcursor", "borderwidth", "class", "cursor",
    "endline", "exportselection", "font", "foreground", "height", "highlightbackground",
    "highlightcolor", "highlightthickness", "inactiveselectbackground", "insertbackground",
    "insertborderwidth", "insertofftime", "insertontime", "insertwidth", "maxundo", "name",
    "padx", "pady", "relief", "selectbackground", "selectborderwidth", "selectforeground",
    "setgrid", "spacing1", "spacing2", "spacing3", "state", "tabs", "tabstyle", "takefocus",
    "undo", "width", "wrap", "xscrollcommand", "yscrollcommand",
}
_CANVAS_OPTIONS = {
    "background", "bd", "borderwidth", "class", "closeenough", "confine", "cursor",
    "height", "highlightbackground", "highlightcolor", "highlightthickness",
    "insertbackground", "insertborderwidth", "insertofftime", "insertontime",
    "insertwidth", "name", "offset", "relief", "scrollregion", "selectbackground",
    "selectborderwidth", "selectforeground", "state", "takefocus", "width",
    "xscrollcommand", "xscrollincrement", "yscrollcommand", "yscrollincrement",
}
_TOPLEVEL_OPTIONS = {
    "background", "bd", "borderwidth", "class", "colormap", "container", "cursor",
    "height", "highlightbackground", "highlightcolor", "highlightthickness", "menu",
    "name", "padx", "pady", "relief", "screen", "takefocus", "use", "visual", "width",
}
# ttk widgets reject the classic tk colours: they are styled through ttk.Style.
_TTK_BASE = {"class", "cursor", "padding", "style", "takefocus", "name"}
_TTK_OPTIONS = {
    "ttk.Frame": _TTK_BASE | {"borderwidth", "height", "relief", "width"},
    "ttk.LabelFrame": _TTK_BASE | {"borderwidth", "height", "labelanchor", "relief",
                                   "text", "underline", "width"},
    "ttk.Label": _TTK_BASE | {"anchor", "background", "compound", "font", "foreground",
                              "image", "justify", "state", "text", "textvariable",
                              "underline", "width", "wraplength"},
    "ttk.Button": _TTK_BASE | {"command", "compound", "default", "image", "state",
                               "text", "textvariable", "underline", "width"},
    "ttk.Entry": {"class", "cursor", "exportselection", "font", "invalidcommand",
                  "justify", "name", "show", "state", "style", "takefocus",
                  "textvariable", "validate", "validatecommand", "width",
                  "xscrollcommand"},
    "ttk.Combobox": {"class", "cursor", "exportselection", "font", "height",
                     "invalidcommand", "justify", "name", "postcommand", "show", "state",
                     "style", "takefocus", "textvariable", "validate", "validatecommand",
                     "values", "width", "xscrollcommand"},
    "ttk.Spinbox": {"class", "command", "cursor", "exportselection", "font", "format",
                    "from", "increment", "invalidcommand", "justify", "name", "show",
                    "state", "style", "takefocus", "textvariable", "to", "validate",
                    "validatecommand", "values", "width", "wrap", "xscrollcommand"},
    "ttk.Checkbutton": {"class", "command", "compound", "cursor", "image", "name",
                        "offvalue", "onvalue", "padding", "state", "style", "takefocus",
                        "text", "textvariable", "underline", "variable", "width"},
    "ttk.Radiobutton": {"class", "command", "compound", "cursor", "image", "name",
                        "padding", "state", "style", "takefocus", "text", "textvariable",
                        "underline", "value", "variable", "width"},
    "ttk.Progressbar": {"class", "cursor", "length", "maximum", "mode", "name", "orient",
                        "phase", "style", "takefocus", "value", "variable"},
    "ttk.Scrollbar": {"class", "command", "cursor", "name", "orient", "style", "takefocus"},
    "ttk.Separator": {"class", "cursor", "name", "orient", "style", "takefocus"},
    "ttk.Notebook": {"class", "cursor", "height", "name", "padding", "style", "takefocus",
                     "width"},
    "ttk.Treeview": {"class", "columns", "cursor", "displaycolumns", "height", "name",
                     "padding", "selectmode", "show", "style", "takefocus",
                     "xscrollcommand", "yscrollcommand"},
}
_ALIASES = {"bg": "background", "fg": "foreground", "bd": "borderwidth"}


def _canonical(option: str) -> str:
    """``from_`` -> ``from``, ``bg`` -> ``background``, as Tk does."""
    name = option.rstrip("_")
    return _ALIASES.get(name, name)


class _StubWidget:
    tk = _StubInterp()
    OPTIONS = _FRAME_OPTIONS
    KIND = "widget"

    def __init__(self, master=None, **kwargs):
        self.master = master
        self.kw = {}
        self.children = []
        self.bindings = {}
        self.destroyed = False
        self._check_options(kwargs)
        self.kw.update({_canonical(key): value for key, value in kwargs.items()})
        if isinstance(master, _StubWidget):
            master.children.append(self)

    def _check_options(self, options):
        for option in options:
            name = _canonical(option)
            if name not in self.OPTIONS:
                raise _StubError(
                    f"unknown option -{name} for {self.KIND} "
                    f"(valid: {sorted(self.OPTIONS)[:6]}...)")

    # configuration -----------------------------------------------------
    def configure(self, cnf=None, **kwargs):
        self._check_options(kwargs)
        self.kw.update({_canonical(key): value for key, value in kwargs.items()})
    config = configure

    def cget(self, key):
        return self.kw.get(_canonical(key))

    def __getitem__(self, key):
        return self.kw.get(_canonical(key))

    def __setitem__(self, key, value):
        self.kw[_canonical(key)] = value

    # geometry managers --------------------------------------------------
    def pack(self, **kwargs):
        pass
    grid = place = pack

    def pack_propagate(self, flag=None):
        pass

    def pack_forget(self):
        pass
    grid_forget = place_forget = pack_forget

    def columnconfigure(self, *args, **kwargs):
        pass
    rowconfigure = columnconfigure

    # notebook surface (tabbed pickers / guide)
    def add(self, child, **kwargs):
        self.children.append(child)
        self.tabs_list = getattr(self, "tabs_list", []) + [child]

    def select(self, child=None):
        self.selected_tab = child
        return child

    def index(self, child):
        return getattr(self, "tabs_list", []).index(child)

    def tabs(self):
        return tuple(getattr(self, "tabs_list", []))

    def enable_traversal(self):
        pass

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

    def wm_overrideredirect(self, *args):
        pass

    def wm_geometry(self, *args):
        pass

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_width(self):
        return 640

    def winfo_height(self):
        return 24

    def after(self, delay, func=None, *args):
        # Delayed work is recorded, not run: a real main loop would execute it
        # later, but firing it inline would recurse (the app re-arms its queue
        # poll from inside the callback). Tests that care about a callback call
        # it directly.
        self.pending_after = getattr(self, "pending_after", [])
        self.pending_after.append((delay, func, args))
        return f"after#{len(self.pending_after)}"

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
    OPTIONS = _CANVAS_OPTIONS
    KIND = "canvas"
    ITEM_OPTIONS = {"anchor", "dash", "dashoffset", "disableddash", "disabledfill",
                    "disabledoutline", "disabledstipple", "disabledwidth", "extent",
                    "fill", "joinstyle", "offset", "outline", "outlineoffset",
                    "outlinestipple", "smooth", "splinesteps", "start", "state",
                    "stipple", "tags", "text", "width", "capstyle", "arrow", "arrowshape"}

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.items = {}
        self.item_bindings = {}
        self._next_id = 1

    def _check_item_options(self, kwargs):
        for option in kwargs:
            if option not in self.ITEM_OPTIONS:
                raise _StubError(f"unknown canvas item option -{option}")

    def _create_item(self, kind, coords, **kwargs):
        self._check_item_options(kwargs)
        item = self._next_id
        self._next_id += 1
        self.items[item] = {"kind": kind, "points": list(coords), **kwargs}
        return item

    def create_polygon(self, points, **kwargs):
        return self._create_item("polygon", points, **kwargs)

    def create_rectangle(self, *coords, **kwargs):
        return self._create_item("rectangle", coords, **kwargs)

    def create_oval(self, *coords, **kwargs):
        return self._create_item("oval", coords, **kwargs)

    def create_line(self, *coords, **kwargs):
        return self._create_item("line", coords, **kwargs)

    def create_text(self, *coords, **kwargs):
        return self._create_item("text", coords, **kwargs)

    def coords(self, item, *args):
        if args:
            self.items.setdefault(item, {})["points"] = list(args)
        return self.items.get(item, {}).get("points", [])

    def delete(self, *items):
        for item in items:
            if item == "all":
                self.items.clear()
            else:
                self.items.pop(item, None)

    def create_window(self, *args, **kwargs):
        item = self._next_id
        self._next_id += 1
        self.items[item] = {"window": True}
        return item

    def tag_bind(self, item, sequence, func=None, add=None):
        self.item_bindings.setdefault((item, sequence), []).append(func)

    def itemconfigure(self, item, **kwargs):
        self._check_item_options(kwargs)
        self.items.setdefault(item, {}).update(kwargs)
    itemconfig = itemconfigure

    def find_overlapping(self, *args):
        return []

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


def _widget_class(kind, options, base=_StubWidget):
    """A stub widget class that only accepts the options real Tk accepts."""
    return type(kind, (base,), {"OPTIONS": frozenset(options), "KIND": kind.lower()})


def _make_tk_stub():
    tk_module = types.ModuleType("tkinter")
    tk_module.TclError = _StubError
    tk_module.Tk = _widget_class("Tk", _TOPLEVEL_OPTIONS)
    tk_module.Toplevel = _widget_class("Toplevel", _TOPLEVEL_OPTIONS)
    tk_module.Frame = _widget_class("Frame", _FRAME_OPTIONS)
    tk_module.LabelFrame = _widget_class("LabelFrame", _LABELFRAME_OPTIONS)
    tk_module.Label = _widget_class("Label", _LABEL_OPTIONS)
    tk_module.Button = _widget_class("Button", _BUTTON_OPTIONS)
    tk_module.Entry = _widget_class("Entry", _ENTRY_OPTIONS)
    tk_module.Radiobutton = _widget_class("Radiobutton", _TOGGLE_OPTIONS)
    tk_module.Checkbutton = _widget_class("Checkbutton", _TOGGLE_OPTIONS)
    tk_module.Scale = _widget_class("Scale", _SCALE_OPTIONS)
    tk_module.Text = _widget_class("Text", _TEXT_OPTIONS)
    tk_module.Menu = _widget_class("Menu", _COMMON_WIDGET_OPTIONS | {"tearoff", "title"})
    tk_module.Canvas = _StubCanvas
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
        options = _TTK_OPTIONS.get(f"ttk.{name}", _TTK_BASE)
        setattr(ttk_module, name, _widget_class(f"ttk{name}", options))
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
    """Smoke tests for the hexagon picker and the custom palette editor."""

    @classmethod
    def setUpClass(cls):
        cls.mod, cls.messagebox = _load_module_with_tk_stub()

    def setUp(self):
        self.messagebox.calls.clear()
        self.root = self.mod.tk.Frame(None)

    def test_picker_draws_every_swatch(self):
        picker = self.mod.ColourHexagonPicker(self.root)
        expected = len(self.mod.build_colour_hexagon()) + self.mod.GREYSCALE_STEPS
        self.assertEqual(len(picker.canvas.items), expected)
        self.assertEqual(len(picker.swatch_colours()), expected)

    def test_clicking_a_hexagon_reports_its_colour(self):
        picked = []
        picker = self.mod.ColourHexagonPicker(self.root, on_pick=picked.append)
        item = sorted(picker.canvas.items)[0]
        picker.canvas.click(item)
        self.assertEqual(picked, ["#FFFFFF"])          # centre cell
        self.assertEqual(picker.selected_colour, "#FFFFFF")
        self.assertEqual(picker.canvas.items[item]["width"], 3)

    def test_selection_highlight_moves(self):
        picker = self.mod.ColourHexagonPicker(self.root)
        first, second = sorted(picker.canvas.items)[:2]
        picker.canvas.click(first)
        picker.canvas.click(second)
        self.assertEqual(picker.canvas.items[first]["width"], 1)
        self.assertEqual(picker.canvas.items[second]["width"], 3)

    def test_set_selected_accepts_known_and_unknown_colours(self):
        picker = self.mod.ColourHexagonPicker(self.root)
        picker.set_selected("#ffffff")
        self.assertEqual(picker.selected_colour, "#FFFFFF")
        picker.set_selected("#123456")                 # not on the honeycomb
        self.assertEqual(picker.selected_colour, "#123456")

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
        editor.name_var.set("Hexagon Green")
        editor._save()

        self.assertEqual(self.app.palette_name, "Hexagon Green")
        self.assertEqual(self.app.custom_palettes["Hexagon Green"][1], "#00FF00")
        self.assertIn("★ Hexagon Green", [radio.cget("text")
                                          for _, radio, _, _ in self.app._settings_cards])
        self.assertEqual(self._cards()[-1], "Hexagon Green")

        saved = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(saved["palette"], "Hexagon Green")
        self.assertEqual(saved["custom_palettes"]["Hexagon Green"][1], "#00FF00")

    def test_saved_palettes_reload_on_the_next_start(self):
        self.app._save_custom_palette("Hexagon Green", ("#101010", "#00FF00", "#FFFFFF"))
        reopened = self.mod.AutoTyperApp()
        self.assertEqual(reopened.custom_palettes,
                         {"Hexagon Green": ("#101010", "#00FF00", "#FFFFFF")})
        self.assertEqual(reopened.palette_name, "Hexagon Green")
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
        self.assertEqual(self.app._settings_cards, [])
        # Rebuilding the cards with no window must not explode.
        self.app._refresh_palette_cards()

    def test_custom_palette_limit_is_reported(self):
        for index in range(self.mod.MAX_CUSTOM_PALETTES):
            self.app._save_custom_palette(f"P{index}", ("#101010", "#202020", "#303030"))
        self.app._open_custom_editor(None)
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")
        self.assertIsNone(self.app._custom_editor)


if __name__ == "__main__":
    unittest.main()
