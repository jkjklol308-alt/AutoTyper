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
     the executable next to the user's other downloads. Since v1.1.2 the
     restart is started with a clean environment, exactly like a manual
     double-click: PyInstaller's onefile variables are cleared first, so the
     next build unpacks its own files instead of looking for the previous
     process's temporary folder (which made the app die with "Error loading
     Python DLL" straight after an update). Since v1.1.3 the swap is also
     *verified*: a download must match the size the release advertises, the
     restarted build has to signal that its window came up (see
     `mark_startup_complete`), and if it does not, the previous build is
     restored and started again, with the whole exchange written to
     `AutoTyper.log` and `AutoTyper-update.log` so a failure can never be
     silent or unexplained.
 10. Custom UI Colours (v1.1.0, reworked in v1.1.1): a Microsoft-Paint style
     gradient colour picker — a full colour field (rainbow of hues across,
     saturation fading down, drawn at the current shade) plus a white-to-black
     shade strip — that lets you click or drag to any colour, choose a
     primary, accent and background colour, name the result and save it
     alongside the built-in palettes.

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

APP_VERSION = "1.1.3"
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
#   * Restarting is clean: the relaunch is started without PyInstaller's
#     onefile bookkeeping in the environment (see
#     `restart_environment()`), so the new build extracts its own files
#     instead of looking for the previous process's temporary folder.
#
# Why the environment matters: a onefile build keeps the path of its unpacked
# temporary directory in the environment (_PYI_APPLICATION_HOME_DIR, and
# _PYI_ARCHIVE_FILE for the executable itself) and hands both to any process
# it starts. A restart that inherits those variables makes the *new* build
# believe it is the child of a still-running launcher: it skips unpacking and
# loads python3xx.dll straight out of the previous process's folder — which
# has just been deleted — and dies with "Error loading Python DLL" before a
# single line of Python runs. Launching the same file by hand works, because a
# double-click starts with a clean environment. Every relaunch therefore
# scrubs those variables, and the swap script additionally asks the bootloader
# for a reset (PYINSTALLER_RESET_ENVIRONMENT=1) as a second line of defence.

# PyInstaller's onefile bookkeeping. They describe *this* process's unpacked
# files, so they must never be handed to a freshly started build.
PYINSTALLER_RUNTIME_ENV_VARS = (
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_ARCHIVE_FILE",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_SPLASH_IPC",
    "_PYI_LINUX_PROCESS_NAME",
    "_MEIPASS2",
)

# PyInstaller honours this one itself: "1" forces a full environment reset, as
# if the build had been started from a clean shell.
PYINSTALLER_RESET_ENV_VAR = "PYINSTALLER_RESET_ENVIRONMENT"

# Windows environment variable names are case-insensitive, so matching is done
# on upper case copies.
_PYINSTALLER_RUNTIME_ENV_VARS_UPPER = frozenset(name.upper() for name in PYINSTALLER_RUNTIME_ENV_VARS)

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


def restart_environment(env: Optional[dict] = None) -> Dict[str, str]:
    """A copy of the environment with PyInstaller's onefile state removed.

    Everything a freshly started build needs (``PATH``, ``TEMP``, the user's
    Windows folders) is kept; only the variables that describe *this*
    process's unpacked files are dropped, so the new build unpacks its own.
    Used for every relaunch and restart this program performs.
    """
    source = os.environ if env is None else env
    clean: Dict[str, str] = {}
    for name, value in source.items():
        if name.upper() in _PYINSTALLER_RUNTIME_ENV_VARS_UPPER:
            continue
        clean[name] = value
    return clean


#: The PyInstaller onefile variables this process was *started* with, captured
#: before `scrub_pyinstaller_runtime_environment()` deletes them. They are the
#: only evidence of which extraction folder this build was handed: once they
#: are gone, "nothing was inherited" and "we deleted it ourselves" look the
#: same in the environment. `None` means nothing was captured.
STARTUP_RUNTIME_ENV: Optional[Dict[str, str]] = None


def capture_startup_runtime_environment(env=None) -> Dict[str, str]:
    """Remember the PyInstaller variables in ``env`` (default: ours).

    Must run before the scrub. `log_startup_environment()` reports from this
    record, so the log says what the *bootloader* handed us rather than what is
    left after we cleaned up.
    """
    global STARTUP_RUNTIME_ENV
    target = os.environ if env is None else env
    STARTUP_RUNTIME_ENV = {name: value for name, value in target.items()
                           if name.upper() in _PYINSTALLER_RUNTIME_ENV_VARS_UPPER}
    return STARTUP_RUNTIME_ENV


def startup_runtime_env() -> Dict[str, str]:
    """What this process started with, or the live environment if uncaptured."""
    if STARTUP_RUNTIME_ENV is not None:
        return dict(STARTUP_RUNTIME_ENV)
    return {name: value for name, value in os.environ.items()
            if name.upper() in _PYINSTALLER_RUNTIME_ENV_VARS_UPPER}


def describe_onefile_home() -> str:
    """Where this build's unpacked files came from — the "Error loading Python
    DLL" question — as one clause for the log and the update probes.

    Three states, and only the last one is broken:

    * **no `_PYI_APPLICATION_HOME_DIR` at start**: this process unpacked its own
      files; `_MEIPASS` (a property of this process, not an environment
      variable) is therefore this build's own folder. This is the state of a
      build started from a scrubbed environment — the normal post-update case.
    * **a folder equal to `_MEIPASS`**: a onefile child handed its parent's
      extraction directory, which *is* this build's folder.
    * **anything else**: somebody else's folder. That is the reported failure —
      the folder was deleted when the build that owned it exited, so the Python
      DLL is gone by the time this process looks for it.
    """
    home = startup_runtime_env().get("_PYI_APPLICATION_HOME_DIR", "")
    meipass = getattr(sys, "_MEIPASS", None) or ""
    if not home:
        if meipass:
            return f"onefile-home=unset (fresh: this build unpacked its own files into {meipass})"
        return "onefile-home=unset (nothing inherited)"
    if meipass and os.path.normcase(home) == os.path.normcase(meipass):
        return f"onefile-home={home} (own extraction dir)"
    return f"onefile-home={home} (NOT this build's extraction dir {meipass or 'unknown'})"


def scrub_pyinstaller_runtime_environment(env=None) -> List[str]:
    """Delete this process's PyInstaller onefile state from ``env``.

    Called once at start-up so that *any* child process — the update swap
    script, a file manager, anything spawned later — inherits a clean
    environment instead of a description of our own unpacked files.

    ``env`` defaults to ``os.environ``; returns the names actually removed.
    """
    target = os.environ if env is None else env
    removed: List[str] = []
    for name in PYINSTALLER_RUNTIME_ENV_VARS:
        try:
            target.pop(name)
        except (KeyError, TypeError):
            continue
        removed.append(name)
    return removed


# -----------------------------------------------------------------------------
# The log, and the files the app and the swap script pass to each other
# -----------------------------------------------------------------------------
#
# A failed update used to leave nothing behind: the window is gone, the
# bootloader's message box is dismissed, and there is no record of what the old
# build did before it quit. That is exactly how an update can appear to "keep
# failing with the same error" and stay undiagnosed. Three small files change
# that, all of them in one folder:
#
#   AutoTyper.log          what this build is and what it did (version,
#                          executable, onefile environment, update events,
#                          unhandled exceptions)
#   startup-ok             touched by `mark_startup_complete()` once the window
#                          really is up; the swap script waits for it
#   update-result.txt      the swap script's verdict, "ok <version>" or
#                          "rolled-back <version> <detail>", which the next
#                          window reads, reports and clears
#
# The swap script keeps its own log (`AutoTyper-update.log`) next to them, and
# both logs survive the restart, so the story of an update is complete even if
# the new build never gets as far as Python.

APP_DATA_DIR_NAME = APP_NAME


def app_data_dir() -> Path:
    """The folder that holds AutoTyper's log and update hand-off files."""
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    if base:
        return Path(base) / APP_DATA_DIR_NAME
    return Path.home() / f".{APP_DATA_DIR_NAME.lower()}"


def log_file_path() -> Path:
    return app_data_dir() / f"{APP_NAME}.log"


def swap_log_path() -> Path:
    return app_data_dir() / f"{APP_NAME}-update.log"


def startup_marker_path() -> Path:
    return app_data_dir() / "startup-ok"


def update_result_path() -> Path:
    return app_data_dir() / "update-result.txt"


def describe_size(path) -> str:
    """``"1234567 bytes"`` for the log, or a placeholder if it cannot be read.

    Logging must never be the reason an update fails, so an unreadable file is
    described as unknown rather than raised.
    """
    try:
        return f"{Path(path).stat().st_size} bytes"
    except OSError:
        return "size unknown"


def log_event(message: str, *, path: Optional[Path] = None) -> None:
    """Append one timestamped line to the log, and never raise.

    Logging is a diagnostic aid, so a read-only home directory or a full disk
    must not stop the typer (the same rule the settings file follows).
    """
    try:
        target = Path(path) if path is not None else log_file_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] v{APP_VERSION} {message}\n")
    except (OSError, ValueError, TypeError):
        pass


def log_startup_environment() -> None:
    """Record what this build is and what the bootloader handed it.

    Reports the variables captured *before* the scrub (see
    `capture_startup_runtime_environment`), so `onefile-env` lists what this
    process inherited rather than what is left after we cleaned up — the
    distinction the "Error loading Python DLL" failure turns on.
    """
    meipass = getattr(sys, "_MEIPASS", None) or ""
    inherited = sorted(startup_runtime_env())
    where = describe_onefile_home() if is_frozen() else "onefile-home=n/a (source run)"
    log_event(
        "start: "
        f"frozen={is_frozen()} sys.executable={getattr(sys, 'executable', '')!r} "
        f"_MEIPASS={meipass!r} {where} onefile-env={inherited if inherited else 'clean'} "
        f"python={sys.version.split()[0]} platform={sys.platform}"
    )


def mark_startup_complete() -> Path:
    """Signal that this window is up; the update swap script waits for it.

    The marker names the version, so a swap script that knows which build it
    started can also check that the *right* build answered.
    """
    marker = startup_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"v{APP_VERSION} pid={os.getpid()}\n", encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass
    log_event("start: window ready")
    return marker


