"""Probe what a *real* Tk actually paints in the colour picker.

The unit test suite drives the picker through a ``tkinter`` stub, so it proves
which pixel data the widget *hands to* Tk, never what Tk then draws. This probe
closes that gap: it opens the real editor, reads pixels back out of the
``PhotoImage`` Tk stored, and saves a screenshot of the window.

Run it on a machine with a display (or under ``xvfb-run`` on Linux):

    python tools/render_picker_probe.py --out probe-out

It prints a per-pixel comparison of what Tk stored against what
``gradient_square_colour`` says that pixel should be, writes
``probe-out/picker.png`` (a screenshot of the editor) and exits non-zero when
the colour field did not paint.

Used by the manual "Picker rendering" workflow, which runs it on Windows and
Linux so a rendering bug can be told apart from a modelling bug.
"""

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_typer as at  # noqa: E402  (path is set up above)

# Corner/centre/mid-edge samples of the colour field, in field coordinates.
SAMPLE_POINTS = ((0, 0), (120, 0), (239, 0), (0, 80), (120, 80),
                 (239, 80), (0, 159), (120, 159), (239, 159))
PALETTE = ("#1E3A8A", "#3B82F6", "#F8FAFC")

# Findings are published as GitHub workflow annotations: on hosted runners the
# raw log and the uploaded artifacts are not always reachable, while the
# annotation API is. GitHub truncates an annotation message at 4096 characters,
# so payloads are zlib+base64 chunked well below that and reassembled by
# tools/read_probe_annotations.py.
ANNOTATION_PREFIX = "AUTOTYPER-PROBE:"
ANNOTATION_CHUNK = 3800     # characters per annotation, under the 4096 limit


def emit_annotation(name: str, payload, level: str = "error") -> None:
    """Print ``payload`` as chunked workflow annotations."""
    blob = json.dumps(payload, separators=(",", ":"), default=str).encode()
    encoded = base64.b64encode(zlib.compress(blob, 9)).decode()
    chunks = [encoded[i:i + ANNOTATION_CHUNK]
              for i in range(0, len(encoded), ANNOTATION_CHUNK)] or [""]
    for index, chunk in enumerate(chunks, start=1):
        print(f"::{level}::{ANNOTATION_PREFIX}{name}:{index}/{len(chunks)}:{chunk}",
              flush=True)
    return len(chunks)



def normalise_pixel(value) -> str:
    """``PhotoImage.get`` returns ints on Tk 8.6 and names on older builds."""
    if isinstance(value, str):
        return at.normalise_hex_colour(value) or value
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return "#{:02X}{:02X}{:02X}".format(*(int(part) for part in value[:3]))
    return str(value)


def read_back(image, points):
    """Ask Tk what it really holds at each field coordinate."""
    pixels = {}
    for x, y in points:
        try:
            pixels[f"{x},{y}"] = normalise_pixel(image.get(x, y))
        except tk.TclError as err:
            pixels[f"{x},{y}"] = f"<error: {err}>"
    return pixels


def screenshot(window, destination: Path) -> str:
    """Save a picture of ``window``; best effort, returns how it was taken."""
    window.update_idletasks()
    box = (window.winfo_rootx(), window.winfo_rooty(),
           window.winfo_rootx() + window.winfo_width(),
           window.winfo_rooty() + window.winfo_height())
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab(bbox=box)
        image.save(destination)
        return f"PIL.ImageGrab bbox={box}"
    except Exception as err:                      # pragma: no cover - platform
        print(f"PIL screenshot unavailable ({err}); trying ImageMagick")
    for tool in ("import", "magick"):
        found = shutil.which(tool)
        if found is None:
            continue
        try:
            if tool == "import":
                subprocess.run([found, "-window", "root", str(destination)], check=True)
            else:
                subprocess.run([found, "import", "-window", "root", str(destination)], check=True)
            return f"{tool} (whole screen)"
        except subprocess.CalledProcessError as err:  # pragma: no cover
            print(f"{tool} failed: {err}")
    return "unavailable"


