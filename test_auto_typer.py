import io
import os
import random
import re
import tempfile
import unittest
from auto_typer import (
    TypingProfile,
    TypingModel,
    TypingPlanner,
    TypingState,
    IndentPolicy,
    Event,
    Transition,
    events_to_transitions,
    find_pascal_blocks,
    RNGStreams,
    build_trace,
    simulate,
    run_benchmark,
    summarize_trace,
    export_trace_csv,
    TracePlayer,
    PlaybackPolicy,
    UP,
    DOWN,
    LEFT,
    RIGHT,
    HOME,
    END_KEY,
    BACKSPACE,
    ENTER,
    SHIFT_L,
    SHIFT_R,
    MIN_IKI,
    MIN_GAP,
    SHIFT_MAP,
    key_finger,
    key_distance,
    fitts_difficulty,
)

_REV_SHIFT = {v: k for k, v in SHIFT_MAP.items()}


def _shift_key(key: str) -> str:
    if key in _REV_SHIFT:
        return _REV_SHIFT[key]
    if isinstance(key, str) and key.isalpha():
        return key.upper()
    return key


class VirtualEditor:
    """A small, *faithful* model of the editor the planner targets.

    It implements exactly the behaviours the trace planner relies on and
    nothing more:

      * Enter inserts a newline and the editor's auto-indent, which is
        predicted by ``indent_policy.expected_autoindent``.
      * Shift+End extends a selection to the end of the row, and Backspace
        with a non-empty selection deletes only that selection -- it never
        merges the row with its neighbour (which is why the planner resets a
        row with a sentinel + Home + Shift+End + Backspace instead of a run
        of Delete presses).
      * Backspace with no selection at column 0 joins with the row above.
      * Delete removes the character at the cursor, or joins the next row
        when the cursor is at the end of the line.
    """

    def __init__(self, indent_policy: IndentPolicy = None, unit: str = "    "):
        self.lines = [""]
        self.row = 0
        self.col = 0
        self.indent_policy = indent_policy or IndentPolicy()
        self.unit = unit
        self.shift_held = False
        self.anchor = None          # selection anchor column, or None for none

    # -- selection plumbing ------------------------------------------------
    def selection(self):
        """The selected (start, end) columns, or None when nothing is selected."""
        if self.anchor is None or self.anchor == self.col:
            return None
        return tuple(sorted((self.anchor, self.col)))

    def _collapse_selection(self):
        """A plain arrow key drops the selection; the cursor stays put."""
        self.anchor = None

    def _move_to(self, column: int, extend: bool):
        line = self.lines[self.row]
        target = max(0, min(column, len(line)))
        if extend:
            if self.anchor is None:
                self.anchor = self.col
            self.col = target
        else:
            self._collapse_selection()
            self.col = target

    def _delete_selection(self) -> bool:
        sel = self.selection()
        if sel is None:
            return False
        start, end = sel
        line = self.lines[self.row]
        self.lines[self.row] = line[:start] + line[end:]
        self.col = start
        self.anchor = None
        return True

    def _insert(self, text: str):
        if self._delete_selection():
            pass                       # typing over a selection replaces it
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col] + text + line[self.col:]
        self.col += len(text)

    def _backspace(self):
        if self._delete_selection():
            return
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
        elif self.row > 0:
            previous = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.lines[self.row]
            self.lines.pop(self.row)
            self.row -= 1
            self.col = previous

    def _delete(self):
        if self._delete_selection():
            return
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
        elif self.row < len(self.lines) - 1:
            self.lines[self.row] += self.lines[self.row + 1]
            self.lines.pop(self.row + 1)

    def on_transition(self, tr: Transition):
        key = tr.key
        if key in (SHIFT_L, SHIFT_R):
            # Releasing Shift must NOT drop the selection: Shift+End followed
            # by Shift-up then Backspace still deletes the selection, which is
            # exactly the row-reset transaction the planner relies on.
            self.shift_held = tr.down
            return
        if not tr.down:
            return

        if key in (ENTER, "\n"):
            left = self.lines[self.row][:self.col]
            right = self.lines[self.row][self.col:]
            self.lines[self.row] = left
            auto = self.indent_policy.expected_autoindent(left, self.unit)
            self.lines.insert(self.row + 1, auto + right)
            self.row += 1
            self.col = len(auto)
            self._collapse_selection()
        elif key == BACKSPACE:
            self._backspace()
        elif key == chr(0x7F) or key == "<DEL>":
            self._delete()
        elif key == UP:
            if self.row > 0:
                self.row -= 1
                self._move_to(self.col, self.shift_held)
            else:
                self._collapse_selection()
        elif key == DOWN:
            if self.row < len(self.lines) - 1:
                self.row += 1
                self._move_to(self.col, self.shift_held)
            else:
                self._collapse_selection()
        elif key == END_KEY:
            self._move_to(len(self.lines[self.row]), self.shift_held)
        elif key == HOME:
            self._move_to(0, self.shift_held)
        elif key == LEFT:
            self._move_to(self.col - 1, self.shift_held)
        elif key == RIGHT:
            self._move_to(self.col + 1, self.shift_held)
        else:
            self._insert(_shift_key(key) if self.shift_held else key)

    def text(self) -> str:
        return "\n".join(self.lines)