def clear_startup_marker() -> None:
    try:
        startup_marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def read_update_result() -> Optional[str]:
    """The swap script's verdict from the last update, if it left one."""
    try:
        return update_result_path().read_text(encoding="utf-8").strip() or None
    except (OSError, ValueError, TypeError):
        return None


def clear_update_result() -> None:
    try:
        update_result_path().unlink(missing_ok=True)
    except OSError:
        pass


def report_previous_update(parent=None) -> Optional[str]:
    """Explain what the last update did — but only when it went wrong.

    A successful update stays silent (the app never bothers the user about
    something that worked); a rollback is spelled out, because otherwise the
    user is left with an app that simply refuses to change version, which is
    indistinguishable from "the update keeps failing".
    """
    result = read_update_result()
    if result is None:
        return None
    clear_update_result()
    log_event(f"update: previous run reported {result!r}")
    if result.startswith("ok"):
        return result
    detail = result.split(" ", 2)[2] if len(result.split(" ", 2)) > 2 else result
    if messagebox is not None and tk is not None:
        try:
            messagebox.showwarning(
                "Update rolled back",
                "The last update could not be started, so AutoTyper restored the "
                "previous version and opened it again.\n\n"
                f"What happened: {detail}\n\n"
                f"Details are in:\n{log_file_path()}\n{swap_log_path()}\n\n"
                "You can also update by hand: download AutoTyper.exe from "
                f"{RELEASES_PAGE_URL} and replace this file with it.",
                parent=parent,
            )
        except tk.TclError:
            pass
    return result


