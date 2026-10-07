"""Draw the picture of the colour picker used by the README.

Not part of the application: this renders a *mock-up* of the "Edit colours"
picker (same geometry, same colour maths and the same P6 pixel data the widget
sends to Tk) so the documentation shows what the widget draws. Render it with:

    ../.venv/bin/python tools/render_picker_docs.py docs/colour-gradient.png

The left panel is the picker holding ``#3B82F6``; the right panel is the same
picker while a near-black ``#101010`` is being edited, where the field is drawn
at ``FIELD_MIN_SHADE`` so the rainbow stays readable and the exact colour is
shown by the swatch and the marker dot.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_typer as at  # noqa: E402  (path is set up above)

SCALE = 3                       # the field is drawn 3x its real size
W, H = at.GRADIENT_WIDTH, at.GRADIENT_HEIGHT
STRIP_W = at.HUE_STRIP_WIDTH
PAD, GAP = at.ColourGradientPicker.PAD, at.ColourGradientPicker.GAP
MARKER_R = at.ColourGradientPicker.MARKER_R
MARGIN, GUTTER, LABEL_H = 24, 30, 26
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BORDER = (140, 150, 168)
MARKER = (17, 24, 39)
# (colour being held, colour the marker is positioned from, caption)
CASES = (("#3B82F6", "#3B82F6",
          "Holding #3B82F6: the field is drawn at its brightness and the swatch "
          "shows the colour."),
         ("#101010", "#3B82F6",
          "Editing #101010: the field floors at FIELD_MIN_SHADE, the marker keeps "
          "its place and the swatch keeps the exact colour."))


def ppm_image(data, width, height):
    """The app's P6 bytes as a PIL image (scaled up for the document)."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y, row in enumerate(at.ppm_pixels(data, width, height)):
        for x, colour in enumerate(row.split(" ")):
            pixels[x, y] = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return image.resize((width * SCALE, height * SCALE), Image.NEAREST)


def draw_picker(colour: str, marker_at: str = None) -> Image.Image:
    """One picker panel, laid out exactly as ``ColourGradientPicker`` does.

    ``marker_at`` is the colour whose hue/saturation the marker sits on: the
    widget keeps the position it had when a grey or near-black colour is
    selected, so the picture shows the same thing.
    """
    shade = at.rendered_shade(at.hex_to_hsv(colour)[2])
    marker_at = marker_at or colour
    width = (PAD * 2 + W + GAP + STRIP_W) * SCALE
    height = (PAD * 2 + H) * SCALE
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(ppm_image(at.gradient_square_ppm(shade, W, H), W, H), (PAD * SCALE, PAD * SCALE))
    strip_x = (PAD + W + GAP) * SCALE
    canvas.paste(ppm_image(at.shade_strip_ppm(STRIP_W, H), STRIP_W, H), (strip_x, PAD * SCALE))
    draw = ImageDraw.Draw(canvas)

    def box(x0, y0, x1, y1):
        return [round(v * SCALE) for v in (x0, y0, x1, y1)]

    draw.rectangle(box(PAD - 1, PAD - 1, PAD + W, PAD + H), outline=BORDER, width=SCALE)
    draw.rectangle(box(PAD + W + GAP - 1, PAD - 1, PAD + W + GAP + STRIP_W, PAD + H),
                   outline=BORDER, width=SCALE)

    # The current-colour chip in the field's bottom-left corner, halo and all.
    swatch = (PAD + 8, PAD + H - 8 - 26, PAD + 8 + 46, PAD + H - 8)
    draw.rectangle(box(swatch[0] - 2, swatch[1] - 2, swatch[2] + 2, swatch[3] + 2),
                   outline=(255, 255, 255), width=2 * SCALE)
    draw.rectangle(box(*swatch), fill=tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)),
                   outline=MARKER, width=SCALE)

    # Marker: filled dot, dark ring, white halo -- where the colour sits.
    hue, saturation, _ = at.hex_to_hsv(marker_at)
    cx = PAD + round(hue * (W - 1))
    cy = PAD + round((1.0 - saturation) * (H - 1))
    draw.ellipse(box(cx - MARKER_R, cy - MARKER_R, cx + MARKER_R, cy + MARKER_R),
                 outline=(255, 255, 255), width=2 * SCALE)
    draw.ellipse(box(cx - MARKER_R + 1, cy - MARKER_R + 1,
                     cx + MARKER_R - 1, cy + MARKER_R - 1), outline=MARKER, width=SCALE)
    draw.ellipse(box(cx - MARKER_R + 2, cy - MARKER_R + 2,
                     cx + MARKER_R - 2, cy + MARKER_R - 2),
                 fill=tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)))

    # Shade selector handle, same geometry as the widget's strip markers.
    strip_x0 = PAD + W + GAP
    strip_y = PAD + round(at.value_to_y(at.hex_to_hsv(colour)[2], H))
    draw.rectangle(box(strip_x0 - 5, strip_y - 5, strip_x0 + STRIP_W + 5, strip_y + 5),
                   outline=(255, 255, 255), width=2 * SCALE)
    draw.rectangle(box(strip_x0 - 3, strip_y - 3, strip_x0 + STRIP_W + 3, strip_y + 3),
                   outline=MARKER, width=SCALE)
    return canvas


def wrap(text, font, width):
    """Break ``text`` into lines that fit ``width`` pixels."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def main(destination="docs/colour-gradient.png"):
    label_font = ImageFont.truetype(FONT, 13)
    panels = [draw_picker(colour, marker_at) for colour, marker_at, _ in CASES]
    panel_w = (PAD * 2 + W + GAP + STRIP_W) * SCALE
    panel_h = (PAD * 2 + H) * SCALE
    captions = [wrap(caption, label_font, panel_w) for _, _, caption in CASES]
    label_h = 20 * max(len(lines) for lines in captions)

    width = MARGIN * 2 + panel_w * 2 + GUTTER
    height = MARGIN * 2 + label_h + panel_h
    sheet = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(sheet)
    for index, (panel, lines) in enumerate(zip(panels, captions)):
        x0 = MARGIN + index * (panel_w + GUTTER)
        for number, line in enumerate(lines):
            draw.text((x0, MARGIN + number * 18), line, font=label_font, fill=(23, 32, 51))
        sheet.paste(panel, (x0, MARGIN + label_h))
    sheet.save(destination)
    print(f"wrote {destination} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/colour-gradient.png")
