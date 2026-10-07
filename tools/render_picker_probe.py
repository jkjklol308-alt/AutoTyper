"""Probe what a *real* Tk actually paints in the colour picker.

The unit test suite drives the picker through a ``tkinter`` stub, so it proves
which pixel data the widget *hands to* Tk, never what Tk then draws. This probe
closes that gap: it opens the real editor, reads pixels back out of the
``PhotoImage`` Tk stored, and tries each way of feeding Tk a colour field so a
failing call can be told apart from a modelling mistake.

    python tools/render_picker_probe.py --out probe-out

It writes ``probe-out/report.json`` plus a screenshot, prints a summary and
exits non-zero when the picker's own images did not paint. On a workflow runner
the findings are also published as annotations (the raw log and the uploaded
artifacts are not always reachable); see tools/read_probe_annotations.py.
"""

import argparse
import base64
import io
import json
import shutil
import subprocess
import sys
import tkinter as tk
import traceback
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_typer as at  # noqa: E402  (path is set up above)

# Corner/centre/mid-edge samples of the colour field, in field coordinates.
SAMPLE_POINTS = ((0, 0), (120, 0), (239, 0), (0, 80), (120, 80),
                 (239, 80), (0, 159), (120, 159), (239, 159))
PALETTE = ("#1E3A8A", "#3B82F6", "#F8FAFC")

# GitHub truncates an annotation message at 4096 characters, so payloads are
# zlib+base64 chunked below that and reassembled by the reader script.
ANNOTATION_PREFIX = "AUTOTYPER-PROBE:"
ANNOTATION_CHUNK = 3800


def emit_annotation(name: str, payload, level: str = "error") -> int:
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
    """Ask Tk what it really holds at each coordinate."""
    pixels = {}
    for x, y in points:
        try:
            pixels[f"{x},{y}"] = normalise_pixel(image.get(x, y))
        except tk.TclError as err:
            pixels[f"{x},{y}"] = f"<error: {err}>"
    return pixels


def read_back_grid(image, width, height, step: int = 2):
    """Sample the whole image (every ``step`` pixels) as ``{x,y: colour}``."""
    return {f"{x},{y}": normalise_pixel(image.get(x, y))
            for y in range(0, height, step) for x in range(0, width, step)}


# ---------------------------------------------------------------------------
# Painting experiments: which calls can a real Tk actually honour?
# ---------------------------------------------------------------------------
def colour_list(value: float, width: int, height: int) -> str:
    """The payload the picker sends today: one nested colour-name list."""
    return "{" + " ".join(at.gradient_square_rows(value, width, height)) + "}"


def row_list(value: float, width: int, height: int) -> list:
    """One single-row colour list per scanline."""
    return at.gradient_square_rows(value, width, height)


def ppm_bytes(value: float, width: int, height: int, binary: bool = True) -> bytes:
    """The same field as PPM image data (P6 binary or P3 ASCII)."""
    header = f"P{6 if binary else 3}\n{width} {height}\n255\n"
    if not binary:
        body = "\n".join(" ".join(cell.lstrip("#") for cell in
                                  row.strip("{}").split())
                         for row in at.gradient_square_rows(value, width, height))
        return (header + body).encode("ascii")
    raw = bytearray()
    for row in at.gradient_square_rows(value, width, height):
        for cell in row.strip("{}").split():
            raw += bytes.fromhex(cell.lstrip("#"))
    return header.encode("ascii") + bytes(raw)


def try_paint(root, label, width, height, put) -> dict:
    """Run one painting strategy on a fresh image and read the result back."""
    image = tk.PhotoImage(master=root, width=width, height=height)
    result = {"method": label, "size": f"{width}x{height}"}
    try:
        put(image)
    except Exception as err:
        result["result"] = f"{type(err).__name__}: {err}"
        return result
    result["result"] = "ok"
    result["corners"] = read_back(image, ((0, 0), (width - 1, height - 1)))
    return result


