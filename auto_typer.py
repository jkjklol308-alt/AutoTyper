"""
===============================================================================
                        AUTOTYPER: BIOMECHANICAL & COGNITIVE
                          KEYSTROKE SIMULATION ENGINE
===============================================================================

A next-generation human typing simulator implementing:
  1. Biomechanical Finger Model (10-finger assignment, same-finger penalty,
     alternating-hand fluidity, Fitts' Law difficulty index).
  2. Polyphonic Key Rollover (natural overlapping keypresses across distinct
     fingers and hands at conversational and fast speeds).
  3. Cognitive Chunking & Morphological Rhythm (acceleration within frequent
     syllables and programming keywords, word-boundary micro-pauses, line-start
     reading pauses, syntax hesitation).
  4. Natural Human Error & Repair Psychology (tactile immediate corrections,
     visual lag overshoots, finger-race transpositions, neighbor key brush
     insertions, accelerating backspace cadence, orientation pauses).
  5. Full Pascal Lexical Scanner & Structural Coding Mode (multiline comments,
     string escapes, matching begin/end block lookahead, realistic arrow key
     navigation to fill body statements, guaranteed line integrity).
  6. Multi-stream Seeded RNG (independent streams for timing, errors, cognition,
     and navigation).
  7. Strict Invariant Validation & Closed-Loop Calibration.
  8. Silent Update Check & Self-Updating (v1.0.0): compares APP_VERSION against
     the newest GitHub release each time the UI opens; stays completely quiet
     unless a newer version exists, and never blocks startup or forces an
     upgrade.
  9. .exe Delivery: updates download the published AutoTyper.exe rather than a
     Python script. A packaged build swaps itself in and restarts
     automatically (keeping a .old backup); a build running from source saves
     the executable next to the user's other downloads.
 10. Custom UI Colours: a Microsoft-Paint style hexagon ("honeycomb") colour
     picker that lets you choose a primary, accent and background colour, name
     the result and save it alongside the built-in palettes.

Usage:
    python auto_typer.py --benchmark --wpm 110 --mode net --coding-mode --file code.pas
    python auto_typer.py --check-update
    python auto_typer.py --download-exe            (fetch the published .exe)
    python auto_typer.py  (launches interactive UI)
===============================================================================
"""

import argparse
import csv
import json
import colorsys
import math
import os
import queue
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    tk = messagebox = ttk = None

APP_VERSION = "1.1.0"
APP_NAME = "AutoTyper"
GITHUB_REPO = "jkjklol308-alt/AutoTyper"
EXE_ASSET_NAME = "AutoTyper.exe"

# The updater reads the published GitHub *release* (which carries the built
# .exe), falling back to the published source file when the API is
# unreachable. The download page is only ever used as a last resort.
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
UPDATE_SOURCE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/auto_typer.py"
UPDATE_PAGE_URL = RELEASES_PAGE_URL
UPDATE_CHECK_TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 30.0
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
# Sanity ceiling for the updater: a real build is tens of megabytes, so a
# stream that keeps growing past this is treated as broken rather than
# allowed to fill the user's disk.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

# =============================================================================
# 1. PHYSICAL KEYBOARD GEOMETRY & BIOMECHANICAL FINGER ASSIGNMENTS
# =============================================================================

BACKSPACE = "<BS>"
ENTER = "<ENTER>"
TAB = "<TAB>"
SHIFT_L = "<SHIFT_L>"
SHIFT_R = "<SHIFT_R>"
UP = "<UP>"
DOWN = "<DOWN>"
LEFT = "<LEFT>"
RIGHT = "<RIGHT>"
HOME = "<HOME>"
END_KEY = "<END>"
DELETE_KEY = "<DEL>"

SPECIAL_TOKENS = frozenset({
    BACKSPACE, ENTER, TAB, SHIFT_L, SHIFT_R,
    UP, DOWN, LEFT, RIGHT, HOME, END_KEY, DELETE_KEY,
})

KEY_GEOMETRY: Dict[str, Tuple[float, float]] = {
    '`': (0, -1.0),
    '1': (0, 0.0), '2': (0, 1.0), '3': (0, 2.0), '4': (0, 3.0), '5': (0, 4.0),
    '6': (0, 5.0), '7': (0, 6.0), '8': (0, 7.0), '9': (0, 8.0), '0': (0, 9.0),
    '-': (0, 10.0), '=': (0, 11.0), BACKSPACE: (0, 13.0),
    TAB: (1, -0.5), 'q': (1, 0.5), 'w': (1, 1.5), 'e': (1, 2.5), 'r': (1, 3.5),
    't': (1, 4.5), 'y': (1, 5.5), 'u': (1, 6.5), 'i': (1, 7.5), 'o': (1, 8.5),
    'p': (1, 9.5), '[': (1, 10.5), ']': (1, 11.5), '\\': (1, 12.5),
    'a': (2, 0.75), 's': (2, 1.75), 'd': (2, 2.75), 'f': (2, 3.75), 'g': (2, 4.75),
    'h': (2, 5.75), 'j': (2, 6.75), 'k': (2, 7.75), 'l': (2, 8.75), ';': (2, 9.75),
    "'": (2, 10.75), ENTER: (2, 12.25),
    SHIFT_L: (3, -0.4), 'z': (3, 1.25), 'x': (3, 2.25), 'c': (3, 3.25), 'v': (3, 4.25),
    'b': (3, 5.25), 'n': (3, 6.25), 'm': (3, 7.25), ',': (3, 8.25), '.': (3, 9.25),
    '/': (3, 10.25), SHIFT_R: (3, 12.1),
    ' ': (4, 5.0),
    UP: (3, 14.5), DOWN: (4, 14.5), LEFT: (4, 13.5), RIGHT: (4, 15.5),
    HOME: (1, 14.5), END_KEY: (2, 14.5), DELETE_KEY: (0, 14.5),
}

SHIFT_MAP: Dict[str, str] = {
    '~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6',
    '&': '7', '*': '8', '(': '9', ')': '0', '_': '-', '+': '=',
    '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'",
    '<': ',', '>': '.', '?': '/',
}

FINGER_MAP: Dict[str, Tuple[str, int]] = {
    '`': ('L', 1), '1': ('L', 1), 'q': ('L', 1), 'a': ('L', 1), 'z': ('L', 1),
    TAB: ('L', 1), SHIFT_L: ('L', 1),
    '2': ('L', 2), 'w': ('L', 2), 's': ('L', 2), 'x': ('L', 2),
    '3': ('L', 3), 'e': ('L', 3), 'd': ('L', 3), 'c': ('L', 3),
    '4': ('L', 4), '5': ('L', 4), 'r': ('L', 4), 't': ('L', 4),
    'f': ('L', 4), 'g': ('L', 4), 'v': ('L', 4), 'b': ('L', 4),
    '6': ('R', 4), '7': ('R', 4), 'y': ('R', 4), 'u': ('R', 4),
    'h': ('R', 4), 'j': ('R', 4), 'n': ('R', 4), 'm': ('R', 4),
    '8': ('R', 3), 'i': ('R', 3), 'k': ('R', 3), ',': ('R', 3),
    '9': ('R', 2), 'o': ('R', 2), 'l': ('R', 2), '.': ('R', 2),
    '0': ('R', 1), '-': ('R', 1), '=': ('R', 1), BACKSPACE: ('R', 1),
    'p': ('R', 1), '[': ('R', 1), ']': ('R', 1), '\\': ('R', 1),
    ';': ('R', 1), "'": ('R', 1), ENTER: ('R', 1), '/': ('R', 1),
    SHIFT_R: ('R', 1),
    UP: ('R', 3), DOWN: ('R', 3), LEFT: ('R', 4), RIGHT: ('R', 2),
    HOME: ('R', 2), END_KEY: ('R', 1), DELETE_KEY: ('R', 1),
    ' ': ('R', 5),
}

COMMON_DIGRAPHS = frozenset({
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "st", "es",
    "or", "te", "of", "ed", "is", "it", "al", "ar", "to", "nt", "ti", "as",
    "de", "se", "le", "sa", "ra", "ro", "ri", "ne", "me", "li", "co", "ca",
})

SYNTAX_CHARS = frozenset("={}()[]:;,.<>+-*/&|^~!@#$%?")

MIN_IKI = 0.012   # Physical floor on press-to-press interval (12 ms)
MIN_GAP = 0.006   # Physical floor on sequential non-overlapping key gap (6 ms)


def base_key(ch: str) -> str:
    if not ch:
        return ""
    if ch == "\t":
        return TAB
    if ch == "\n":
        return ENTER
    if ch in SPECIAL_TOKENS:
        return ch
    return SHIFT_MAP.get(ch, ch.lower() if isinstance(ch, str) else ch)


def key_finger(ch: str) -> Optional[Tuple[str, int]]:
    bk = base_key(ch)
    return FINGER_MAP.get(bk)


def needs_shift(ch: str) -> bool:
    if not isinstance(ch, str) or len(ch) != 1:
        return False
    if ch in SHIFT_MAP:
        return True
    return ch.isupper() and ch.lower() in KEY_GEOMETRY


def shift_key_for(ch: str) -> Optional[str]:
    if not needs_shift(ch):
        return None
    f = key_finger(ch)
    if f and f[0] == "L":
        return SHIFT_R
    return SHIFT_L


def physical_key(ch: str) -> str:
    if ch in SPECIAL_TOKENS:
        return ch
    if needs_shift(ch):
        return base_key(ch)
    return ch


def key_distance(k1: str, k2: str) -> float:
    p1 = KEY_GEOMETRY.get(base_key(k1), (2.0, 5.0))
    p2 = KEY_GEOMETRY.get(base_key(k2), (2.0, 5.0))
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def fitts_difficulty(k1: str, k2: str, target_width: float = 1.0) -> float:
    d = key_distance(k1, k2)
    return 0.0 if d <= 0.0 else math.log2(1.0 + d / target_width)


def build_neighbours() -> Dict[str, List[str]]:
    out = {}
    for ch, (r, c) in KEY_GEOMETRY.items():
        if ch == ' ' or len(ch) > 1:
            continue
        out[ch] = [
            o for o, (orr, oc) in KEY_GEOMETRY.items()
            if o != ch and o != ' ' and len(o) == 1 and math.hypot(r - orr, c - oc) <= 1.45
        ]
    return out


NEIGHBOURS = build_neighbours()


# =============================================================================
# 2. PASCAL LEXER & STRUCTURAL BLOCK PARSER
# =============================================================================

@dataclass(frozen=True)
class PascalToken:
    line: int
    col: int
    kind: str
    value: str


def scan_pascal_tokens(text: str) -> List[PascalToken]:
    tokens = []
    i = 0
    n = len(text)
    line_idx = 0
    line_start = 0
    state = "NORMAL"

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        col = i - line_start

        if state == "NORMAL":
            if ch == "\n":
                line_idx += 1
                line_start = i + 1
                i += 1
            elif ch == "/" and nxt == "/":
                state = "COMMENT_LINE"
                i += 2
            elif ch == "{":
                state = "COMMENT_CURLY"
                i += 1
            elif ch == "(" and nxt == "*":
                state = "COMMENT_STAR"
                i += 2
            elif ch == "'":
                state = "STRING"
                i += 1
            elif ch.isalpha() or ch == "_":
                start = i
                while i < n and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                word = text[start:i].lower()
                tokens.append(PascalToken(line_idx, col, "ID", word))
            else:
                i += 1
        elif state == "COMMENT_LINE":
            if ch == "\n":
                line_idx += 1
                line_start = i + 1
                state = "NORMAL"
            i += 1
        elif state == "COMMENT_CURLY":
            if ch == "\n":
                line_idx += 1
                line_start = i + 1
            elif ch == "}":
                state = "NORMAL"
            i += 1
        elif state == "COMMENT_STAR":
            if ch == "\n":
                line_idx += 1
                line_start = i + 1
            elif ch == "*" and nxt == ")":
                state = "NORMAL"
                i += 1
            i += 1
        elif state == "STRING":
            if ch == "\n":
                line_idx += 1
                line_start = i + 1
            elif ch == "'":
                if nxt == "'":
                    i += 1
                else:
                    state = "NORMAL"
            i += 1

    return tokens


def find_pascal_blocks(text_or_lines, max_lookahead: int = 120) -> Dict[int, int]:
    text = "\n".join(text_or_lines) if isinstance(text_or_lines, list) else text_or_lines
    tokens = scan_pascal_tokens(text)

    OPENERS = {"begin", "case", "record", "asm"}
    CLOSERS = {"end"}

    blocks = {}
    stack: List[Tuple[int, str]] = []

    for tok in tokens:
        if tok.value in OPENERS:
            stack.append((tok.line, tok.value))
        elif tok.value in CLOSERS:
            if stack:
                start_line, opener = stack.pop()
                if start_line != tok.line and (tok.line - start_line <= max_lookahead):
                    blocks[start_line] = tok.line

    return blocks


# =============================================================================
# 3. INDENTATION POLICY
# =============================================================================