def open_path(path) -> bool:
    """Open a file (or folder) with the desktop's default application."""
    path = Path(path)
    try:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606 - Windows shell open
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


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
                  progress=None, opener=None, expected_size: Optional[int] = None) -> Path:
    """Download `url` to `destination` atomically and verify it is complete.

    The payload is written to a temporary ".part" file and only moved into
    place once the transfer finished, arrived in one piece *and* starts with
    the Windows "MZ" header, so a failed, truncated or garbled download can
    never overwrite a good executable. `progress(bytes_done, total_bytes_or_zero)`
    is called as the transfer advances (total is 0 when the server sends no
    length).

    `expected_size` is the size the release advertises for this asset. A short
    download used to pass every check that existed (it is non-empty and it
    starts with "MZ") and would then be *installed*, leaving the user with a
    build that cannot start — one of the ways the same error survives an
    update. Now it is rejected before anything is touched.
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
    declared = 0
    content_encoding = ""
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
                content_encoding = str(headers.get("Content-Encoding") or "").strip().lower()
            declared = total if content_encoding in ("", "identity") else 0
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
    wanted = int(expected_size) if expected_size else declared
    if wanted and written != wanted:
        partial.unlink(missing_ok=True)
        raise DownloadError(
            f"The download was incomplete: {written} of {wanted} bytes arrived "
            f"({written / 1048576:.1f} of {wanted / 1048576:.1f} MiB). "
            "Nothing was installed — please try again."
        )
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


@dataclass(frozen=True)
class UpdateHandoff:
    """The files the app and its swap script exchange across a restart."""

    marker: Path
    result: Path
    log: Path


def update_handoff(directory: Optional[Path] = None) -> UpdateHandoff:
    """Where a swap script looks for the started build and leaves its verdict.

    Defaults to the same folder as the app's log, so a failed update is
    diagnosable from inside the app (⚙ Settings → *Open log file*) without
    asking the user to find anything in %TEMP%.
    """
    base = Path(directory) if directory is not None else app_data_dir()
    return UpdateHandoff(
        marker=base / "startup-ok",
        result=base / "update-result.txt",
        log=base / f"{APP_NAME}-update.log",
    )


def build_windows_swap_script(new_exe, target_exe, wait_seconds: int = 120,
                              backup: bool = True, *, version: Optional[str] = None,
                              handoff: Optional[UpdateHandoff] = None,
                              watch_seconds: int = 60) -> str:
    """A detached .bat that swaps in the new .exe, proves it started, and rolls
    back if it did not.

    Windows locks a running executable, so the copy is retried once a second
    until it succeeds (or `wait_seconds` elapse); `copy` failing while the old
    build is still alive is expected and simply loops. The previous executable
    is copied to "<name>.old" *before* the swap, so a bad build can always be
    rolled back.

    The script also clears PyInstaller's onefile variables and asks the
    bootloader for a full environment reset before starting the new build:
    without that, the relaunched executable inherits the path of this
    process's temporary folder, skips unpacking and fails to load the Python
    DLL (the "error right after an update" that a manual double-click of the
    very same file does not show).

    Starting it is not the same as *it starting*, so the script does not stop
    there. It deletes the start-up marker, launches the new build and waits for
    the new build to write that marker back once its window is up. If the
    marker never appears, the previous build is restored and started again and
    the whole story is written to `handoff.log` / `handoff.result` — the app
    reports it the next time it opens instead of leaving the user with an app
    that silently refuses to update.
    """
    new_path = _bat_quote(new_exe)
    target_path = _bat_quote(target_exe)
    files = handoff if handoff is not None else update_handoff()
    marker = _bat_quote(files.marker)
    result = _bat_quote(files.result)
    log = _bat_quote(files.log)
    version_text = str(version) if version else ""
    # Taken while the old build is still in place: after the swap the target
    # *is* the new build, so a later copy would back up the wrong file.
    backup_lines = 'copy /Y "%TARGET%" "%TARGET%.old" >nul 2>&1\r\n' if backup else ""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "NEW={new_path}"\r\n'
        f'set "TARGET={target_path}"\r\n'
        f'set "VERSION={version_text}"\r\n'
        f'set "TRIES={max(1, int(wait_seconds))}"\r\n'
        f'set "WATCH={max(1, int(watch_seconds))}"\r\n'
        f'set "MARKER={marker}"\r\n'
        f'set "RESULT={result}"\r\n'
        f'set "LOG={log}"\r\n'
        # Start the new build exactly like a hand-launched copy: no unpacked-
        # file paths from this process, and an explicit reset in case something
        # else re-adds them.
        f'set "{PYINSTALLER_RESET_ENV_VAR}=1"\r\n'
        # `set "NAME="` is cmd.exe's documented way to delete a variable: the
        # quotes keep stray whitespace out of the value and an empty value
        # removes the variable from the environment the next build inherits.
        + "".join(f'set "{name}="\r\n' for name in PYINSTALLER_RUNTIME_ENV_VARS)
        + 'for %%F in ("%TARGET%") do set "IMAGE=%%~nxF"\r\n'
        'for %%D in ("%RESULT%") do set "DIR=%%~dpD"\r\n'
        'if not exist "%DIR%" mkdir "%DIR%" >nul 2>&1\r\n'
        "set /a COUNT=0\r\n"
        "set /a GONE=0\r\n"
        '>>"%LOG%" echo [%DATE% %TIME%] v%VERSION%: replacing "%TARGET%" (waiting for it to unlock).\r\n'
        f"{backup_lines}"
        ":waitloop\r\n"
        'copy /Y "%NEW%" "%TARGET%" >nul 2>&1\r\n'
        "if not errorlevel 1 goto installed\r\n"
        "set /a COUNT+=1\r\n"
        "if %COUNT% GEQ %TRIES% goto giveup\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto waitloop\r\n"
        ":installed\r\n"
        'del "%NEW%" >nul 2>&1\r\n'
        'del "%MARKER%" >nul 2>&1\r\n'
        '>>"%LOG%" echo [%DATE% %TIME%] v%VERSION%: copied into place; starting it and waiting for its start-up signal.\r\n'
        'start "" "%TARGET%"\r\n'
        "set /a WAITS=0\r\n"
        ":watch\r\n"
        "rem The marker names the version that wrote it, so a marker left by\r\n"
        "rem some other build is not mistaken for the answer we are waiting for.\r\n"
        'if not exist "%MARKER%" goto watching\r\n'
        'findstr /C:"v%VERSION%" "%MARKER%" >nul 2>&1\r\n'
        "if not errorlevel 1 goto started\r\n"
        ":watching\r\n"
        "set /a WAITS+=1\r\n"
        "if %WAITS% GEQ %WATCH% goto notstarted\r\n"
        # Log the first few waits: if the script ever dies or hangs in here,
        # the log shows how far it got instead of ending at "starting it".
        'if %WAITS% LEQ 3 >>"%LOG%" echo [%DATE% %TIME%] waiting for the start-up signal (%WAITS% of %WATCH%).\r\n'
        # A build that died at once (instead of waiting for a click on its
        # error box) should not keep the user waiting a minute for the
        # rollback, so watch for the process disappearing as well.
        f'tasklist /NH /FI "IMAGENAME eq %IMAGE%" 2>nul | find /I "%IMAGE%" >nul\r\n'
        "if errorlevel 1 goto missing\r\n"
        "set /a GONE=0\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto watch\r\n"
        ":missing\r\n"
        "set /a GONE+=1\r\n"
        "if %GONE% GEQ 10 goto notstarted\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto watch\r\n"
        ":started\r\n"
        '>>"%RESULT%" echo ok v%VERSION%\r\n'
        '>>"%LOG%" echo [%DATE% %TIME%] v%VERSION% started and signalled that its window is up.\r\n'
        "(goto) 2>nul & del \"%~f0\"\r\n"
        ":notstarted\r\n"
        "rem The new build never signalled that it came up: put the previous\r\n"
        "rem build back and start it, so the user still has a working app.\r\n"
        '>>"%RESULT%" echo rolled-back v%VERSION% the new build was installed but never signalled that its window came up\r\n'
        '>>"%LOG%" echo [%DATE% %TIME%] v%VERSION% never signalled its start-up (waited %WATCH%s); restoring "%TARGET%.old".\r\n'
        'copy /Y "%TARGET%.old" "%TARGET%" >nul 2>&1\r\n'
        'del "%MARKER%" >nul 2>&1\r\n'
        'start "" "%TARGET%"\r\n'
        "exit /b 1\r\n"
        ":giveup\r\n"
        "rem The swap never succeeded: bring the existing build back up so the\r\n"
        "rem user is not left without a working program.\r\n"
        '>>"%RESULT%" echo rolled-back v%VERSION% the update file could not be copied over "%TARGET%"\r\n'
        '>>"%LOG%" echo [%DATE% %TIME%] could not copy "%NEW%" over "%TARGET%" (tried %TRIES% times); starting the existing build.\r\n'
        'start "" "%TARGET%"\r\n'
        "exit /b 1\r\n"
    )


def build_posix_swap_script(new_exe, target_exe, pid: int = 0, *,
                            version: Optional[str] = None,
                            handoff: Optional[UpdateHandoff] = None,
                            watch_seconds: int = 60) -> str:
    """A detached shell script that swaps in the new build after the app exits.

    Kept for completeness (development builds on Linux/macOS); the packaged
    application is Windows-only. Like the Windows script it clears the
    PyInstaller onefile variables before relaunching, so the new build unpacks
    its own files, and it verifies the restart: the new build has to write the
    start-up marker, otherwise the previous build is put back.
    """
    files = handoff if handoff is not None else update_handoff()
    version_text = str(version) if version else ""
    unset_lines = "".join(f"unset {name}\n" for name in PYINSTALLER_RUNTIME_ENV_VARS)
    marker_check = (f'grep -q "v{version_text}" "$MARKER" 2>/dev/null &&\n  '
                    if version_text else "")
    return (
        "#!/bin/sh\n"
        f'NEW="{new_exe}"\n'
        f'TARGET="{target_exe}"\n'
        f'VERSION="{version_text}"\n'
        f'MARKER="{files.marker}"\n'
        f'RESULT="{files.result}"\n'
        f'LOG="{files.log}"\n'
        f"PID={int(pid)}\n"
        f"WATCH={max(1, int(watch_seconds))}\n"
        f"export {PYINSTALLER_RESET_ENV_VAR}=1\n"
        f"{unset_lines}"
        'mkdir -p "$(dirname "$MARKER")" 2>/dev/null\n'
        "i=0\n"
        'while kill -0 "$PID" 2>/dev/null; do\n'
        "  i=$((i+1))\n"
        '  [ "$i" -ge 120 ] && break\n'
        "  sleep 1\n"
        "done\n"
        'cp -f "$TARGET" "$TARGET.old" 2>/dev/null\n'
        'if ! mv -f "$NEW" "$TARGET" 2>/dev/null; then\n'
        '  echo "rolled-back v$VERSION the update file could not be copied over $TARGET" >> "$RESULT"\n'
        '  echo "[$(date "+%Y-%m-%d %H:%M:%S")] could not move $NEW over $TARGET; starting the existing build." >> "$LOG"\n'
        '  nohup "$TARGET" >/dev/null 2>&1 &\n'
        '  rm -f "$0"\n'
        "  exit 1\n"
        "fi\n"
        'chmod +x "$TARGET" 2>/dev/null\n'
        'rm -f "$MARKER"\n'
        'nohup "$TARGET" >/dev/null 2>&1 &\n'
        "i=0\n"
        'while [ "$i" -lt "$WATCH" ]; do\n'
        f"  {marker_check}[ -f \"$MARKER\" ] && {{\n"
        '    echo "ok v$VERSION" >> "$RESULT"\n'
        '    echo "[$(date "+%Y-%m-%d %H:%M:%S")] v$VERSION started and signalled that its window is up." >> "$LOG"\n'
        '    rm -f "$0"\n'
        "    exit 0\n"
        "  }\n"
        "  i=$((i+1))\n"
        "  sleep 1\n"
        "done\n"
        'echo "rolled-back v$VERSION the new build was installed but never signalled that its window came up" >> "$RESULT"\n'
        'echo "[$(date "+%Y-%m-%d %H:%M:%S")] v$VERSION never signalled its start-up; restoring $TARGET.old." >> "$LOG"\n'
        'cp -f "$TARGET.old" "$TARGET" 2>/dev/null\n'
        'chmod +x "$TARGET" 2>/dev/null\n'
        'rm -f "$MARKER"\n'
        'nohup "$TARGET" >/dev/null 2>&1 &\n'
        'rm -f "$0"\n'
        "exit 1\n"
    )


def build_swap_script(new_exe, target_exe, pid: int = 0, *, windows: bool = None,
                      wait_seconds: int = 120, version: Optional[str] = None,
                      handoff: Optional[UpdateHandoff] = None,
                      watch_seconds: int = 60) -> str:
    """Return the platform-appropriate swap script text."""
    on_windows = (os.name == "nt") if windows is None else windows
    if on_windows:
        return build_windows_swap_script(new_exe, target_exe,
                                         wait_seconds=wait_seconds, version=version,
                                         handoff=handoff, watch_seconds=watch_seconds)
    return build_posix_swap_script(new_exe, target_exe, pid, version=version,
                                   handoff=handoff, watch_seconds=watch_seconds)


def launch_swap_script(script_path: Path, *, windows: bool = None) -> None:
    """Run the swap script detached, so it survives this process exiting.

    The script is started with a scrubbed environment (`restart_environment`),
    so everything it starts later — including the new build — is launched as
    if the user had double-clicked it.

    No file this process owns is handed to the script: the script writes its
    own progress to the swap log, and a handle held here would make that write
    fail. Its three standard handles are pointed at the null device rather than
    left unset — a detached ``cmd.exe`` with no valid handles is not something
    to rely on, and it guarantees nothing of ours can be written to from the
    process that outlives us.
    """
    on_windows = (os.name == "nt") if windows is None else windows
    env = restart_environment()
    if on_windows:
        creationflags = 0
        for flag in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= getattr(subprocess, flag, 0)
        process = subprocess.Popen(
            ["cmd", "/c", str(script_path)], close_fds=True, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=creationflags)
    else:
        process = subprocess.Popen(
            ["/bin/sh", str(script_path)], start_new_session=True, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    log_event(f"update: the swap script is running as pid {process.pid}")


def install_update_and_restart(new_exe, target_exe=None, *, windows: bool = None,
                               temp_dir: Optional[Path] = None, pid: Optional[int] = None,
                               version: Optional[str] = None,
                               expected_size: Optional[int] = None,
                               handoff: Optional[UpdateHandoff] = None,
                               watch_seconds: int = 60) -> Path:
    """Arrange for `new_exe` to replace the running program and start it again.

    Returns the path of the swap script. The caller is expected to quit the
    application immediately afterwards: the script waits for this process to
    exit before touching the executable, starts the new build, waits for it to
    report its window (see `mark_startup_complete`) and puts the previous build
    back if it never does.
    """
    on_windows = (os.name == "nt") if windows is None else windows
    new_exe = Path(new_exe)
    target_exe = Path(target_exe) if target_exe is not None else running_executable()
    if target_exe is None:
        raise DownloadError("Cannot self-update: the running program is not a packaged executable.")
    if not new_exe.is_file():
        raise DownloadError(f"The downloaded update disappeared: {new_exe}")
    if expected_size:
        actual = new_exe.stat().st_size
        if actual != int(expected_size):
            raise DownloadError(
                f"The staged update is the wrong size ({actual} of {expected_size} bytes), "
                "so it was not installed. Please download it again.")
    log_event(f"update: staging v{version or '?'} over {target_exe} "
              f"(new build: {new_exe}, {describe_size(new_exe)})")
    stage = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    try:
        stage.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise DownloadError(f"Could not prepare {stage}: {err}") from err
    suffix = ".bat" if on_windows else ".sh"
    script_path = stage / f"{APP_NAME}-update{suffix}"
    process_id = int(pid if pid is not None else os.getpid())
    files = handoff if handoff is not None else update_handoff()
    # `newline=""` matters: the script is written with CRLF line endings on
    # purpose, and text mode would translate the \n inside them into CRLF
    # again, leaving cmd.exe a stray carriage return on every line.
    with script_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(build_swap_script(new_exe, target_exe, process_id, windows=on_windows,
                                       version=version, handoff=files,
                                       watch_seconds=watch_seconds))
    log_event(f"update: swap script written to {script_path} "
              f"(waits for {files.marker}); starting it detached")
    # A verdict from an older update must not be mistaken for this one's.
    clear_update_result()
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
    """Return whether a hex colour needs a light foreground."""
    value = colour.lstrip("#")
    r, g, b = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 145


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
# 11a. CUSTOM UI COLOURS — MS-PAINT STYLE GRADIENT ("EDIT COLOURS") MODEL
# =============================================================================
#
# Everything in this block is pure data: no Tk objects are touched, so the
# gradient geometry, the colour ramps and the saved-palette validation can be
# unit tested headlessly. The Tk widgets further down only render this model.
#
# The layout mirrors Microsoft Paint's "Edit colours" dialog: one big colour
# field (left->right = hue, top->bottom = saturation, drawn at the current
# brightness so the picked colour is always the pixel under the marker) next
# to a thin white->black strip that picks the shade (brightness) itself.

GRADIENT_WIDTH = 240         # px across the saturation axis of the square
GRADIENT_HEIGHT = 160        # px down the brightness ("shade") axis
HUE_STRIP_WIDTH = 22         # px-wide rainbow strip beside the square
MAX_CUSTOM_PALETTES = 16     # guard against an unbounded settings file
CUSTOM_PALETTE_ROLES = ("primary", "accent", "background")

# The colour field is drawn at the shade being held, but never darker than
# this: a palette whose current colour is nearly black (most of the dark
# built-ins are) used to leave the user staring at a black box with no visible
# gradient at all. The exact colour is always shown by the swatch and the hex
# box, so nothing is lost by keeping the field readable.
FIELD_MIN_SHADE = 0.4

_HEX_COLOUR_RE = re.compile(r"^#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def clamp_unit(value) -> float:
    """Clamp ``value`` into the 0..1 range every HSV component lives in."""
    number = float(value)
    if number != number:  # NaN
        return 0.0
    return min(max(number, 0.0), 1.0)


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


def hex_to_hsv(colour) -> Optional[Tuple[float, float, float]]:
    """Inverse of ``hsv_to_hex``; None when ``colour`` is not usable.

    Grey/black/white come back with hue 0 and saturation 0, so callers that
    keep a hue strip position must preserve their previous hue for them.
    """
    normalised = normalise_hex_colour(colour)
    if normalised is None:
        return None
    digits = normalised.lstrip("#")
    r, g, b = (int(digits[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)


def point_to_hs(x: float, y: float, width: int = GRADIENT_WIDTH,
                height: int = GRADIENT_HEIGHT) -> Tuple[float, float]:
    """Hue/saturation (each 0..1) at pixel ``(x, y)`` of the colour field.

    Mirrors the Paint gradient square: the whole rainbow runs left to right
    (hue) and the pure colours fade to greyscale top to bottom (saturation).
    Brightness lives on the separate shade strip, not in the square.
    """
    width = max(2, int(width))
    height = max(2, int(height))
    return (clamp_unit(x / (width - 1)), clamp_unit(1.0 - y / (height - 1)))


def hs_to_point(hue: float, saturation: float, width: int = GRADIENT_WIDTH,
                height: int = GRADIENT_HEIGHT) -> Tuple[float, float]:
    """Pixel of the colour field showing ``(hue, saturation)``."""
    width = max(2, int(width))
    height = max(2, int(height))
    return (clamp_unit(hue) * (width - 1),
            (1.0 - clamp_unit(saturation)) * (height - 1))


def value_at(y: float, height: int = GRADIENT_HEIGHT) -> float:
    """Brightness (1 at the top .. 0 at the bottom) at row ``y`` of the strip."""
    height = max(2, int(height))
    return clamp_unit(1.0 - y / (height - 1))


def value_to_y(value: float, height: int = GRADIENT_HEIGHT) -> float:
    """Pixel row of the shade strip showing ``value``."""
    height = max(2, int(height))
    return (1.0 - clamp_unit(value)) * (height - 1)


def rendered_shade(value: float) -> float:
    """Brightness the colour field is drawn at for a held ``value``.

    Never below ``FIELD_MIN_SHADE``: whichever colour is being edited, the
    field stays a readable rainbow instead of fading to black.
    """
    return max(clamp_unit(value), FIELD_MIN_SHADE)


def gradient_square_colour(x: float, y: float, value: float,
                           width: int = GRADIENT_WIDTH,
                           height: int = GRADIENT_HEIGHT) -> str:
    """The ``#RRGGBB`` colour painted at pixel ``(x, y)`` of the field."""
    hue, saturation = point_to_hs(x, y, width, height)
    return hsv_to_hex(hue, saturation, value)