def image_from_pixels(pixels: dict, width: int, height: int):
    """Rebuild a picture from the pixels Tk reported holding."""
    from PIL import Image
    image = Image.new("RGB", (width, height), (255, 255, 255))
    for key, colour in pixels.items():
        x, y = (int(part) for part in key.split(","))
        normalised = at.normalise_hex_colour(colour)
        if normalised is not None:
            image.putpixel((x, y), tuple(int(normalised[i:i + 2], 16) for i in (1, 3, 5)))
    return image


def read_back_grid(image, width, height, step: int = 2):
    """Sample the whole image (every ``step`` pixels) as ``{x,y: colour}``."""
    return {f"{x},{y}": normalise_pixel(image.get(x, y))
            for y in range(0, height, step) for x in range(0, width, step)}


def thumbnail_base64(image, scale: int, colours: int = 32) -> str:
    """A small PNG of ``image``, base64 encoded, for the annotation budget."""
    from PIL import Image
    small = image.convert("RGB")
    if scale > 1:
        small = small.resize((max(1, small.width // scale),
                              max(1, small.height // scale)), Image.NEAREST)
    small = small.convert("P", palette=Image.ADAPTIVE, colors=colours)
    buffer = io.BytesIO()
    small.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="probe-out", help="folder for the screenshot")
    parser.add_argument("--palette", default="Trust Corporate",
                        help="palette whose colours the editor starts from")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"python {sys.version.split()[0]} | tk {tk.TkVersion} "
          f"| patchlevel {tk.Tcl().eval('info patchlevel')} | platform {sys.platform}")

    root = tk.Tk()
    root.title("AutoTyper probe root")
    colours = at._palette_colours(args.palette, at.PALETTE_DEFINITIONS)
    editor = at.CustomPaletteEditor(root, colours, on_save=lambda *a: None,
                                    initial=PALETTE, initial_name="Probe")
    editor.title("AutoTyper colour editor probe")
    root.update()
    editor.update()
    picker = editor.picker
    picker.update()

    value = picker.hsv[2]
    actual = read_back(picker._square_image, SAMPLE_POINTS)
    expected = {f"{x},{y}": at.gradient_square_colour(x, y, value)
                for x, y in SAMPLE_POINTS}
    mismatches = {point: (actual[point], expected[point])
                  for point in expected if actual[point] != expected[point]}
    strip = read_back(picker._strip_image, ((0, 0), (0, 159)))

    report = {
        "tk": tk.TkVersion,
        "tcl": tk.Tcl().eval("info patchlevel"),
        "shade": value,
        "field_size": [picker.width, picker.height],
        "field_actual": actual,
        "field_expected": expected,
        "field_mismatches": mismatches,
        "shade_strip_actual": strip,
    }
    how = screenshot(editor, out / "picker.png")
    report["screenshot"] = how
    (out / "probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    images = {}
    try:
        grid = read_back_grid(picker._square_image, picker.width, picker.height)
        images["tk_stored_field_half"] = thumbnail_base64(
            image_from_pixels(grid, picker.width, picker.height), 2)
        expected_grid = {f"{x},{y}": at.gradient_square_colour(x, y, value)
                         for y in range(0, picker.height, 2)
                         for x in range(0, picker.width, 2)}
        images["model_field_half"] = thumbnail_base64(
            image_from_pixels(expected_grid, picker.width, picker.height), 2)
        shot = out / "picker.png"
        if shot.is_file():
            from PIL import Image
            with Image.open(shot) as grabbed:
                images["screenshot_third"] = thumbnail_base64(grabbed, 3, colours=64)
    except Exception as err:                       # pragma: no cover - reporting only
        images["error"] = f"{type(err).__name__}: {err}"

    printed = {k: report[k] for k in
               ("tk", "tcl", "shade", "field_actual", "field_expected",
                "field_mismatches", "shade_strip_actual", "screenshot")}
    print(json.dumps(printed, indent=2))
    emit_annotation("report", {"report": printed}, "error")
    emit_annotation("images", images, "notice")
    root.destroy()

    if mismatches:
        print(f"FAIL: {len(mismatches)} of {len(expected)} sampled pixels do not "
              f"match the model — the field did not paint as expected")
        return 1
    print(f"OK: all {len(expected)} sampled pixels match; screenshot via {how}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