def leading_ws(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def detect_space_width(lines: List[str]) -> int:
    increases, prev = Counter(), 0
    for line in lines:
        if not line.strip():
            continue
        cur = len(line) - len(line.lstrip(" "))
        if cur > prev:
            increases[cur - prev] += 1
        prev = cur
    width = increases.most_common(1)[0][0] if increases else 4
    return width if 2 <= width <= 8 else 4


def detect_indent_unit(lines: List[str]) -> str:
    tab_lines = sum(1 for ln in lines if ln.startswith("\t"))
    space_lines = sum(1 for ln in lines if ln.startswith(" "))
    if tab_lines and tab_lines >= space_lines:
        return "\t"
    return " " * detect_space_width(lines)


# Pascal keywords/punctuation after which a "smart indent" editor typically
# opens one additional indentation level on the line that follows.
SMART_INDENT_OPENERS = frozenset({
    "begin", "then", "do", "else", "try", "finally", "repeat",
    "case", "record", "var", "const", "type", "label", "with",
    "private", "public", "protected", "published", "interface",
    "implementation", "automated",
})


def _last_word(stripped: str) -> str:
    core = stripped.rstrip(";")
    parts = core.split()
    return parts[-1].lower() if parts else ""


def _ends_with_block_opener(stripped: str) -> bool:
    """Heuristic mirroring what a Pascal-aware smart-indent editor checks on
    the line that was just finished, to decide whether the *next* line should
    be indented one level deeper."""
    if not stripped:
        return False
    last = _last_word(stripped)
    if last in SMART_INDENT_OPENERS:
        return True
    if stripped.endswith(":") and not stripped.endswith("::"):
        return True
    return False


@dataclass(frozen=True)
class IndentPolicy:
    """Models what the *target* editor does to whitespace automatically,
    so the planner can correct for it instead of (a) blindly retyping
    indentation on top of what the editor already inserted -- causing
    double indentation -- or (b) blindly backspacing a fixed number of
    times regardless of what is actually on the line -- which can delete
    through the start of the line and merge it with the line above.

    mode:
        "off"   - editor does not auto-indent at all; type indentation verbatim.
        "copy"  - editor copies the previous line's leading whitespace onto
                  the new line (the most common basic auto-indent feature).
        "smart" - editor copies the previous line's indentation, and adds one
                  extra indent unit when the previous line opens a block
                  (``begin``, ``then``, ``do``, ``case``, trailing ``:`` ...).
        "fixed" - editor always inserts the same fixed-width whitespace after
                  every Enter press, regardless of context.
    """
    mode: str = "off"
    fixed_width: int = 0
    tab_stop_backspace: bool = False

    def expected_autoindent(self, prev_line: Optional[str], unit: str) -> str:
        """Predict the whitespace string the target editor will insert on a
        fresh line immediately after Enter is pressed, based solely on the
        line that was just finished (never on text that has not been typed
        yet). Returns "" when no such line exists (e.g. document start)."""
        if prev_line is None or self.mode == "off":
            return ""
        if self.mode == "fixed":
            return " " * max(0, min(64, self.fixed_width))
        prev_indent = leading_ws(prev_line)
        stripped = prev_line.strip()
        if self.mode == "copy":
            return prev_indent
        if self.mode == "smart":
            if not stripped:
                return prev_indent
            if _ends_with_block_opener(stripped):
                return prev_indent + (unit or "    ")
            return prev_indent
        return ""

    def backspace_presses(self, auto_indent: str, unit: str) -> int:
        """Number of Backspace keystrokes required to fully clear
        `auto_indent` (and nothing more) from the start of a fresh line."""
        n = len(auto_indent)
        if n <= 0:
            return 0
        if not self.tab_stop_backspace or not unit:
            return n
        width = max(1, len(unit))
        return -(-n // width)  # ceil(n / width); each press clears to the previous tab stop


# =============================================================================
# 4. RANDOMNESS STREAMS & STOCHASTIC MODEL
# =============================================================================

@dataclass
class RNGStreams:
    timing: random.Random
    error: random.Random
    planner: random.Random
    nav: random.Random

    @classmethod
    def from_seed(cls, seed: Optional[int]):
        if seed is None:
            return cls(
                timing=random.SystemRandom(),
                error=random.SystemRandom(),
                planner=random.SystemRandom(),
                nav=random.SystemRandom(),
            )
        root = random.Random(seed)
        return cls(
            timing=random.Random(root.randint(0, 2**31 - 1)),
            error=random.Random(root.randint(0, 2**31 - 1)),
            planner=random.Random(root.randint(0, 2**31 - 1)),
            nav=random.Random(root.randint(0, 2**31 - 1)),
        )


@dataclass
class TypingProfile:
    fitts_a: float = 0.070
    fitts_b: float = 0.040
    fitts_ref_id: float = 1.6

    pace_cv: float = 0.048
    pace_theta: float = 0.38
    pace_min: float = 0.78
    pace_max: float = 1.28

    workload_rate: float = 0.0018
    recovery_lambda: float = 0.022
    fatigue_max: float = 0.32
    fatigue_slowdown: float = 0.35
    fatigue_typo_gain: float = 2.8

    dwell_mu: float = -2.88
    dwell_sigma: float = 0.18

    enable_rollover: bool = True
    rollover_ratio: float = 0.28

    shift_iki_lo: float = 1.04
    shift_iki_hi: float = 1.15
    shift_lead_lo: float = 0.016
    shift_lead_hi: float = 0.045
    shift_lag_lo: float = 0.006
    shift_lag_hi: float = 0.028


@dataclass
class TypingState:
    pace_factor: float = 1.0
    fatigue: float = 0.0
    elapsed: float = 0.0
    prev_dwell: float = 0.0


class TypingModel:
    def __init__(self, profile: TypingProfile, streams: RNGStreams, target_wpm: float, base_typo_rate: float):
        self.profile = profile
        self.streams = streams
        self.target_wpm = target_wpm
        self.base_typo_rate = base_typo_rate
        self.timing_scale = 1.0

    def advance(self, state: TypingState, dt: float, working: bool = True):
        p = self.profile
        dt = max(1e-3, dt)
        decay = math.exp(-p.pace_theta * dt)
        noise = p.pace_cv * math.sqrt(max(0.0, 1.0 - decay * decay)) * self.streams.timing.gauss(0.0, 1.0)
        state.pace_factor = max(p.pace_min, min(p.pace_max, 1.0 + (state.pace_factor - 1.0) * decay + noise))

        work = p.workload_rate * dt if working else 0.0
        state.fatigue = max(0.0, min(p.fatigue_max, state.fatigue * math.exp(-p.recovery_lambda * dt) + work))
        state.elapsed += dt

    def sample_iki(self, state: TypingState, prev_phys: Optional[str], prev_logical: Optional[str],
                   cur: str, origin: Optional[str] = None) -> float:
        rng = self.streams.timing
        p = self.profile

        base = 60.0 / (5.0 * self.target_wpm) * self.timing_scale
        src = origin or prev_phys
        id_val = fitts_difficulty(src, cur) if src else p.fitts_ref_id
        fitts_factor = (p.fitts_a + p.fitts_b * id_val) / (p.fitts_a + p.fitts_b * p.fitts_ref_id)

        speed = max(0.1, state.pace_factor * (1.0 - p.fatigue_slowdown * state.fatigue))
        mean = max(MIN_IKI, base * fitts_factor / speed)

        alpha = max(2.0, 3.5 - 2.5 * state.fatigue)
        iki = rng.gammavariate(alpha, mean / alpha)

        f_prev = key_finger(prev_phys) if prev_phys else None
        f_cur = key_finger(cur)

        if f_prev and f_cur:
            hand_prev, fing_prev = f_prev
            hand_cur, fing_cur = f_cur

            if hand_prev != hand_cur:
                iki *= rng.uniform(0.72, 0.86)
            else:
                if fing_prev == fing_cur:
                    iki *= rng.uniform(1.25, 1.45)
                elif abs(fing_prev - fing_cur) == 1:
                    iki *= rng.uniform(0.96, 1.08)
                else:
                    iki *= rng.uniform(0.88, 0.98)

        if prev_logical and (prev_logical + cur).lower() in COMMON_DIGRAPHS:
            iki *= rng.uniform(0.65, 0.80)

        if cur in SYNTAX_CHARS:
            iki *= rng.uniform(1.12, 1.35)

        if needs_shift(cur):
            iki *= rng.uniform(p.shift_iki_lo, p.shift_iki_hi)

        return max(MIN_IKI, iki)

    def dwell_time(self, state: TypingState, key: str) -> float:
        p = self.profile
        bk = base_key(key)
        hold = self.streams.timing.lognormvariate(p.dwell_mu + 0.10 * (1.0 - state.pace_factor), p.dwell_sigma)
        if bk == " ":
            hold *= 1.20
        elif bk in (BACKSPACE, DELETE_KEY, ENTER, TAB):
            hold *= 1.30
        elif bk in (UP, DOWN, LEFT, RIGHT, HOME, END_KEY):
            hold *= 1.12
        return max(0.018, min(0.135, hold))

    def typo_probability(self, state: TypingState, origin: Optional[str], cur: str) -> float:
        p = self.profile
        id_val = fitts_difficulty(origin, cur) if origin else 0.0
        prob = self.base_typo_rate * (1.0 + 0.18 * id_val) * (1.0 + p.fatigue_typo_gain * state.fatigue)
        # The GUI exposes the full 0.01%–100% range. Keep the probability
        # bounded at one while still allowing an intentional 100% error mode.
        return min(1.0, prob)

    def misstrike(self, ch: str) -> str:
        near = NEIGHBOURS.get(ch.lower() if isinstance(ch, str) else ch)
        if not near:
            return ch
        wrong = self.streams.error.choice(near)
        return wrong.upper() if isinstance(ch, str) and ch.isupper() else wrong

    def calibrate(self, sample_text: str, samples: int = 2500, iterations: int = 2) -> float:
        text = sample_text.replace("\r", "").replace("\n", " ")
        if len(text) < 2:
            text = DEFAULT_SAMPLE.replace("\n", " ")
        pairs = [(text[k - 1], text[k]) for k in range(1, len(text))]
        target = 60.0 / (5.0 * self.target_wpm)
        neutral = TypingState()
        self.timing_scale = 1.0
        for _ in range(iterations):
            total = 0.0
            for n in range(samples):
                prev, cur = pairs[n % len(pairs)]
                total += self.sample_iki(neutral, prev, prev, cur)
            self.timing_scale *= target / (total / samples)
        return self.timing_scale


# =============================================================================
# 5. EVENT TRACE & LAYERED STRUCTURES
# =============================================================================

@dataclass(frozen=True)
class Event:
    action: str        # "key" | "backspace" | "delete" | "enter" | "shift" | "pause" | "nav"
    char: str
    press_at: float
    release_at: float
    line: int
    note: str = ""

    @property
    def dwell(self) -> float:
        return self.release_at - self.press_at

    @property
    def key(self) -> str:
        return "" if self.action == "pause" else physical_key(self.char)


@dataclass(frozen=True)
class Transition:
    at: float
    down: bool
    key: str
    line: int


def events_to_transitions(events: List[Event]) -> List[Transition]:
    tagged = []
    for idx, ev in enumerate(events):
        if ev.action == "pause":
            continue
        tagged.append((ev.press_at, 1, idx, Transition(ev.press_at, True, ev.key, ev.line)))
        tagged.append((ev.release_at, 0, idx, Transition(ev.release_at, False, ev.key, ev.line)))
    tagged.sort(key=lambda t: t[:3])
    return [t[3] for t in tagged]


@dataclass(frozen=True)
class ErrorEpisode:
    kind: str
    intended_char: str
    mistyped_keys: List[str]
    backspace_count: int


ERROR_KINDS = ["substitution", "transposition", "omission", "insertion", "overshoot"]
ERROR_WEIGHTS = [0.42, 0.20, 0.15, 0.13, 0.10]


# =============================================================================
# 6. BIOMECHANICAL & COGNITIVE PLANNER
# =============================================================================

class TypingPlanner:
    def __init__(self, model: TypingModel, streams: RNGStreams, indent: Optional[IndentPolicy] = None,
                 coding_mode: bool = False, max_lookahead: int = 120):
        self.model = model
        self.streams = streams
        self.indent = indent or IndentPolicy()
        self.coding_mode = coding_mode
        self.max_lookahead = max_lookahead
        self.unit = "    "
        self.space_width = 4
        self.state = TypingState()
        self.events: List[Event] = []
        self.buffer: List[str] = []
        self.prev_phys: Optional[str] = None
        self.hand_pos: Dict[str, Optional[str]] = {"L": None, "R": None}
        self.clock = 0.0
        self.line = 0

    def _emit(self, action: str, char: str, delay: float, dwell: float, note: str = "", hold_extra: float = 0.0):
        press_at = self.clock + delay
        release_at = press_at + dwell
        self.events.append(Event(action, char, press_at, release_at, self.line, note))
        self.clock = release_at + hold_extra
        self.model.advance(self.state, delay + dwell + hold_extra, working=True)
        self.state.prev_dwell = dwell + hold_extra

    def _pause(self, duration: float, note: str = "pause"):
        start, end = self.clock, self.clock + duration
        self.events.append(Event("pause", "", start, end, self.line, note))
        self.clock = end
        self.model.advance(self.state, duration, working=False)
        self.state.prev_dwell = 0.0

    def _origin(self, ch: str) -> Optional[str]:
        f = key_finger(ch)
        h = f[0] if f else None
        return (self.hand_pos[h] if h else None) or self.prev_phys

    def _struck(self, key: str):
        self.prev_phys = key
        f = key_finger(key)
        if f:
            self.hand_pos[f[0]] = key

    def _press(self, ch: str, note: str = ""):
        tail = self.buffer[-1] if self.buffer else None
        iki = self.model.sample_iki(self.state, self.prev_phys, tail, ch, origin=self._origin(ch))
        dwell = self.model.dwell_time(self.state, ch)

        f_prev = key_finger(self.prev_phys) if self.prev_phys else None
        f_cur = key_finger(ch)
        can_rollover = (
            self.model.profile.enable_rollover
            and f_prev is not None
            and f_cur is not None
            and (f_prev[0] != f_cur[0] or f_prev[1] != f_cur[1])
            and not needs_shift(ch)
        )

        prev_dwell = self.state.prev_dwell
        if can_rollover and prev_dwell > MIN_GAP:
            max_overlap = prev_dwell * self.model.profile.rollover_ratio
            delay = max(MIN_GAP, iki - prev_dwell - max_overlap)
        else:
            delay = max(MIN_GAP, iki - prev_dwell)

        shift = shift_key_for(ch)
        hold_extra = 0.0
        if shift:
            p = self.model.profile
            lead = min(self.streams.timing.uniform(p.shift_lead_lo, p.shift_lead_hi), 0.75 * delay)
            hold_extra = self.streams.timing.uniform(p.shift_lag_lo, p.shift_lag_hi)
            down = self.clock + delay
            self.events.append(Event("shift", shift, down - lead, down + dwell + hold_extra, self.line))

        self._emit("key", ch, delay, dwell, note, hold_extra)
        self.buffer.append(ch)
        self._struck(ch)

    def _nav(self, nav_key: str, note: str = ""):
        iki = self.model.sample_iki(self.state, self.prev_phys, None, nav_key, origin=self._origin(nav_key))
        dwell = self.model.dwell_time(self.state, nav_key)
        delay = max(MIN_GAP, iki - self.state.prev_dwell)
        self._emit("nav", nav_key, delay, dwell, note)
        self._struck(nav_key)

    def _select_to_end(self, note: str = "line_reset_select"):
        """Hold Shift while pressing End to select the current line safely.

        This is deliberately used instead of a run of Delete presses when a
        fresh line's auto-indent is uncertain. Delete at column 0 on an empty
        line can join that line to the next line; a non-empty selection cannot
        do that. The caller first inserts a harmless visible sentinel, so the
        selection is guaranteed to be non-empty even when the target editor
        supplied no indentation at all.
        """
        iki = self.model.sample_iki(self.state, self.prev_phys, None, END_KEY,
                                    origin=self._origin(END_KEY))
        dwell = self.model.dwell_time(self.state, END_KEY)
        delay = max(MIN_GAP, iki - self.state.prev_dwell)
        shift = SHIFT_L
        lead = min(self.streams.timing.uniform(0.015, 0.040), 0.75 * delay)
        hold_extra = self.streams.timing.uniform(0.006, 0.020)
        down = self.clock + delay
        self.events.append(Event("shift", shift, down - lead,
                                 down + dwell + hold_extra, self.line, note))
        self._emit("nav", END_KEY, delay, dwell, note, hold_extra)
        self._struck(END_KEY)

    def _backspaces(self, count: int, first_delay: Tuple[float, float], note: str = "", first_note: Optional[str] = None):
        for idx in range(count):
            if idx == 0:
                delay = self.streams.planner.uniform(*first_delay)
            else:
                delay = max(0.020, 0.058 - idx * 0.0035) + self.streams.planner.uniform(-0.003, 0.005)
            dwell = self.model.dwell_time(self.state, BACKSPACE)
            self._emit("backspace", BACKSPACE, delay, dwell, first_note if (idx == 0 and first_note) else note)
            if self.buffer:
                self.buffer.pop()
            self._struck(BACKSPACE)

    def _deletes(self, count: int, first_delay: Tuple[float, float], note: str = "", first_note: Optional[str] = None):
        """Press forward-Delete `count` times. Unlike Backspace, Delete only
        ever removes characters at/after the cursor -- it can never reach
        back into already-finished text on the line (or lines) above.
        Used together with a preceding Home press so that clearing a
        mispredicted auto-indent can never eat into the previous line's
        content (e.g. deleting the trailing ';' of the line above)."""
        for idx in range(count):
            if idx == 0:
                delay = self.streams.planner.uniform(*first_delay)
            else:
                delay = max(0.020, 0.058 - idx * 0.0035) + self.streams.planner.uniform(-0.003, 0.005)
            dwell = self.model.dwell_time(self.state, DELETE_KEY)
            self._emit("delete", DELETE_KEY, delay, dwell, first_note if (idx == 0 and first_note) else note)
            if self.buffer:
                self.buffer.pop(0)
            self._struck(DELETE_KEY)

    def _enter(self, finished_line: str) -> str:
        """Press Enter after `finished_line` (the exact text now on the line
        the cursor is leaving). Returns the whitespace the target editor is
        predicted to auto-insert on the new line, and seeds `self.buffer`
        with it so later typing is reconciled against what is really there
        instead of assuming a blank line."""
        dwell = self.model.dwell_time(self.state, ENTER)
        self._emit("enter", "\n", self.streams.planner.uniform(0.06, 0.16), dwell)
        self._struck("\n")
        auto_indent = self.indent.expected_autoindent(finished_line, self.unit)
        self.buffer = list(auto_indent)
        return auto_indent

    def _reconcile_line(self, target_line: str):
        """Make a fresh editor row read exactly as ``target_line``.

        The old implementation tried to reconcile a *prediction* of the
        editor's auto-indent with Backspace/Delete. That is fundamentally
        unsafe in an external application: a blank row may be trimmed, a
        different indent width may be used, or the cursor may be clipped by
        the editor. In particular, Delete at column zero on an empty row can
        delete the row's newline and join it to the next row.

        We now use a transaction that is independent of the prediction:
        write one harmless sentinel, go Home, select to End while holding
        Shift, and Backspace the non-empty selection. This removes the whole
        current row only; because the selection is guaranteed non-empty it
        cannot merge either neighbouring row. The requested text, including
        its exact indentation, is then typed from a known empty row.

        This is intentionally a little more conservative than only fixing a
        predicted prefix. It is what makes the live OS-level typer safe when
        the target editor is not the editor used to generate the trace.
        """
        # A visible sentinel is important. On a truly empty row, selecting
        # from Home to End would be an empty selection, and Backspace at
        # column zero has editor-dependent newline-joining behaviour. The
        # sentinel guarantees that Backspace deletes a selection instead.
        self._press("~", note="line_reset_sentinel")
        self._nav(HOME, note="line_reset_home")
        self._select_to_end(note="line_reset_select")
        self._backspaces(1, (0.035, 0.080), note="line_reset", first_note="line_reset_delete_selection")
        self.buffer = []
        self._plan_line(target_line)

    def _build_episode(self, kind: str, text: str, i: int) -> Optional[ErrorEpisode]:
        cur = text[i]
        rest = text[i + 1:]
        rng = self.streams.error

        if kind == "substitution":
            wrong = self.model.misstrike(cur)
            if wrong != cur:
                return ErrorEpisode(kind, cur, [wrong], 1)
            return None

        if kind == "transposition":
            nxt = rest[:1]
            if nxt and nxt.isalnum() and nxt != cur:
                extra = list(rest[1:1 + rng.randint(0, 2)])
                keys = [nxt, cur] + extra
                return ErrorEpisode(kind, cur, keys, len(keys))
            return None

        if kind == "omission":
            k = rng.randint(1, 3)
            keys = list(rest[:k])
            if keys and keys[0] != cur:
                return ErrorEpisode(kind, cur, keys, len(keys))
            return None

        if kind == "insertion":
            extra = self.model.misstrike(cur)
            if extra != cur:
                keys = [extra, cur] + list(rest[:rng.randint(0, 2)])
                return ErrorEpisode(kind, cur, keys, len(keys))
            return None

        if kind == "overshoot":
            wrong = self.model.misstrike(cur)
            if wrong != cur:
                keys = [wrong] + list(rest[:rng.randint(1, 3)])
                return ErrorEpisode(kind, cur, keys, len(keys))
            return None

        return None

    def _episode_is_safe(self, episode_keys: List[str]) -> bool:
        if not self.indent.tab_stop_backspace:
            return True
        line_is_blank = not "".join(self.buffer).strip()
        return not (line_is_blank and any(k.isspace() for k in episode_keys))

    def _maybe_typo(self, text: str, i: int):
        cur = text[i]
        if not cur.isalnum():
            return
        if self.streams.error.random() >= self.model.typo_probability(self.state, self._origin(cur), cur):
            return

        kind = self.streams.error.choices(ERROR_KINDS, weights=ERROR_WEIGHTS)[0]
        episode = self._build_episode(kind, text, i)
        if not episode or not self._episode_is_safe(episode.mistyped_keys):
            return

        for n, ch in enumerate(episode.mistyped_keys):
            self._press(ch, note=f"typo:{kind}" if n == 0 else "typo")

        if kind == "substitution":
            first = (0.12, 0.26)
        else:
            self._pause(self.streams.planner.uniform(0.16, 0.40), "realize")
            first = (0.050, 0.090)
        self._backspaces(episode.backspace_count, first, note=f"fix:{kind}")

    def _plan_line(self, text: str):
        i = 0
        burst = self.streams.planner.randint(4, 10)
        while i < len(text):
            tail = self.buffer[-1] if self.buffer else None
            at_word_boundary = (tail and tail in " ;:()[],." and text[i] not in " \t")
            if burst <= 0 or at_word_boundary:
                if self.streams.planner.random() < 0.18:
                    self._pause(min(1.0, self.streams.planner.gammavariate(2.2, 0.16)), "think")
                burst = self.streams.planner.randint(4, 11)

            self._maybe_typo(text, i)
            self._press(text[i])
            burst -= 1
            i += 1

    def _plan_lines_range(self, lines: List[str], start: int, end: int, blocks: Dict[int, int]):
        """Plan lines in range [start, end], executing lookahead on Pascal blocks."""
        i = start
        while i <= end:
            if self.coding_mode and i in blocks and blocks[i] <= end:
                end_block = blocks[i]

                # 1. Type opening block statement, reconciling any indentation
                #    the editor may have already auto-inserted on this line.
                self.line = i
                self._reconcile_line(lines[i])
                self._enter(lines[i])
                self._pause(self.streams.planner.uniform(0.10, 0.30), "newline")

                inner_start = i + 1
                inner_end = end_block - 1

                if inner_start <= inner_end:
                    # 2. Press Enter again on the (still blank) body line to
                    #    push a fresh row below it -- that row is where the
                    #    closing statement will be typed next, while this row
                    #    keeps whatever auto-indent the editor placed on it.
                    body_row_content = "".join(self.buffer)
                    self._enter(body_row_content)
                    self._pause(self.streams.planner.uniform(0.06, 0.18), "block_prep")

                    # 3. Type closing block statement, reconciling indentation.
                    self.line = end_block
                    self._reconcile_line(lines[end_block])
                    self._pause(self.streams.planner.uniform(0.10, 0.22), "block_close")

                    # 4. Navigate UP back to the body slot, then explicitly to
                    #    its End -- a plain Up arrow only preserves the
                    #    previous column and clips to the target line's
                    #    length, which does NOT reliably land at the end of
                    #    the body row when sibling lines have different
                    #    lengths (e.g. a closing "end" with no trailing ";").
                    #    Its content is untouched since step 2, so restore
                    #    the tracked buffer to match reality afterwards.
                    self._nav(UP, note="block_up")
                    self._nav(END_KEY, note="block_up_end")
                    self._pause(self.streams.nav.uniform(0.08, 0.22), "nav_pause")
                    self.buffer = list(body_row_content)

                    # 5. Recursively plan inner body statements
                    self._plan_lines_range(lines, inner_start, inner_end, blocks)

                    # 6. Navigate DOWN past closing block
                    self._nav(DOWN, note="block_down")
                    self._nav(END_KEY, note="block_end")
                    self._pause(self.streams.nav.uniform(0.08, 0.22), "nav_pause")
                    self.buffer = list(lines[end_block])
                else:
                    self.line = end_block
                    self._reconcile_line(lines[end_block])

                if end_block < end:
                    self._enter(lines[end_block])
                    self._pause(self.streams.planner.uniform(0.10, 0.35), "newline")

                i = end_block + 1
            else:
                self.line = i
                self._reconcile_line(lines[i])
                if i < end:
                    self._enter(lines[i])
                    self._pause(self.streams.planner.uniform(0.10, 0.35), "newline")
                i += 1

    def plan(self, text: str) -> List[Event]:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.unit = detect_indent_unit(lines)
        self.space_width = detect_space_width(lines)
        blocks = find_pascal_blocks(lines, self.max_lookahead) if self.coding_mode else {}

        self._pause(self.streams.planner.uniform(0.08, 0.24), "start")
        if lines:
            self._plan_lines_range(lines, 0, len(lines) - 1, blocks)
        return self.events


# =============================================================================
# 7. INVARIANT VALIDATION & TRACE METRICS
# =============================================================================

def validate_trace(events: List[Event]) -> List[str]:
    errors = []
    active_shift: Optional[Event] = None

    for idx, ev in enumerate(events):
        if ev.line < 0:
            errors.append(f"Event {idx} has negative line {ev.line}")

        if ev.action == "pause":
            if ev.press_at < 0 or ev.release_at < ev.press_at:
                errors.append(f"Invalid pause at {idx}: [{ev.press_at}, {ev.release_at}]")
            continue

        if ev.dwell <= 0:
            errors.append(f"Event {idx} ({ev.char}) has non-positive dwell: {ev.dwell:.6f}s")

        if ev.action == "shift":
            active_shift = ev
        elif ev.action == "key" and needs_shift(ev.char):
            if not active_shift:
                errors.append(f"Shifted key {ev.char} at idx {idx} without active Shift event")
            else:
                if not (active_shift.press_at < ev.press_at and ev.release_at < active_shift.release_at):
                    errors.append(f"Shift does not properly enclose key {ev.char} at idx {idx}")
                active_shift = None
        elif ev.action in ("key", "backspace", "delete", "enter", "nav"):
            if active_shift and ev.action == "nav" and ev.char == END_KEY:
                if not (active_shift.press_at < ev.press_at and ev.release_at < active_shift.release_at):
                    errors.append(f"Shift does not properly enclose selection End at idx {idx}")
                active_shift = None
            elif active_shift and active_shift.release_at > ev.press_at:
                errors.append(f"Shift still active when pressing unshifted key {ev.char} at idx {idx}")

    return errors


DEFAULT_SAMPLE = (
    "The quick brown fox jumps over the lazy dog while the rain falls on the hills.\n"
    "def add(a, b):\n    result = a + b  # sum the values\n    return result\n"
    "Typing is a motor skill; speed and accuracy improve with practice over time.\n"
)


def sample_corpus(n_chars: int) -> str:
    reps = n_chars // len(DEFAULT_SAMPLE) + 1
    return (DEFAULT_SAMPLE * reps)[:n_chars]


def trace_duration(events: List[Event]) -> float:
    return max((e.release_at for e in events), default=0.0)


def chain_intervals(events: List[Event]) -> List[Tuple[float, str, str]]:
    out, prev = [], None
    for ev in events:
        if ev.action == "shift":
            continue
        if ev.action == "key":
            if prev is not None:
                out.append((ev.press_at - prev.press_at, prev.char, ev.char))
            prev = ev
        else:
            prev = None
    return out


def _pct(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    return sorted_vals[min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1) + 0.5))]


def summarize_trace(events: List[Event], text: str) -> Dict[str, object]:
    logical_chars = len(text.replace("\r\n", "\n").replace("\r", "\n"))
    total = trace_duration(events)
    chain = chain_intervals(events)
    ikis = [c[0] for c in chain]
    alt = [c[0] for c in chain if key_finger(c[1]) and key_finger(c[2]) and key_finger(c[1])[0] != key_finger(c[2])[0]]
    same_f = [c[0] for c in chain if key_finger(c[1]) and key_finger(c[2]) and key_finger(c[1]) == key_finger(c[2])]
    dwells = [e.dwell for e in events if e.action not in ("pause", "shift")]
    shift_holds = [e.dwell for e in events if e.action == "shift"]
    kinds = Counter(e.note.split(":", 1)[1] for e in events if e.note.startswith("typo:"))
    episodes = sum(kinds.values())
    # A reset is a safe, non-empty line selection rather than a blind run
    # of indentation Delete presses. Keep the legacy metric names for CSV/
    # benchmark compatibility, but report the new transaction accurately.
    indent_lines = sum(1 for e in events if e.note == "line_reset_sentinel")
    indent_backspaces = sum(1 for e in events if e.note == "line_reset_delete_selection")
    backspaces = sum(
        1 for e in events
        if e.action == "backspace" and not e.note.startswith(("indent", "line_reset"))
    )
    nav_presses = sum(1 for e in events if e.action in ("nav", "delete"))
    key_presses = sum(1 for e in events if e.action in ("key", "backspace", "delete", "enter", "nav"))
    pause_time = sum(e.dwell for e in events if e.action == "pause")
    active_time = max(0.001, total - pause_time)

    s = sorted(ikis)
    nan = float("nan")
    mean_iki = statistics.fmean(ikis) if ikis else nan

    stats = {
        "events": len(events),
        "logical_chars": logical_chars,
        "total_seconds": total,
        "net_wpm": logical_chars / 5.0 / (total / 60.0) if total > 0 else nan,
        "gross_wpm": 60.0 / (5.0 * mean_iki) if ikis else nan,
        "motor_wpm": key_presses / 5.0 / (active_time / 60.0) if active_time > 0 else nan,
        "mean_iki": mean_iki,
        "std_iki": statistics.pstdev(ikis) if ikis else nan,
        "median_iki": statistics.median(ikis) if ikis else nan,
        "p05_iki": _pct(s, 0.05),
        "p95_iki": _pct(s, 0.95),
        "mean_iki_alternating_hand": statistics.fmean(alt) if alt else nan,
        "mean_iki_same_finger": statistics.fmean(same_f) if same_f else nan,
        "mean_dwell": statistics.fmean(dwells) if dwells else nan,
        "std_dwell": statistics.pstdev(dwells) if dwells else nan,
        "shift_presses": len(shift_holds),
        "mean_shift_hold": statistics.fmean(shift_holds) if shift_holds else nan,
        "error_episodes": episodes,
        "achieved_error_rate_per_char": episodes / logical_chars if logical_chars else nan,
        "backspaces": backspaces,
        "correction_rate_per_char": backspaces / logical_chars if logical_chars else nan,
        "pauses": sum(1 for e in events if e.action == "pause"),
        "nav_presses": nav_presses,
        "indent_clear_lines": indent_lines,
        "indent_clear_backspaces": indent_backspaces,
    }
    for kind in ERROR_KINDS:
        stats[f"errors_{kind}"] = kinds.get(kind, 0)
    return stats


def format_stats(stats: Dict[str, object]) -> str:
    lines = []
    for k, v in stats.items():
        lines.append(f"{k:32s} {v:.4f}" if isinstance(v, float) else f"{k:32s} {v}")
    return "\n".join(lines)


def export_trace_csv(events: List[Event], path: str):
    def esc(s):
        return s.encode("unicode_escape").decode()

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["action", "char", "press_at", "release_at", "line", "note", "key"])
        for e in events:
            w.writerow([e.action, esc(e.char), f"{e.press_at:.6f}", f"{e.release_at:.6f}",
                        e.line, e.note, esc(e.key)])


# =============================================================================
# 8. CLOSED-LOOP CALIBRATION & SIMULATION
# =============================================================================

def _calibration_events(text: str, wpm: float, typo_rate: float, indent: IndentPolicy,
                        scale: float, k: int, coding_mode: bool = False) -> List[Event]:
    streams = RNGStreams.from_seed(10000 + k)
    model = TypingModel(TypingProfile(), streams, wpm, typo_rate)
    model.timing_scale = scale
    return TypingPlanner(model, streams, indent, coding_mode=coding_mode).plan(text)


def calibrate_trace(model: TypingModel, text: str, typo_rate: float, indent: IndentPolicy,
                    mode: str, n_traces: int = 3, iterations: int = 2, scatter_traces: int = 6,
                    coding_mode: bool = False) -> Dict[str, float]:
    sample = text.replace("\r\n", "\n").replace("\r", "\n")[:2000]
    if len(sample) < 200:
        sample = sample_corpus(2000)

    if mode == "net":
        target = len(sample) / 5.0 * 60.0 / model.target_wpm
        to_wpm = lambda q: len(sample) / 5.0 * 60.0 / q
        measure = trace_duration
    else:
        target = 60.0 / (5.0 * model.target_wpm)
        to_wpm = lambda q: 60.0 / (5.0 * q)
        measure = lambda ev: statistics.fmean([c[0] for c in chain_intervals(ev)]) if chain_intervals(ev) else target

    def measurements(scale, n):
        return [measure(_calibration_events(sample, model.target_wpm, typo_rate, indent, scale, k, coding_mode))
                for k in range(n)]

    def quantity(scale):
        return statistics.fmean(measurements(scale, n_traces))

    s0 = model.timing_scale
    lo, hi = s0 * 0.3, s0 * 3.0
    s1 = s0 * 0.85
    q0 = quantity(s0)
    for _ in range(iterations):
        q1 = quantity(s1)
        if abs(q1 - q0) < 1e-9:
            break
        s2 = s1 + (target - q1) * (s1 - s0) / (q1 - q0)
        s0, q0 = s1, q1
        s1 = max(lo, min(hi, s2))
    model.timing_scale = s1

    final = measurements(s1, max(n_traces, scatter_traces))
    mean_q = statistics.fmean(final)
    cv = statistics.stdev(final) / mean_q if len(final) > 1 and mean_q > 0 else float("nan")
    return {"timing_scale": s1, "estimated_wpm": to_wpm(mean_q), "calibration_cv": cv}


def build_trace(text: str, wpm: int, typo_rate: float, indent: IndentPolicy,
                rng_or_streams, mode: str = "net", coding_mode: bool = False,
                max_lookahead: int = 120) -> Tuple[List[Event], Dict[str, object]]:
    if not 0.0 <= typo_rate <= 1.0:
        raise ValueError(f"typo_rate must be a probability in [0, 1], got {typo_rate!r}")
    if wpm <= 0:
        raise ValueError("wpm must be positive")
    if mode not in ("net", "gross"):
        raise ValueError("mode must be 'net' or 'gross'")

    streams = rng_or_streams if isinstance(rng_or_streams, RNGStreams) else RNGStreams.from_seed(None)

    model = TypingModel(TypingProfile(), streams, wpm, typo_rate)
    model.calibrate(text)
    cal = calibrate_trace(model, text, typo_rate, indent, mode, coding_mode=coding_mode)
    events = TypingPlanner(model, streams, indent, coding_mode=coding_mode, max_lookahead=max_lookahead).plan(text)

    validation_errors = validate_trace(events)
    if validation_errors:
        raise RuntimeError(f"Trace validation failed:\n" + "\n".join(validation_errors[:5]))

    return events, {"mode": mode, "coding_mode": coding_mode, **cal}


def simulate(text: str, wpm: int, typo_rate: float, indent: IndentPolicy,
             seed: Optional[int], n_chars: int = 10000, mode: str = "net",
             coding_mode: bool = False) -> Tuple[List[Event], Dict[str, object], str]:
    if not text.strip():
        text = sample_corpus(n_chars)
    streams = RNGStreams.from_seed(seed)
    events, info = build_trace(text, wpm, typo_rate, indent, streams, mode, coding_mode=coding_mode)
    return events, info, text


def run_benchmark(text: str, wpm: int, typo_rate: float, indent: IndentPolicy,
                  seed: Optional[int], n_chars: int = 10000, mode: str = "net",
                  coding_mode: bool = False) -> Dict[str, object]:
    events, info, used = simulate(text, wpm, typo_rate, indent, seed, n_chars, mode, coding_mode=coding_mode)
    stats = summarize_trace(events, used)
    stats["requested_wpm"] = wpm
    stats["mode"] = mode
    stats["coding_mode"] = coding_mode
    stats["base_typo_rate"] = typo_rate
    stats["calibration_estimate_wpm"] = info["estimated_wpm"]
    stats["calibration_cv"] = info["calibration_cv"]
    return stats


# =============================================================================
# 9. KEYBOARD OUTPUT & PLAYBACK
# =============================================================================

class KeyboardOutput:
    def __init__(self):
        from pynput.keyboard import Controller, Key
        self._ctl = Controller()
        self.ctrl_key = Key.ctrl
        shift_l = getattr(Key, "shift_l", getattr(Key, "shift", None))
        shift_r = getattr(Key, "shift_r", getattr(Key, "shift", None))
        self._special = {
            "\t": Key.tab, "\n": Key.enter, TAB: Key.tab, ENTER: Key.enter,
            BACKSPACE: Key.backspace, SHIFT_L: shift_l, SHIFT_R: shift_r,
            UP: Key.up, DOWN: Key.down, LEFT: Key.left, RIGHT: Key.right,
            HOME: Key.home, END_KEY: Key.end, DELETE_KEY: Key.delete,
        }

    def resolve(self, key: str):
        return self._special.get(key, key)

    def press(self, key):
        self._ctl.press(key)

    def release(self, key):
        self._ctl.release(key)

    def hotkey(self, *keys):
        """Press a short modifier chord, used by editor feedback only."""
        resolved = [self.resolve(key) for key in keys]
        for key in resolved:
            self._ctl.press(key)
        for key in reversed(resolved):
            self._ctl.release(key)