def shade_strip_colour(y: float, height: int = GRADIENT_HEIGHT) -> str:
    """The greyscale shade at pixel row ``y`` of the white->black strip."""
    return hsv_to_hex(0.0, 0.0, value_at(y, height))


def ppm_header(width: int, height: int) -> bytes:
    """The P6 (binary RGB) PPM header Tk's photo reader expects."""
    return b"P6\n%d %d\n255\n" % (max(1, int(width)), max(1, int(height)))


def _hue_runs(width: int) -> List[Tuple[int, int, int]]:
    """Contiguous ``(sector, first_column, end_column)`` runs of the rainbow.

    Columns sharing a colorsys sector are rendered together so the field
    builder stays a handful of list comprehensions instead of a per-pixel
    branch.
    """
    runs: List[Tuple[int, int, int]] = []
    for x in range(width):
        scaled = (x / (width - 1)) * 6.0
        sector = int(scaled) % 6
        if runs and runs[-1][0] == sector:
            runs[-1] = (sector, runs[-1][1], x + 1)
        else:
            runs.append((sector, x, x + 1))
    return runs


def gradient_square_ppm(value: float, width: int = GRADIENT_WIDTH,
                        height: int = GRADIENT_HEIGHT) -> bytes:
    """P6 PPM image data for the colour field at brightness ``value``.

    This is what is handed to Tk (``image configure -data <bytes> -format ppm``;
    ``PhotoImage.put`` cannot name a format before Python 3.14). A nested list of
    ``#RRGGBB`` colour names — the obvious-looking alternative, and what this
    widget used to send — is *rejected* by Tk with ``can't parse color
    "#FF0000 #FF0000"``: the photo ``put`` parser treats a leading ``#`` as a
    comment, so a row of colours collapses into a single unparsable "colour"
    and the whole block is thrown away. Because that error was swallowed, the
    field and the shade strip silently stayed unset and the editor showed two
    empty boxes. Raw image data has no such pitfall.

    Pixel-for-pixel identical to ``gradient_square_colour`` but built without a
    per-pixel function call, so dragging the shade strip re-renders the whole
    field in milliseconds. The per-row products evaluate exactly the
    expressions ``colorsys`` uses.
    """
    width = max(2, int(width))
    height = max(2, int(height))
    v = clamp_unit(value)
    fracs = []
    for x in range(width):
        scaled = (x / (width - 1)) * 6.0
        fracs.append(scaled - math.floor(scaled))
    runs = _hue_runs(width)
    data = bytearray(ppm_header(width, height))
    for y in range(height):
        s = 1.0 - y / (height - 1)
        p = round(v * (1.0 - s) * 255)
        q = [round(v * (1.0 - s * f) * 255) for f in fracs]
        t_ = [round(v * (1.0 - s * (1.0 - f)) * 255) for f in fracs]
        v_byte = round(v * 255)
        for sector, first, end in runs:
            if sector == 0:      # (v, t, p)
                for c in t_[first:end]:
                    data += bytes((v_byte, c, p))
            elif sector == 1:    # (q, v, p)
                for c in q[first:end]:
                    data += bytes((c, v_byte, p))
            elif sector == 2:    # (p, v, t)
                for c in t_[first:end]:
                    data += bytes((p, v_byte, c))
            elif sector == 3:    # (p, q, v)
                for c in q[first:end]:
                    data += bytes((p, c, v_byte))
            elif sector == 4:    # (t, p, v)
                for c in t_[first:end]:
                    data += bytes((c, p, v_byte))
            else:                # (v, p, q)
                for c in q[first:end]:
                    data += bytes((v_byte, p, c))
    return bytes(data)


def shade_strip_ppm(width: int = HUE_STRIP_WIDTH,
                    height: int = GRADIENT_HEIGHT) -> bytes:
    """P6 PPM data for the white->black shade strip (greyscale, so all equal)."""
    width = max(1, int(width))
    height = max(2, int(height))
    data = bytearray(ppm_header(width, height))
    for y in range(height):
        grey = round(value_at(y, height) * 255)
        data += bytes((grey, grey, grey)) * width
    return bytes(data)


def ppm_pixels(data: bytes, width: int, height: int) -> List[str]:
    """Decode P6 data back into ``#RRGGBB`` rows (used by the tests).

    Reading the payload back proves what the field will contain without
    needing a display, which is as close to "what does the user see" as a
    headless test can get.
    """
    header = ppm_header(width, height)
    if not data.startswith(header):
        raise ValueError("not P6 data for this size")
    body = data[len(header):]
    rows: List[str] = []
    for y in range(height):
        start = y * width * 3
        chunk = body[start:start + width * 3]
        rows.append(" ".join(
            "#{:02X}{:02X}{:02X}".format(*chunk[offset:offset + 3])
            for offset in range(0, len(chunk), 3)))
    return rows


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


