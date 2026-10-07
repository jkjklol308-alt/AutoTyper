# AutoTyper

A high-fidelity keystroke trace simulator and auto-typer featuring motor kinematics (Fitts' Law ID, hand alternation), cognitive models (Ornstein-Uhlenbeck pace drift, fatigue, log-normal dwells, error episodes), editor auto-indent integration, and an intelligent **Coding Mode** with Pascal `begin`/`end` lookahead.

## Download (no Python required)

1. Open the [latest release](https://github.com/jkjklol308-alt/AutoTyper/releases/latest).
2. Download **`AutoTyper.exe`**.
3. Run it. That's it — the executable is self-contained.

You can also grab the executable from inside the app itself: open **⚙ Settings** and press **⬇ Download latest AutoTyper.exe** under *Updates & downloads*. The updater always fetches the built executable — never a Python script.

### Running from source instead

```bash
pip install pynput
python auto_typer.py            # launches the interactive UI
python auto_typer.py --check-update
```

## Updating

AutoTyper checks the newest GitHub release once, silently, when the window opens. It stays completely quiet unless a genuinely newer version exists, and it never blocks startup or forces an upgrade.

When an update does exist, the status bar names the new version, AutoTyper asks once whether to download it, and the download button in ⚙ Settings is relabelled **⬇ Get vX .exe**. You always choose what happens:

| How you are running | What updating does |
| --- | --- |
| The packaged **AutoTyper.exe** | Downloads the new build, then offers to install it. On install the app replaces itself, restarts automatically, and keeps your previous build as `AutoTyper.exe.old` in case you want to roll back. |
| From **source** (`python auto_typer.py`) | Downloads the new `AutoTyper.exe` into your Downloads folder and shows you where it went, so you can switch to the packaged build. |

The automatic restart is deliberately set up like a manual double-click: it starts the new build with a **clean environment**. A onefile build keeps the path of its unpacked temporary folder in the environment, and a restart that inherited it would look for that (already deleted) folder instead of unpacking its own files — which made the app fail with *"Error loading Python DLL"* right after an update while the very same file started fine from a shortcut. If the swap cannot complete at all, the existing build is brought back up instead of leaving you without a program.

Only files that begin with the Windows `MZ` executable header are ever accepted, so a failed, truncated or HTML-error-page download can never overwrite a working build. The CLI mirrors this:

```bash
python auto_typer.py --check-update            # is there anything newer?
python auto_typer.py --download-exe            # fetch AutoTyper.exe (optionally: --download-exe DIR)
python auto_typer.py --self-update             # download, swap, restart (packaged builds)
```

## Key Features

1. **Stochastic Timing & Kinematic Modeling**
   - **Inter-Key Interval (IKI)**: Gammavariate distributions parameterized by WPM, Fitts' difficulty index, hand alternation, digraph speed-ups, syntax delays, and shift modifier reach penalties.
   - **Dwell Time**: Log-normally distributed key hold durations adapted to current pace and key type.
   - **Pace Drift & Fatigue**: Exact Ornstein-Uhlenbeck discretisation with mean-reversion and workload/recovery dynamics.
   - **Error Episodes**: Naturalistic typing errors (substitution, transposition, omission, insertion, overshoot) with realization pauses and backspace corrections.
   - **Natural Thinking Pauses**: Pauses occur naturally at word boundaries rather than within runs of whitespace.

2. **Editor Auto-Indent Policies**
   - `"off"`: Types text verbatim without deleting indentation.
   - `"copy"`: Automatically predicts and clears indentation copied from the preceding line.
   - `"smart"`: Predicts additional indentation levels opened by block characters (`:`, `{`, `(`, `[`) or Pascal keywords (`begin`, `then`, `do`, `try`, etc.).
   - `"fixed"`: Issues a fixed count of backspaces after each newline.
   - `tab_stop_backspace`: Supports editor behavior where Backspace removes full indentation levels at once (e.g. VS Code smart backspace).

3. **Coding Mode (Pascal / Structured Code Lookahead)**
   - Scans forward to detect matching `begin` ... `end` blocks (with full support for nested blocks, comments, and string literals).
   - Types out the block frame (`begin`, newline, `end`), navigates back up (`<UP>`), fills in all body statements in logical order, and navigates down (`<DOWN>`) past the closing `end`.
   - Produces 100% exact source code in the target editor while capturing authentic coding behavior.

## CLI Usage

### Run Benchmark (Simulated, no keys pressed)
```bash
python auto_typer.py --benchmark --wpm 110 --mode net --typo 3.0 --seed 12345
```

### Benchmark Coding Mode on a Pascal File
```bash
python auto_typer.py --benchmark --coding-mode --file program.pas --indent smart
```

### Export Keystroke Trace to CSV
```bash
python auto_typer.py --benchmark --wpm 100 --seed 42 --csv trace.csv --coding-mode --file program.pas
```

## Running the Test Suite

```bash
python -m unittest test_auto_typer.py test_custom_colours.py test_update_checker.py
```

`test_auto_typer.py` replays planned traces through a virtual editor to prove the emitted keystrokes reproduce the source text exactly, `test_update_checker.py` covers the release lookup, the download/verification path and the self-update swap, and `test_custom_colours.py` exercises the colour picker through a miniature `tkinter` stub so the suite runs with no display.

## Custom UI Colours

![The Paint-style gradient used by the custom colour picker](docs/colour-gradient.png)

The header keeps a single **⚙ Settings** button — palettes, window behaviour and updates all live inside it:

- **Custom “UI colour” section**: press **🎨 New colours…** to open the editor, which uses the *Microsoft Paint “Edit colours” style gradient picker* — a big colour field (the whole rainbow left to right, pure colours fading to greyscale towards the bottom, drawn at the current shade) beside a white‑to‑black shade strip. Click or **drag** anywhere in the field to pick the colour itself — the colour you have chosen is always the pixel under the marker — then slide the strip to lighten or darken it; every intermediate colour is reachable, not just a fixed set of swatches.
- Choose a **Primary**, **Accent** and **Background** colour (drag in the gradient or type `#RRGGBB`), watch the live preview, give the set a name, and **Save colours**.
- Saved palettes appear in the palette grid marked with a ★, are applied instantly, survive restarts (stored in `~/.autotyper_settings.json`; settings from earlier releases under the old file name are picked up automatically), and can be re-opened for editing by double-clicking a card or pressing **Edit selected**. **Delete selected** removes one; built-in palettes cannot be deleted. Up to 16 custom palettes are kept.

## Building the executable yourself

```bash
pip install pyinstaller pynput
pyinstaller AutoTyper.spec --noconfirm     # -> dist/AutoTyper.exe
```

Pushing a tag that matches `APP_VERSION` (for example `v1.1.1`) makes GitHub Actions run the tests, build the executable and attach it to a release automatically — see `.github/workflows/release.yml`.