def replay_events_in_editor(events, indent_policy=None, unit="    ") -> str:
    """Replay transitions through a virtual editor with shift and auto-indent tracking."""
    editor = VirtualEditor(indent_policy, unit)
    for tr in events_to_transitions(events):
        editor.on_transition(tr)
    return editor.text()


class MockKeyboard:
    def __init__(self):
        self.log = []
        self.currently_held = set()

    def resolve(self, key):
        return key

    def press(self, key):
        self.currently_held.add(key)
        self.log.append(("press", key))

    def release(self, key):
        if key in self.currently_held:
            self.currently_held.remove(key)
        self.log.append(("release", key))


class TestAutoTyper(unittest.TestCase):

    def test_reproducibility_with_seed(self):
        """Same seed must produce the exact same sequence of events."""
        text = "procedure Hello;\nbegin\n    Writeln('Hello World');\nend;"
        rng1 = RNGStreams.from_seed(42)
        rng2 = RNGStreams.from_seed(42)
        events1, _ = build_trace(text, 100, 0.05, IndentPolicy("smart"), rng1, coding_mode=True)
        events2, _ = build_trace(text, 100, 0.05, IndentPolicy("smart"), rng2, coding_mode=True)
        self.assertEqual(len(events1), len(events2))
        for e1, e2 in zip(events1, events2):
            self.assertEqual(e1.action, e2.action)
            self.assertEqual(e1.char, e2.char)
            self.assertAlmostEqual(e1.press_at, e2.press_at, places=7)
            self.assertAlmostEqual(e1.release_at, e2.release_at, places=7)

    def test_different_seeds_produce_different_traces(self):
        text = "The quick brown fox jumps over the lazy dog."
        rng1 = RNGStreams.from_seed(101)
        rng2 = RNGStreams.from_seed(202)
        events1, _ = build_trace(text, 100, 0.05, IndentPolicy("off"), rng1)
        events2, _ = build_trace(text, 100, 0.05, IndentPolicy("off"), rng2)
        t1 = [e.press_at for e in events1]
        t2 = [e.press_at for e in events2]
        self.assertNotEqual(t1, t2)

    def test_timing_invariants(self):
        """All dwell times > 0, all releases >= presses, all intervals valid."""
        text = "Hello, world! 123 + 456 = 579.\nSecond line with indentation.\n"
        rng = RNGStreams.from_seed(123)
        events, _ = build_trace(text, 120, 0.08, IndentPolicy("smart"), rng)
        for ev in events:
            self.assertGreater(ev.release_at, ev.press_at)
            if ev.action == "key":
                self.assertGreaterEqual(ev.dwell, 0.015)
        transitions = events_to_transitions(events)
        for i in range(1, len(transitions)):
            self.assertGreaterEqual(transitions[i].at, transitions[i - 1].at)

    def test_virtual_editor_replay_accuracy_standard_mode(self):
        """Standard mode typing must reproduce the original text in the editor."""
        code = (
            "def factorial(n):\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * factorial(n - 1)"
        )
        for mode in ("off", "copy", "smart"):
            policy = IndentPolicy(mode)
            rng = RNGStreams.from_seed(77)
            events, _ = build_trace(code, 90, 0.0, policy, rng, coding_mode=False)
            result = replay_events_in_editor(events, policy)
            self.assertEqual(result, code)

    def test_virtual_editor_replay_accuracy_coding_mode_simple(self):
        """Coding mode with simple Pascal begin...end block."""
        pascal = (
            "procedure DoWork;\n"
            "begin\n"
            "    x := 10;\n"
            "    y := 20;\n"
            "end;"
        )
        for mode in ("smart", "copy", "off"):
            policy = IndentPolicy(mode)
            rng = RNGStreams.from_seed(99)
            events, _ = build_trace(pascal, 100, 0.0, policy, rng, coding_mode=True)
            result = replay_events_in_editor(events, policy)
            self.assertEqual(result, pascal)

    def test_virtual_editor_replay_accuracy_nested_blocks(self):
        """Coding mode with nested Pascal blocks."""
        pascal = (
            "program NestedDemo;\n"
            "procedure Outer;\n"
            "begin\n"
            "    if x > 0 then\n"
            "    begin\n"
            "        x := x - 1;\n"
            "        Writeln('Decreased');\n"
            "    end;\n"
            "    Writeln('Outer done');\n"
            "end;\n"
            "begin\n"
            "    Outer;\n"
            "end."
        )
        for mode in ("smart", "copy", "off"):
            policy = IndentPolicy(mode)
            rng = RNGStreams.from_seed(54321)
            events, _ = build_trace(pascal, 110, 0.0, policy, rng, coding_mode=True)
            result = replay_events_in_editor(events, policy)
            self.assertEqual(result, pascal)

    def test_coding_mode_with_typos(self):
        """Coding mode with typos and corrections still accurately finishes the text."""
        pascal = (
            "begin\n"
            "    a := 1;\n"
            "    b := 2;\n"
            "end;"
        )
        policy = IndentPolicy("smart")
        rng = RNGStreams.from_seed(42)
        events, _ = build_trace(pascal, 90, 0.08, policy, rng, coding_mode=True)
        result = replay_events_in_editor(events, policy)
        self.assertEqual(result, pascal)

    def test_empty_block_and_single_line(self):
        """Empty begin...end and single-line code."""
        pascal = (
            "begin\n"
            "end;"
        )
        policy = IndentPolicy("off")
        rng = RNGStreams.from_seed(111)
        events, _ = build_trace(pascal, 100, 0.0, policy, rng, coding_mode=True)
        result = replay_events_in_editor(events, policy)
        self.assertEqual(result, pascal)

    def test_strings_and_comments_ignored_by_block_finder(self):
        """'begin' and 'end' inside strings and comments do not create false blocks."""
        lines = [
            "procedure Test;",
            "begin",
            "    msg := 'begin and end in string';",
            "    // begin comment",
            "    (* end comment *)",
            "    Writeln(msg);",
            "end;",
        ]
        blocks = find_pascal_blocks(lines)
        self.assertEqual(blocks, {1: 6})

    def test_lookahead_limit(self):
        """Blocks farther than max_lookahead are ignored and typed sequentially."""
        lines = ["begin"] + [f"    x := {i};" for i in range(15)] + ["end;"]
        blocks_short = find_pascal_blocks(lines, max_lookahead=5)
        self.assertEqual(blocks_short, {})
        blocks_long = find_pascal_blocks(lines, max_lookahead=20)
        self.assertEqual(blocks_long, {0: 16})

    def test_benchmark_simulation_gross_and_net(self):
        """Benchmark runs cleanly in both net and gross modes."""
        stats_net = run_benchmark("begin\n    x := 1;\nend;", wpm=100, typo_rate=0.03,
                                  indent=IndentPolicy("smart"), seed=123, mode="net", coding_mode=True)
        self.assertEqual(stats_net["mode"], "net")
        self.assertTrue(stats_net["coding_mode"])
        self.assertGreater(stats_net["net_wpm"], 0)

        stats_gross = run_benchmark("begin\n    x := 1;\nend;", wpm=100, typo_rate=0.03,
                                    indent=IndentPolicy("smart"), seed=123, mode="gross", coding_mode=True)
        self.assertEqual(stats_gross["mode"], "gross")
        self.assertGreater(stats_gross["gross_wpm"], 0)

    def test_csv_export(self):
        """export_trace_csv writes valid CSV output."""
        events, _ = build_trace("Test line", 100, 0.0, IndentPolicy("off"), RNGStreams.from_seed(1))
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".csv") as tf:
            path = tf.name
        try:
            export_trace_csv(events, path)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("action,char,press_at,release_at,line,note,key", content)
            self.assertIn("key,T,", content)
            self.assertIn("key,e,", content)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_motor_geometry_and_nav_keys(self):
        """Navigation keys have valid geometry and motor hand assignments."""
        for k in (UP, DOWN, LEFT, RIGHT, HOME, END_KEY):
            finger = key_finger(k)
            self.assertIsNotNone(finger, k)
            self.assertEqual(finger[0], "R")           # navigation is a right-hand job
            self.assertGreater(key_distance("a", k), 0)
            self.assertGreater(fitts_difficulty("a", k), 0)


if __name__ == "__main__":
    unittest.main()