class ColourGradientPicker(_TkFrame):
    """The Microsoft Paint style colour picker ("Edit colours").

    The big square is the colour field itself: the whole rainbow runs left to
    right and pure colours fade to greyscale towards the bottom. It is drawn
    at the current shade (never darker than ``FIELD_MIN_SHADE``, so the field
    is always a readable rainbow instead of a black box), and the colour
    currently held is shown twice: as a filled dot inside the marker ring and
    as a swatch in the bottom-left corner of the field. The white-to-black
    strip beside the square is the shade selector.

    Clicking or dragging *in the field* picks the colour of the very pixel
    under the pointer and takes its brightness to full (Paint does the same
    with its brightness slider), so what you click is what you get. Dragging
    the shade strip then darkens or lightens that colour while the field stays
    legible — the swatch and the hex box always show the exact result.
    """

    PAD = 10          # px of margin around the artwork
    GAP = 16          # px between the colour field and the shade strip
    MARKER_R = 6      # radius of the ring marking the picked colour
    SWATCH_W = 46     # px of the "current colour" swatch inside the field
    SWATCH_H = 26
    SWATCH_MARGIN = 8

    def __init__(self, master, *, width: int = GRADIENT_WIDTH, height: int = GRADIENT_HEIGHT,
                 hue_width: int = HUE_STRIP_WIDTH, on_pick=None, background: str = "#FFFFFF",
                 border: str = "#8C96A8", marker: str = "#111827", **kwargs):
        super().__init__(master, bg=background, **kwargs)
        self.width = max(2, int(width))
        self.height = max(2, int(height))
        self.hue_width = max(1, int(hue_width))
        self._on_pick = on_pick
        self._border = border
        self._marker = marker
        self._hsv: Tuple[float, float, float] = (0.0, 1.0, 1.0)
        self.selected_colour: Optional[str] = None
        # Set when Tk refused the pixel data; the probe workflow checks it.
        self.last_paint_error: Optional[str] = None

        pad = self.PAD
        self.square_box = (pad, pad, pad + self.width - 1, pad + self.height - 1)
        hue_x = pad + self.width + self.GAP
        self.hue_box = (hue_x, pad, hue_x + self.hue_width - 1, pad + self.height - 1)
        # The swatch is a corner chip *of the field*: it scales down with
        # small fields so it is never a large share of the artwork.
        margin = min(self.SWATCH_MARGIN, max(2, self.width // 12), max(2, self.height // 12))
        swatch_w = max(1, min(self.SWATCH_W, self.width // 3))
        swatch_h = max(1, min(self.SWATCH_H, self.height // 4))
        self.swatch_box = (pad + margin, pad + self.height - margin - swatch_h,
                           pad + margin + swatch_w, pad + self.height - margin)
        # A click counts as landing on the swatch only when the field is big
        # enough for the chip to be a genuine corner of it; in a tiny canvas
        # (as the tests use) every pixel stays clickable. The editor's own
        # field is GRADIENT_WIDTH x GRADIENT_HEIGHT, far above the threshold.
        self._swatch_clickable = self.width >= 60 and self.height >= 40

        self.canvas = tk.Canvas(self, width=hue_x + self.hue_width + pad,
                                height=pad * 2 + self.height, bg=background,
                                highlightthickness=0, bd=0, cursor="crosshair")
        self.canvas.pack()

        self._square_image = tk.PhotoImage(master=self, width=self.width, height=self.height)
        self._strip_image = tk.PhotoImage(master=self, width=self.hue_width, height=self.height)
        self.canvas.create_image(pad, pad, image=self._square_image, anchor="nw")
        self.canvas.create_image(hue_x, pad, image=self._strip_image, anchor="nw")

        sx0, sy0, sx1, sy1 = self.square_box
        hx0, hy0, hx1, hy1 = self.hue_box
        self.canvas.create_rectangle(sx0 - 1, sy0 - 1, sx1 + 1, sy1 + 1,
                                     outline=border, fill="", width=1)
        self.canvas.create_rectangle(hx0 - 1, hy0 - 1, hx1 + 1, hy1 + 1,
                                     outline=border, fill="", width=1)
        # The swatch sits inside the field and shows the colour being held, at
        # the shade being held: a white halo under a dark outline keeps it
        # visible on any part of the rainbow.
        swatch = self.swatch_box
        self.canvas.create_rectangle(swatch[0] - 2, swatch[1] - 2, swatch[2] + 2, swatch[3] + 2,
                                     outline="#FFFFFF", fill="", width=2)
        self._swatch_item = self.canvas.create_rectangle(swatch[0] - 1, swatch[1] - 1,
                                                         swatch[2] + 1, swatch[3] + 1,
                                                         outline=marker, fill="", width=1)
        # A white ring around a dark ring stays visible on any shade, from
        # near-white to near-black; the dot inside carries the picked colour.
        self._marker_fill = self.canvas.create_oval(0, 0, 0, 0, outline="", fill="")
        self._shade_marker_outer = self.canvas.create_oval(0, 0, 0, 0, outline="#FFFFFF",
                                                           fill="", width=2)
        self._shade_marker_inner = self.canvas.create_oval(0, 0, 0, 0, outline=marker,
                                                           fill="", width=1)
        self._hue_marker_outer = self.canvas.create_rectangle(0, 0, 0, 0, outline="#FFFFFF",
                                                              fill="", width=2)
        self._hue_marker_inner = self.canvas.create_rectangle(0, 0, 0, 0, outline=marker,
                                                              fill="", width=1)

        self.canvas.bind("<Button-1>", self._pointer)
        self.canvas.bind("<B1-Motion>", self._pointer)

        self._render_strip()
        self._render_square()
        self._move_markers()
        # Nothing has been picked yet, so the chip shows the colour the marker
        # is sitting on (the top-left of the field): the box is never blank.
        self._show_current_colour(hsv_to_hex(*self._hsv))

    # -- properties ------------------------------------------------------
    @property
    def hsv(self) -> Tuple[float, float, float]:
        """The hue/saturation/value currently shown by the markers."""
        return self._hsv

    @property
    def field_shade(self) -> float:
        """Brightness the field itself is drawn at (never below the floor)."""
        return rendered_shade(self._hsv[2])

    # -- rendering -------------------------------------------------------
    def _paint(self, image, data: bytes) -> None:
        """Show P6 pixel data on ``image`` (see ``gradient_square_ppm``).

        ``image configure -data`` is used rather than ``photo put``: before
        Python 3.14 ``PhotoImage.put`` cannot take an image format, and its
        colour-name list form is what silently failed — see
        ``gradient_square_ppm``. A build that cannot draw the gradient records
        the reason in ``last_paint_error`` instead of leaving an empty box
        behind, and the editor shows a note when that happens.
        """
        try:
            image.configure(data=data, format="ppm")
            self.last_paint_error = None
        except tk.TclError as err:
            self.last_paint_error = str(err)

    def _render_square(self):
        try:
            self._paint(self._square_image,
                        gradient_square_ppm(self.field_shade, self.width, self.height))
        except tk.TclError:
            pass  # destroyed mid-drag or no usable display: markers still move

    def _render_strip(self):
        try:
            self._paint(self._strip_image, shade_strip_ppm(self.hue_width, self.height))
        except tk.TclError:
            pass

    def _move_markers(self):
        sx0, sy0 = self.square_box[0], self.square_box[1]
        hx0, hy0, hx1 = self.hue_box[0], self.hue_box[1], self.hue_box[2]
        x, y = hs_to_point(self._hsv[0], self._hsv[1], self.width, self.height)
        cx, cy = sx0 + x, sy0 + y
        r = self.MARKER_R
        strip_y = hy0 + value_to_y(self._hsv[2], self.height)
        try:
            self.canvas.coords(self._marker_fill, cx - r + 2, cy - r + 2,
                               cx + r - 2, cy + r - 2)
            self.canvas.coords(self._shade_marker_outer, cx - r, cy - r, cx + r, cy + r)
            self.canvas.coords(self._shade_marker_inner, cx - r + 2, cy - r + 2,
                               cx + r - 2, cy + r - 2)
            self.canvas.coords(self._hue_marker_outer, hx0 - 5, strip_y - 5, hx1 + 5, strip_y + 5)
            self.canvas.coords(self._hue_marker_inner, hx0 - 3, strip_y - 3, hx1 + 3, strip_y + 3)
        except tk.TclError:
            pass

    def _show_current_colour(self, colour: Optional[str] = None):
        """Fill the marker dot and the field's swatch with the current colour."""
        shade = colour or self.selected_colour
        if shade is None:
            return
        try:
            self.canvas.itemconfigure(self._swatch_item, fill=shade)
            self.canvas.itemconfigure(self._marker_fill, fill=shade)
        except tk.TclError:
            pass

    # -- interaction -----------------------------------------------------
    def _pointer(self, event):
        """Handle a click or a drag: whichever area the pointer is in wins."""
        x = float(getattr(event, "x", 0))
        y = float(getattr(event, "y", 0))
        sx0, sy0, sx1, sy1 = self.square_box
        hx0, hy0, hx1, hy1 = self.hue_box
        slack = self.PAD / 2.0
        hue, saturation, value = self._hsv
        if (sx0 - slack <= x <= sx1 + slack and sy0 - slack <= y <= sy1 + slack
                and not self._in_swatch(x, y)):
            hue, saturation = point_to_hs(x - sx0, y - sy0, self.width, self.height)
            # Full brightness: the colour you clicked is the colour you get,
            # and the field keeps showing every hue (the strip darkens it
            # afterwards if you want a quieter colour).
            value = 1.0
        elif hx0 - slack <= x <= hx1 + slack and hy0 - slack <= y <= hy1 + slack:
            value = value_at(y - hy0, self.height)
        else:
            return  # clicked the margin (or the swatch): keep the current colour
        self._apply_hsv((hue, saturation, value))

    def _in_swatch(self, x: float, y: float) -> bool:
        """True when ``(x, y)`` is on the current-colour swatch chip.

        The chip is painted over the field, so clicks on it must not pick the
        colour of the pixels it hides; two pixels of slack cover its outline.
        """
        if not self._swatch_clickable:
            return False
        return (self.swatch_box[0] - 2 <= x <= self.swatch_box[2] + 2
                and self.swatch_box[1] - 2 <= y <= self.swatch_box[3] + 2)

    def _apply_hsv(self, hsv: Tuple[float, float, float], notify: bool = True):
        hue, saturation, value = (clamp_unit(part) for part in hsv)
        shade_changed = rendered_shade(value) != self.field_shade
        self._hsv = (hue, saturation, value)
        self.selected_colour = hsv_to_hex(hue, saturation, value)
        if shade_changed:
            self._render_square()  # the field is drawn at the current shade
        self._move_markers()
        self._show_current_colour()
        if notify and self._on_pick is not None:
            self._on_pick(self.selected_colour)

    def set_selected(self, colour: Optional[str]):
        """Point the markers at ``colour`` without firing the callback.

        Greys and black keep the hue/saturation the field already shows
        (Paint behaves the same way), so choosing a neutral background does
        not scramble the gradient the user was browsing.
        """
        hsv = hex_to_hsv(colour)
        if hsv is None:
            self.selected_colour = None
            return
        hue, saturation, value = hsv
        if saturation == 0.0 or value == 0.0:
            hue, saturation = self._hsv[0], self._hsv[1]
        self._apply_hsv((hue, saturation, value), notify=False)
        self.selected_colour = normalise_hex_colour(colour)
        self._show_current_colour(self.selected_colour)


class CustomPaletteEditor(_TkToplevel):
    """Dialog that builds and saves a user-defined palette.

    Three colour roles (primary, accent, background) are filled in from the
    Paint-style gradient picker or typed as hex, previewed live, named, and
    then handed back to the app through ``on_save``.
    """

    def __init__(self, master, colours: Dict[str, str], *, on_save,
                 initial: Optional[Tuple[str, str, str]] = None,
                 initial_name: str = "", editing: Optional[str] = None,
                 topmost: bool = False):
        super().__init__(master)
        self._on_save = on_save
        self._editing = editing
        c = colours
        base = initial or ("#1E3A8A", "#3B82F6", "#F8FAFC")
        self._values = {
            "primary": normalise_hex_colour(base[0]) or "#1E3A8A",
            "accent": normalise_hex_colour(base[1]) or "#3B82F6",
            "background": normalise_hex_colour(base[2]) or "#F8FAFC",
        }

        self.title("Custom UI Colour — Paint-style gradient")
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
        tk.Label(body, text="Custom UI Colour", bg=c["background"], fg=c["primary"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(body,
                 text="Drag in the colour gradient to pick a hue and its intensity, slide the shade\n"
                      "strip for lighter and darker, then name the set and save it with the palettes.",
                 bg=c["background"], fg=c["muted"], font=("Segoe UI", 9),
                 justify="left").pack(anchor="w", pady=(2, 12))

        main = tk.Frame(body, bg=c["background"])
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=c["background"])
        left.pack(side="left", anchor="n")
        self.picker = ColourGradientPicker(left, on_pick=self._picked,
                                           background=c["surface"],
                                           border=c["muted"], marker=c["foreground"],
                                           highlightthickness=1,
                                           highlightbackground=c["muted"])
        self.picker.pack(anchor="n")

        hex_row = tk.Frame(left, bg=c["background"])
        hex_row.pack(fill="x", pady=(10, 0))
        tk.Label(hex_row, text="Hex", bg=c["background"], fg=c["foreground"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.hex_var = tk.StringVar()
        self.hex_entry = tk.Entry(hex_row, textvariable=self.hex_var, width=10,
                                  bg=c["surface"], fg=c["foreground"],
                                  insertbackground=c["foreground"], relief="flat",
                                  highlightthickness=1, highlightbackground=c["muted"],
                                  font=("Consolas", 10))
        self.hex_entry.pack(side="left", padx=(8, 8))
        self.hex_entry.bind("<Return>", lambda event: self._apply_typed_hex())
        tk.Button(hex_row, text="Use hex", command=self._apply_typed_hex, relief="flat",
                  bg=c["primary"], fg=c["button_foreground"],
                  activebackground=c["accent"], activeforeground=c["accent_foreground"],
                  padx=10, pady=2, font=("Segoe UI", 9, "bold")).pack(side="left")
        self._hex_hint = tk.Label(hex_row, text="", bg=c["background"], fg=c["muted"],
                                  font=("Segoe UI", 8))
        self._hex_hint.pack(side="left", padx=(8, 0))

        # If Tk ever refuses the gradient's pixel data the box would be blank,
        # which is exactly the bug this picker exists to fix: say so instead.
        self._paint_hint = tk.Label(left, text="", bg=c["background"], fg=c["accent"],
                                    font=("Segoe UI", 8), justify="left",
                                    wraplength=GRADIENT_WIDTH + HUE_STRIP_WIDTH + 40)
        self._paint_hint.pack(anchor="w", pady=(6, 0))

        right = tk.Frame(main, bg=c["background"])
        right.pack(side="left", anchor="n", padx=(20, 0), fill="both", expand=True)

        tk.Label(right, text="Colour being edited", bg=c["background"], fg=c["primary"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.role_var = tk.StringVar(value="primary")
        self._role_swatches = {}
        self._role_labels = {}
        for role, caption in (("primary", "Primary (headings, buttons)"),
                              ("accent", "Accent (highlights, progress)"),
                              ("background", "Background (window + panels)")):
            row = tk.Frame(right, bg=c["background"])
            row.pack(fill="x", pady=3)
            radio = tk.Radiobutton(row, text=caption, value=role, variable=self.role_var,
                                   command=self._role_changed, bg=c["background"],
                                   fg=c["foreground"], activebackground=c["background"],
                                   activeforeground=c["foreground"], selectcolor=c["surface"],
                                   anchor="w", font=("Segoe UI", 9))
            radio.pack(side="left", anchor="w")
            swatch = tk.Frame(row, width=34, height=18, bg=self._values[role],
                              highlightthickness=1, highlightbackground=c["foreground"])
            swatch.pack(side="right")
            label = tk.Label(row, text=self._values[role], bg=c["background"], fg=c["muted"],
                             font=("Consolas", 9))
            label.pack(side="right", padx=(0, 8))
            self._role_swatches[role] = swatch
            self._role_labels[role] = label

        tk.Label(right, text="Preview", bg=c["background"], fg=c["primary"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 4))
        self._preview = tk.Frame(right, height=96, highlightthickness=1,
                                 highlightbackground=c["muted"])
        self._preview.pack(fill="x")
        self._preview.pack_propagate(False)
        self._preview_title = tk.Label(self._preview, text="AutoTyper", font=("Segoe UI", 12, "bold"))
        self._preview_title.pack(anchor="w", padx=10, pady=(12, 0))
        self._preview_body = tk.Label(self._preview, text="Your colours, applied live.",
                                      font=("Segoe UI", 9))
        self._preview_body.pack(anchor="w", padx=10)
        self._preview_button = tk.Label(self._preview, text="  Accent button  ", font=("Segoe UI", 9, "bold"))
        self._preview_button.pack(anchor="w", padx=10, pady=(8, 0))

        tk.Label(right, text="Palette name", bg=c["background"], fg=c["primary"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 4))
        self.name_var = tk.StringVar(value=initial_name or "My Colours")
        tk.Entry(right, textvariable=self.name_var, bg=c["surface"], fg=c["foreground"],
                 insertbackground=c["foreground"], relief="flat", highlightthickness=1,
                 highlightbackground=c["muted"], font=("Segoe UI", 10)).pack(fill="x")

        buttons = tk.Frame(body, bg=c["background"])
        buttons.pack(fill="x", pady=(16, 0))
        tk.Button(buttons, text="Cancel", command=self.destroy, relief="flat",
                  bg=c["surface"], fg=c["foreground"], activebackground=c["muted"],
                  padx=14, pady=5, font=("Segoe UI", 9)).pack(side="right")
        tk.Button(buttons, text="Save colours", command=self._save, relief="flat",
                  bg=c["accent"], fg=c["accent_foreground"],
                  activebackground=c["primary"], activeforeground=c["button_foreground"],
                  padx=16, pady=5, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(0, 8))

        self._role_changed()
        self._refresh_preview()
        self._report_paint_state()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # -- internals -----------------------------------------------------
    def _picked(self, colour: str):
        self._set_role_colour(self.role_var.get(), colour)
        self._report_paint_state()

    def _report_paint_state(self):
        """Tell the user when the gradient itself could not be drawn."""
        error = self.picker.last_paint_error
        if error:
            self._paint_hint.configure(
                text="The colour gradient could not be drawn on this system "
                     f"({error}). Pick colours with the shade strip or the hex box.")
        else:
            self._paint_hint.configure(text="")

    def _apply_typed_hex(self):
        colour = normalise_hex_colour(self.hex_var.get())
        if colour is None:
            self._hex_hint.configure(text="use #RRGGBB")
            return
        self._hex_hint.configure(text="")
        self._set_role_colour(self.role_var.get(), colour)
        self.picker.set_selected(colour)

    def _set_role_colour(self, role: str, colour: str):
        colour = normalise_hex_colour(colour) or self._values[role]
        self._values[role] = colour
        self.hex_var.set(colour)
        self._role_swatches[role].configure(bg=colour)
        self._role_labels[role].configure(text=colour)
        self._refresh_preview()

    def _role_changed(self):
        colour = self._values[self.role_var.get()]
        self.hex_var.set(colour)
        self.picker.set_selected(colour)

    def _refresh_preview(self):
        preview = _palette_colours("__preview__", {"__preview__": self.triple()})
        self._preview.configure(bg=preview["background"])
        self._preview_title.configure(bg=preview["background"], fg=preview["primary"])
        self._preview_body.configure(bg=preview["background"], fg=preview["foreground"])
        self._preview_button.configure(bg=preview["accent"], fg=preview["accent_foreground"])

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


class AutoTyperApp(_TkBase):
    """The V2 desktop interface.

    The simulator remains Tk-free outside this class. All visual state lives
    here so the planner and trace engine can still be tested headlessly.
    """

    def __init__(self):
        super().__init__()
        self.title("AutoTyper — Biomechanical Keystroke Simulator")
        self.geometry("780x980")
        self.minsize(680, 760)
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
        self.colors = _palette_colours(self.palette_name, self.available_palettes())
        self._settings_window = None
        self._settings_cards = []
        self._settings_theme_widgets = []
        self._settings_headings = []
        self._palette_grid = None
        self._custom_hint = None
        self._custom_editor = None
        self._preview_widgets = {}
        self._comboboxes = []
        self._download_thread = None
        # Update/download affordances live inside the settings window (the
        # header keeps only the Settings button), so these exist only while
        # that window is open.
        self._available_version: Optional[str] = None
        self._download_exe_button = None
        self._update_check_button = None
        self._update_hint = None
        self._log_button = None
        self._log_hint = None

        try:
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
        except tk.TclError:
            self.style = ttk.Style(self)

        self._configure_styles()
        self._build_ui()
        self._apply_palette(self.palette_name)
        self._apply_topmost()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_id = self.after(50, self._poll_queue)
        self._start_update_check()

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
        """Open the gradient colour editor for a new or existing custom palette."""
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
        palettes = self.available_palettes()
        if name not in palettes:
            name = DEFAULT_PALETTE
        self.palette_name = name
        self.palette_var.set(name)
        self.colors = _palette_colours(name, palettes)
        self._save_ui_settings()
        self.configure(background=self.colors["background"])
        self._configure_styles()

        if hasattr(self, "text_box"):
            self.text_box.configure(
                background=self.colors["surface"],
                foreground=self.colors["foreground"],
                insertbackground=self.colors["accent"],
                selectbackground=self.colors["accent"],
                selectforeground=self.colors["accent_foreground"],
                highlightbackground=self.colors["primary"],
                highlightcolor=self.colors["accent"],
            )
        for scale in (getattr(self, "wpm_scale", None), getattr(self, "typo_scale", None)):
            if scale is not None:
                scale.configure(
                    bg=self.colors["background"],
                    fg=self.colors["foreground"],
                    troughcolor=self.colors["surface"],
                    activebackground=self.colors["accent"],
                    highlightbackground=self.colors["background"],
                )
        self._refresh_settings_window()
        self._style_combobox_dropdowns()

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
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            return

        c = self.colors
        window = tk.Toplevel(self)
        self._settings_window = window
        window.title("AutoTyper — Appearance & Window Settings")
        window.geometry("720x840")
        window.minsize(640, 620)
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
        self._bind_settings_mousewheel(scroller)

        self._settings_title = tk.Label(outer, text="Appearance & Window Settings", bg=c["background"],
                                        fg=c["primary"], font=("Segoe UI", 18, "bold"))
        self._settings_title.pack(anchor="w")
        self._settings_subtitle = tk.Label(
            outer, text="Choose a palette, design your own colours, and keep the typer visible while you work.",
            bg=c["background"], fg=c["muted"], font=("Segoe UI", 10))
        self._settings_subtitle.pack(anchor="w", pady=(2, 14))

        palette_box = tk.LabelFrame(outer, text=" Colour palette ", bg=c["background"],
                                    fg=c["primary"], bd=1, relief="groove",
                                    padx=12, pady=10, font=("Segoe UI", 10, "bold"))
        palette_box.pack(fill="both", expand=True)
        grid = tk.Frame(palette_box, bg=c["background"])
        grid.pack(fill="both", expand=True)
        self._palette_grid = grid

        custom_box = tk.LabelFrame(outer, text=" Custom UI colour ", bg=c["background"],
                                   fg=c["primary"], bd=1, relief="groove",
                                   padx=12, pady=10, font=("Segoe UI", 10, "bold"))
        custom_box.pack(fill="x", pady=(14, 0))
        self._custom_hint = tk.Label(
            custom_box,
            text="", bg=c["background"], fg=c["muted"], font=("Segoe UI", 9),
            justify="left", anchor="w")
        self._custom_hint.pack(anchor="w", pady=(0, 8))
        custom_buttons = tk.Frame(custom_box, bg=c["background"])
        custom_buttons.pack(anchor="w")
        ttk.Button(custom_buttons, text="🎨 New colours…", style="Accent.TButton",
                   command=lambda: self._open_custom_editor(None)).pack(side="left")
        ttk.Button(custom_buttons, text="Edit selected", style="App.TButton",
                   command=self._edit_selected_custom_palette).pack(side="left", padx=(8, 0))
        ttk.Button(custom_buttons, text="Delete selected", style="App.TButton",
                   command=self._delete_custom_palette).pack(side="left", padx=(8, 0))

        window_box = tk.LabelFrame(outer, text=" Window ", bg=c["background"],
                                   fg=c["primary"], bd=1, relief="groove",
                                   padx=12, pady=10, font=("Segoe UI", 10, "bold"))
        window_box.pack(fill="x", pady=(14, 0))
        self._topmost_checkbutton = tk.Checkbutton(
            window_box,
            text="Keep Auto-Typer above other applications (prevents it disappearing when you click your editor)",
            variable=self.topmost_var,
            command=self._apply_topmost,
            bg=c["background"], fg=c["foreground"],
            activebackground=c["background"], activeforeground=c["foreground"],
            selectcolor=c["surface"], anchor="w",
        )
        self._topmost_checkbutton.pack(anchor="w")

        updates_box = tk.LabelFrame(outer, text=" Updates & downloads ", bg=c["background"],
                                    fg=c["primary"], bd=1, relief="groove",
                                    padx=12, pady=10, font=("Segoe UI", 10, "bold"))
        updates_box.pack(fill="x", pady=(14, 0))
        self._update_hint = tk.Label(updates_box, text="", bg=c["background"], fg=c["muted"],
                                     font=("Segoe UI", 9), justify="left", anchor="w",
                                     wraplength=590)
        self._update_hint.pack(anchor="w", pady=(0, 8))
        self._update_check_button = ttk.Button(
            updates_box, text="Check for updates now", style="App.TButton",
            command=self._manual_update_check)
        self._update_check_button.pack(anchor="w")
        # The single place to fetch the published executable — the old header
        # button duplicated this and has been removed to declutter the UI.
        self._download_exe_button = ttk.Button(
            updates_box, text="⬇ Download latest AutoTyper.exe", style="App.TButton",
            command=self._start_exe_download)
        self._download_exe_button.pack(anchor="w", pady=(8, 0))
        # Updates are the one part of the app that can go wrong where the app
        # itself is not there to explain it, so the record it leaves behind is
        # one click away instead of buried in a hidden folder.
        self._log_button = ttk.Button(updates_box, text="🗒 Open update log", style="App.TButton",
                                      command=self._open_log_file)
        self._log_button.pack(anchor="w", pady=(8, 0))
        self._log_hint = tk.Label(
            updates_box, bg=c["background"], fg=c["muted"], font=("Segoe UI", 8),
            text=f"Updates write a log to {log_file_path()} — open it if an update "
                 "ever fails to start.",
            justify="left", anchor="w", wraplength=590)
        self._log_hint.pack(anchor="w", pady=(4, 0))

        preview_box = tk.LabelFrame(outer, text=" Live preview ", bg=c["background"],
                                    fg=c["primary"], bd=1, relief="groove",
                                    padx=12, pady=10, font=("Segoe UI", 10, "bold"))
        preview_box.pack(fill="x", pady=(0, 10))
        preview = tk.Frame(preview_box, bg=c["background"], height=86)
        preview.pack(fill="x")
        preview.pack_propagate(False)
        self._preview_widgets = {
            "frame": preview,
            "title": tk.Label(preview, text="AutoTyper", font=("Segoe UI", 13, "bold")),
            "body": tk.Label(preview, text="Settings preview — your selected palette is applied immediately.",
                             font=("Segoe UI", 9)),
            "button": tk.Button(preview, text="Accent button", relief="flat", padx=12, pady=4),
        }
        self._preview_widgets["title"].pack(side="left", padx=(4, 20), pady=22)
        self._preview_widgets["body"].pack(side="left", fill="x", expand=True, pady=22)
        self._preview_widgets["button"].pack(side="right", padx=4, pady=20)

        self._settings_theme_widgets = [scroller, outer, palette_box, grid, custom_box,
                                        custom_buttons, window_box, updates_box,
                                        preview_box, preview,
                                        self._settings_title, self._settings_subtitle,
                                        self._custom_hint, self._update_hint,
                                        self._log_hint, self._topmost_checkbutton]
        self._settings_headings = [palette_box, custom_box, window_box, updates_box,
                                   preview_box]

        ttk.Button(outer, text="Close", style="App.TButton", command=self._close_settings).pack(anchor="e")

        self._refresh_palette_cards()
        self._refresh_settings_window()
        self._refresh_update_controls()

    def _bind_settings_mousewheel(self, scroller):
        """Scroll the settings body with the wheel on Windows, macOS and X11."""
        def on_wheel(event):
            if event.num == 4:
                delta = -1
            elif event.num == 5:
                delta = 1
            else:
                delta = -1 if event.delta > 0 else 1
            scroller.yview_scroll(delta, "units")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            scroller.bind_all(sequence, on_wheel, add="+")
        self._settings_wheel_bindings = ("<MouseWheel>", "<Button-4>", "<Button-5>")

    def _edit_selected_custom_palette(self):
        if not self.is_custom_palette(self.palette_name):
            messagebox.showinfo(
                "Pick your own colours first",
                "Select one of your saved custom palettes to edit it, or press "
                "“New colours…” to design one on the colour gradient.")
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
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=4, pady=4)
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
                         highlightthickness=1, highlightbackground=c["foreground"]).pack(side="left", padx=(0, 3))
            self._settings_cards.append((card, radio, swatches, name))

            # Make the whole card, including whitespace and colour swatches,
            # behave like one large palette selector instead of requiring a
            # precise click on the radio control.
            for selectable in (card, radio, swatches, *swatches.winfo_children()):
                selectable.bind("<Button-1>", lambda event, selected=name: self._choose_palette(selected))
            if custom:
                for selectable in (card, radio, swatches, *swatches.winfo_children()):
                    selectable.bind("<Double-Button-1>",
                                    lambda event, selected=name: self._open_custom_editor(selected))

        if self._custom_hint is not None:
            try:
                saved = len(self.custom_palettes)
                self._custom_hint.configure(
                    text=("Design your own palette on the Microsoft-Paint style colour gradient: "
                          "drag the colour field for hue and intensity, slide the strip for the shade,\n"
                          f"then name it and save. Saved custom palettes: {saved} of {MAX_CUSTOM_PALETTES}"
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
        for widget in self._settings_theme_widgets:
            try:
                widget.configure(bg=c["background"])
            except tk.TclError:
                pass
        self._settings_title.configure(bg=c["background"], fg=c["primary"])
        self._settings_subtitle.configure(bg=c["background"], fg=c["muted"])
        if self._custom_hint is not None:
            try:
                self._custom_hint.configure(bg=c["background"], fg=c["muted"])
            except tk.TclError:
                pass
        if self._update_hint is not None:
            try:
                self._update_hint.configure(bg=c["background"], fg=c["muted"])
            except tk.TclError:
                pass
        self._topmost_checkbutton.configure(
            bg=c["background"], fg=c["foreground"],
            activebackground=c["background"], activeforeground=c["foreground"],
            selectcolor=c["surface"],
        )
        for widget in self._settings_headings:
            try:
                widget.configure(fg=c["primary"])
            except tk.TclError:
                pass
        for card, radio, swatches, name in self._settings_cards:
            card.configure(bg=c["background"], highlightbackground=c["accent"] if name == self.palette_name else c["surface"])
            radio.configure(bg=c["background"], fg=c["foreground"],
                            activebackground=c["background"], activeforeground=c["foreground"],
                            selectcolor=c["surface"])
            swatches.configure(bg=c["background"])
        for key, widget in self._preview_widgets.items():
            if key == "frame":
                widget.configure(bg=c["background"])
            elif key == "title":
                widget.configure(bg=c["background"], fg=c["primary"])
            elif key == "body":
                widget.configure(bg=c["background"], fg=c["foreground"])
            elif key == "button":
                widget.configure(bg=c["accent"], fg=c["accent_foreground"],
                                 activebackground=c["primary"], activeforeground="#FFFFFF")

    def _refresh_update_controls(self):
        """Label the settings download button with the version it will fetch.

        Safe to call at any time: while the settings window is closed the
        button and hint simply do not exist yet, and the remembered version
        is applied the next time the window opens.
        """
        latest = getattr(self, "_available_version", None)
        button = getattr(self, "_download_exe_button", None)
        if button is not None:
            try:
                if button.winfo_exists():
                    button.configure(text=(f"⬇ Get v{latest} .exe" if latest
                                           else "⬇ Download latest AutoTyper.exe"))
            except tk.TclError:
                pass
        hint = getattr(self, "_update_hint", None)
        if hint is not None:
            try:
                if hint.winfo_exists():
                    hint.configure(text=(
                        f"AutoTyper v{latest} is available (you have v{APP_VERSION}). The button "
                        "below downloads the new executable — updating is always optional."
                        if latest else
                        f"You have v{APP_VERSION}. AutoTyper checks GitHub quietly when it opens; "
                        "“Check for updates now” looks again on demand."))
            except tk.TclError:
                pass

    def _open_log_file(self):
        """Show the update/diagnostics log (see `log_event`)."""
        path = log_file_path()
        log_event("log: opened from the settings window")  # also creates the file
        if open_path(path):
            return
        messagebox.showinfo(
            "Update log",
            f"AutoTyper's update log is:\n{path}\n\nThe swap script writes to:\n{swap_log_path()}",
            parent=self,
        )

    def _set_download_button_state(self, state: str):
        """Enable/disable the settings download button while a fetch runs."""
        button = getattr(self, "_download_exe_button", None)
        if button is None:
            return
        try:
            if button.winfo_exists():
                button.configure(state=state)
        except tk.TclError:
            pass

    def _close_settings(self):
        for sequence in getattr(self, "_settings_wheel_bindings", ()):  # stop scrolling the dead window
            try:
                self.unbind_all(sequence)
            except tk.TclError:
                pass
        self._settings_wheel_bindings = ()
        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except tk.TclError:
                pass
        self._settings_window = None
        self._settings_cards = []
        self._settings_theme_widgets = []
        self._settings_headings = []
        self._palette_grid = None
        self._custom_hint = None
        self._download_exe_button = None
        self._update_check_button = None
        self._update_hint = None
        self._log_button = None
        self._log_hint = None
        self._preview_widgets = {}

    # ------------------------------------------------------------------
    # Main window
    # ------------------------------------------------------------------
    def _build_ui(self):
        header = ttk.Frame(self, style="App.TFrame", padding=(24, 18, 24, 8))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AutoTyper", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Biomechanical typing with Pascal-aware block navigation", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0))
        self.settings_btn = ttk.Button(header, text="⚙ Settings", style="App.TButton", command=self._open_settings)
        self.settings_btn.grid(row=0, column=1, rowspan=2, sticky="e")
        # The header deliberately keeps this one button: update checks and
        # .exe downloads all live in the Settings window ("Updates &
        # downloads"), so nothing redundant sits next to it out here.

        body = ttk.Frame(self, style="App.TFrame", padding=(24, 8, 24, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=0)
        body.rowconfigure(1, weight=1)

        cfg = ttk.LabelFrame(body, text=" Typing settings ", style="App.TLabelframe", padding=14)
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        cfg.columnconfigure(0, weight=1)

        ttk.Label(cfg, text="Target speed (WPM)", style="App.TLabel").grid(row=0, column=0, sticky="w")
        self.wpm_var = tk.IntVar(value=110)
        self.wpm_entry = ttk.Entry(cfg, textvariable=self.wpm_var, width=9,
                                   justify="right", style="App.TEntry")
        self.wpm_entry.grid(row=0, column=1, sticky="e")
        self.wpm_entry.bind("<FocusOut>", lambda event: self._normalise_entry(self.wpm_var, 20, 150, 0))
        self.wpm_entry.bind("<Return>", lambda event: self._normalise_entry(self.wpm_var, 20, 150, 0))
        self.wpm_scale = tk.Scale(
            cfg, from_=20, to=150, orient="horizontal", variable=self.wpm_var,
            resolution=1, showvalue=False, length=250, highlightthickness=0, bd=0,
        )
        self.wpm_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(cfg, text="Base typo rate (%)", style="App.TLabel").grid(row=2, column=0, sticky="w")
        self.typo_var = tk.DoubleVar(value=0.01)
        self.typo_entry = ttk.Entry(cfg, textvariable=self.typo_var, width=9,
                                    justify="right", style="App.TEntry")
        self.typo_entry.grid(row=2, column=1, sticky="e")
        self.typo_entry.bind("<FocusOut>", lambda event: self._normalise_entry(self.typo_var, 0.01, 100.0, 2))
        self.typo_entry.bind("<Return>", lambda event: self._normalise_entry(self.typo_var, 0.01, 100.0, 2))
        self.typo_scale = tk.Scale(
            cfg, from_=0.01, to=100.0, orient="horizontal", variable=self.typo_var,
            resolution=0.01, showvalue=False, length=250, highlightthickness=0, bd=0,
        )
        self.typo_scale.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.mode_var = tk.StringVar(value="Net (incl. pauses & fixes)")
        ttk.Label(cfg, text="Speed definition", style="App.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        self.mode_combo = ttk.Combobox(
            cfg, textvariable=self.mode_var, values=list(MODE_LABELS), state="readonly", width=26,
            style="App.TCombobox", postcommand=self._style_combobox_dropdowns,
        )
        self.mode_combo.grid(row=4, column=1, sticky="e", pady=4)
        self._comboboxes.append(self.mode_combo)

        self.delay_var = tk.IntVar(value=4)
        ttk.Label(cfg, text="Countdown (seconds)", style="App.TLabel").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Spinbox(cfg, textvariable=self.delay_var, from_=1, to=30, width=8,
                    style="App.TSpinbox").grid(row=5, column=1, sticky="e", pady=4)

        self.indent_mode_var = tk.StringVar(value="Off (type text as-is)")
        ttk.Label(cfg, text="Editor indentation", style="App.TLabel").grid(row=6, column=0, sticky="w", pady=4)
        self.indent_combo = ttk.Combobox(
            cfg, textvariable=self.indent_mode_var, values=list(INDENT_LABELS), state="readonly", width=26,
            style="App.TCombobox", postcommand=self._style_combobox_dropdowns,
        )
        self.indent_combo.grid(row=6, column=1, sticky="e", pady=4)
        self._comboboxes.append(self.indent_combo)

        self.indent_var = tk.IntVar(value=4)
        ttk.Label(cfg, text="Fixed indent width", style="App.TLabel").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Spinbox(cfg, textvariable=self.indent_var, from_=0, to=16, width=8,
                    style="App.TSpinbox").grid(row=7, column=1, sticky="e", pady=4)

        self.coding_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Pascal coding mode (begin/end navigation)", variable=self.coding_mode_var,
                        style="App.TCheckbutton").grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 3))
        self.verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Verify and repair target editor", variable=self.verify_var,
                        style="App.TCheckbutton").grid(row=9, column=0, columnspan=2, sticky="w", pady=3)
        self.det_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="Deterministic seed", variable=self.det_var,
                        style="App.TCheckbutton").grid(row=10, column=0, sticky="w", pady=3)
        self.seed_var = tk.IntVar(value=12345)
        ttk.Spinbox(cfg, textvariable=self.seed_var, from_=0, to=2**31 - 1, width=9,
                    style="App.TSpinbox").grid(row=10, column=1, sticky="e", pady=3)

        items = ttk.LabelFrame(body, text=" Source code / text input ", style="App.TLabelframe", padding=12)
        items.grid(row=1, column=0, sticky="nsew")
        items.rowconfigure(1, weight=1)
        items.columnconfigure(0, weight=1)
        tools = ttk.Frame(items, style="App.TFrame")
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(tools, text="Clear", style="App.TButton", command=self._clear_text).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="Paste clipboard", style="App.TButton", command=self._paste_clipboard).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="Benchmark", style="App.TButton", command=self._benchmark).pack(side="left")

        box = ttk.Frame(items, style="App.TFrame")
        box.grid(row=1, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.text_box = tk.Text(box, height=10, font=("Consolas", 11), wrap="none", undo=True,
                                relief="flat", padx=10, pady=10)
        sy = ttk.Scrollbar(box, orient="vertical", command=self.text_box.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.text_box.xview)
        self.text_box.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.text_box.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.text_box.bind("<Control-a>", self._select_all_text)
        self.text_box.bind("<Control-A>", self._select_all_text)

        footer = ttk.Frame(self, style="App.TFrame", padding=(24, 4, 24, 18))
        footer.pack(fill="x")
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, text="Status: Ready", style="App.TLabel", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="determinate", style="App.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(7, 10))
        buttons = ttk.Frame(footer, style="App.TFrame")
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.start_btn = ttk.Button(buttons, text="Start AutoTyper", style="Accent.TButton", command=self.start_process)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_btn = ttk.Button(buttons, text="Stop", style="Stop.TButton", command=self.stop_process, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._normalise_entry(self.wpm_var, 20, 150, 0)
        self._normalise_entry(self.typo_var, 0.01, 100.0, 2)

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

    def _paste_clipboard(self):
        try:
            content = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Clipboard", "Clipboard is empty or contains non-text data.")
            return
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert("1.0", content)

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
        self.after_cancel(self._poll_id)
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
        # Remember the version and relabel the settings download button (if
        # the settings window happens to be open); the header stays clean.
        self._available_version = latest
        self._refresh_update_controls()
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
        self._set_download_button_state("disabled")
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
            log_event(f"update: downloading {asset.url} ({asset.size} bytes) to {plan.destination}")
            path = download_file(
                asset.url,
                plan.destination,
                progress=lambda done, total: self._post("progress", done, total or None),
                # The size the release advertises: a transfer that stops early
                # is rejected here instead of being installed and then failing
                # to start (which looks exactly like "the update keeps
                # breaking").
                expected_size=asset.size,
            )
            log_event(f"update: downloaded {path} ({describe_size(path)})")
        except DownloadError as err:
            self._post("download_result", "failed", str(err))
            return
        except Exception as err:  # never let a download crash the UI
            self._post("download_result", "failed", f"{type(err).__name__}: {err}")
            return
        self._post("download_result", plan.kind, (str(path), plan.version))

    def _on_download_result(self, outcome: str, payload):
        """React to a finished download on the Tk main thread."""
        self._set_download_button_state("normal")
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
                "and the app restarts automatically. If the new build does not come "
                "up, the previous one is restored and starts instead.",
                icon="question", parent=self,
            ):
                self._install_downloaded_update(path, version)
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

    def _install_downloaded_update(self, path: str, version: Optional[str] = None):
        """Swap in the new executable and quit so the swap script can run.

        `path` is the *staged* download in the temp folder; the build it
        replaces is the one currently running. The swap script watches the new
        build come up and restores this one if it does not.
        """
        try:
            script = install_update_and_restart(path, running_executable(), version=version)
        except DownloadError as err:
            log_event(f"update: refused to install {path}: {err}")
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
            "build is kept as a .old backup, and if the new one fails to start it is "
            "the one that comes back.)",
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
    # Drop PyInstaller's onefile bookkeeping before anything else happens:
    # every process this program starts (the update swap script, a file
    # manager, a helper such as pbpaste) then inherits a clean environment,
    # and a restarted build unpacks its own files. See the notes on
    # `restart_environment` at the top of section 10.
    capture_startup_runtime_environment()
    scrub_pyinstaller_runtime_environment()
    log_startup_environment()

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
            path = download_file(asset.url, destination, progress=report,
                                 expected_size=asset.size)
        except DownloadError as err:
            print(f"\nDownload failed: {err}", file=sys.stderr)
            return 1
        print(f"\r  saved to {path}")
        if args.self_update:
            if not is_frozen():
                print("Not a packaged build, so nothing was replaced; run the .exe above to update.")
                return 0
            try:
                script = install_update_and_restart(path, version=release.version,
                                                    expected_size=asset.size)
            except DownloadError as err:
                print(f"Could not install the update: {err}", file=sys.stderr)
                return 1
            print(f"Update staged ({script.name}); close this program and it will restart on "
                  f"v{release.version} (or come back on v{APP_VERSION} if the new build does "
                  "not start).")
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
    app = AutoTyperApp()
    # Tell the update swap script (if one is waiting) that this build really
    # did come up. Without this signal it assumes the start failed and puts the
    # previous build back.
    mark_startup_complete()
    report_previous_update(app)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