class ClipboardBridge:
    """Small optional cross-platform clipboard adapter.

    Reading the focused editor through Ctrl+A/C is more reliable than OCR for
    source code: OCR routinely confuses punctuation, indentation, and quoted
    strings. The adapter uses pyperclip when available and otherwise tries the
    standard clipboard command for the current desktop. It is deliberately
    optional; the typer still works when no clipboard backend is installed.
    """

    def __init__(self):
        self._pyperclip = None
        try:
            import pyperclip
            self._pyperclip = pyperclip
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        if self._pyperclip is not None:
            return True
        if sys.platform == "darwin":
            return shutil.which("pbpaste") is not None and shutil.which("pbcopy") is not None
        if sys.platform.startswith("win"):
            return True  # PowerShell is present on supported Windows installs.
        return any(shutil.which(cmd) for cmd in ("wl-paste", "wl-copy", "xclip", "xsel"))

    def paste(self) -> Optional[str]:
        if self._pyperclip is not None:
            try:
                return self._pyperclip.paste()
            except Exception:
                pass

        if sys.platform == "darwin" and shutil.which("pbpaste"):
            try:
                return subprocess.run(["pbpaste"], check=True, stdout=subprocess.PIPE).stdout.decode()
            except Exception:
                return None
        if sys.platform.startswith("win"):
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                return result.stdout.decode(errors="replace")
            except Exception:
                return None
        for cmd in (("wl-paste", "--no-newline"), ("xclip", "-selection", "clipboard", "-o"),
                    ("xsel", "--clipboard", "--output")):
            if shutil.which(cmd[0]):
                try:
                    return subprocess.run(list(cmd), check=True, stdout=subprocess.PIPE).stdout.decode()
                except Exception:
                    continue
        return None

    def copy(self, text: str) -> bool:
        if self._pyperclip is not None:
            try:
                self._pyperclip.copy(text)
                return True
            except Exception:
                pass

        data = text.encode()
        if sys.platform == "darwin" and shutil.which("pbcopy"):
            command = ["pbcopy"]
        elif sys.platform.startswith("win"):
            command = ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"]
        else:
            command = None
            for candidate in (("wl-copy",), ("xclip", "-selection", "clipboard"),
                              ("xsel", "--clipboard", "--input")):
                if shutil.which(candidate[0]):
                    command = list(candidate)
                    break
        if command is None:
            return False
        try:
            subprocess.run(command, input=data, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False


class FocusedEditorFeedback:
    """Read and, only when necessary, repair the focused editor document.

    This is a feedback safety net for real applications whose auto-indent
    rules differ from the selected policy. It uses the editor's own text
    selection and clipboard rather than attempting unreliable screenshot OCR.
    """

    def __init__(self, keyboard: KeyboardOutput):
        self.keyboard = keyboard
        self.clipboard = ClipboardBridge()

    @staticmethod
    def _normalise(text: str) -> str:
        return text.replace("\\r\\n", "\\n").replace("\\r", "\\n")

    def _copy_focused_document(self) -> Optional[str]:
        if not self.clipboard.available:
            return None
        self.keyboard.hotkey(self.keyboard.ctrl_key, "a")
        time.sleep(0.12)
        self.keyboard.hotkey(self.keyboard.ctrl_key, "c")
        # Clipboard managers and remote desktop sessions can publish Ctrl+C
        # asynchronously, so give them a short window to update.
        deadline = time.monotonic() + 0.45
        value = self.clipboard.paste()
        while value is None and time.monotonic() < deadline:
            time.sleep(0.03)
            value = self.clipboard.paste()
        return value

    def verify_or_repair(self, target: str) -> str:
        """Return verified, repaired, unavailable, or failed.

        The user's existing clipboard is restored after the check whenever
        the platform backend permits it. Repair is a last resort: it selects
        the focused document and pastes the exact requested source, so a
        misbehaving editor cannot leave a missing declaration or a fragment
        appended after ``end.``.
        """
        if not self.clipboard.available:
            return "unavailable"
        saved_clipboard = self.clipboard.paste()
        actual = self._copy_focused_document()
        if actual is None:
            return "unavailable"
        if self._normalise(actual) == self._normalise(target):
            if saved_clipboard is not None:
                self.clipboard.copy(saved_clipboard)
            return "verified"

        if not self.clipboard.copy(target):
            return "failed"
        self.keyboard.hotkey(self.keyboard.ctrl_key, "a")
        time.sleep(0.08)
        self.keyboard.hotkey(self.keyboard.ctrl_key, "v")
        time.sleep(0.20)
        repaired = self._copy_focused_document()
        ok = repaired is not None and self._normalise(repaired) == self._normalise(target)
        if saved_clipboard is not None:
            self.clipboard.copy(saved_clipboard)
        return "repaired" if ok else "failed"


@dataclass(frozen=True)
class PlaybackPolicy:
    stall_threshold: float = 0.25
    resync_on_stall: bool = True


def sleep_until(deadline: float, stop_event: threading.Event, clock=time.monotonic, poll: float = 0.015) -> bool:
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return not stop_event.is_set()
        if stop_event.wait(min(remaining, poll)):
            return False


class TracePlayer:
    def __init__(self, keyboard, stop_event: threading.Event, policy: Optional[PlaybackPolicy] = None,
                 clock=time.monotonic, on_line=None):
        self.keyboard = keyboard
        self.stop_event = stop_event
        self.policy = policy or PlaybackPolicy()
        self.clock = clock
        self.on_line = on_line

    def play(self, events: List[Event]) -> bool:
        policy = self.policy
        t0 = self.clock()
        held = []
        current_line = -1
        try:
            for tr in events_to_transitions(events):
                if self.stop_event.is_set():
                    return False

                if tr.down and policy.resync_on_stall:
                    lag = self.clock() - (t0 + tr.at)
                    if lag > policy.stall_threshold:
                        t0 += lag

                if not sleep_until(t0 + tr.at, self.stop_event, self.clock):
                    return False

                key = self.keyboard.resolve(tr.key)
                if tr.down:
                    if tr.line != current_line:
                        current_line = tr.line
                        if self.on_line:
                            self.on_line(current_line)
                    self.keyboard.press(key)
                    held.append(key)
                else:
                    self.keyboard.release(key)
                    if key in held:
                        held.remove(key)
            return True
        finally:
            for key in reversed(held):
                self.keyboard.release(key)


# =============================================================================
# 10. UPDATE CHECKING & SELF-UPDATING (SILENT, NON-BLOCKING, NEVER FORCED)
# =============================================================================
#
# The published artefact is the *Windows executable* built by GitHub Actions
# and attached to the latest GitHub release, so updating never means copying a
# Python script around by hand. Three behaviours are guaranteed:
#
#   * Checking is silent: nothing is reported unless the published version is
#     genuinely newer, and a failed check never blocks or bothers the user.
#   * Updating is optional: the user always keeps the choice of installing the
#     new build, saving it next to their other downloads, or doing nothing.
#   * Installing is safe: the replacement happens after the running process
#     exits (Windows keeps the .exe locked while it runs), a .old backup of the
#     previous executable is left behind, and a download that is not a real
#     Windows executable is rejected before anything is touched.

_VERSION_DECLARATION = re.compile(
    r'^[ \t]*APP_VERSION[ \t]*=[ \t]*["\']([0-9A-Za-z._+-]+)["\']', re.MULTILINE
)


class DownloadError(RuntimeError):
    """Raised when a release asset could not be downloaded or verified."""


def _numeric_prefix(part: str) -> Optional[int]:
    digits = ""
    for ch in part:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else None


def parse_version(version) -> Optional[Tuple[int, ...]]:
    """Parse a dotted version string into a comparable integer tuple.

    Tolerates a leading "v", surrounding whitespace, and trailing junk on a
    component ("2.0.0rc1" parses as (2, 0, 0)). Returns None when the string
    does not start with a number, so malformed data can never look "newer".
    """
    if not isinstance(version, str):
        return None
    text = version.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    numbers: List[int] = []
    for part in text.split("."):
        value = _numeric_prefix(part)
        if value is None:
            if numbers:
                break  # trailing junk such as "-beta" on the last component
            return None
        numbers.append(value)
    return tuple(numbers) if numbers else None


def is_newer_version(candidate: str, current: str) -> bool:
    """True only when `candidate` is strictly newer than `current`.

    Any unparsable input yields False: a garbled response must never
    produce an "update available" notification.
    """
    remote = parse_version(candidate)
    local = parse_version(current)
    if remote is None or local is None:
        return False
    return remote > local


def update_to_announce(latest: Optional[str], current: str = APP_VERSION) -> Optional[str]:
    """Return the version string to announce to the user, or None.

    None (and therefore silence) is returned when there is no information,
    when the published version cannot be parsed, or when it is not newer
    than the running version. This is the single decision point that keeps
    the automatic check quiet unless an update genuinely exists.
    """
    if latest is None or not is_newer_version(latest, current):
        return None
    return latest


def extract_version_from_source(source: str) -> Optional[str]:
    """Return the APP_VERSION declared in a copy of this module's source."""
    if not source:
        return None
    match = _VERSION_DECLARATION.search(source)
    return match.group(1) if match else None


_VERSION_IN_TEXT = re.compile(r"v?\d+(?:\.\d+)+")


def version_from_tag(text) -> Optional[str]:
    """Pull a version out of a release tag or title ("v1.2.3" -> "1.2.3").

    Unlike `extract_version_from_source`, which looks for an
    ``APP_VERSION = "..."`` declaration, this accepts the bare version strings
    GitHub tags use, and still refuses anything unparsable.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_IN_TEXT.search(text)
    if match is None:
        return None
    candidate = match.group(0).lstrip("vV")
    return candidate if parse_version(candidate) is not None else None


@dataclass(frozen=True)
class UpdateAsset:
    """One downloadable file attached to a GitHub release."""

    name: str
    url: str
    size: int = 0

    @property
    def is_windows_executable(self) -> bool:
        return self.name.lower().endswith(".exe")


@dataclass(frozen=True)
class ReleaseInfo:
    """A published GitHub release: its version and downloadable assets."""

    version: Optional[str] = None
    assets: Tuple[UpdateAsset, ...] = ()
    page_url: str = RELEASES_PAGE_URL

    @property
    def exe_asset(self) -> Optional[UpdateAsset]:
        """The Windows executable to download, if the release carries one."""
        return select_exe_asset(self.assets)


def select_exe_asset(assets, preferred_name: str = EXE_ASSET_NAME) -> Optional[UpdateAsset]:
    """Pick the Windows executable to download from a release's assets.

    The canonical `AutoTyper.exe` wins; otherwise the alphabetically first
    other .exe is used, so a renamed asset never silently disables updates.
    Returns None when the release carries no .exe at all (for example a
    source-only tag), in which case callers fall back to the release page.
    """
    executables = [asset for asset in assets if getattr(asset, "is_windows_executable", False)]
    if not executables:
        return None
    for asset in executables:
        if asset.name.lower() == preferred_name.lower():
            return asset
    return sorted(executables, key=lambda asset: asset.name.lower())[0]


def _coerce_asset(raw) -> Optional[UpdateAsset]:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    url = raw.get("browser_download_url") or raw.get("url")
    if not isinstance(name, str) or not isinstance(url, str):
        return None
    size = raw.get("size")
    return UpdateAsset(name=name, url=url, size=int(size) if isinstance(size, int) else 0)


def parse_release_payload(payload) -> Optional[ReleaseInfo]:
    """Turn a GitHub `releases/latest` payload into a ReleaseInfo.

    Accepts either an already-decoded mapping or the raw JSON text. Returns
    None for anything that does not carry a parsable version, so a malformed
    or error payload can never masquerade as an available update.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            # Not JSON at all: fall back to scanning raw text for a version,
            # which keeps older/garbled responses informative but harmless.
            version = extract_version_from_source(payload)
            return ReleaseInfo(version=version) if version else None
    if not isinstance(payload, dict):
        return None
    version = version_from_tag(payload.get("tag_name"))
    if version is None:
        version = version_from_tag(payload.get("name"))
    raw_assets = payload.get("assets")
    assets = tuple(
        asset for asset in (_coerce_asset(raw) for raw in raw_assets) if asset is not None
    ) if isinstance(raw_assets, list) else ()
    if version is None and not assets:
        return None
    return ReleaseInfo(
        version=version,
        assets=assets,
        page_url=str(payload.get("html_url") or RELEASES_PAGE_URL),
    )


class UpdateChecker:
    """Best-effort reader of the latest published GitHub release.

    Contract relied on by the GUI:
      * Returns a ReleaseInfo, or None.
      * None means "no information" (offline, HTTP error, timeout, or a
        payload without a parsable version). Callers must treat None as
        "say nothing" -- never as "update available" or "up to date".
      * The version may be present without an .exe asset (an older tag, or a
        build that has not finished uploading); callers then fall back to the
        release page instead of a download.
    """

    def __init__(self, source_url: str = UPDATE_SOURCE_URL,
                 releases_url: str = RELEASES_API_URL,
                 timeout: float = UPDATE_CHECK_TIMEOUT,
                 opener=None):
        self.source_url = source_url
        self.releases_url = releases_url
        self.timeout = timeout
        # Kept as a plain attribute and resolved at call time so tests (and
        # future transports) can swap urllib.request.urlopen out from under us.
        self._opener = opener

    def _read(self, url: str, accept: str, limit: int = 1 << 20) -> Optional[str]:
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": accept},
            )
            open_fn = self._opener or urllib.request.urlopen
            with open_fn(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    return None
                return response.read(limit).decode("utf-8", errors="replace")
        except Exception:
            # Best effort by design: any failure simply means "no information".
            return None

    def fetch_latest_release(self) -> Optional[ReleaseInfo]:
        """Fetch the latest release, falling back to the published source.

        The releases API knows about the .exe asset; the raw source file is
        only used to answer "is there a newer version?" when the API cannot be
        reached, and yields a ReleaseInfo without assets in that case.
        """
        payload = self._read(self.releases_url, "application/vnd.github+json")
        if payload is not None:
            release = parse_release_payload(payload)
            if release is not None and release.version is not None:
                return release
        source = self._read(self.source_url, "text/plain")
        if source is None:
            return None
        version = extract_version_from_source(source)
        return ReleaseInfo(version=version) if version else None

    def fetch_latest_version(self) -> Optional[str]:
        """The published version, or None when it cannot be determined."""
        release = self.fetch_latest_release()
        return release.version if release is not None else None


# -----------------------------------------------------------------------------
# Downloading, verifying and installing the published .exe
# -----------------------------------------------------------------------------

def is_frozen() -> bool:
    """True when running as a packaged executable (PyInstaller and friends)."""
    return bool(getattr(sys, "frozen", False))


def running_executable() -> Optional[Path]:
    """Path of the packaged executable, or None when running from source."""
    if not is_frozen():
        return None
    executable = getattr(sys, "executable", None)
    return Path(executable) if executable else None


def default_download_dir() -> Path:
    """Where a .exe is saved when it cannot replace the running program."""
    for candidate in (Path.home() / "Downloads", Path.home()):
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return Path.cwd()


def sanitise_asset_filename(name: str, default: str = EXE_ASSET_NAME) -> str:
    """Reduce a release asset name to a safe local file name.

    Any directory part is discarded and everything outside a small safe
    alphabet is replaced, so a hostile asset name can never escape the folder
    the download was aimed at.
    """
    leaf = re.split(r"[\\/]+", str(name or ""))[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._-")
    if not cleaned:
        return default
    if not cleaned.lower().endswith(".exe"):
        cleaned += ".exe"
    return cleaned


def looks_like_windows_executable(path: Path) -> bool:
    """Reject HTML error pages, truncated files and zero-byte downloads."""
    try:
        with Path(path).open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def download_file(url: str, destination: Path, *, timeout: float = DOWNLOAD_TIMEOUT,
                  progress=None, opener=None) -> Path:
    """Download `url` to `destination` atomically and verify it looks real.

    The payload is written to a temporary ".part" file and only moved into
    place once the transfer finished *and* the file starts with the Windows
    "MZ" header, so a failed or garbled download can never overwrite a good
    executable. `progress(bytes_done, total_bytes_or_zero)` is called as the
    transfer advances (total is 0 when the server sends no length).
    """
    destination = Path(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise DownloadError(f"Could not create {destination.parent}: {err}") from err
    partial = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
    )
    open_fn = opener or urllib.request.urlopen
    written = 0
    try:
        with open_fn(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise DownloadError(f"The server returned HTTP {status}.")
            headers = getattr(response, "headers", None)
            total = 0
            if headers is not None:
                try:
                    total = int(headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    if written + len(chunk) > MAX_DOWNLOAD_BYTES:
                        raise DownloadError(
                            "The download exceeded the expected size and was stopped.")
                    handle.write(chunk)
                    written += len(chunk)
                    if progress is not None:
                        try:
                            progress(written, total)
                        except Exception:
                            pass  # a progress-reporting bug must not abort the download
    except DownloadError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as err:
        partial.unlink(missing_ok=True)
        raise DownloadError(str(err) or err.__class__.__name__) from err

    if written == 0:
        partial.unlink(missing_ok=True)
        raise DownloadError("The downloaded file was empty.")
    if not looks_like_windows_executable(partial):
        partial.unlink(missing_ok=True)
        raise DownloadError("The downloaded file is not a Windows executable.")
    try:
        os.replace(partial, destination)
    except OSError:
        # Cross-device or locked destination: fall back to a plain copy.
        try:
            shutil.copyfile(partial, destination)
            partial.unlink(missing_ok=True)
        except OSError as err:
            partial.unlink(missing_ok=True)
            raise DownloadError(f"Could not save {destination}: {err}") from err
    return destination


@dataclass(frozen=True)
class UpdatePlan:
    """How the downloaded release should be applied on this machine."""

    kind: str  # "self_update" | "download" | "open_page"
    asset: Optional[UpdateAsset] = None
    version: Optional[str] = None
    destination: Optional[Path] = None       # where the .exe is downloaded to
    install_target: Optional[Path] = None    # the build it will replace, if any
    reason: str = ""


def staging_path(asset: UpdateAsset, staging_dir: Optional[Path] = None) -> Path:
    """Where a self-update is downloaded before it replaces the running build.

    Windows locks a running executable, so the new file is *never* written
    straight over the program that is executing: it is staged in the temp
    folder and swapped in later by a detached script, once this process is gone.
    """
    directory = Path(staging_dir) if staging_dir is not None \
        else Path(tempfile.gettempdir()) / f"{APP_NAME}-update"
    return directory / sanitise_asset_filename(asset.name)


def plan_update(*, frozen: bool, asset: Optional[UpdateAsset],
                target: Optional[Path] = None,
                fallback_dir: Optional[Path] = None,
                staging_dir: Optional[Path] = None,
                version: Optional[str] = None) -> UpdatePlan:
    """Decide what a downloaded release can actually do here.

    * packaged build  -> "self_update": stage the new .exe, then replace the
      running one and restart.
    * running from source -> "download": save the .exe where the user can find
      it (a script cannot meaningfully replace itself with an executable).
    * no .exe published -> "open_page": send the user to the release page.
    """
    if asset is None:
        return UpdatePlan(kind="open_page", version=version,
                          reason="This release has no AutoTyper.exe attached yet.")
    if frozen and target is not None:
        return UpdatePlan(kind="self_update", asset=asset, version=version,
                          destination=staging_path(asset, staging_dir),
                          install_target=Path(target))
    directory = Path(fallback_dir) if fallback_dir is not None else default_download_dir()
    return UpdatePlan(kind="download", asset=asset, version=version,
                      destination=directory / sanitise_asset_filename(asset.name),
                      reason="Running from source: the .exe is saved for you to run.")


def _bat_quote(path) -> str:
    """Quote a path for a `set "VAR=value"` line in a .bat script."""
    return str(path).replace('"', "")


def build_windows_swap_script(new_exe, target_exe, wait_seconds: int = 120,
                              backup: bool = True) -> str:
    """A detached .bat that swaps in the new .exe once this process exits.

    Windows locks a running executable, so the copy is retried once a second
    until it succeeds (or `wait_seconds` elapse); `copy` failing while the old
    build is still alive is expected and simply loops. The previous executable
    is kept as "<name>.old" so a bad build can always be rolled back.
    """
    new_path = _bat_quote(new_exe)
    target_path = _bat_quote(target_exe)
    backup_lines = f'copy /Y "%TARGET%" "%TARGET%.old" >nul 2>&1\n' if backup else ""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "NEW={new_path}"\r\n'
        f'set "TARGET={target_path}"\r\n'
        f'set "TRIES={max(1, int(wait_seconds))}"\r\n'
        "set /a COUNT=0\r\n"
        ":waitloop\r\n"
        'copy /Y "%NEW%" "%TARGET%" >nul 2>&1\r\n'
        "if not errorlevel 1 goto installed\r\n"
        "set /a COUNT+=1\r\n"
        "if %COUNT% GEQ %TRIES% goto giveup\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto waitloop\r\n"
        ":installed\r\n"
        f"{backup_lines}"
        'del "%NEW%" >nul 2>&1\r\n'
        'start "" "%TARGET%"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
        ":giveup\r\n"
        "exit /b 1\r\n"
    )


def build_posix_swap_script(new_exe, target_exe, pid: int = 0) -> str:
    """A detached shell script that swaps in the new build after the app exits.

    Kept for completeness (development builds on Linux/macOS); the packaged
    application is Windows-only.
    """
    return (
        "#!/bin/sh\n"
        f'NEW="{new_exe}"\n'
        f'TARGET="{target_exe}"\n'
        f"PID={int(pid)}\n"
        "i=0\n"
        'while kill -0 "$PID" 2>/dev/null; do\n'
        "  i=$((i+1))\n"
        '  [ "$i" -ge 120 ] && break\n'
        "  sleep 1\n"
        "done\n"
        'cp -f "$TARGET" "$TARGET.old" 2>/dev/null\n'
        'mv -f "$NEW" "$TARGET" 2>/dev/null && chmod +x "$TARGET"\n'
        'nohup "$TARGET" >/dev/null 2>&1 &\n'
        'rm -f "$0"\n'
    )


def build_swap_script(new_exe, target_exe, pid: int = 0, *, windows: bool = None,
                      wait_seconds: int = 120) -> str:
    """Return the platform-appropriate swap script text."""
    on_windows = (os.name == "nt") if windows is None else windows
    if on_windows:
        return build_windows_swap_script(new_exe, target_exe, wait_seconds=wait_seconds)
    return build_posix_swap_script(new_exe, target_exe, pid)


def launch_swap_script(script_path: Path, *, windows: bool = None) -> None:
    """Run the swap script detached, so it survives this process exiting."""
    on_windows = (os.name == "nt") if windows is None else windows
    if on_windows:
        creationflags = 0
        for flag in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= getattr(subprocess, flag, 0)
        subprocess.Popen(["cmd", "/c", str(script_path)], close_fds=True,
                         creationflags=creationflags)
    else:
        subprocess.Popen(["/bin/sh", str(script_path)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_update_and_restart(new_exe, target_exe=None, *, windows: bool = None,
                               temp_dir: Optional[Path] = None, pid: Optional[int] = None) -> Path:
    """Arrange for `new_exe` to replace the running program and start it again.

    Returns the path of the swap script. The caller is expected to quit the
    application immediately afterwards: the script waits for this process to
    exit before touching the executable.
    """
    on_windows = (os.name == "nt") if windows is None else windows
    new_exe = Path(new_exe)
    target_exe = Path(target_exe) if target_exe is not None else running_executable()
    if target_exe is None:
        raise DownloadError("Cannot self-update: the running program is not a packaged executable.")
    if not new_exe.is_file():
        raise DownloadError(f"The downloaded update disappeared: {new_exe}")
    stage = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    try:
        stage.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise DownloadError(f"Could not prepare {stage}: {err}") from err
    suffix = ".bat" if on_windows else ".sh"
    script_path = stage / f"{APP_NAME}-update{suffix}"
    process_id = int(pid if pid is not None else os.getpid())
    script_path.write_text(
        build_swap_script(new_exe, target_exe, process_id, windows=on_windows),
        encoding="utf-8",
    )
    if not on_windows:
        try:
            script_path.chmod(0o755)
        except OSError:
            pass
    launch_swap_script(script_path, windows=on_windows)
    return script_path


def open_in_file_manager(path) -> bool:
    """Reveal `path` in the desktop's file browser; best effort."""
    path = Path(path)
    try:
        if os.name == "nt":
            if path.is_dir():
                os.startfile(str(path))  # noqa: S606 - Windows shell open
            else:
                subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])
        return True
    except Exception:
        return False


def release_to_announce(release: Optional[ReleaseInfo],
                        current: str = APP_VERSION) -> Optional[ReleaseInfo]:
    """The silent-check decision point for a whole release object."""
    if release is None or update_to_announce(release.version, current) is None:
        return None
    return release


# =============================================================================
# 11. GRAPHICAL INTERFACE
# =============================================================================

PALETTE_DEFINITIONS = {
    "Trust Corporate": ("#1E3A8A", "#3B82F6", "#F8FAFC"),
    "Fresh Mint": ("#065F46", "#10B981", "#F0FDF4"),
    "Soft Lavender": ("#5B21B6", "#8B5CF6", "#FAFAFE"),
    "Sunset Glow": ("#9A3412", "#F97316", "#FFF7ED"),
    "Berry Modern": ("#9D174D", "#EC4899", "#FDF2F8"),
    "Sage Wellness": ("#2D3A34", "#4CAF50", "#F4F7F5"),
    "Ocean Breeze": ("#0369A1", "#0EA5E9", "#F0F9FF"),
    "Luxury Gold": ("#1E1B4B", "#D97706", "#FAFAF9"),
    "Playful Bubblegum": ("#4338CA", "#F472B6", "#F8FAFC"),
    "Cyberpunk Neon": ("#0F172A", "#06B6D4", "#0B0F19"),
    "Midnight Amethyst": ("#1E1B4B", "#A855F7", "#090514"),
    "Emerald Dark": ("#064E3B", "#34D399", "#022C22"),
    "Dark Chocolate & Orange": ("#1C1917", "#F97316", "#0C0A09"),
    "Deep Space Blue": ("#1E293B", "#38BDF8", "#0F172A"),
    "Charcoal Crimson": ("#1F2937", "#EF4444", "#111827"),
    "Electric Purple": ("#311042", "#BB86FC", "#121212"),
    "Sleek Obsidian": ("#111111", "#FFFFFF", "#000000"),
    "Nord Winter": ("#2E3440", "#88C0D0", "#1E222A"),
    "Cosmic Indigo": ("#2D1B4E", "#818CF8", "#0D0B14"),
}


def _colour_is_dark(colour: str) -> bool:
    """Return whether a hex colour needs a light foreground.

    Anything that is not a usable colour is treated as light, so a hand-edited
    settings file can never make text unreadable.
    """
    rgb = hex_to_rgb(colour)
    if rgb is None:
        return False
    red, green, blue = rgb
    return (0.299 * red + 0.587 * green + 0.114 * blue) < 145


DEFAULT_PALETTE = "Trust Corporate"


def _palette_colours(name: str, definitions: Optional[Dict[str, Tuple[str, str, str]]] = None) -> Dict[str, str]:
    """Derive the full colour role map for a named palette.

    ``definitions`` lets the caller mix user-defined palettes into the lookup
    without touching the built-in table.
    """
    table = PALETTE_DEFINITIONS if definitions is None else definitions
    primary, accent, background = table[name]
    dark = _colour_is_dark(background)
    return {
        "primary": primary,
        "accent": accent,
        "background": background,
        "foreground": "#F8FAFC" if dark else "#172033",
        # Keep the source editor in the same dark family as the selected
        # palette. A fixed light surface here made source text unreadable in
        # dark themes even though the rest of the UI had changed.
        "surface": background if dark else "#FFFFFF",
        "button_foreground": "#FFFFFF" if _colour_is_dark(primary) else "#111827",
        "accent_foreground": "#FFFFFF" if _colour_is_dark(accent) else "#111827",
        "muted": "#CBD5E1" if dark else "#526176",
    }


# =============================================================================
# 11a. CUSTOM UI COLOURS — MS-PAINT STYLE HEXAGON ("HONEYCOMB") PICKER MODEL
# =============================================================================
#
# Everything in this block is pure data: no Tk objects are touched, so the
# honeycomb geometry, the colour ramps and the saved-palette validation can be
# unit tested headlessly. The Tk widgets further down only render this model.

HEXAGON_RINGS = 5            # rings of swatches around the white centre cell
GREYSCALE_STEPS = 13         # black -> white strip underneath the honeycomb
MAX_CUSTOM_PALETTES = 16     # guard against an unbounded settings file
CUSTOM_PALETTE_ROLES = ("primary", "accent", "background")

# Paint-style gradient field ("Define Custom Colors"): hue runs left to right,
# saturation top to bottom, and the separate bar on its right controls the
# brightness the whole square is painted with.
GRADIENT_COLUMNS = 42        # hue steps across the gradient field
GRADIENT_ROWS = 28           # saturation steps down the gradient field
GRADIENT_CELL = 6            # pixels per gradient cell (42 * 6 = 252 wide)
BRIGHTNESS_STEPS = 24        # cells in the Paint luminosity bar
PAINT_SWATCH_COLUMNS = 12    # "Basic colors" board: four rows of twelve
PAINT_SWATCH_ROWS = 4
SHADE_STEPS = 11             # white -> pure colour -> black, per colour

_HEX_COLOUR_RE = re.compile(r"^#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")

# Axial (q, r) neighbour directions for a pointy-top hexagonal grid.
_AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


@dataclass(frozen=True)
class HexCell:
    """One hexagonal swatch of the honeycomb."""
    q: int
    r: int
    ring: int
    colour: str


def normalise_hex_colour(value) -> Optional[str]:
    """Return ``#RRGGBB`` (upper case) for any accepted hex spelling.

    Accepts ``#abc``, ``abc``, ``#AABBCC`` and ``aabbcc``. Returns None for
    anything that is not a usable colour so callers can reject bad input from
    the hex entry box or from a hand-edited settings file.
    """
    if not isinstance(value, str):
        return None
    match = _HEX_COLOUR_RE.match(value.strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.upper()


def hsv_to_hex(hue: float, saturation: float, value: float) -> str:
    """Convert HSV (each 0..1, hue wrapping) to a ``#RRGGBB`` string."""
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, min(max(saturation, 0.0), 1.0),
                                  min(max(value, 0.0), 1.0))
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def hex_to_rgb(colour: str) -> Optional[Tuple[int, int, int]]:
    """Split a hex colour into its 0-255 red, green and blue channels."""
    normalised = normalise_hex_colour(colour)
    if normalised is None:
        return None
    return (int(normalised[1:3], 16), int(normalised[3:5], 16), int(normalised[5:7], 16))


def rgb_to_hex(red: float, green: float, blue: float) -> str:
    """Build a ``#RRGGBB`` string from 0-255 channels, clamped for safety."""
    channels = []
    for channel in (red, green, blue):
        try:
            value = float(channel)
        except (TypeError, ValueError):
            value = 0.0
        channels.append(int(round(max(0.0, min(255.0, value)))))
    return "#{:02X}{:02X}{:02X}".format(*channels)


def hsv_from_hex(colour: str) -> Optional[Tuple[float, float, float]]:
    """Hue, saturation and brightness (each 0..1) of a hex colour."""
    rgb = hex_to_rgb(colour)
    if rgb is None:
        return None
    return colorsys.rgb_to_hsv(*(channel / 255.0 for channel in rgb))


def format_rgb(colour: str) -> str:
    """Human-readable channel readout, e.g. ``"RGB 30 58 138"``."""
    rgb = hex_to_rgb(colour)
    if rgb is None:
        return "RGB —"
    return "RGB {:3d} {:3d} {:3d}".format(*rgb)


def build_shade_ramp(hue: float, saturation: float, value: float,
                     steps: int = SHADE_STEPS) -> List[str]:
    """Tints and shades of one colour: white → tints → pure → shades → black.

    This is the strip that sits under the gradient field, so a colour can be
    nudged lighter or darker in a single click instead of hunting for the same
    hue on a different part of the square.
    """
    steps = max(3, steps)
    middle = steps // 2
    ramp: List[str] = []
    for index in range(steps):
        if index < middle:
            amount = (middle - index) / middle           # 1.0 = white
            ramp.append(hsv_to_hex(hue,
                                   saturation * (1.0 - amount),
                                   value + (1.0 - value) * amount))
        elif index == middle:
            ramp.append(hsv_to_hex(hue, saturation, value))
        else:
            depth = (index - middle) / (steps - 1 - middle)
            ramp.append(hsv_to_hex(hue, saturation, value * (1.0 - depth)))
    return ramp


def build_brightness_ramp(hue: float, saturation: float,
                          steps: int = BRIGHTNESS_STEPS) -> List[str]:
    """Brightness bar colours, brightest at the top down to black."""
    steps = max(2, steps)
    return [hsv_to_hex(hue, saturation, 1.0 - index / (steps - 1))
            for index in range(steps)]


def build_paint_basic_palette() -> List[str]:
    """The 48-swatch "basic colours" board, laid out like Paint's.

    Four rows of twelve:

    * row 1 — the twelve hues of the colour wheel at full saturation,
    * row 2 — light tints of the same hues (pastels),
    * row 3 — deep shades of the same hues,
    * row 4 — the neutral ramp, white through to black.
    """
    hues = [index / PAINT_SWATCH_COLUMNS for index in range(PAINT_SWATCH_COLUMNS)]
    vivid = [hsv_to_hex(hue, 1.0, 1.0) for hue in hues]
    tints = [hsv_to_hex(hue, 0.32, 1.0) for hue in hues]
    shades = [hsv_to_hex(hue, 0.88, 0.55) for hue in hues]
    neutrals = [hsv_to_hex(0.0, 0.0, 1.0 - index / (PAINT_SWATCH_COLUMNS - 1))
                for index in range(PAINT_SWATCH_COLUMNS)]
    board = vivid + tints + shades + neutrals
    assert len(board) == PAINT_SWATCH_COLUMNS * PAINT_SWATCH_ROWS
    return board


def hexagon_ring_colour(ring: int, rings: int, hue: float) -> str:
    """Colour for a cell on ``ring`` at angular position ``hue`` (0..1).

    Mirrors the Microsoft colour hexagon: white in the middle, progressively
    more saturated tints as you move outwards, and a ring of darker shades
    right on the rim.
    """
    if ring <= 0:
        return "#FFFFFF"
    if ring >= rings:
        return hsv_to_hex(hue, 1.0, 0.56)
    saturation = ring / max(1, rings - 1)
    return hsv_to_hex(hue, saturation, 1.0)


def build_colour_hexagon(rings: int = HEXAGON_RINGS) -> List[HexCell]:
    """Build the honeycomb: one white centre plus ``6 * ring`` cells per ring."""
    cells = [HexCell(0, 0, 0, "#FFFFFF")]
    for ring in range(1, rings + 1):
        # Walk the ring starting from the cell straight "below-left" of centre
        # so that a given angular position keeps the same hue on every ring.
        q = _AXIAL_DIRECTIONS[4][0] * ring
        r = _AXIAL_DIRECTIONS[4][1] * ring
        total = 6 * ring
        index = 0
        for dq, dr in _AXIAL_DIRECTIONS:
            for _ in range(ring):
                cells.append(HexCell(q, r, ring, hexagon_ring_colour(ring, rings, index / total)))
                q += dq
                r += dr
                index += 1
    return cells


def build_greyscale_strip(steps: int = GREYSCALE_STEPS) -> List[str]:
    """Black-to-white hexagon row shown beneath the honeycomb."""
    steps = max(2, steps)
    return [hsv_to_hex(0.0, 0.0, index / (steps - 1)) for index in range(steps)]


def hexagon_centre(q: int, r: int, size: float) -> Tuple[float, float]:
    """Pixel centre of axial cell (q, r) for pointy-top hexagons of ``size``."""
    return (math.sqrt(3.0) * size * (q + r / 2.0), 1.5 * size * r)


def hexagon_points(cx: float, cy: float, size: float) -> List[float]:
    """Flattened polygon coordinates for a pointy-top hexagon."""
    points: List[float] = []
    for corner in range(6):
        angle = math.radians(60.0 * corner - 90.0)
        points.append(cx + size * math.cos(angle))
        points.append(cy + size * math.sin(angle))
    return points


def sanitise_custom_palettes(raw) -> Dict[str, Tuple[str, str, str]]:
    """Validate user-saved palettes loaded from the settings file.

    Anything malformed (bad colour, wrong shape, clashing with a built-in
    name) is dropped silently: a corrupted settings file must never stop the
    typer from starting.
    """
    result: Dict[str, Tuple[str, str, str]] = {}
    if not isinstance(raw, dict):
        return result
    for name, value in raw.items():
        if not isinstance(name, str):
            continue
        clean = name.strip()
        if not clean or clean in PALETTE_DEFINITIONS or clean in result:
            continue
        if isinstance(value, (list, tuple)) and len(value) == 3:
            parts = [normalise_hex_colour(item) for item in value]
        elif isinstance(value, dict):
            parts = [normalise_hex_colour(value.get(role)) for role in CUSTOM_PALETTE_ROLES]
        else:
            continue
        if any(part is None for part in parts):
            continue
        result[clean] = (parts[0], parts[1], parts[2])
        if len(result) >= MAX_CUSTOM_PALETTES:
            break
    return result


def merged_palettes(custom: Optional[Dict[str, Tuple[str, str, str]]] = None
                    ) -> Dict[str, Tuple[str, str, str]]:
    """Built-in palettes first, then the user's saved custom colours."""
    table: Dict[str, Tuple[str, str, str]] = dict(PALETTE_DEFINITIONS)
    for name, triple in (custom or {}).items():
        if name in PALETTE_DEFINITIONS:
            continue
        table[name] = triple
    return table


def unique_palette_name(name: str, existing) -> str:
    """Return ``name`` or ``name 2``/``name 3``... so saves never overwrite."""
    taken = set(existing or ())
    base = (name or "").strip() or "My Colours"
    if base not in taken:
        return base
    index = 2
    while f"{base} {index}" in taken:
        index += 1
    return f"{base} {index}"


MODE_LABELS = {
    "Net (incl. pauses & fixes)": "net",
    "Gross (keystroke rate)": "gross",
}

INDENT_LABELS = {
    "Off (type text as-is)": "off",
    "Copy previous line's indentation": "copy",
    "Smart (Pascal-aware block indent)": "smart",
    "Fixed width (use box below)": "fixed",
}


@dataclass(frozen=True)
class RunConfig:
    wpm: int
    mode: str
    typo_rate: float
    countdown: int
    indent: IndentPolicy
    coding_mode: bool
    verify_editor: bool
    seed: Optional[int]
    playback: PlaybackPolicy = PlaybackPolicy()


_TkBase = tk.Tk if tk is not None else object
_TkFrame = tk.Frame if tk is not None else object
_TkToplevel = tk.Toplevel if tk is not None else object


class ColourHexagonPicker(_TkFrame):
    """The Microsoft Paint / Office style colour hexagon.

    A honeycomb of hexagonal swatches (white in the middle, tints fanning out
    by hue, dark shades on the rim) plus a black-to-white hexagon strip below
    it. This is deliberately *not* the gradient/"Define Custom Colors" square:
    every colour is a discrete hexagon you click.
    """

    def __init__(self, master, *, rings: int = HEXAGON_RINGS, cell_size: int = 13,
                 on_pick=None, background: str = "#FFFFFF",
                 outline: str = "#8C96A8", highlight: str = "#111827", **kwargs):
        super().__init__(master, bg=background, **kwargs)
        self.rings = rings
        self.cell_size = cell_size
        self._on_pick = on_pick
        self._outline = outline
        self._highlight = highlight
        self._item_colour: Dict[int, str] = {}
        self._colour_items: Dict[str, List[int]] = {}
        self._selected_item: Optional[int] = None
        self.selected_colour: Optional[str] = None

        cells = build_colour_hexagon(rings)
        centres = [(cell, hexagon_centre(cell.q, cell.r, cell_size)) for cell in cells]
        xs = [point[0] for _, point in centres]
        ys = [point[1] for _, point in centres]
        pad = cell_size * 0.9
        offset_x = pad + cell_size - min(xs)
        offset_y = pad + cell_size - min(ys)
        width = (max(xs) - min(xs)) + 2 * cell_size + 2 * pad
        honeycomb_bottom = offset_y + max(ys) + cell_size

        strip = build_greyscale_strip()
        strip_step = math.sqrt(3.0) * cell_size
        strip_y = honeycomb_bottom + cell_size * 1.45
        strip_width = strip_step * len(strip)
        height = strip_y + cell_size + pad

        self.canvas = tk.Canvas(self, width=round(max(width, strip_width + 2 * pad)),
                                height=round(height), bg=background,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        for cell, (cx, cy) in centres:
            self._add_cell(cx + offset_x, cy + offset_y, cell.colour)

        strip_x = (max(width, strip_width + 2 * pad) - strip_width) / 2.0 + strip_step / 2.0
        for index, colour in enumerate(strip):
            self._add_cell(strip_x + index * strip_step, strip_y, colour)

    # -- construction helpers -----------------------------------------
    def _add_cell(self, cx: float, cy: float, colour: str):
        item = self.canvas.create_polygon(
            hexagon_points(cx, cy, self.cell_size),
            fill=colour, outline=self._outline, width=1, joinstyle="miter")
        self._item_colour[item] = colour
        self._colour_items.setdefault(colour, []).append(item)
        self.canvas.tag_bind(item, "<Button-1>", lambda event, i=item: self._clicked(i))
        self.canvas.tag_bind(item, "<Enter>",
                             lambda event, i=item: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind(item, "<Leave>",
                             lambda event: self.canvas.configure(cursor=""))

    # -- interaction ---------------------------------------------------
    def _clicked(self, item: int):
        colour = self._item_colour.get(item)
        if colour is None:
            return
        self._highlight_item(item)
        self.selected_colour = colour
        if self._on_pick is not None:
            self._on_pick(colour)

    def _highlight_item(self, item: Optional[int]):
        if self._selected_item is not None:
            try:
                self.canvas.itemconfigure(self._selected_item, outline=self._outline, width=1)
            except tk.TclError:
                pass
        self._selected_item = item
        if item is not None:
            try:
                self.canvas.itemconfigure(item, outline=self._highlight, width=3)
                self.canvas.tag_raise(item)
            except tk.TclError:
                pass

    def set_selected(self, colour: Optional[str]):
        """Highlight the hexagon holding ``colour`` (no callback fired)."""
        normalised = normalise_hex_colour(colour) if colour else None
        self.selected_colour = normalised
        items = self._colour_items.get(normalised or "", [])
        self._highlight_item(items[0] if items else None)

    def swatch_colours(self) -> List[str]:
        """Every colour offered by the honeycomb, in drawing order."""
        return [self._item_colour[item] for item in sorted(self._item_colour)]


class ColourShadeStrip(_TkFrame):
    """A tints-and-shades ramp for one colour: white → pure → black.

    Sits under the gradient field and lets a colour be nudged lighter or
    darker with a single click, without having to find the same hue again on a
    different row of the square.
    """

    def __init__(self, master, *, on_pick=None, steps: int = SHADE_STEPS,
                 swatch: Tuple[int, int] = (24, 20), gap: int = 2,
                 background: str = "#FFFFFF", outline: str = "#8C96A8",
                 highlight: str = "#111827", **kwargs):
        super().__init__(master, bg=background, **kwargs)
        self._on_pick = on_pick
        self.steps = max(3, steps)
        self._swatch_w, self._swatch_h = swatch
        self._gap = gap
        self._outline = outline
        self._highlight = highlight
        self._colours: List[str] = []
        self._item_colour: Dict[int, str] = {}
        self._colour_items: Dict[str, List[int]] = {}
        self._selected_item: Optional[int] = None
        self.selected_colour: Optional[str] = None

        width = self.steps * (self._swatch_w + self._gap) - self._gap
        self.canvas = tk.Canvas(self, width=width, height=self._swatch_h,
                                bg=background, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.set_base_colour("#3B82F6")

    # -- model ---------------------------------------------------------
    def set_base_colour(self, colour: str):
        """Rebuild the ramp around ``colour`` (no callback fired)."""
        hsv = hsv_from_hex(colour)
        if hsv is None:
            hsv = (0.58, 0.85, 0.9)
        self._colours = build_shade_ramp(*hsv, steps=self.steps)
        self._draw_ramp()

    def swatch_colours(self) -> List[str]:
        """Every colour on the ramp, lightest first."""
        return list(self._colours)

    def _draw_ramp(self):
        try:
            self.canvas.delete("all")
        except tk.TclError:
            return
        self._item_colour = {}
        self._colour_items = {}
        self._selected_item = None
        for index, colour in enumerate(self._colours):
            x0 = index * (self._swatch_w + self._gap)
            item = self.canvas.create_rectangle(
                x0, 0, x0 + self._swatch_w, self._swatch_h,
                fill=colour, outline=self._outline, width=1)
            self._item_colour[item] = colour
            self._colour_items.setdefault(colour, []).append(item)
            self.canvas.tag_bind(item, "<Button-1>", lambda event, i=item: self._clicked(i))
            self.canvas.tag_bind(item, "<Enter>",
                                 lambda event: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind(item, "<Leave>",
                                 lambda event: self.canvas.configure(cursor=""))
        self.set_selected(self.selected_colour)

    # -- interaction ---------------------------------------------------
    def _clicked(self, item: int):
        colour = self._item_colour.get(item)
        if colour is None:
            return
        self.selected_colour = colour
        self._highlight_item(item)
        if self._on_pick is not None:
            self._on_pick(colour)

    def _highlight_item(self, item: Optional[int]):
        if self._selected_item is not None:
            try:
                self.canvas.itemconfigure(self._selected_item,
                                          outline=self._outline, width=1)
            except tk.TclError:
                pass
        self._selected_item = item
        if item is not None:
            try:
                self.canvas.itemconfigure(item, outline=self._highlight, width=3)
                self.canvas.tag_raise(item)
            except tk.TclError:
                pass

    def set_selected(self, colour: Optional[str]):
        """Outline the swatch holding ``colour`` (no callback fired)."""
        normalised = normalise_hex_colour(colour) if colour else None
        self.selected_colour = normalised
        items = self._colour_items.get(normalised or "", [])
        self._highlight_item(items[0] if items else None)


class ColourSwatchBoard(_TkFrame):
    """Paint's "basic colours" board: four rows of twelve clickable swatches.

    Row 1 holds the twelve colour-wheel hues at full saturation, row 2 their
    pastel tints, row 3 their deep shades and row 4 the neutral ramp from
    white to black — the quick, chunky starting points of the classic Paint
    dialog, with the gradient field for everything in between.
    """

    def __init__(self, master, *, colours: Optional[List[str]] = None,
                 on_pick=None, columns: int = PAINT_SWATCH_COLUMNS,
                 swatch: Tuple[int, int] = (20, 17), gap: int = 3,
                 background: str = "#FFFFFF", outline: str = "#8C96A8",
                 highlight: str = "#111827", hover: str = "#111827", **kwargs):
        super().__init__(master, bg=background, **kwargs)
        self._on_pick = on_pick
        self.columns = max(1, columns)
        self._swatch_w, self._swatch_h = swatch
        self._gap = gap
        self._outline = outline
        self._highlight = highlight
        self._hover = hover
        self._colours = list(colours) if colours else build_paint_basic_palette()
        self._item_colour: Dict[int, str] = {}
        self._colour_items: Dict[str, List[int]] = {}
        self._items: List[int] = []
        self._selected_item: Optional[int] = None
        self._hover_item: Optional[int] = None
        self.selected_colour: Optional[str] = None

        rows = max(1, math.ceil(len(self._colours) / self.columns))
        width = self.columns * (self._swatch_w + self._gap) - self._gap
        height = rows * (self._swatch_h + self._gap) - self._gap
        self.canvas = tk.Canvas(self, width=width, height=height, bg=background,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self._draw_board()

    # -- model ---------------------------------------------------------
    def swatch_colours(self) -> List[str]:
        """Every colour on the board, in reading order."""
        return list(self._colours)

    def _draw_board(self):
        for index, colour in enumerate(self._colours):
            row, column = divmod(index, self.columns)
            x0 = column * (self._swatch_w + self._gap)
            y0 = row * (self._swatch_h + self._gap)
            item = self.canvas.create_rectangle(
                x0, y0, x0 + self._swatch_w, y0 + self._swatch_h,
                fill=colour, outline=self._outline, width=1)
            self._item_colour[item] = colour
            self._items.append(item)
            self._colour_items.setdefault(colour, []).append(item)
            self.canvas.tag_bind(item, "<Button-1>", lambda event, i=item: self._clicked(i))
            self.canvas.tag_bind(item, "<Enter>",
                                 lambda event: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind(item, "<Leave>",
                                 lambda event: self.canvas.configure(cursor=""))
        self.set_selected(self.selected_colour)

    # -- interaction ---------------------------------------------------
    def _item_at(self, x: float, y: float) -> Optional[int]:
        column = int(x // (self._swatch_w + self._gap))
        row = int(y // (self._swatch_h + self._gap))
        if column < 0 or column >= self.columns or row < 0:
            return None
        if x - column * (self._swatch_w + self._gap) > self._swatch_w:
            return None
        if y - row * (self._swatch_h + self._gap) > self._swatch_h:
            return None
        index = row * self.columns + column
        if index < 0 or index >= len(self._items):
            return None
        return self._items[index]

    def _motion(self, event):
        item = self._item_at(getattr(event, "x", 0), getattr(event, "y", 0))
        if item == self._hover_item:
            return
        self._unhover()
        self._hover_item = item
        if item is not None and item != self._selected_item:
            try:
                self.canvas.itemconfigure(item, outline=self._hover, width=2)
            except tk.TclError:
                pass

    def _leave(self, event=None):
        self._unhover()
        try:
            self.canvas.configure(cursor="")
        except tk.TclError:
            pass

    def _unhover(self):
        item, self._hover_item = self._hover_item, None
        if item is None or item == self._selected_item:
            return
        try:
            self.canvas.itemconfigure(item, outline=self._outline, width=1)
        except tk.TclError:
            pass

    def _clicked(self, item: int):
        colour = self._item_colour.get(item)
        if colour is None:
            return
        self.selected_colour = colour
        self._highlight_item(item)
        if self._on_pick is not None:
            self._on_pick(colour)

    def _highlight_item(self, item: Optional[int]):
        if self._selected_item is not None:
            try:
                self.canvas.itemconfigure(self._selected_item,
                                          outline=self._outline, width=1)
            except tk.TclError:
                pass
        self._selected_item = item
        if item is not None:
            try:
                self.canvas.itemconfigure(item, outline=self._highlight, width=2)
                self.canvas.tag_raise(item)
            except tk.TclError:
                pass

    def set_selected(self, colour: Optional[str]):
        """Outline the swatch holding ``colour`` (no callback fired)."""
        normalised = normalise_hex_colour(colour) if colour else None
        self.selected_colour = normalised
        items = self._colour_items.get(normalised or "", [])
        self._highlight_item(items[0] if items else None)


class ColourGradientPicker(_TkFrame):
    """Microsoft Paint's "Define Custom Colors" field.

    A hue (left to right) × saturation (top to bottom) gradient square with a
    brightness bar down its right-hand side: every hue is reachable at every
    tint, tone and shade, which is what gives the studio the full colour
    range rather than a fixed set of discrete swatches.
    """

    def __init__(self, master, *, on_pick=None, cell_size: int = GRADIENT_CELL,
                 columns: int = GRADIENT_COLUMNS, rows: int = GRADIENT_ROWS,
                 brightness_steps: int = BRIGHTNESS_STEPS,
                 bar_width: int = 24, gap: int = 8,
                 background: str = "#FFFFFF", outline: str = "#8C96A8",
                 highlight: str = "#111827", **kwargs):
        super().__init__(master, bg=background, **kwargs)
        self._on_pick = on_pick
        self.columns = max(2, columns)
        self.rows = max(2, rows)
        self.cell_size = max(2, cell_size)
        self.brightness_steps = max(3, brightness_steps)
        self._outline = outline
        self._highlight = highlight
        self._bar_width = max(8, bar_width)
        self._gap = max(2, gap)

        self.hue = 0.58
        self.saturation = 0.85
        self.value = 0.9
        self.selected_colour: Optional[str] = None

        self.field_width = self.columns * self.cell_size
        self.field_height = self.rows * self.cell_size
        self._bar_origin = self.field_width + self._gap
        self._field_items: Dict[int, Tuple[float, float]] = {}
        self._bar_items: Dict[int, float] = {}
        self._marker_items: List[int] = []
        self._bar_marker: Optional[int] = None
        self._redraw_pending = False

        self.canvas = tk.Canvas(self, width=self.field_width + self._gap + self._bar_width,
                                height=self.field_height, bg=background,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._draw_brightness_bar()
        self._draw_field()
        self._draw_markers()
        self.canvas.bind("<Button-1>", self._pressed)
        self.canvas.bind("<B1-Motion>", self._dragged)
        self.canvas.bind("<ButtonRelease-1>", self._released)
        self.canvas.bind("<Leave>", lambda event: self.canvas.configure(cursor=""))

    # -- drawing -------------------------------------------------------
    def _draw_field(self):
        """(Re)paint the hue × saturation square at the current brightness."""
        try:
            for item in self._field_items:
                self.canvas.delete(item)
        except tk.TclError:
            pass
        self._field_items = {}
        cell = self.cell_size
        hue_steps = max(1, self.columns - 1)
        sat_steps = max(1, self.rows - 1)
        for row in range(self.rows):
            saturation = row / sat_steps
            for column in range(self.columns):
                hue = column / hue_steps
                x0 = column * cell
                y0 = row * cell
                item = self.canvas.create_rectangle(
                    x0, y0, x0 + cell, y0 + cell,
                    fill=hsv_to_hex(hue, saturation, self.value), outline="", width=0)
                self._field_items[item] = (hue, saturation)
        if self._field_items:
            self._place_field_marker(raise_it=True)

    def _draw_brightness_bar(self):
        step = self.field_height / self.brightness_steps
        for index in range(self.brightness_steps):
            value = 1.0 - index / (self.brightness_steps - 1)
            item = self.canvas.create_rectangle(
                self._bar_origin, index * step,
                self._bar_origin + self._bar_width, (index + 1) * step,
                fill=hsv_to_hex(self.hue, self.saturation, value),
                outline=self._outline, width=1)
            self._bar_items[item] = value
        self._bar_marker = self.canvas.create_rectangle(
            self._bar_origin - 2, 0, self._bar_origin + self._bar_width + 2, 3,
            outline=self._highlight, width=2)

    def _refresh_brightness_bar(self):
        for item, value in self._bar_items.items():
            try:
                self.canvas.itemconfigure(item, fill=hsv_to_hex(self.hue, self.saturation, value))
            except tk.TclError:
                pass

    def _draw_markers(self):
        self._marker_items = [
            self.canvas.create_oval(0, 0, 0, 0, outline="#FFFFFF", width=2),
            self.canvas.create_oval(0, 0, 0, 0, outline=self._highlight, width=1),
        ]
        self._place_field_marker()
        self._place_bar_marker()

    def _field_marker_centre(self) -> Tuple[float, float]:
        columns = max(1, self.columns - 1)
        rows = max(1, self.rows - 1)
        cx = min(self.columns - 1, self.hue * columns) * self.cell_size + self.cell_size / 2.0
        cy = min(self.rows - 1, self.saturation * rows) * self.cell_size + self.cell_size / 2.0
        return cx, cy

    def _place_field_marker(self, raise_it: bool = False):
        if len(self._marker_items) != 2:
            return
        cx, cy = self._field_marker_centre()
        radius = max(4.0, self.cell_size * 0.8)
        try:
            self.canvas.coords(self._marker_items[0], cx - radius, cy - radius,
                               cx + radius, cy + radius)
            self.canvas.coords(self._marker_items[1], cx - radius + 2, cy - radius + 2,
                               cx + radius - 2, cy + radius - 2)
            if raise_it:
                for item in self._marker_items:
                    self.canvas.tag_raise(item)
        except tk.TclError:
            pass

    def _place_bar_marker(self):
        if self._bar_marker is None:
            return
        y = (1.0 - self.value) * self.field_height
        try:
            self.canvas.coords(self._bar_marker,
                               self._bar_origin - 2, y - 1.5,
                               self._bar_origin + self._bar_width + 2, y + 1.5)
            self.canvas.tag_raise(self._bar_marker)
        except tk.TclError:
            pass

    # -- selection -----------------------------------------------------
    def current_colour(self) -> str:
        return hsv_to_hex(self.hue, self.saturation, self.value)

    def set_selected(self, colour: Optional[str]):
        """Move the crosshair onto ``colour`` (no callback fired)."""
        hsv = hsv_from_hex(colour) if colour else None
        self.selected_colour = normalise_hex_colour(colour) if colour else None
        if hsv is None:
            return
        self.hue, self.saturation, self.value = hsv
        self._draw_field()
        self._refresh_brightness_bar()
        self._place_bar_marker()

    def _schedule_redraw(self):
        """Coalesce brightness redraws so dragging stays smooth."""
        if self._redraw_pending:
            return
        self._redraw_pending = True
        try:
            self.after(25, self._flush_redraw)
        except tk.TclError:
            self._flush_redraw()

    def _flush_redraw(self):
        self._redraw_pending = False
        try:
            if not self.canvas.winfo_exists():
                return
        except tk.TclError:
            return
        self._draw_field()
        self._refresh_brightness_bar()
        self._place_bar_marker()

    # -- interaction ---------------------------------------------------
    def _pressed(self, event):
        self._apply_pointer(getattr(event, "x", 0), getattr(event, "y", 0))

    def _dragged(self, event):
        self._apply_pointer(getattr(event, "x", 0), getattr(event, "y", 0))

    def _released(self, event=None):
        self._flush_redraw()

    def _apply_pointer(self, x: float, y: float):
        if x >= self._bar_origin:
            self.value = max(0.0, min(1.0, 1.0 - y / max(1.0, self.field_height)))
            self._schedule_redraw()
        else:
            self.hue = max(0.0, min(1.0, x / max(1.0, self.field_width)))
            self.saturation = max(0.0, min(1.0, y / max(1.0, self.field_height)))
            self._place_field_marker()
        self._emit()

    def _emit(self):
        colour = self.current_colour()
        self.selected_colour = colour
        if self._on_pick is not None:
            self._on_pick(colour)


class PaletteBinder:
    """Keeps a group of widgets painted in the palette currently in force.

    Every widget registers once with a *role*: the set of palette colours it
    should follow (a heading, a text field, a card...). Switching palette then
    repaints the whole window with one :meth:`apply` call instead of dozens of
    hand-written ``configure`` calls scattered through the UI code.
    """

    ROLES = ("background", "body", "heading", "muted", "card", "field",
             "accent", "primary_button", "button", "selectable", "scale", "swatch")

    def __init__(self, colours: Optional[Dict[str, str]] = None):
        self._colours: Dict[str, str] = dict(colours) if colours else {}
        self._slots: List[Tuple[object, object, str, Dict[str, object]]] = []

    # -- registration --------------------------------------------------
    def register(self, widget, role: str = "body", window=None, **extra):
        """Track ``widget`` and paint it straight away when possible."""
        self._slots.append((window, widget, role, dict(extra)))
        if self._colours:
            self._paint(widget, role, extra)
        return widget

    def register_all(self, widgets, role: str = "body", window=None, **extra):
        for widget in widgets:
            self.register(widget, role, window=window, **extra)

    def apply(self, colours: Optional[Dict[str, str]] = None):
        """Repaint every registered widget for ``colours``."""
        if colours:
            self._colours = dict(colours)
        if not self._colours:
            return
        for _, widget, role, extra in list(self._slots):
            self._paint(widget, role, extra)

    def forget(self, window) -> int:
        """Drop the widgets of a closed window (avoids touching dead ones)."""
        before = len(self._slots)
        self._slots = [slot for slot in self._slots if slot[0] != window]
        return before - len(self._slots)

    def count(self) -> int:
        return len(self._slots)

    # -- painting ------------------------------------------------------
    def _options(self, role: str, extra: Dict[str, object]) -> Dict[str, object]:
        c = self._colours
        table = {
            "background": {"bg": c["background"]},
            "body": {"bg": c["background"], "fg": c["foreground"]},
            "heading": {"bg": c["background"], "fg": c["primary"]},
            "muted": {"bg": c["background"], "fg": c["muted"]},
            "card": {"bg": c["background"], "highlightbackground": c["surface"],
                     "highlightcolor": c["surface"]},
            "field": {"bg": c["surface"], "fg": c["foreground"],
                      "insertbackground": c["foreground"],
                      "highlightbackground": c["muted"],
                      "highlightcolor": c["accent"],
                      "selectbackground": c["accent"],
                      "selectforeground": c["accent_foreground"]},
            "accent": {"bg": c["accent"], "fg": c["accent_foreground"],
                       "activebackground": c["primary"],
                       "activeforeground": c["button_foreground"]},
            "primary_button": {"bg": c["primary"], "fg": c["button_foreground"],
                               "activebackground": c["accent"],
                               "activeforeground": c["accent_foreground"]},
            "button": {"bg": c["surface"], "fg": c["foreground"],
                       "activebackground": c["muted"],
                       "activeforeground": c["foreground"]},
            "selectable": {"bg": c["background"], "fg": c["foreground"],
                           "activebackground": c["background"],
                           "activeforeground": c["foreground"],
                           "selectcolor": c["surface"]},
            "scale": {"bg": c["background"], "fg": c["foreground"],
                      "troughcolor": c["surface"],
                      "activebackground": c["accent"],
                      "highlightbackground": c["background"]},
            "swatch": {"bg": c["surface"], "highlightbackground": c["foreground"]},
        }
        options = dict(table.get(role, table["body"]))
        options.update(extra)
        return options

    def _paint(self, widget, role: str, extra: Dict[str, object]):
        try:
            widget.configure(**self._options(role, extra))
        except tk.TclError:
            # ttk widgets reject bg/fg; they are styled through ttk.Style.
            pass
        except (AttributeError, TypeError):
            pass


class CustomPaletteEditor(_TkToplevel):
    """Dialog that builds and saves a user-defined palette.

    Three colour roles (primary, accent, background) are filled in from any of
    three pickers — the Paint-style hue/saturation gradient field with its
    brightness bar, the 48-swatch "basic colours" board, or the hexagon
    honeycomb — then previewed live, named, and handed back to the app through
    ``on_save``.
    """

    def __init__(self, master, colours: Dict[str, str], *, on_save,
                 initial: Optional[Tuple[str, str, str]] = None,
                 initial_name: str = "", editing: Optional[str] = None,
                 topmost: bool = False):
        super().__init__(master)
        self._on_save = on_save
        self._editing = editing
        self._initial_name = initial_name
        c = self.colours = dict(colours)
        base = initial or ("#1E3A8A", "#3B82F6", "#F8FAFC")
        self._values = {
            "primary": normalise_hex_colour(base[0]) or "#1E3A8A",
            "accent": normalise_hex_colour(base[1]) or "#3B82F6",
            "background": normalise_hex_colour(base[2]) or "#F8FAFC",
        }
        self._binder = PaletteBinder(c)

        self.title("Custom UI Colour — colour studio")
        self.configure(background=c["background"])
        self.resizable(False, False)
        try:
            self.transient(master)
        except tk.TclError:
            pass
        if topmost:
            try:
                self.wm_attributes("-topmost", True)
            except tk.TclError:
                pass

        body = tk.Frame(self, bg=c["background"], padx=18, pady=16)
        body.pack(fill="both", expand=True)
        self._binder.register(body, "background", window=self)
        self._title = tk.Label(body, text="Custom UI Colour", bg=c["background"],
                               fg=c["primary"], font=("Segoe UI", 16, "bold"))
        self._title.pack(anchor="w")
        self._binder.register(self._title, "heading", window=self)
        self._subtitle = tk.Label(
            body,
            text="Pick any colour from the gradient, the swatch board or the hexagon — "
                 "then choose which role it fills.",
            bg=c["background"], fg=c["muted"], font=("Segoe UI", 9))
        self._subtitle.pack(anchor="w", pady=(2, 12))
        self._binder.register(self._subtitle, "muted", window=self)

        main = tk.Frame(body, bg=c["background"])
        main.pack(fill="both", expand=True)
        self._binder.register(main, "background", window=self)

        self._build_picker_column(main)
        self._build_role_column(main)

        buttons = tk.Frame(body, bg=c["background"])
        buttons.pack(fill="x", pady=(16, 0))
        self._binder.register(buttons, "background", window=self)
        cancel = tk.Button(buttons, text="Cancel", command=self.destroy, relief="flat",
                           bg=c["surface"], fg=c["foreground"], activebackground=c["muted"],
                           padx=14, pady=5, font=("Segoe UI", 9))
        cancel.pack(side="right")
        self._binder.register(cancel, "button", window=self)
        save = tk.Button(buttons, text="Save colours", command=self._save, relief="flat",
                         padx=16, pady=5, font=("Segoe UI", 9, "bold"))
        save.pack(side="right", padx=(0, 8))
        self._binder.register(save, "accent", window=self)

        self._role_changed()
        self._refresh_preview()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_picker_column(self, parent):
        c = self.colours
        left = tk.Frame(parent, bg=c["background"])
        left.pack(side="left", anchor="n")
        self._binder.register(left, "background", window=self)

        self._style_notebook()
        self.notebook = ttk.Notebook(left, style="Studio.TNotebook")
        self.notebook.pack(anchor="n")
        self._binder.register(self.notebook, "background", window=self)

        gradient_tab = tk.Frame(self.notebook, bg=c["background"])
        self._binder.register(gradient_tab, "background", window=self)
        self.gradient = ColourGradientPicker(
            gradient_tab, on_pick=lambda colour: self._picked(colour, "gradient"),
            background=c["surface"],
            outline=c["muted"], highlight=c["foreground"])
        self.gradient.pack(padx=12, pady=(12, 4))
        hint = tk.Label(gradient_tab,
                        text="Hue across, saturation down · use the bar for brightness",
                        bg=c["background"], fg=c["muted"], font=("Segoe UI", 8))
        hint.pack(pady=(0, 10))
        self._binder.register(hint, "muted", window=self)

        swatch_tab = tk.Frame(self.notebook, bg=c["background"])
        self._binder.register(swatch_tab, "background", window=self)
        self.swatches = ColourSwatchBoard(
            swatch_tab, on_pick=lambda colour: self._picked(colour, "swatches"),
            background=c["surface"],
            outline=c["muted"], highlight=c["foreground"], hover=c["foreground"])
        self.swatches.pack(padx=12, pady=(16, 6))
        hint = tk.Label(swatch_tab,
                        text="48 basic colours · tints and shades of every hue",
                        bg=c["background"], fg=c["muted"], font=("Segoe UI", 8))
        hint.pack(pady=(0, 12))
        self._binder.register(hint, "muted", window=self)

        hexagon_tab = tk.Frame(self.notebook, bg=c["background"])
        self._binder.register(hexagon_tab, "background", window=self)
        self.picker = ColourHexagonPicker(
            hexagon_tab, on_pick=lambda colour: self._picked(colour, "hexagon"),
            background=c["surface"],
            outline=c["muted"], highlight=c["foreground"], highlightthickness=1,
            highlightbackground=c["muted"])
        self.picker.pack(padx=12, pady=(12, 4))
        hint = tk.Label(hexagon_tab,
                        text="Honeycomb of discrete shades · black-to-white strip below",
                        bg=c["background"], fg=c["muted"], font=("Segoe UI", 8))
        hint.pack(pady=(0, 10))
        self._binder.register(hint, "muted", window=self)

        self.notebook.add(gradient_tab, text="Gradient")
        self.notebook.add(swatch_tab, text="Swatches")
        self.notebook.add(hexagon_tab, text="Hexagon")
        try:
            self.notebook.select(gradient_tab)
        except tk.TclError:
            pass

        shades_head = tk.Label(left, text="Tints & shades", bg=c["background"],
                               fg=c["primary"], font=("Segoe UI", 9, "bold"))
        shades_head.pack(anchor="w", pady=(12, 0))
        self._binder.register(shades_head, "heading", window=self)
        shades_hint = tk.Label(left, text="Click a shade to apply it to the selected role.",
                               bg=c["background"], fg=c["muted"], font=("Segoe UI", 8))
        shades_hint.pack(anchor="w", pady=(0, 4))
        self._binder.register(shades_hint, "muted", window=self)
        self.shades = ColourShadeStrip(left, on_pick=self._shade_picked,
                                       background=c["surface"], outline=c["muted"],
                                       highlight=c["foreground"])
        self.shades.pack(anchor="w")
        self._binder.register(self.shades, "background", window=self)

        hex_row = tk.Frame(left, bg=c["background"])
        hex_row.pack(fill="x", pady=(12, 0))
        self._binder.register(hex_row, "background", window=self)
        hex_label = tk.Label(hex_row, text="Hex", bg=c["background"], fg=c["foreground"],
                             font=("Segoe UI", 9, "bold"))
        hex_label.pack(side="left")
        self._binder.register(hex_label, "body", window=self)
        self.hex_var = tk.StringVar()
        self.hex_entry = tk.Entry(hex_row, textvariable=self.hex_var, width=10,
                                  bg=c["surface"], fg=c["foreground"],
                                  insertbackground=c["foreground"], relief="flat",
                                  highlightthickness=1, highlightbackground=c["muted"],
                                  font=("Consolas", 10))
        self.hex_entry.pack(side="left", padx=(8, 8))
        self._binder.register(self.hex_entry, "field", window=self)
        self.hex_entry.bind("<Return>", lambda event: self._apply_typed_hex())
        use_hex = tk.Button(hex_row, text="Use hex", command=self._apply_typed_hex,
                            relief="flat", bg=c["primary"], fg=c["button_foreground"],
                            activebackground=c["accent"],
                            activeforeground=c["accent_foreground"],
                            padx=10, pady=2, font=("Segoe UI", 9, "bold"))
        use_hex.pack(side="left")
        self._binder.register(use_hex, "primary_button", window=self)
        self._hex_hint = tk.Label(hex_row, text="", bg=c["background"], fg=c["muted"],
                                  font=("Segoe UI", 8))
        self._hex_hint.pack(side="left", padx=(8, 0))
        self._binder.register(self._hex_hint, "muted", window=self)

        self.rgb_label = tk.Label(left, text="", bg=c["background"], fg=c["muted"],
                                  font=("Consolas", 8))
        self.rgb_label.pack(anchor="w", pady=(4, 0))
        self._binder.register(self.rgb_label, "muted", window=self)

    def _build_role_column(self, parent):
        c = self.colours
        right = tk.Frame(parent, bg=c["background"])
        right.pack(side="left", anchor="n", padx=(20, 0), fill="both", expand=True)
        self._binder.register(right, "background", window=self)

        heading = tk.Label(right, text="Colour being edited", bg=c["background"],
                           fg=c["primary"], font=("Segoe UI", 10, "bold"))
        heading.pack(anchor="w")
        self._binder.register(heading, "heading", window=self)

        self.role_var = tk.StringVar(value="primary")
        self._role_swatches: Dict[str, tk.Frame] = {}
        self._role_labels: Dict[str, tk.Label] = {}
        for role, caption in (("primary", "Primary — headings, buttons"),
                              ("accent", "Accent — highlights, progress"),
                              ("background", "Background — window + panels")):
            row = tk.Frame(right, bg=c["background"])
            row.pack(fill="x", pady=3)
            self._binder.register(row, "background", window=self)
            radio = tk.Radiobutton(row, text=caption, value=role, variable=self.role_var,
                                   command=self._role_changed, anchor="w",
                                   font=("Segoe UI", 9))
            radio.pack(side="left", anchor="w")
            self._binder.register(radio, "selectable", window=self)
            swatch = tk.Frame(row, width=34, height=18, bg=self._values[role],
                              highlightthickness=1,
                              highlightbackground=c["foreground"])
            swatch.pack(side="right")
            self._binder.register(swatch, "swatch", window=self, bg=self._values[role])
            label = tk.Label(row, text=self._values[role], bg=c["background"],
                             fg=c["muted"], font=("Consolas", 9))
            label.pack(side="right", padx=(0, 8))
            self._binder.register(label, "muted", window=self)
            self._role_swatches[role] = swatch
            self._role_labels[role] = label

        preview_heading = tk.Label(right, text="Live preview", bg=c["background"],
                                   fg=c["primary"], font=("Segoe UI", 10, "bold"))
        preview_heading.pack(anchor="w", pady=(14, 4))
        self._binder.register(preview_heading, "heading", window=self)
        self._preview = tk.Frame(right, height=120, highlightthickness=1,
                                 highlightbackground=c["muted"])
        self._preview.pack(fill="x")
        self._preview.pack_propagate(False)
        self._preview_title = tk.Label(self._preview, text="AutoTyper",
                                       font=("Segoe UI", 12, "bold"))
        self._preview_title.pack(anchor="w", padx=10, pady=(12, 0))
        self._preview_body = tk.Label(self._preview, text="Your colours, applied live.",
                                      font=("Segoe UI", 9))
        self._preview_body.pack(anchor="w", padx=10)
        self._preview_button = tk.Label(self._preview, text="  Accent button  ",
                                        font=("Segoe UI", 9, "bold"))
        self._preview_button.pack(anchor="w", padx=10, pady=(10, 0))

        name_heading = tk.Label(right, text="Palette name", bg=c["background"],
                                fg=c["primary"], font=("Segoe UI", 10, "bold"))
        name_heading.pack(anchor="w", pady=(14, 4))
        self._binder.register(name_heading, "heading", window=self)
        self.name_var = tk.StringVar(value=self._initial_name or "My Colours")
        name_entry = tk.Entry(right, textvariable=self.name_var, bg=c["surface"],
                              fg=c["foreground"], insertbackground=c["foreground"],
                              relief="flat", highlightthickness=1,
                              highlightbackground=c["muted"], font=("Segoe UI", 10))
        name_entry.pack(fill="x")
        self._binder.register(name_entry, "field", window=self)

    def _style_notebook(self):
        c = self.colours
        try:
            style = ttk.Style(self)
            style.configure("Studio.TNotebook", background=c["background"],
                            borderwidth=0, tabmargins=(0, 0, 0, 0))
            style.configure("Studio.TNotebook.Tab", padding=(14, 6),
                            font=("Segoe UI", 9, "bold"), background=c["surface"],
                            foreground=c["foreground"])
            style.map("Studio.TNotebook.Tab",
                      background=[("selected", c["accent"])],
                      foreground=[("selected", c["accent_foreground"])])
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Palette changes
    # ------------------------------------------------------------------
    def apply_palette(self, colours: Dict[str, str]):
        """Repaint the dialog when the app palette changes underneath it."""
        self.colours = dict(colours)
        self.configure(background=colours["background"])
        self._binder.apply(colours)
        self._style_notebook()
        for canvas in (self.gradient.canvas, self.swatches.canvas,
                       self.shades.canvas, self.picker.canvas):
            try:
                canvas.configure(bg=colours["surface"])
            except tk.TclError:
                pass
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _picked(self, colour: str, source: str = "external"):
        """A colour came from one of the three pickers."""
        self._set_role_colour(self.role_var.get(), colour, source=source)

    def _shade_picked(self, colour: str):
        self._set_role_colour(self.role_var.get(), colour, source="shades")

    def _apply_typed_hex(self):
        colour = normalise_hex_colour(self.hex_var.get())
        if colour is None:
            self._hex_hint.configure(text="use #RRGGBB")
            return
        self._hex_hint.configure(text="")
        self._set_role_colour(self.role_var.get(), colour, source="hex")

    def _set_role_colour(self, role: str, colour: str, source: str = "picker"):
        colour = normalise_hex_colour(colour) or self._values[role]
        self._values[role] = colour
        self.hex_var.set(colour)
        self._role_swatches[role].configure(bg=colour)
        self._role_labels[role].configure(text=colour)
        self.rgb_label.configure(text=format_rgb(colour))
        if source != "shades":
            self.shades.set_base_colour(colour)
        self._sync_pickers(colour, source)
        self._refresh_preview()

    def _sync_pickers(self, colour: str, source: str):
        """Keep the other two pickers pointing at the colour just chosen."""
        if source != "gradient":
            self.gradient.set_selected(colour)
        if source != "swatches":
            self.swatches.set_selected(colour)
        if source != "hexagon":
            self.picker.set_selected(colour)
        if source != "shades":
            self.shades.set_selected(colour)

    def _role_changed(self):
        colour = self._values[self.role_var.get()]
        self._set_role_colour(self.role_var.get(), colour, source="role")

    def _refresh_preview(self):
        preview = _palette_colours("__preview__", {"__preview__": self.triple()})
        self._preview.configure(bg=preview["background"])
        self._preview_title.configure(bg=preview["background"], fg=preview["primary"])
        self._preview_body.configure(bg=preview["background"], fg=preview["foreground"])
        self._preview_button.configure(bg=preview["accent"],
                                       fg=preview["accent_foreground"])

    def triple(self) -> Tuple[str, str, str]:
        return (self._values["primary"], self._values["accent"], self._values["background"])

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Give your colours a name before saving.",
                                   parent=self)
            return
        self._on_save(name, self.triple(), self._editing)
        self.destroy()


# =============================================================================
# 11c. IN-APP GUIDE — WHAT EVERY CONTROL DOES
# =============================================================================
#
# The guide is plain data (so it can be unit tested and proof-read without a
# display) rendered by the small window at the bottom of this block. Every
# control of the main window, the settings window and the colour studio has an
# entry here; ``test_guide_ui.py`` fails if one is ever added without being
# documented.


@dataclass(frozen=True)
class GuideItem:
    """One documented control: its label and what it does."""

    name: str
    text: str


@dataclass(frozen=True)
class GuideSection:
    """A titled group of :class:`GuideItem` entries."""

    title: str
    blurb: str
    items: Tuple[GuideItem, ...]


WHEEL_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def bind_wheel_scrolling(canvas, sequences=WHEEL_SEQUENCES) -> Tuple[str, ...]:
    """Scroll ``canvas`` with the mouse wheel on Windows, macOS and X11.

    Tk delivers wheel events to the widget under the pointer, which is usually
    a child of the canvas being scrolled, so the binding is global. The
    sequences that were bound are returned so the window can release them when
    it closes (see :func:`release_wheel_scrolling`).
    """
    def on_wheel(event):
        try:
            if getattr(event, "num", None) == 4:
                delta = -1
            elif getattr(event, "num", None) == 5:
                delta = 1
            else:
                delta = -1 if getattr(event, "delta", 0) > 0 else 1
            canvas.yview_scroll(delta, "units")
        except tk.TclError:
            pass

    bound = []
    for sequence in sequences:
        try:
            canvas.bind_all(sequence, on_wheel, add="+")
            bound.append(sequence)
        except tk.TclError:
            continue
    return tuple(bound)


def release_wheel_scrolling(widget, sequences) -> None:
    """Undo :func:`bind_wheel_scrolling` for a window that is closing."""
    for sequence in sequences or ():
        try:
            widget.unbind_all(sequence)
        except tk.TclError:
            pass


def _guide_item(name: str, text: str) -> GuideItem:
    return GuideItem(name, " ".join(text.split()))


_GUIDE_ITEMS: Tuple[GuideSection, ...] = (
    GuideSection(
        "Start here", "Three steps are all it takes to watch AutoTyper type.",
        (
            _guide_item("1. Paste your text",
                        "Paste or type the text you want reproduced into the large box, "
                        "then set your speed. Pasting a block of Pascal shows Coding "
                        "Mode at its best."),
            _guide_item("2. Press Start AutoTyper",
                        "AutoTyper plans the whole keystroke trace, then counts down so "
                        "you can click the window you want the text typed into."),
            _guide_item("3. Watch the countdown, then let go of the mouse",
                        "Keystrokes are sent to whatever window has focus. Keep the "
                        "target window in front until the status line says Completed."),
        ),
    ),
    GuideSection(
        "Header buttons", "The three controls in the top-right corner.",
        (
            _guide_item("❓ Guide",
                        "Opens this window. It is also on F1, and AutoTyper opens it "
                        "automatically the first time you start the app."),
            _guide_item("⚙ Settings",
                        "Appearance and window options: colour palettes, custom "
                        "colours, always-on-top and the update controls."),
            _guide_item("⬇ Get .exe",
                        "Downloads the newest published AutoTyper.exe from GitHub so "
                        "you can run AutoTyper without Python. Progress is shown on the "
                        "bar above the Start button."),
            _guide_item("⬇ Get vX .exe (update button)",
                        "Only appears when a newer release exists. Nothing is ever "
                        "downloaded or installed until you agree to it."),
        ),
    ),
    GuideSection(
        "Typing settings — speed & realism",
        "How fast and how human the simulated typing is.",
        (
            _guide_item("Target speed (WPM)",
                        "20 to 150 words per minute — the pace AutoTyper aims for on "
                        "average. Each inter-key interval is drawn from a gamma "
                        "distribution and modulated by Fitts' law, hand alternation, "
                        "digraph speed-ups and syntax delays, so the trace breathes "
                        "like a real typist. Use the box or drag the slider."),
            _guide_item("Base typo rate (%)",
                        "0.01 to 100 — the chance per keystroke of a natural error "
                        "episode (finger-race transposition, neighbour-key brush, "
                        "omission, insertion or overshoot). Every error is followed by "
                        "an accelerating backspace correction, exactly as it is "
                        "described in the trace statistics."),
            _guide_item("Speed definition",
                        "Net (incl. pauses & fixes) measures the speed you actually "
                        "see: thinking pauses, error corrections and line resets all "
                        "eat into it. Gross (keystroke rate) counts raw keystrokes "
                        "only, so the same setting feels faster."),
            _guide_item("Countdown (seconds)",
                        "1 to 30 seconds of grace between pressing Start and the first "
                        "keystroke, so you can focus your editor. AutoTyper shows the "
                        "remaining seconds in the status line."),
        ),
    ),
    GuideSection(
        "Typing settings — editor behaviour",
        "How AutoTyper copes with the editor it is typing into.",
        (
            _guide_item("Editor indentation",
                        "Off types the text exactly as written. Copy previous line's "
                        "indentation predicts and removes the whitespace a copied "
                        "indent inserts. Smart is Pascal-aware: it predicts the extra "
                        "level opened by begin, then, do, try, {, (, [ and clears it "
                        "again. Fixed width backspaces a constant number of spaces "
                        "after every newline."),
            _guide_item("Fixed indent width",
                        "How many spaces one indent level is worth. Only used by the "
                        "Fixed width policy — the other policies detect the width from "
                        "your text."),
            _guide_item("Pascal coding mode (begin/end navigation)",
                        "Types Pascal blocks the way a person does: it lays down "
                        "begin … end first (lookahead finds the matching end, even "
                        "through nested blocks, comments and strings), walks back up "
                        "into the block with the arrow keys and fills the body lines in "
                        "order. Leave it off for prose or other languages."),
            _guide_item("Verify and repair target editor",
                        "After the last keystroke AutoTyper reads the focused window "
                        "back (select all, copy) and compares it with your text. If "
                        "something is missing it types a repair pass. Turn it off for "
                        "applications where select-all or copy would do something "
                        "unexpected."),
            _guide_item("Deterministic seed",
                        "Ticks every run into a repeatable one: the same seed always "
                        "produces the same timings, pauses and mistakes. Leave it off "
                        "and each run is seeded from the operating system, so no two "
                        "runs are identical."),
            _guide_item("Seed value",
                        "The 0 to 2147483647 number used when Deterministic seed is "
                        "ticked. Share it with a trace export to reproduce a run "
                        "exactly."),
        ),
    ),
    GuideSection(
        "Source text panel", "The big text box and the buttons above it.",
        (
            _guide_item("Text box",
                        "The source that will be typed. Indentation and blank lines are "
                        "preserved; long lines scroll sideways instead of wrapping, so "
                        "what you see is what gets typed. Ctrl+A selects everything."),
            _guide_item("Paste clipboard",
                        "Replaces the contents of the box with your clipboard text — "
                        "the quickest way to load a document or source file."),
            _guide_item("Clear",
                        "Empties the text box. It does not touch your clipboard."),
            _guide_item("Benchmark",
                        "Runs the whole simulation without pressing a single key and "
                        "reports the result: achieved WPM, keystrokes, pauses, error "
                        "episodes and percentiles. Use it to sanity-check a speed "
                        "before letting AutoTyper loose on a real window."),
            _guide_item("Character / line counter",
                        "Next to the buttons: how much text is loaded and how many "
                        "lines the trace will cover. The progress bar counts those "
                        "lines while typing."),
        ),
    ),
    GuideSection(
        "Running a job", "The footer under the text box.",
        (
            _guide_item("Status line",
                        "What the engine is doing right now: planning the trace, the "
                        "countdown, which line is being typed, and the final result "
                        "(Completed, Completed — verified, Stopped, Cancelled)."),
            _guide_item("Progress bar",
                        "Lines typed so far against the total number of lines in the "
                        "trace."),
            _guide_item("Start AutoTyper",
                        "Plans the trace, counts down, then types. The window "
                        "automatically greys this button out and enables Stop. "
                        "Ctrl+Enter does the same thing."),
            _guide_item("Stop",
                        "Sets a stop flag: AutoTyper finishes the keystroke it is on "
                        "and stops, keeping everything typed so far. Esc does the same, "
                        "and the button only works while a job is running."),
            _guide_item("What happens in order",
                        "1) every line of your text is validated against the planner; "
                        "2) the countdown runs; 3) keystrokes are sent with pynput to "
                        "the focused window; 4) if verification is on, the result is "
                        "read back and repaired if needed."),
        ),
    ),
    GuideSection(
        "Settings window", "Appearance & Window Settings, opened from ⚙.",
        (
            _guide_item("Colour palette cards",
                        "Nineteen built-in palettes. Click anywhere on a card to apply "
                        "it instantly; the three swatches show its primary, accent and "
                        "background colour. Your choice is remembered between runs."),
            _guide_item("🎨 New colours…",
                        "Opens the colour studio to design your own palette from "
                        "scratch."),
            _guide_item("Edit selected / Delete selected",
                        "Change or remove one of your saved palettes (they are marked "
                        "with a ★). Double-clicking a ★ card is a shortcut for Edit. "
                        "Built-in palettes cannot be edited or deleted."),
            _guide_item("Keep AutoTyper above other applications",
                        "Keeps this window on top, so it cannot hide behind the editor "
                        "you are about to click. Untick it if AutoTyper covers something "
                        "you need — the countdown still gives you time to switch "
                        "windows."),
            _guide_item("Check for updates now",
                        "Asks GitHub for the newest release straight away. AutoTyper "
                        "also performs this check silently, once, when the window "
                        "opens."),
            _guide_item("⬇ Download latest AutoTyper.exe",
                        "Fetches the published executable into your downloads folder. "
                        "In a packaged build it also offers to install itself and "
                        "restart, keeping the old build as AutoTyper.exe.old."),
            _guide_item("Live preview",
                        "Shows the selected palette on a sample title, body text and "
                        "accent button, so a dark theme can be checked for readability "
                        "before you commit to it."),
            _guide_item("Close",
                        "Closes the settings window. There is no OK button: every "
                        "option applies the moment you change it and is stored in "
                        "~/.autotyper_settings.json."),
        ),
    ),
    GuideSection(
        "The colour studio", "The dialog behind 🎨 New colours….",
        (
            _guide_item("Tabs: Gradient / Swatches / Hexagon",
                        "Three views of the same colour. Whichever one you click, the "
                        "colour is applied to the role selected on the right."),
            _guide_item("Gradient field (Paint style)",
                        "The Microsoft-Paint “Define Custom Colors” square: hue runs "
                        "across, saturation runs down, so every hue is available at "
                        "every tint. Click or drag anywhere — the crosshair marks the "
                        "current colour."),
            _guide_item("Brightness bar",
                        "The tall bar to the right of the square. Slide it to darken "
                        "the whole square towards black or brighten it back up without "
                        "losing the hue you picked."),
            _guide_item("Tints & shades",
                        "An eleven-step ramp of the colour being edited — pastel tints "
                        "on the left, the pure colour in the middle, deep shades on the "
                        "right, ending in black. One click applies a lighter or darker "
                        "version of exactly the same colour."),
            _guide_item("Swatches tab",
                        "Forty-eight basic colours in four rows: the twelve colour "
                        "wheel hues, their pastel tints, their deep shades, and the "
                        "white-to-black neutral ramp."),
            _guide_item("Hexagon tab",
                        "The honeycomb of discrete shades: white in the middle, tints "
                        "fanning out by hue, darker shades on the rim, with a "
                        "black-to-white hexagon strip underneath. Hovering turns the "
                        "pointer into a hand."),
            _guide_item("Hex box and Use hex",
                        "Type any hex colour — #RGB, #RRGGBB or the short form without "
                        "# — and press Use hex or Enter. Anything that is not a colour "
                        "is rejected with a “use #RRGGBB” hint."),
            _guide_item("RGB readout",
                        "The red, green and blue channels of the colour being edited, "
                        "for cross-checking against a style guide."),
            _guide_item("Primary / Accent / Background",
                        "Which role the next colour fills. Primary paints headings and "
                        "the main buttons, Accent paints highlights, progress and "
                        "selections, and Background paints the window, panels and the "
                        "text area. Readable foregrounds (light or dark) are derived "
                        "automatically, so text never becomes invisible."),
            _guide_item("Live preview",
                        "A miniature AutoTyper panel painted with your three colours, "
                        "updated as you pick."),
            _guide_item("Palette name and Save colours",
                        "Name the set and save it — it appears with a ★ in the palette "
                        "grid and is applied immediately. Up to sixteen custom palettes "
                        "are kept; Cancel discards the dialog without saving."),
        ),
    ),
    GuideSection(
        "Keyboard shortcuts", "Faster than reaching for the mouse.",
        (
            _guide_item("Ctrl+Enter", "Start a job from anywhere in the window."),
            _guide_item("Esc", "Stop a running job (does nothing when idle)."),
            _guide_item("F1", "Open this guide from anywhere in the app."),
            _guide_item("Ctrl+A", "Select all of the source text box."),
        ),
    ),
    GuideSection(
        "Troubleshooting", "The handful of things that usually go wrong.",
        (
            _guide_item("Nothing gets typed",
                        "Keystrokes go to whatever window has focus when the countdown "
                        "ends. Click your target window during the countdown. If "
                        "AutoTyper stayed on top, untick “Keep AutoTyper above other "
                        "applications” in Settings."),
            _guide_item("Characters go missing in games or remote desktops",
                        "Some applications drop very fast synthetic input. Lower the "
                        "WPM, or run the target application and AutoTyper at the same "
                        "privilege level (both normal, or both as administrator)."),
            _guide_item("“Completed — verification unavailable”",
                        "The focused window did not answer the select-all/copy probe. "
                        "The typing itself finished; turn off “Verify and repair target "
                        "editor” to skip the check."),
            _guide_item("“mismatch repaired” or an execution failure",
                        "The target editor contained other text, or its auto-indent "
                        "differs from the chosen policy. Empty the target document, "
                        "double-check the indentation setting, and try again with a "
                        "lower typo rate."),
            _guide_item("No update is ever announced",
                        "The check is deliberately silent: no internet, a blocked "
                        "github.com or no newer release all stay quiet. Use “Check for "
                        "updates now” for an explicit answer."),
            _guide_item("macOS or Linux typing does not land",
                        "macOS needs Accessibility permission for the app that launches "
                        "AutoTyper (System Settings → Privacy & Security → "
                        "Accessibility). On Linux, pynput needs an X11 session (or the "
                        "uinput backend) and may need to be run as the desktop user."),
            _guide_item("Where settings live",
                        "~/.autotyper_settings.json holds your palette, custom colours "
                        "and window preferences. Deleting it restores the defaults — it "
                        "never lives inside the AutoTyper folder."),
        ),
    ),
)

GUIDE_SECTIONS: Tuple[GuideSection, ...] = _GUIDE_ITEMS


def guide_item_count() -> int:
    """Total number of documented controls (handy for tests and the header)."""
    return sum(len(section.items) for section in GUIDE_SECTIONS)


def filter_guide(sections, query: str) -> List[GuideSection]:
    """Sections and entries matching ``query`` (case-insensitive, empty-safe)."""
    needle = (query or "").strip().lower()
    if not needle:
        return list(sections)
    matched: List[GuideSection] = []
    for section in sections:
        if needle in section.title.lower() or needle in section.blurb.lower():
            matched.append(section)
            continue
        items = tuple(item for item in section.items
                      if needle in item.name.lower() or needle in item.text.lower())
        if items:
            matched.append(GuideSection(section.title, section.blurb, items))
    return matched


class GuideWindow(_TkToplevel):
    """The scrollable, searchable guide that explains the whole interface."""

    def __init__(self, master, colours: Dict[str, str], *, topmost: bool = False,
                 on_close=None):
        super().__init__(master)
        self.colours = dict(colours)
        self._on_close = on_close
        self._binder = PaletteBinder(self.colours)
        c = self.colours

        self.title("AutoTyper Guide — what everything does")
        self.geometry("800x740")
        self.minsize(620, 420)
        self.configure(background=c["background"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        if topmost:
            try:
                self.wm_attributes("-topmost", True)
            except tk.TclError:
                pass

        header = tk.Frame(self, bg=c["background"], padx=22, pady=14)
        header.pack(fill="x")
        self._binder.register(header, "background", window=self)
        self._heading = tk.Label(header, text="📖 AutoTyper Guide",
                                 bg=c["background"], fg=c["primary"],
                                 font=("Segoe UI", 18, "bold"))
        self._heading.pack(anchor="w")
        self._binder.register(self._heading, "heading", window=self)
        self._subtitle = tk.Label(
            header,
            text=f"Every control in the window, explained — {guide_item_count()} topics.",
            bg=c["background"], fg=c["muted"], font=("Segoe UI", 10))
        self._subtitle.pack(anchor="w", pady=(2, 10))
        self._binder.register(self._subtitle, "muted", window=self)

        search = tk.Frame(header, bg=c["background"])
        search.pack(fill="x")
        self._binder.register(search, "background", window=self)
        label = tk.Label(search, text="Search", bg=c["background"], fg=c["foreground"],
                         font=("Segoe UI", 9, "bold"))
        label.pack(side="left")
        self._binder.register(label, "body", window=self)
        self.filter_var = tk.StringVar(value="")
        self.filter_entry = tk.Entry(search, textvariable=self.filter_var,
                                     bg=c["surface"], fg=c["foreground"],
                                     insertbackground=c["foreground"], relief="flat",
                                     highlightthickness=1,
                                     highlightbackground=c["muted"],
                                     highlightcolor=c["accent"], font=("Segoe UI", 10))
        self.filter_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self._binder.register(self.filter_entry, "field", window=self)
        for sequence in ("<KeyRelease>", "<Return>"):
            self.filter_entry.bind(sequence, lambda event: self.render())
        clear = tk.Button(search, text="Clear", command=self._clear_filter, relief="flat",
                          bg=c["surface"], fg=c["foreground"],
                          activebackground=c["muted"], padx=10, pady=2,
                          font=("Segoe UI", 9))
        clear.pack(side="right")
        self._binder.register(clear, "button", window=self)

        self._count_label = tk.Label(header, text="", bg=c["background"], fg=c["muted"],
                                     font=("Segoe UI", 8))
        self._count_label.pack(anchor="w", pady=(6, 0))
        self._binder.register(self._count_label, "muted", window=self)

        scroller = tk.Canvas(self, bg=c["background"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=scroller.yview,
                                  style="App.Vertical.TScrollbar")
        scroller.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroller.pack(side="left", fill="both", expand=True)
        self._scroller = scroller

        self._body = tk.Frame(scroller, bg=c["background"], padx=22, pady=8)
        self._binder.register(self._body, "background", window=self)
        body_id = scroller.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>",
                        lambda event: scroller.configure(scrollregion=scroller.bbox("all")))
        self._body.bind("<Configure>", self._rewrap, add="+")
        scroller.bind("<Configure>",
                      lambda event: scroller.itemconfigure(body_id, width=event.width))
        self._wheel_sequences = bind_wheel_scrolling(scroller)

        footer = tk.Frame(self, bg=c["background"], padx=22, pady=12)
        footer.pack(fill="x")
        self._binder.register(footer, "background", window=self)
        close = tk.Button(footer, text="Got it — start typing", command=self.close,
                          relief="flat", padx=16, pady=6,
                          font=("Segoe UI", 10, "bold"))
        close.pack(side="right")
        self._binder.register(close, "accent", window=self)
        self._hint = tk.Label(footer, text="Tip: press F1 at any time to reopen this guide.",
                              bg=c["background"], fg=c["muted"], font=("Segoe UI", 9))
        self._hint.pack(side="left")
        self._binder.register(self._hint, "muted", window=self)

        self._section_widgets: List[object] = []
        self._text_labels: List[tk.Label] = []
        self.render()

    # ------------------------------------------------------------------
    def _clear_filter(self):
        self.filter_var.set("")
        self.render()

    def _rewrap(self, event=None):
        """Keep the description column inside the window as it is resized."""
        width = getattr(event, "width", 0)
        if not width:
            try:
                width = self._body.winfo_width()
            except tk.TclError:
                return
        wraplength = max(260, int(width) - 320)
        for label in self._text_labels:
            try:
                label.configure(wraplength=wraplength)
            except tk.TclError:
                pass

    def _theme_section_widget(self, widget, role):
        self._section_widgets.append(widget)
        self._binder.register(widget, role, window=self)
        return widget

    def render(self):
        """(Re)draw the guide body, honouring the search box."""
        try:
            for widget in self._section_widgets:
                widget.destroy()
        except tk.TclError:
            pass
        self._section_widgets = []
        self._text_labels = []

        c = self.colours
        query = self.filter_var.get()
        sections = filter_guide(GUIDE_SECTIONS, query)

        if not sections:
            empty = self._theme_section_widget(
                tk.Label(self._body, text=f"No topic matches “{query.strip()}”.",
                         bg=c["background"], fg=c["muted"], font=("Segoe UI", 10)),
                "muted")
            empty.pack(anchor="w", pady=20)
            self._count_label.configure(text="0 topics shown — try WPM, colours or stop.")
            return

        shown = sum(len(section.items) for section in sections)
        self._count_label.configure(
            text=f"Showing {shown} of {guide_item_count()} topics"
                 + (f" — matching “{query.strip()}”" if query.strip() else ""))

        for section in sections:
            block = tk.Frame(self._body, bg=c["background"])
            block.pack(fill="x", pady=(14, 4))
            self._theme_section_widget(block, "background")
            title = self._theme_section_widget(
                tk.Label(block, text=section.title, bg=c["background"], fg=c["primary"],
                         font=("Segoe UI", 12, "bold")), "heading")
            title.pack(anchor="w")
            blurb = self._theme_section_widget(
                tk.Label(block, text=section.blurb, bg=c["background"], fg=c["muted"],
                         font=("Segoe UI", 9)), "muted")
            blurb.pack(anchor="w", pady=(1, 6))

            for item in section.items:
                row = tk.Frame(block, bg=c["background"])
                row.pack(fill="x", pady=2)
                self._theme_section_widget(row, "background")
                name = self._theme_section_widget(
                    tk.Label(row, text=item.name, bg=c["background"],
                             fg=c["foreground"], font=("Segoe UI", 9, "bold"),
                             anchor="nw", justify="left", width=30), "body")
                name.grid(row=0, column=0, sticky="nw", padx=(0, 10))
                text = self._theme_section_widget(
                    tk.Label(row, text=item.text, bg=c["background"],
                             fg=c["foreground"], font=("Segoe UI", 9),
                             anchor="nw", justify="left", wraplength=470), "body")
                text.grid(row=0, column=1, sticky="nw")
                self._text_labels.append(text)
                row.columnconfigure(1, weight=1)

        self._scroller.configure(scrollregion=self._scroller.bbox("all"))

    def apply_palette(self, colours: Dict[str, str]):
        """Repaint the guide when the app palette changes underneath it."""
        self.colours = dict(colours)
        self.configure(background=self.colours["background"])
        self._binder.apply(self.colours)
        try:
            self._scroller.configure(bg=self.colours["background"])
        except tk.TclError:
            pass

    def close(self):
        release_wheel_scrolling(self, getattr(self, "_wheel_sequences", ()))
        self._binder.forget(self)
        if self._on_close is not None:
            try:
                self._on_close()
            except tk.TclError:
                pass
        try:
            self.destroy()
        except tk.TclError:
            pass


class _HoverTip:
    """A small hover help bubble for one widget.

    Deliberately lazy: nothing is created until the pointer actually rests on
    the widget, and every Tk call is guarded, so a window manager that dislikes
    override-redirect windows cannot break the app.
    """

    def __init__(self, widget, text: str, delay: int = 550, wraplength: int = 330):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _schedule(self, event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._after_id = None

    def _show(self):
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            self._tip = tk.Toplevel(self.widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self._tip, text=self.text, justify="left", background="#111827",
                     foreground="#F9FAFB", relief="solid", borderwidth=1,
                     wraplength=self.wraplength, font=("Segoe UI", 9),
                     padx=8, pady=6).pack()
            self._tip.wm_attributes("-topmost", True)
        except tk.TclError:
            self._tip = None

    def _hide(self, event=None):
        self._cancel()
        tip, self._tip = self._tip, None
        if tip is None:
            return
        try:
            tip.destroy()
        except tk.TclError:
            pass


def attach_tooltip(widget, text: str):
    """Best-effort hover help: never raises, never blocks the interface."""
    if tk is None or not text:
        return None
    try:
        return _HoverTip(widget, text)
    except Exception:
        return None


class AutoTyperApp(_TkBase):
    """The V2 desktop interface.

    The simulator remains Tk-free outside this class. All visual state lives
    here so the planner and trace engine can still be tested headlessly.
    """

    def __init__(self):
        super().__init__()
        self.title("AutoTyper — Biomechanical Keystroke Simulator")
        self.geometry("820x900")
        self.minsize(700, 680)
        self.resizable(True, True)

        self.is_running = False
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self.worker_thread = None
        saved_settings = self._load_ui_settings()
        self.custom_palettes = sanitise_custom_palettes(saved_settings.get("custom_palettes"))
        self.palette_name = saved_settings.get("palette", DEFAULT_PALETTE)
        if self.palette_name not in self.available_palettes():
            self.palette_name = DEFAULT_PALETTE
        self.palette_var = tk.StringVar(value=self.palette_name)
        self.topmost_var = tk.BooleanVar(value=bool(saved_settings.get("topmost", True)))
        self.guide_seen = bool(saved_settings.get("guide_seen", False))
        self.colors = _palette_colours(self.palette_name, self.available_palettes())
        # One registry paints the whole main window, so a palette switch never
        # has to know which widgets exist.
        self._binder = PaletteBinder(self.colors)
        self._settings_binder = PaletteBinder(self.colors)
        self._settings_window = None
        self._settings_cards = []
        self._palette_grid = None
        self._custom_hint = None
        self._custom_editor = None
        self._guide_window = None
        self._preview_widgets = {}
        self._comboboxes = []
        self._download_thread = None
        self.count_var = tk.StringVar(value="")

        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except tk.TclError:
            self.style = ttk.Style(self)

        self._configure_styles()
        self._build_ui()
        self._apply_palette(self.palette_name)
        self._apply_topmost()
        self._bind_shortcuts()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_id = self.after(50, self._poll_queue)
        self._start_update_check()
        if not self.guide_seen:
            # First launch: show what everything does, once.
            self.after(600, self._open_guide)

    # ------------------------------------------------------------------
    # Theming helpers
    # ------------------------------------------------------------------
    def _card(self, parent, title: str, subtitle: str = "", expand: bool = False):
        """A titled panel with consistent spacing; returns the body to fill.

        ``expand`` lets the card absorb spare vertical space — used by the text
        card so the editor grows with the window instead of leaving a gap.
        """
        c = self.colors
        card = tk.Frame(parent, bg=c["background"], highlightthickness=1,
                        highlightbackground=c["surface"], highlightcolor=c["surface"],
                        padx=16, pady=13)
        if expand:
            card.pack(fill="both", expand=True, pady=(0, 12))
        else:
            card.pack(fill="x", pady=(0, 12))
        self._binder.register(card, "card", window="main")
        heading = tk.Label(card, text=title, bg=c["background"], fg=c["primary"],
                           font=("Segoe UI", 11, "bold"))
        heading.pack(anchor="w")
        self._binder.register(heading, "heading", window="main")
        if subtitle:
            note = tk.Label(card, text=subtitle, bg=c["background"], fg=c["muted"],
                            font=("Segoe UI", 9))
            note.pack(anchor="w", pady=(1, 9))
            self._binder.register(note, "muted", window="main")
        body = tk.Frame(card, bg=c["background"])
        body.pack(fill="both", expand=True)
        self._binder.register(body, "background", window="main")
        return body

    def _row(self, body, row: int, label: str, widget, tip: str = "", pady: int = 5):
        """Place a right-aligned control with its label on the left."""
        c = self.colors
        caption = tk.Label(body, text=label, bg=c["background"], fg=c["foreground"],
                           font=("Segoe UI", 10), anchor="w")
        caption.grid(row=row, column=0, sticky="w", pady=pady)
        self._binder.register(caption, "body", window="main")
        widget.grid(row=row, column=1, sticky="e", pady=pady)
        if tip:
            attach_tooltip(caption, tip)
        return widget

    def _check_row(self, body, row: int, text: str, variable, tip: str = ""):
        widget = ttk.Checkbutton(body, text=text, variable=variable,
                                 style="App.TCheckbutton")
        widget.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        if tip:
            attach_tooltip(widget, tip)
        return widget

    def _paint_text_box(self):
        if not hasattr(self, "text_box"):
            return
        c = self.colors
        self.text_box.configure(
            background=c["surface"], foreground=c["foreground"],
            insertbackground=c["accent"], selectbackground=c["accent"],
            selectforeground=c["accent_foreground"],
            highlightbackground=c["primary"], highlightcolor=c["accent"])

    def _bind_shortcuts(self):
        """Ctrl+Enter starts, Esc stops, F1 opens the guide."""
        try:
            self.bind("<Control-Return>", self._shortcut_start)
            self.bind("<Control-KP_Enter>", self._shortcut_start)
            self.bind("<Escape>", self._shortcut_stop)
            self.bind("<F1>", self._shortcut_guide)
        except tk.TclError:
            pass

    def _shortcut_start(self, event=None):
        if not self.is_running:
            self.start_process()
        return "break"

    def _shortcut_stop(self, event=None):
        if self.is_running:
            self.stop_process()
        return "break"

    def _shortcut_guide(self, event=None):
        self._open_guide()
        return "break"

    # ------------------------------------------------------------------
    # Theme and settings window
    # ------------------------------------------------------------------
    def _configure_styles(self):
        c = self.colors
        self.style.configure("App.TFrame", background=c["background"])
        self.style.configure("App.TLabel", background=c["background"], foreground=c["foreground"])
        self.style.configure("Title.TLabel", background=c["background"], foreground=c["primary"],
                             font=("Segoe UI", 20, "bold"))
        self.style.configure("Subtitle.TLabel", background=c["background"], foreground=c["muted"],
                             font=("Segoe UI", 9))
        self.style.configure("App.TLabelframe", background=c["background"], foreground=c["foreground"])
        self.style.configure("App.TLabelframe.Label", background=c["background"], foreground=c["primary"],
                             font=("Segoe UI", 10, "bold"))
        self.style.configure("App.TButton", background=c["primary"], foreground=c["button_foreground"],
                             padding=(12, 7), font=("Segoe UI", 9, "bold"))
        self.style.map("App.TButton", background=[("active", c["accent"]), ("pressed", c["primary"])])
        self.style.configure("Accent.TButton", background=c["accent"], foreground=c["accent_foreground"],
                             padding=(13, 8), font=("Segoe UI", 10, "bold"))
        self.style.map("Accent.TButton", background=[("active", c["primary"]), ("pressed", c["primary"])])
        self.style.configure("Stop.TButton", background="#B91C1C", foreground="#FFFFFF",
                             padding=(13, 8), font=("Segoe UI", 10, "bold"))
        self.style.map("Stop.TButton", background=[("active", "#DC2626"), ("pressed", "#991B1B")])
        self.style.configure("App.TCheckbutton", background=c["background"], foreground=c["foreground"])
        self.style.map("App.TCheckbutton", background=[("active", c["background"])])
        self.style.configure(
            "App.TCombobox",
            fieldbackground=c["surface"],
            background=c["surface"],
            foreground=c["foreground"],
            arrowcolor=c["foreground"],
        )
        self.style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", c["surface"]), ("disabled", c["surface"])],
            foreground=[("readonly", c["foreground"]), ("disabled", c["muted"])],
            selectbackground=[("readonly", c["accent"])],
            selectforeground=[("readonly", c["accent_foreground"])],
            background=[("active", c["accent"]), ("readonly", c["surface"])],
        )
        self.style.configure("App.TSpinbox", fieldbackground=c["surface"], background=c["surface"],
                             foreground=c["foreground"])
        self.style.configure("App.TEntry", fieldbackground=c["surface"], background=c["surface"],
                             foreground=c["foreground"], padding=(6, 4))
        self.style.configure("App.Horizontal.TProgressbar", background=c["accent"], troughcolor=c["surface"])
        self.style.configure("App.Vertical.TScrollbar", background=c["surface"],
                             troughcolor=c["background"], bordercolor=c["surface"],
                             arrowcolor=c["foreground"], lightcolor=c["surface"],
                             darkcolor=c["surface"])
        self.style.map("App.Vertical.TScrollbar", background=[("active", c["accent"])])

    @staticmethod
    def _ui_settings_path() -> Path:
        return Path.home() / ".autotyper_settings.json"

    @staticmethod
    def _legacy_ui_settings_paths() -> Tuple[Path, ...]:
        """Where earlier releases of this app stored the same preferences."""
        return (Path.home() / ".pascal_typing_v2_settings.json",)

    def _load_ui_settings(self) -> Dict[str, object]:
        for path in (self._ui_settings_path(), *self._legacy_ui_settings_paths()):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(data, dict):
                return data
        return {}

    def _save_ui_settings(self):
        """Persist small UI preferences outside the repository."""
        try:
            path = self._ui_settings_path()
            path.write_text(json.dumps({
                "palette": self.palette_name,
                "topmost": bool(self.topmost_var.get()),
                "guide_seen": bool(self.guide_seen),
                "custom_palettes": {name: list(triple)
                                    for name, triple in self.custom_palettes.items()},
            }, indent=2) + "\n", encoding="utf-8")
        except (OSError, TypeError, tk.TclError):
            # A read-only home directory must not stop the typer.
            pass

    # ------------------------------------------------------------------
    # Custom UI colours
    # ------------------------------------------------------------------
    def available_palettes(self) -> Dict[str, Tuple[str, str, str]]:
        """Built-in palettes plus every custom palette the user has saved."""
        return merged_palettes(getattr(self, "custom_palettes", {}))

    def is_custom_palette(self, name: str) -> bool:
        return name in getattr(self, "custom_palettes", {})

    def _open_custom_editor(self, name: Optional[str] = None):
        """Open the colour hexagon editor for a new or existing custom palette."""
        if self._custom_editor is not None:
            try:
                if self._custom_editor.winfo_exists():
                    self._custom_editor.deiconify()
                    self._custom_editor.lift()
                    return
            except tk.TclError:
                pass
        if name is None and len(self.custom_palettes) >= MAX_CUSTOM_PALETTES:
            messagebox.showinfo(
                "Custom colours full",
                f"You can keep up to {MAX_CUSTOM_PALETTES} custom palettes. "
                "Delete one before saving another.")
            return
        initial = self.custom_palettes.get(name) if name else self.available_palettes()[self.palette_name]
        self._custom_editor = CustomPaletteEditor(
            self, self.colors,
            on_save=self._save_custom_palette,
            initial=initial,
            initial_name=name or "My Colours",
            editing=name,
            topmost=bool(self.topmost_var.get()),
        )

    def _save_custom_palette(self, name: str, triple: Tuple[str, str, str],
                             editing: Optional[str] = None):
        """Store a palette from the editor, then select it immediately."""
        cleaned = sanitise_custom_palettes({name: list(triple)})
        if not cleaned:
            return
        name = next(iter(cleaned))
        new_triple = cleaned[name]
        if editing and editing in self.custom_palettes:
            # Rebuild in place so renaming keeps the palette's grid position.
            updated = {}
            for existing_name, existing_triple in self.custom_palettes.items():
                if existing_name == editing:
                    updated[name] = new_triple
                else:
                    updated[existing_name] = existing_triple
            self.custom_palettes = updated
        else:
            if name in self.available_palettes():
                name = unique_palette_name(name, self.available_palettes())
            self.custom_palettes[name] = new_triple
        self._refresh_palette_cards()
        self._apply_palette(name)

    def _delete_custom_palette(self):
        """Remove the selected custom palette (built-ins cannot be deleted)."""
        name = self.palette_name
        if not self.is_custom_palette(name):
            messagebox.showinfo(
                "Nothing to delete",
                "Select one of your own saved colours first — built-in palettes stay put.")
            return
        if not messagebox.askyesno("Delete custom colours", f"Delete the palette “{name}”?"):
            return
        self.custom_palettes.pop(name, None)
        self._refresh_palette_cards()
        self._apply_palette(DEFAULT_PALETTE)

    def _apply_palette(self, name: str):
        """Switch palette: restyle everything that is currently on screen."""
        palettes = self.available_palettes()
        if name not in palettes:
            name = DEFAULT_PALETTE
        self.palette_name = name
        self.palette_var.set(name)
        self.colors = _palette_colours(name, palettes)
        self._save_ui_settings()
        self.configure(background=self.colors["background"])
        self._configure_styles()
        self._binder.apply(self.colors)
        self._paint_text_box()
        self._refresh_palette_cards()
        self._refresh_settings_window()
        self._style_combobox_dropdowns()
        self._restyle_open_windows(self.colors)

    def _restyle_open_windows(self, colours: Dict[str, str]):
        """Repaint the guide and the colour studio if they are open."""
        guide = getattr(self, "_guide_window", None)
        if guide is not None:
            try:
                if guide.winfo_exists():
                    guide.apply_palette(colours)
            except tk.TclError:
                self._guide_window = None
        editor = getattr(self, "_custom_editor", None)
        if editor is not None:
            try:
                if editor.winfo_exists():
                    editor.apply_palette(colours)
            except tk.TclError:
                self._custom_editor = None

    def _style_combobox_dropdowns(self):
        """Apply the palette to the native ttk combobox pop-down list.

        ttk styles control the closed field, but Tk creates the opened listbox
        as a separate native widget. Without this extra step, dark themes
        still show a white dropdown menu and white selection text.
        """
        c = self.colors
        for combo in getattr(self, "_comboboxes", []):
            try:
                popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
                listbox = f"{popdown}.f.l"
                combo.tk.call(
                    listbox,
                    "configure",
                    "-background", c["surface"],
                    "-foreground", c["foreground"],
                    "-selectbackground", c["accent"],
                    "-selectforeground", c["accent_foreground"],
                    "-highlightbackground", c["primary"],
                    "-highlightcolor", c["accent"],
                )
            except tk.TclError:
                # The pop-down may not have been created yet, or a platform
                # theme may use a different internal widget path. The closed
                # combobox is still styled by App.TCombobox.
                pass

    def _apply_topmost(self):
        try:
            self.wm_attributes("-topmost", bool(self.topmost_var.get()))
            if self.topmost_var.get():
                self.lift()
            self._save_ui_settings()
        except tk.TclError:
            # Some window managers do not expose -topmost. The rest of the
            # settings menu and the app remain usable on those systems.
            pass

    def _choose_palette(self, name: str):
        self._apply_palette(name)

    def _open_settings(self):
        """Appearance & Window Settings, built from tidy cards."""
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            return

        c = self.colors
        window = tk.Toplevel(self)
        self._settings_window = window
        window.title("AutoTyper — Appearance & Window Settings")
        window.geometry("760x840")
        window.minsize(660, 560)
        window.configure(background=c["background"])
        window.protocol("WM_DELETE_WINDOW", self._close_settings)
        if self.topmost_var.get():
            try:
                window.wm_attributes("-topmost", True)
            except tk.TclError:
                pass

        # The palette grid and the custom colour section together are taller
        # than a laptop screen, so the whole body scrolls.
        scroller = tk.Canvas(window, bg=c["background"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=scroller.yview,
                                  style="App.Vertical.TScrollbar")
        scroller.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroller.pack(side="left", fill="both", expand=True)
        outer = tk.Frame(scroller, bg=c["background"], padx=22, pady=18)
        body_id = scroller.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>",
                   lambda event: scroller.configure(scrollregion=scroller.bbox("all")))
        scroller.bind("<Configure>",
                      lambda event: scroller.itemconfigure(body_id, width=event.width))
        self._settings_wheel_sequences = bind_wheel_scrolling(scroller)
        self._settings_scroller = scroller
        self._settings_binder.register(scroller, "background", window="settings")
        self._settings_binder.register(outer, "background", window="settings")

        self._settings_title = tk.Label(outer, text="Appearance & Window Settings",
                                        bg=c["background"], fg=c["primary"],
                                        font=("Segoe UI", 18, "bold"))
        self._settings_title.pack(anchor="w")
        self._settings_subtitle = tk.Label(
            outer,
            text="Choose a palette, design your own colours, and keep the typer "
                 "visible while you work.",
            bg=c["background"], fg=c["muted"], font=("Segoe UI", 10))
        self._settings_subtitle.pack(anchor="w", pady=(2, 14))
        self._settings_binder.register(self._settings_title, "heading", window="settings")
        self._settings_binder.register(self._settings_subtitle, "muted", window="settings")

        palette_card = self._settings_card(
            outer, "Colour palette",
            "Click a card to apply it everywhere, instantly. Your choice is remembered.",
            expand=True)
        grid = tk.Frame(palette_card, bg=c["background"])
        grid.pack(fill="both", expand=True)
        self._settings_binder.register(grid, "background", window="settings")
        self._palette_grid = grid

        custom_card = self._settings_card(
            outer, "Custom UI colour",
            "Design your own palette on the Paint-style colour studio and save it "
            "with the built-ins.")
        self._custom_hint = tk.Label(
            custom_card, text="", bg=c["background"], fg=c["muted"], font=("Segoe UI", 9),
            justify="left", anchor="w")
        self._custom_hint.pack(anchor="w", pady=(0, 8))
        self._settings_binder.register(self._custom_hint, "muted", window="settings")
        custom_buttons = tk.Frame(custom_card, bg=c["background"])
        custom_buttons.pack(anchor="w")
        self._settings_binder.register(custom_buttons, "background", window="settings")
        ttk.Button(custom_buttons, text="🎨 New colours…", style="Accent.TButton",
                   command=lambda: self._open_custom_editor(None)).pack(side="left")
        ttk.Button(custom_buttons, text="Edit selected", style="App.TButton",
                   command=self._edit_selected_custom_palette).pack(side="left", padx=(8, 0))
        ttk.Button(custom_buttons, text="Delete selected", style="App.TButton",
                   command=self._delete_custom_palette).pack(side="left", padx=(8, 0))

        window_card = self._settings_card(
            outer, "Window & updates",
            "How AutoTyper behaves while you work, and how it keeps itself current.")
        self._topmost_checkbutton = tk.Checkbutton(
            window_card,
            text="Keep AutoTyper above other applications (so it cannot hide behind "
                 "your editor)",
            variable=self.topmost_var,
            command=self._apply_topmost,
            bg=c["background"], fg=c["foreground"],
            activebackground=c["background"], activeforeground=c["foreground"],
            selectcolor=c["surface"], anchor="w", justify="left")
        self._topmost_checkbutton.pack(anchor="w")
        self._settings_binder.register(self._topmost_checkbutton, "selectable",
                                       window="settings",
                                       selectcolor=c["surface"])
        controls = tk.Frame(window_card, bg=c["background"])
        controls.pack(anchor="w", pady=(10, 0))
        self._settings_binder.register(controls, "background", window="settings")
        self._update_check_button = ttk.Button(controls, text="Check for updates now",
                                               style="App.TButton",
                                               command=self._manual_update_check)
        self._update_check_button.pack(side="left")
        self._download_exe_button = ttk.Button(controls,
                                               text="⬇ Download latest AutoTyper.exe",
                                               style="App.TButton",
                                               command=self._start_exe_download)
        self._download_exe_button.pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="❓ Open the guide", style="App.TButton",
                   command=self._open_guide).pack(side="left", padx=(8, 0))

        preview_card = self._settings_card(
            outer, "Live preview", "Your palette on a sample title, body and button.")
        preview = tk.Frame(preview_card, bg=c["background"], height=92)
        preview.pack(fill="x")
        preview.pack_propagate(False)
        self._settings_binder.register(preview, "background", window="settings")
        self._preview_widgets = {
            "frame": preview,
            "title": tk.Label(preview, text="AutoTyper", font=("Segoe UI", 13, "bold")),
            "body": tk.Label(preview, text="Settings preview — your selected palette is "
                                           "applied immediately.",
                             font=("Segoe UI", 9)),
            "button": tk.Button(preview, text="Accent button", relief="flat", padx=12, pady=4),
        }
        self._preview_widgets["title"].pack(side="left", padx=(4, 20), pady=24)
        self._preview_widgets["body"].pack(side="left", fill="x", expand=True, pady=24)
        self._preview_widgets["button"].pack(side="right", padx=4, pady=22)

        footer = tk.Frame(outer, bg=c["background"])
        footer.pack(fill="x", pady=(6, 0))
        self._settings_binder.register(footer, "background", window="settings")
        ttk.Button(footer, text="Close", style="App.TButton",
                   command=self._close_settings).pack(side="right")
        self._settings_hint = tk.Label(
            footer, text="Every option applies immediately — there is no OK button.",
            bg=c["background"], fg=c["muted"], font=("Segoe UI", 9))
        self._settings_hint.pack(side="left")
        self._settings_binder.register(self._settings_hint, "muted", window="settings")

        self._refresh_palette_cards()
        self._refresh_settings_window()

    def _settings_card(self, parent, title: str, subtitle: str = "", expand: bool = False):
        """A titled card for the settings window; returns the body to fill."""
        c = self.colors
        card = tk.Frame(parent, bg=c["background"], highlightthickness=1,
                        highlightbackground=c["surface"], highlightcolor=c["surface"],
                        padx=14, pady=12)
        card.pack(fill="both" if expand else "x", expand=expand, pady=(0, 12))
        self._settings_binder.register(card, "card", window="settings")
        heading = tk.Label(card, text=title, bg=c["background"], fg=c["primary"],
                           font=("Segoe UI", 11, "bold"))
        heading.pack(anchor="w")
        self._settings_binder.register(heading, "heading", window="settings")
        if subtitle:
            note = tk.Label(card, text=subtitle, bg=c["background"], fg=c["muted"],
                            font=("Segoe UI", 9), justify="left", anchor="w")
            note.pack(anchor="w", pady=(1, 8))
            self._settings_binder.register(note, "muted", window="settings")
        body = tk.Frame(card, bg=c["background"])
        body.pack(fill="both", expand=True)
        self._settings_binder.register(body, "background", window="settings")
        return body

    def _bind_settings_mousewheel(self, scroller):
        """Scroll the settings body with the wheel (kept for compatibility)."""
        self._settings_wheel_sequences = bind_wheel_scrolling(scroller)
        return self._settings_wheel_sequences

    def _edit_selected_custom_palette(self):
        if not self.is_custom_palette(self.palette_name):
            messagebox.showinfo(
                "Pick your own colours first",
                "Select one of your saved custom palettes to edit it, or press "
                "“New colours…” to design one from the colour studio.")
            return
        self._open_custom_editor(self.palette_name)

    def _refresh_palette_cards(self):
        """(Re)build the palette grid so saved custom colours appear in it."""
        grid = self._palette_grid
        if grid is None:
            return
        try:
            if not grid.winfo_exists():
                return
        except tk.TclError:
            return
        for child in grid.winfo_children():
            child.destroy()
        self._settings_cards = []

        c = self.colors
        palettes = self.available_palettes()
        columns = 4
        for column in range(columns):
            grid.columnconfigure(column, weight=1)
        rows = max(1, (len(palettes) + columns - 1) // columns)
        for row in range(rows):
            grid.rowconfigure(row, weight=1)

        for index, name in enumerate(palettes):
            custom = self.is_custom_palette(name)
            card = tk.Frame(grid, bg=c["background"], padx=7, pady=7,
                            highlightthickness=1, highlightbackground=c["surface"])
            card.grid(row=index // columns, column=index % columns, sticky="nsew",
                      padx=4, pady=4)
            radio = tk.Radiobutton(card, text=("★ " + name) if custom else name,
                                   variable=self.palette_var, value=name,
                                   command=lambda selected=name: self._choose_palette(selected),
                                   anchor="w", justify="left", wraplength=135,
                                   bg=c["background"], fg=c["foreground"],
                                   activebackground=c["background"],
                                   activeforeground=c["foreground"],
                                   selectcolor=c["surface"], font=("Segoe UI", 9))
            radio.pack(fill="x", anchor="w")
            swatches = tk.Frame(card, bg=c["background"])
            swatches.pack(anchor="w", pady=(5, 0))
            for colour in palettes[name]:
                tk.Frame(swatches, width=28, height=16, bg=colour,
                         highlightthickness=1,
                         highlightbackground=c["foreground"]).pack(side="left", padx=(0, 3))
            self._settings_cards.append((card, radio, swatches, name))

            # Make the whole card, including whitespace and colour swatches,
            # behave like one large palette selector instead of requiring a
            # precise click on the radio control.
            for selectable in (card, radio, swatches, *swatches.winfo_children()):
                selectable.bind("<Button-1>",
                                lambda event, selected=name: self._choose_palette(selected))
            if custom:
                for selectable in (card, radio, swatches, *swatches.winfo_children()):
                    selectable.bind("<Double-Button-1>",
                                    lambda event, selected=name: self._open_custom_editor(selected))

        if self._custom_hint is not None:
            try:
                saved = len(self.custom_palettes)
                self._custom_hint.configure(
                    text=("Pick a primary, accent and background colour on the colour "
                          "studio — gradient, swatches or hexagon — then name and save "
                          "it.\n"
                          f"Saved custom palettes: {saved} of {MAX_CUSTOM_PALETTES}"
                          " — they appear with a ★ above (double-click one to edit it)."))
            except tk.TclError:
                pass

    def _refresh_settings_window(self):
        if self._settings_window is None:
            return
        try:
            if not self._settings_window.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.colors
        self._settings_window.configure(background=c["background"])
        self._settings_binder.apply(c)
        try:
            self._settings_scroller.configure(bg=c["background"])
        except (tk.TclError, AttributeError):
            pass
        for card, radio, swatches, name in self._settings_cards:
            try:
                card.configure(bg=c["background"],
                               highlightbackground=c["accent"]
                               if name == self.palette_name else c["surface"])
                radio.configure(bg=c["background"], fg=c["foreground"],
                                activebackground=c["background"],
                                activeforeground=c["foreground"],
                                selectcolor=c["surface"])
                swatches.configure(bg=c["background"])
                for chip in swatches.winfo_children():
                    chip.configure(highlightbackground=c["foreground"])
            except tk.TclError:
                continue
        for key, widget in self._preview_widgets.items():
            try:
                if key == "frame":
                    widget.configure(bg=c["background"])
                elif key == "title":
                    widget.configure(bg=c["background"], fg=c["primary"])
                elif key == "body":
                    widget.configure(bg=c["background"], fg=c["foreground"])
                elif key == "button":
                    widget.configure(bg=c["accent"], fg=c["accent_foreground"],
                                     activebackground=c["primary"],
                                     activeforeground=c["button_foreground"])
            except tk.TclError:
                continue

    def _close_settings(self):
        release_wheel_scrolling(self, getattr(self, "_settings_wheel_sequences", ()))
        self._settings_wheel_sequences = ()
        self._settings_binder.forget("settings")
        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except tk.TclError:
                pass
        self._settings_window = None
        self._settings_cards = []
        self._palette_grid = None
        self._custom_hint = None
        self._preview_widgets = {}
        self._settings_scroller = None

    # ------------------------------------------------------------------
    # Guide
    # ------------------------------------------------------------------
    def _open_guide(self):
        """Show the in-app guide (header button, F1, or first launch)."""
        if self._guide_window is not None:
            try:
                if self._guide_window.winfo_exists():
                    self._guide_window.deiconify()
                    self._guide_window.lift()
                    return
            except tk.TclError:
                pass
        self._guide_window = GuideWindow(
            self, self.colors,
            topmost=bool(self.topmost_var.get()),
            on_close=self._forget_guide)
        if not self.guide_seen:
            self.guide_seen = True
            self._save_ui_settings()

    def _forget_guide(self):
        self._guide_window = None

    def _close_guide(self):
        guide = self._guide_window
        self._guide_window = None
        if guide is not None:
            try:
                guide.close()
            except tk.TclError:
                pass

    def _build_ui(self):
        """Main window: header, three tidy cards, and the run footer."""
        c = self.colors

        # ---- header ----------------------------------------------------
        header = tk.Frame(self, bg=c["background"], padx=24, pady=16)
        header.pack(fill="x")
        self._binder.register(header, "background", window="main")
        header.columnconfigure(0, weight=1)
        title = tk.Label(header, text="AutoTyper", bg=c["background"], fg=c["primary"],
                         font=("Segoe UI", 20, "bold"))
        title.grid(row=0, column=0, sticky="w")
        self._binder.register(title, "heading", window="main")
        subtitle = tk.Label(header,
                            text="Biomechanical typing with Pascal-aware block navigation",
                            bg=c["background"], fg=c["muted"], font=("Segoe UI", 9))
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._binder.register(subtitle, "muted", window="main")

        # Grid, not pack: the update button is added to this row later on and
        # Tk does not allow mixing the two managers inside one container.
        buttons = tk.Frame(header, bg=c["background"])
        buttons.grid(row=0, column=1, rowspan=2, sticky="e")
        self._binder.register(buttons, "background", window="main")
        self.guide_btn = ttk.Button(buttons, text="❓ Guide", style="App.TButton",
                                    command=self._open_guide)
        self.guide_btn.grid(row=0, column=0, padx=(0, 6))
        self.settings_btn = ttk.Button(buttons, text="⚙ Settings", style="App.TButton",
                                       command=self._open_settings)
        self.settings_btn.grid(row=0, column=1, padx=(0, 6))
        # Always available: fetches the published AutoTyper.exe from the
        # newest GitHub release, so getting the executable never requires
        # cloning the repository or installing Python.
        self.download_btn = ttk.Button(buttons, text="⬇ Get .exe", style="App.TButton",
                                       command=self._start_exe_download)
        self.download_btn.grid(row=0, column=2)
        # Not gridded here: it only appears when a newer version is found,
        # and clicking it asks before downloading or installing anything.
        self.update_btn = ttk.Button(buttons, text="⬇ Update available", style="App.TButton",
                                     command=self._start_exe_download)
        attach_tooltip(self.guide_btn, "Open the guide: what every control in this window does (F1).")
        attach_tooltip(self.settings_btn, "Palettes, custom colours, always-on-top and updates.")
        attach_tooltip(self.download_btn, "Download the newest published AutoTyper.exe from GitHub.")

        body = tk.Frame(self, bg=c["background"], padx=24, pady=4)
        body.pack(fill="both", expand=True)
        self._binder.register(body, "background", window="main")

        # ---- typing speed ---------------------------------------------
        speed = self._card(body, "Typing speed",
                           "What AutoTyper aims for, and how human it stays.")
        speed.columnconfigure(1, weight=1)
        self.wpm_var = tk.IntVar(value=110)
        self.wpm_entry = ttk.Entry(speed, textvariable=self.wpm_var, width=8,
                                   justify="right", style="App.TEntry")
        self._row(speed, 0, "Target speed (WPM)", self.wpm_entry,
                  tip="20–150 words per minute — the average pace of the whole trace.")
        self.wpm_entry.bind("<FocusOut>", lambda event: self._normalise_entry(self.wpm_var, 20, 150, 0))
        self.wpm_entry.bind("<Return>", lambda event: self._normalise_entry(self.wpm_var, 20, 150, 0))
        self.wpm_scale = tk.Scale(
            speed, from_=20, to=150, orient="horizontal", variable=self.wpm_var,
            resolution=1, showvalue=False, highlightthickness=0, bd=0)
        self.wpm_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 9))
        self._binder.register(self.wpm_scale, "scale", window="main")

        self.typo_var = tk.DoubleVar(value=0.01)
        self.typo_entry = ttk.Entry(speed, textvariable=self.typo_var, width=8,
                                    justify="right", style="App.TEntry")
        self._row(speed, 2, "Base typo rate (%)", self.typo_entry,
                  tip="Chance per keystroke of a natural error episode and its correction.")
        self.typo_entry.bind("<FocusOut>", lambda event: self._normalise_entry(self.typo_var, 0.01, 100.0, 2))
        self.typo_entry.bind("<Return>", lambda event: self._normalise_entry(self.typo_var, 0.01, 100.0, 2))
        self.typo_scale = tk.Scale(
            speed, from_=0.01, to=100.0, orient="horizontal", variable=self.typo_var,
            resolution=0.01, showvalue=False, highlightthickness=0, bd=0)
        self.typo_scale.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 9))
        self._binder.register(self.typo_scale, "scale", window="main")

        self.mode_var = tk.StringVar(value="Net (incl. pauses & fixes)")
        self.mode_combo = ttk.Combobox(
            speed, textvariable=self.mode_var, values=list(MODE_LABELS), state="readonly",
            width=28, style="App.TCombobox", postcommand=self._style_combobox_dropdowns)
        self._row(speed, 4, "Speed definition", self.mode_combo,
                  tip="Net counts pauses and corrections; Gross counts raw keystrokes.")
        self._comboboxes.append(self.mode_combo)

        self.delay_var = tk.IntVar(value=4)
        self.delay_spin = ttk.Spinbox(speed, textvariable=self.delay_var, from_=1, to=30,
                                      width=8, style="App.TSpinbox")
        self._row(speed, 5, "Countdown (seconds)", self.delay_spin,
                  tip="Grace period to click the window you want typed into (1–30s).")

        # ---- editor behaviour -----------------------------------------
        editor = self._card(body, "Editor behaviour",
                            "How the text lands in the window you are typing into.")
        editor.columnconfigure(1, weight=1)

        self.indent_mode_var = tk.StringVar(value="Off (type text as-is)")
        self.indent_combo = ttk.Combobox(
            editor, textvariable=self.indent_mode_var, values=list(INDENT_LABELS),
            state="readonly", width=28, style="App.TCombobox",
            postcommand=self._style_combobox_dropdowns)
        self._row(editor, 0, "Editor indentation", self.indent_combo,
                  tip="Predict and clear the indentation the target editor inserts by itself.")
        self._comboboxes.append(self.indent_combo)

        self.indent_var = tk.IntVar(value=4)
        self.indent_spin = ttk.Spinbox(editor, textvariable=self.indent_var, from_=0, to=16,
                                       width=8, style="App.TSpinbox")
        self._row(editor, 1, "Fixed indent width", self.indent_spin,
                  tip="Spaces per indent level; used by the Fixed width policy only.")

        self.coding_mode_var = tk.BooleanVar(value=True)
        self._check_row(editor, 2, "Pascal coding mode (begin/end navigation)",
                        self.coding_mode_var,
                        tip="Lay down begin … end first, then fill the body in order.")
        self.verify_var = tk.BooleanVar(value=True)
        self._check_row(editor, 3, "Verify and repair target editor", self.verify_var,
                        tip="Read the finished text back and repair it if it differs.")
        self.det_var = tk.BooleanVar(value=False)
        seed_check = ttk.Checkbutton(editor, text="Deterministic seed", variable=self.det_var,
                                     style="App.TCheckbutton")
        seed_check.grid(row=4, column=0, sticky="w", pady=3)
        attach_tooltip(seed_check, "Reuse the same seed to repeat a run exactly.")
        self.seed_var = tk.IntVar(value=12345)
        self.seed_entry = ttk.Spinbox(editor, textvariable=self.seed_var, from_=0,
                                      to=2**31 - 1, width=9, style="App.TSpinbox")
        self.seed_entry.grid(row=4, column=1, sticky="e", pady=3)

        # ---- source text ----------------------------------------------
        text_card = self._card(body, "Text to type",
                               "Paste the source, then press Start AutoTyper.",
                               expand=True)
        toolbar = tk.Frame(text_card, bg=c["background"])
        toolbar.pack(fill="x", pady=(0, 8))
        self._binder.register(toolbar, "background", window="main")
        paste_btn = ttk.Button(toolbar, text="Paste clipboard", style="App.TButton",
                               command=self._paste_clipboard)
        paste_btn.pack(side="left", padx=(0, 6))
        clear_btn = ttk.Button(toolbar, text="Clear", style="App.TButton",
                               command=self._clear_text)
        clear_btn.pack(side="left", padx=(0, 6))
        bench_btn = ttk.Button(toolbar, text="Benchmark", style="App.TButton",
                               command=self._benchmark)
        bench_btn.pack(side="left")
        attach_tooltip(paste_btn, "Replace the text with the contents of the clipboard.")
        attach_tooltip(clear_btn, "Empty the text box.")
        attach_tooltip(bench_btn, "Simulate the trace and report the statistics "
                                  "without pressing a single key.")
        self.count_label = tk.Label(toolbar, textvariable=self.count_var,
                                    bg=c["background"], fg=c["muted"],
                                    font=("Segoe UI", 9))
        self.count_label.pack(side="right")
        self._binder.register(self.count_label, "muted", window="main")

        box = tk.Frame(text_card, bg=c["background"])
        box.pack(fill="both", expand=True)
        self._binder.register(box, "background", window="main")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.text_box = tk.Text(box, height=8, font=("Consolas", 11), wrap="none", undo=True,
                                relief="flat", padx=10, pady=10)
        sy = ttk.Scrollbar(box, orient="vertical", command=self.text_box.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.text_box.xview)
        self.text_box.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.text_box.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.text_box.bind("<Control-a>", self._select_all_text)
        self.text_box.bind("<Control-A>", self._select_all_text)
        self.text_box.bind("<KeyRelease>", lambda event: self._update_count_label())
        self.text_box.bind("<<Paste>>", lambda event: self.after(10, self._update_count_label))
        attach_tooltip(self.text_box, "The text that will be typed. Blank lines and "
                                      "indentation are preserved; lines scroll sideways.")

        # ---- footer ---------------------------------------------------
        footer = tk.Frame(self, bg=c["background"], padx=24, pady=(6, 16))
        footer.pack(fill="x", side="bottom")
        self._binder.register(footer, "background", window="main")
        self.status_label = tk.Label(footer, text="Status: Ready", bg=c["background"],
                                     fg=c["foreground"], font=("Segoe UI", 10, "bold"))
        self.status_label.pack(anchor="w")
        self._binder.register(self.status_label, "body", window="main")
        self.progress = ttk.Progressbar(footer, mode="determinate",
                                        style="App.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(7, 10))

        run_row = tk.Frame(footer, bg=c["background"])
        run_row.pack(fill="x")
        self._binder.register(run_row, "background", window="main")
        run_row.columnconfigure(0, weight=1)
        run_row.columnconfigure(1, weight=1)
        self.start_btn = ttk.Button(run_row, text="Start AutoTyper", style="Accent.TButton",
                                    command=self.start_process)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_btn = ttk.Button(run_row, text="Stop", style="Stop.TButton",
                                   command=self.stop_process, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        attach_tooltip(self.start_btn, "Plan the trace, count down, then type (Ctrl+Enter).")
        attach_tooltip(self.stop_btn, "Stop at the next keystroke boundary (Esc).")
        hint = tk.Label(footer,
                        text="Ctrl+Enter starts · Esc stops · F1 opens the guide · "
                             "AutoTyper types into whichever window has focus",
                        bg=c["background"], fg=c["muted"], font=("Segoe UI", 8))
        hint.pack(anchor="w", pady=(8, 0))
        self._binder.register(hint, "muted", window="main")

        self._normalise_entry(self.wpm_var, 20, 150, 0)
        self._normalise_entry(self.typo_var, 0.01, 100.0, 2)
        self._update_count_label()

    @staticmethod
    def _normalise_entry(variable, minimum: float, maximum: float, decimals: int):
        try:
            value = float(variable.get())
        except (tk.TclError, TypeError, ValueError):
            value = minimum
        value = max(minimum, min(maximum, value))
        variable.set(int(round(value)) if decimals == 0 else round(value, decimals))

    def _clear_text(self):
        self.text_box.delete("1.0", tk.END)
        self._update_count_label()

    def _paste_clipboard(self):
        try:
            content = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Clipboard", "Clipboard is empty or contains non-text data.")
            return
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert("1.0", content)
        self._update_count_label()

    def _text_contents(self) -> str:
        try:
            return self.text_box.get("1.0", "end-1c")
        except tk.TclError:
            return ""

    def _update_count_label(self):
        """Keep the character/line counter next to the toolbar accurate."""
        text = self._text_contents()
        lines = text.count("\n") + 1 if text else 0
        if not text:
            summary = "Empty — paste some text to begin"
        else:
            characters = "character" if len(text) == 1 else "characters"
            line_word = "line" if lines == 1 else "lines"
            summary = f"{len(text):,} {characters} · {lines:,} {line_word}"
        try:
            self.count_var.set(summary)
        except tk.TclError:
            pass

    def _select_all_text(self, event=None):
        self.text_box.tag_add("sel", "1.0", "end")
        return "break"

    def _snapshot_config(self) -> RunConfig:
        try:
            wpm = int(round(float(self.wpm_var.get())))
            typo_percent = float(self.typo_var.get())
            countdown = int(self.delay_var.get())
            indent_width = int(self.indent_var.get())
            seed = int(self.seed_var.get())
        except (tk.TclError, TypeError, ValueError):
            raise tk.TclError("invalid numeric setting")
        return RunConfig(
            wpm=max(20, min(150, wpm)),
            mode=MODE_LABELS[self.mode_var.get()],
            typo_rate=max(0.0001, min(1.0, typo_percent / 100.0)),
            countdown=max(1, min(30, countdown)),
            indent=IndentPolicy(
                mode=INDENT_LABELS[self.indent_mode_var.get()],
                fixed_width=max(0, min(64, indent_width)),
            ),
            coding_mode=self.coding_mode_var.get(),
            verify_editor=self.verify_var.get(),
            seed=seed if self.det_var.get() else None,
        )

    def _benchmark(self):
        try:
            cfg = self._snapshot_config()
        except tk.TclError:
            messagebox.showerror("Error", "Please enter valid numeric configuration values.")
            return
        text = self.text_box.get("1.0", "end-1c")
        stats = run_benchmark(text, cfg.wpm, cfg.typo_rate, cfg.indent, cfg.seed,
                              mode=cfg.mode, coding_mode=cfg.coding_mode)
        src = "input code" if text.strip() else "10,000-char sample"
        messagebox.showinfo("AutoTyper Benchmark",
                            f"Requested: {cfg.wpm} WPM ({cfg.mode}), typo {cfg.typo_rate:.2%}, "
                            f"indent {cfg.indent.mode} on {src}\n\n" + format_stats(stats))

    def _post(self, *msg):
        self.msg_queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_label.config(text=msg[1], foreground=msg[2])
                elif kind == "progress":
                    if msg[2] is not None:
                        self.progress["maximum"] = msg[2]
                    self.progress["value"] = msg[1]
                elif kind == "done":
                    self._finish(msg[1])
                elif kind == "update":
                    self._on_update_available(msg[1])
                elif kind == "update_manual":
                    self._on_manual_update_result(msg[1], msg[2])
                elif kind == "download_result":
                    self._on_download_result(msg[1], msg[2])
                elif kind == "error":
                    self._finish("Failed")
                    messagebox.showerror("Execution Failed", msg[1])
        except queue.Empty:
            pass
        self._poll_id = self.after(50, self._poll_queue)

    def _finish(self, final_status: str):
        self.is_running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text=f"Status: {final_status}", foreground=self.colors["foreground"])

    def start_process(self):
        full_text = self.text_box.get("1.0", "end-1c")
        if not full_text.strip():
            messagebox.showwarning("Warning", "Text box cannot be empty. Paste or type text first.")
            return
        try:
            config = self._snapshot_config()
        except tk.TclError:
            messagebox.showerror("Error", "Please enter valid numeric configuration values.")
            return

        self.stop_event.clear()
        self.is_running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.worker_thread = threading.Thread(target=self._worker, args=(full_text, config), daemon=True)
        self.worker_thread.start()

    def stop_process(self):
        self.stop_event.set()
        self.status_label.config(text="Status: Stopping...", foreground="#DC2626")

    def _on_close(self):
        self.stop_event.set()
        self._close_settings()
        self._close_guide()
        try:
            self.after_cancel(self._poll_id)
        except tk.TclError:
            pass
        self.destroy()

    def _worker(self, text: str, config: RunConfig):
        try:
            self._post("status", "Status: Planning biomechanical trace...", self.colors["muted"])
            streams = RNGStreams.from_seed(config.seed)
            events, info = build_trace(text, config.wpm, config.typo_rate, config.indent, streams,
                                       config.mode, coding_mode=config.coding_mode)
            total_lines = max((e.line for e in events), default=0) + 1 if events else 1
            estimate = info["estimated_wpm"]
            note = f" (trace estimate {estimate:.0f} WPM)"

            for sec in range(config.countdown, 0, -1):
                self._post("status", f"Click target editor! Starting in {sec}s...{note}", self.colors["accent"])
                if not sleep_until(time.monotonic() + 1.0, self.stop_event):
                    self._post("done", "Cancelled")
                    return

            def on_line(line):
                self._post("status", f"Typing line {line + 1} of {total_lines}...", self.colors["accent"])
                self._post("progress", line + 1, None)

            keyboard = KeyboardOutput()
            self._post("progress", 0, total_lines)
            player = TracePlayer(keyboard, self.stop_event, config.playback, on_line=on_line)
            finished = player.play(events)
            if finished and config.verify_editor and not self.stop_event.is_set():
                self._post("status", "Reading focused editor and checking exact text...", self.colors["accent"])
                result = FocusedEditorFeedback(keyboard).verify_or_repair(text)
                if result == "verified":
                    self._post("done", "Completed — verified")
                elif result == "repaired":
                    self._post("done", "Completed — mismatch repaired")
                elif result == "unavailable":
                    self._post("done", "Completed — verification unavailable")
                else:
                    self._post("error", "The focused editor did not match and automatic repair failed.")
            else:
                self._post("done", "Completed" if finished else "Stopped")
        except Exception as err:
            self._post("error", f"{type(err).__name__}: {err}")

    # ------------------------------------------------------------------
    # Updating: check silently, then download the published .exe
    # ------------------------------------------------------------------
    def _start_update_check(self):
        """Compare APP_VERSION with the newest published GitHub release.

        Runs once, in a background daemon thread, every time the window is
        opened. It must never delay startup, and it stays completely silent
        when no newer version exists or when the check cannot be performed
        (offline, GitHub unreachable, malformed response).
        """
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        release = release_to_announce(UpdateChecker().fetch_latest_release(), APP_VERSION)
        if release is not None:
            self._post("update", release)

    def _manual_update_check(self):
        """User-initiated check from the settings window."""
        self._post("status", "Status: Checking for updates...", self.colors["muted"])
        threading.Thread(target=self._manual_update_worker, daemon=True).start()

    def _manual_update_worker(self):
        release = UpdateChecker().fetch_latest_release()
        if release is None or release.version is None:
            self._post("update_manual", "unavailable", None)
        elif is_newer_version(release.version, APP_VERSION):
            self._post("update_manual", "newer", release)
        else:
            self._post("update_manual", "current", release.version)

    def _open_update_page(self):
        webbrowser.open(RELEASES_PAGE_URL)

    def _on_update_available(self, release: ReleaseInfo):
        """Announce an available update without forcing anything."""
        latest = release.version
        self.status_label.config(
            text=f"Status: Update available — v{latest} (you have v{APP_VERSION})",
            foreground=self.colors["accent"],
        )
        try:
            self.update_btn.config(text=f"⬇ Get v{latest} .exe")
            self.update_btn.grid(row=0, column=3, sticky="e", padx=(6, 0))
        except tk.TclError:
            pass
        has_exe = release.exe_asset is not None
        prompt = (
            f"{APP_NAME} v{latest} is available (you have v{APP_VERSION}).\n\n"
            + ("Download and install it now?\n\n" if is_frozen() else
               "Download the new .exe now?\n\n")
            + ("You can keep using this version either way -- updating is always optional."
               if has_exe else
               "This release does not have an .exe attached yet, so the release page "
               "will open in your browser instead.")
        )
        if messagebox.askyesno("Update available", prompt, icon="question", parent=self):
            if has_exe:
                self._start_exe_download()
            else:
                self._open_update_page()

    def _on_manual_update_result(self, outcome: str, release):
        if outcome == "newer":
            self._on_update_available(release)
        elif outcome == "current":
            self._post("status", f"Status: Up to date (v{APP_VERSION})", self.colors["foreground"])
            messagebox.showinfo("Up to date",
                                f"You are running the latest version (v{APP_VERSION}).",
                                parent=self)
        else:
            messagebox.showwarning(
                "Update check unavailable",
                "Could not reach GitHub to check for updates.\n"
                "Check your internet connection and try again.",
                parent=self,
            )

    # ------------------------------------------------------------------
    # Downloading the published AutoTyper.exe
    # ------------------------------------------------------------------
    def _start_exe_download(self):
        """Fetch the newest published .exe in the background (never blocks)."""
        if getattr(self, "_download_thread", None) is not None and self._download_thread.is_alive():
            return  # one download at a time
        self.download_btn.config(state="disabled")
        self._download_thread = threading.Thread(target=self._exe_download_worker, daemon=True)
        self._download_thread.start()

    def _exe_download_worker(self):
        self._post("status", "Status: Looking up the latest release...", self.colors["muted"])
        self._post("progress", 0, None)
        try:
            release = UpdateChecker(timeout=UPDATE_CHECK_TIMEOUT).fetch_latest_release()
            asset = release.exe_asset if release is not None else None
            plan = plan_update(
                frozen=is_frozen(),
                asset=asset,
                target=running_executable(),
                fallback_dir=default_download_dir(),
                version=release.version if release is not None else None,
            )
            if plan.kind == "open_page":
                self._post("download_result", "open_page", plan)
                return
            label = f"v{plan.version}" if plan.version else "the latest release"
            self._post("status", f"Status: Downloading {asset.name} ({label})...", self.colors["accent"])
            path = download_file(
                asset.url,
                plan.destination,
                progress=lambda done, total: self._post("progress", done, total or None),
            )
        except DownloadError as err:
            self._post("download_result", "failed", str(err))
            return
        except Exception as err:  # never let a download crash the UI
            self._post("download_result", "failed", f"{type(err).__name__}: {err}")
            return
        self._post("download_result", plan.kind, (str(path), plan.version))

    def _on_download_result(self, outcome: str, payload):
        """React to a finished download on the Tk main thread."""
        self.download_btn.config(state="normal")
        self.progress["value"] = 0
        if outcome == "failed":
            self._post("status", "Status: Download failed", "#DC2626")
            messagebox.showerror("Download failed",
                                 f"The update could not be downloaded.\n\n{payload}",
                                 parent=self)
            return
        if outcome == "open_page":
            self._post("status", f"Status: No .exe published (v{APP_VERSION})", self.colors["foreground"])
            messagebox.showinfo("No .exe yet", payload.reason, parent=self)
            self._open_update_page()
            return

        path, version = payload
        label = f"v{version}" if version else "the latest build"
        if outcome == "self_update":
            self._post("status", f"Status: Downloaded {label} — ready to install", self.colors["accent"])
            if messagebox.askyesno(
                "Install update",
                f"{APP_NAME} {label} has been downloaded.\n\n"
                "Install it now?\n\n"
                f"The current version is kept as a backup ({Path(path).name}.old), "
                "and the app restarts automatically.",
                icon="question", parent=self,
            ):
                self._install_downloaded_update(path)
            else:
                self._post("status", f"Status: Downloaded {label} (not installed)",
                           self.colors["foreground"])
            return

        # Running from source: the .exe has been saved somewhere sensible.
        self._post("status", f"Status: Saved {Path(path).name} to {Path(path).parent}",
                   self.colors["foreground"])
        messagebox.showinfo(
            "Download complete",
            f"{APP_NAME} {label} was saved to:\n{path}\n\n"
            "Double-click it to run the app without Python.",
            parent=self,
        )
        open_in_file_manager(path)

    def _install_downloaded_update(self, path: str):
        """Swap in the new executable and quit so the swap script can run.

        `path` is the *staged* download in the temp folder; the build it
        replaces is the one currently running.
        """
        try:
            script = install_update_and_restart(path, running_executable())
        except DownloadError as err:
            messagebox.showerror("Could not install the update", str(err), parent=self)
            return
        self._post("status", "Status: Restarting with the new version...", self.colors["accent"])
        try:
            self.update()
        except tk.TclError:
            pass
        messagebox.showinfo(
            "Restarting",
            f"{APP_NAME} will now close and reopen with the new version.\n\n"
            f"(The swap script is {script.name} in your temp folder; your previous "
            "build is kept as a .old backup.)",
            parent=self,
        )
        self._quit_for_restart()

    def _quit_for_restart(self):
        """Close the window without cancelling the pending update."""
        try:
            self.stop_event.set()
            self._close_settings()
            self.after_cancel(self._poll_id)
        except tk.TclError:
            pass
        try:
            self.quit()
            self.destroy()
        except tk.TclError:
            pass


# =============================================================================
# 12. COMMAND LINE ENTRY POINT
# =============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="AutoTyper: Biomechanical Keystroke Simulator")
    ap.add_argument("--benchmark", action="store_true", help="simulate trace and print biomechanical metrics")
    ap.add_argument("--wpm", type=int, default=110, help="target typing speed in words per minute")
    ap.add_argument("--mode", choices=["net", "gross"], default="net", help="speed metric: net throughput or gross cadence")
    ap.add_argument("--typo", type=float, default=3.0, help="baseline typo rate in percent")
    ap.add_argument("--indent", choices=["off", "copy", "smart", "fixed"], default="off",
                     help="editor auto-indent policy to predict and correct for (off/copy/smart/fixed)")
    ap.add_argument("--indent-fixed", type=int, default=0,
                     help="whitespace width the editor always inserts after Enter, fixed indent mode only")
    ap.add_argument("--indent-tab-stop-backspace", action="store_true",
                     help="model an editor where Backspace clears a whole indent level per press")
    ap.add_argument("--coding-mode", action="store_true", help="enable Pascal block lookahead & body navigation")
    ap.add_argument("--max-lookahead", type=int, default=120, help="max lines to look ahead for matching end block")
    ap.add_argument("--seed", type=int, default=None, help="fixed random seed for deterministic reproduction")
    ap.add_argument("--chars", type=int, default=10000, help="characters to simulate in sample corpus")
    ap.add_argument("--file", type=str, default=None, help="file to simulate instead of default sample")
    ap.add_argument("--csv", type=str, default=None, help="export simulated trace to CSV file")
    ap.add_argument("--check-update", action="store_true",
                    help="compare this install's APP_VERSION with the published one and exit")
    ap.add_argument("--download-exe", nargs="?", const="", default=None, metavar="DIR",
                    help="download the published AutoTyper.exe (optionally into DIR) and exit")
    ap.add_argument("--self-update", action="store_true",
                    help="download the published AutoTyper.exe, install it over this build and restart")
    args = ap.parse_args(argv)

    if args.check_update:
        release = UpdateChecker().fetch_latest_release()
        if release is None or release.version is None:
            print(f"Could not check for updates ({RELEASES_API_URL}).")
            return 1
        if is_newer_version(release.version, APP_VERSION):
            print(f"Update available: v{release.version} (this install: v{APP_VERSION}).")
            asset = release.exe_asset
            print(f"Download: {asset.url}" if asset is not None else f"Download: {release.page_url}")
        else:
            print(f"{APP_NAME} is up to date (v{APP_VERSION}; published version: v{release.version}).")
        return 0

    if args.download_exe is not None or args.self_update:
        release = UpdateChecker().fetch_latest_release()
        if release is None or release.version is None:
            print(f"Could not reach GitHub to find the latest release ({RELEASES_API_URL}).",
                  file=sys.stderr)
            return 1
        asset = release.exe_asset
        if asset is None:
            print(f"Release v{release.version} has no .exe attached yet: {release.page_url}",
                  file=sys.stderr)
            return 1
        if args.self_update and is_frozen():
            destination = staging_path(asset)
        else:
            directory = Path(args.download_exe).expanduser() if args.download_exe else default_download_dir()
            destination = directory / sanitise_asset_filename(asset.name)
        print(f"Downloading {asset.name} (v{release.version}) -> {destination}")

        def report(done, total):
            if total:
                print(f"\r  {done / 1048576:6.1f} / {total / 1048576:.1f} MiB", end="", flush=True)

        try:
            path = download_file(asset.url, destination, progress=report)
        except DownloadError as err:
            print(f"\nDownload failed: {err}", file=sys.stderr)
            return 1
        print(f"\r  saved to {path}")
        if args.self_update:
            if not is_frozen():
                print("Not a packaged build, so nothing was replaced; run the .exe above to update.")
                return 0
            try:
                script = install_update_and_restart(path)
            except DownloadError as err:
                print(f"Could not install the update: {err}", file=sys.stderr)
                return 1
            print(f"Update staged ({script.name}); close this program and it will restart on v{release.version}.")
        return 0

    if args.benchmark:
        typo_probability = args.typo / 100.0
        text = ""
        if args.file:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        policy = IndentPolicy(args.indent, args.indent_fixed, args.indent_tab_stop_backspace)
        events, info, used = simulate(text, args.wpm, typo_probability, policy,
                                      args.seed, args.chars, args.mode, coding_mode=args.coding_mode)
        stats = summarize_trace(events, used)
        cm_str = " (coding-mode)" if args.coding_mode else ""
        print(f"=== AutoTyper Biomechanical Trace Simulation ===")
        print(f"Requested: {args.wpm} WPM ({args.mode}){cm_str}   base typo: {args.typo}%   seed: {args.seed}")
        print(f"Calibration estimate: {info['estimated_wpm']:.2f} WPM ({args.mode}), "
              f"trace-to-trace scatter (CV): {info['calibration_cv']:.2%}\n")
        print(format_stats(stats))
        if args.csv:
            export_trace_csv(events, args.csv)
            print(f"\nTrace written to {args.csv}")
        return 0

    if tk is None:
        print("tkinter is not available in this Python install; use --benchmark for headless CLI execution.",
              file=sys.stderr)
        return 1
    AutoTyperApp().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