def experiment_matrix(root) -> list:
    """Every plausible way to paint the field, smallest sizes first."""
    value = 1.0
    results = []
    for size in (2, 8, 16, 60, 120, 240):
        width, height = size, max(2, size * 2 // 3)
        results.append(try_paint(
            root, "colour-list, one nested list", width, height,
            lambda image, w=width, h=height: image.put(colour_list(value, w, h))))

    big_w, big_h = at.GRADIENT_WIDTH, at.GRADIENT_HEIGHT
    results.append(try_paint(
        root, "colour-list, one row per put (-to)", big_w, big_h,
        lambda image: [image.tk.call(image.name, "put", row, "-to", 0, y)
                       for y, row in enumerate(row_list(value, big_w, big_h))]))

    for binary in (True, False):
        results.append(try_paint(
            root, f"ppm {'P6' if binary else 'P3'} (-format ppm, bytes)", 40, 26,
            lambda image, b=binary: image.tk.call(
                image.name, "put", ppm_bytes(value, 40, 26, b),
                "-to", 0, 0, "-format", "ppm")))
        results.append(try_paint(
            root, f"ppm {'P6' if binary else 'P3'} (-format ppm, sized -to)",
            big_w, big_h,
            lambda image, b=binary: image.tk.call(
                image.name, "put", ppm_bytes(value, big_w, big_h, b),
                "-to", 0, 0, "-format", "ppm", "-to", big_w, big_h)))
    return results


def rebuild_from_ppm(root, value, width, height) -> dict:
    """Create a photo image straight from PPM data (no put at all)."""
    result = {"method": "-data ppm at construction", "size": f"{width}x{height}"}
    try:
        image = tk.PhotoImage(master=root, data=ppm_bytes(value, width, height),
                              format="ppm")
    except Exception as err:
        result["result"] = f"{type(err).__name__}: {err}"
        return result
    result["result"] = "ok"
    result["corners"] = read_back(image, ((0, 0), (width - 1, height - 1)))
    return result


# ---------------------------------------------------------------------------
# Rendering, screenshots and reporting
# ---------------------------------------------------------------------------
def screenshot(window, destination: Path) -> str:
    """Save a picture of ``window``; best effort, returns how it was taken."""
    window.update_idletasks()
    box = (window.winfo_rootx(), window.winfo_rooty(),
           window.winfo_rootx() + window.winfo_width(),
           window.winfo_rooty() + window.winfo_height())
    try:
        from PIL import ImageGrab
        ImageGrab.grab(bbox=box).save(destination)
        return f"PIL.ImageGrab bbox={box}"
    except Exception as err:                      # pragma: no cover - platform
        print(f"PIL screenshot unavailable ({err}); trying ImageMagick")
    for tool in ("import", "magick"):
        found = shutil.which(tool)
        if found is None:
            continue
        try:
            command = ([found, "-window", "root", str(destination)] if tool == "import"
                       else [found, "import", "-window", "root", str(destination)])
            subprocess.run(command, check=True)
            return f"{tool} (whole screen)"
        except subprocess.CalledProcessError as err:  # pragma: no cover
            print(f"{tool} failed: {err}")
    return "unavailable"


def image_from_pixels(pixels, width, height):
    """Rebuild a picture from the pixels Tk reported holding."""
    from PIL import Image
    image = Image.new("RGB", (width, height), (255, 255, 255))
    for key, colour in pixels.items():
        x, y = (int(part) for part in key.split(","))
        normalised = at.normalise_hex_colour(colour)
        if normalised is not None:
            image.putpixel((x, y), tuple(int(normalised[i:i + 2], 16) for i in (1, 3, 5)))
    return image


def thumbnail_base64(image, scale: int, colours: int = 32) -> str:
    """A small PNG of ``image``, base64 encoded, to fit the annotation budget."""
    from PIL import Image
    small = image.convert("RGB")
    if scale > 1:
        small = small.resize((max(1, small.width // scale),
                              max(1, small.height // scale)), Image.NEAREST)
    small = small.convert("P", palette=Image.ADAPTIVE, colors=colours)
    buffer = io.BytesIO()
    small.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode()


def collect_images(picker, out, images: dict) -> None:
    """Thumbnails of what Tk stored, what the model wanted, and the window."""
    try:
        value = picker.hsv[2]
        grid = read_back_grid(picker._square_image, picker.width, picker.height)
        images["tk_stored_field_half"] = thumbnail_base64(
            image_from_pixels(grid, picker.width, picker.height), 2)
        expected = {f"{x},{y}": at.gradient_square_colour(x, y, value)
                    for y in range(0, picker.height, 2)
                    for x in range(0, picker.width, 2)}
        images["model_field_half"] = thumbnail_base64(
            image_from_pixels(expected, picker.width, picker.height), 2)
        shot = out / "picker.png"
        if shot.is_file():
            from PIL import Image
            with Image.open(shot) as grabbed:
                images["screenshot_third"] = thumbnail_base64(grabbed, 3, colours=64)
    except Exception:                              # pragma: no cover - reporting only
        images["error"] = traceback.format_exc(limit=3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="probe-out", help="folder for the report")
    parser.add_argument("--palette", default="Trust Corporate",
                        help="palette whose colours the editor starts from")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"python {sys.version.split()[0]} | tk {tk.TkVersion} "
          f"| patchlevel {tk.Tcl().eval('info patchlevel')} | platform {sys.platform}")

    report = {"python": sys.version.split()[0], "tk": tk.TkVersion,
              "tcl": tk.Tcl().eval("info patchlevel"), "platform": sys.platform}
    images = {}
    exit_code = 0
    root = tk.Tk()
    root.title("AutoTyper probe root")
    try:
        colours = at._palette_colours(args.palette, at.PALETTE_DEFINITIONS)
        editor = at.CustomPaletteEditor(root, colours, on_save=lambda *a: None,
                                        initial=PALETTE, initial_name="Probe")
        editor.title("AutoTyper colour editor probe")
        root.update()
        editor.update()
        picker = editor.picker
        picker.update()
        root.update()

        value = picker.hsv[2]
        actual = read_back(picker._square_image, SAMPLE_POINTS)
        expected = {f"{x},{y}": at.gradient_square_colour(x, y, value)
                    for x, y in SAMPLE_POINTS}
        mismatches = {point: [actual[point], expected[point]]
                      for point in expected if actual[point] != expected[point]}
        report.update({
            "shade": round(value, 4),
            "field_size": [picker.width, picker.height],
            "field_actual": actual,
            "field_mismatches": mismatches,
            "field_mismatch_count": len(mismatches),
            "shade_strip_actual": read_back(picker._strip_image, ((0, 0), (0, 159))),
        })
        # Re-run the exact call the widget makes so a silent failure shows up.
        try:
            picker._square_image.put(colour_list(value, picker.width, picker.height))
            report["widget_put_replay"] = "ok"
        except Exception as err:
            report["widget_put_replay"] = f"{type(err).__name__}: {err}"

        report["paint_experiments"] = experiment_matrix(root)
        report["ppm_construct"] = rebuild_from_ppm(
            root, value, picker.width, picker.height)

        report["screenshot"] = screenshot(editor, out / "picker.png")
        collect_images(picker, out, images)
        if mismatches:
            exit_code = 1
    except Exception:
        report["fatal"] = traceback.format_exc()
        emit_annotation("report", report, "error")
        raise
    finally:
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8")
        print(json.dumps(report, indent=2))
        emit_annotation("report", report, "error" if exit_code else "notice")
        emit_annotation("images", images, "notice")
        try:
            root.destroy()
        except tk.TclError:
            pass

    if exit_code:
        print(f"FAIL: {report['field_mismatch_count']} of {len(SAMPLE_POINTS)} "
              f"sampled pixels do not match the model — the field did not paint")
    else:
        print(f"OK: all {len(SAMPLE_POINTS)} sampled pixels match")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
