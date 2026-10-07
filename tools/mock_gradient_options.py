"""Render mock-ups of the custom-colour picker for a design question.

Not part of the application: this script draws *pictures* of the "Edit colours"
dialog (using the real geometry and colour maths from ``auto_typer.py``) so a
change to the gradient box can be agreed on before it is coded.

It is a development aid, not shipped in the .exe and not covered by the test
suite. Render it with:

    ../.venv/bin/python tools/mock_gradient_options.py out.png
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_typer as at  # noqa: E402  (path is set up above)

PAD = at.ColourGradientPicker.PAD
GAP = at.ColourGradientPicker.GAP
MARKER_R = at.ColourGradientPicker.MARKER_R
W, H = at.GRADIENT_WIDTH, at.GRADIENT_HEIGHT
STRIP_W = at.HUE_STRIP_WIDTH
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _rgba(colour: str):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def rows_to_image(rows, width, height) -> Image.Image:
    """Turn ``{"#RRGGBB ..."}`` PhotoImage rows into a PIL image."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y, row in enumerate(rows):
        for x, colour in enumerate(row.strip("{}").split()):
            pixels[x, y] = _rgba(colour)
    return image


def draw_picker(picked, value=1.0, variant="current"):
    """Draw the picker exactly as ``ColourGradientPicker`` lays it out."""
    width = PAD * 2 + W + GAP + STRIP_W
    height = PAD * 2 + H
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    field = rows_to_image(at.gradient_square_rows(value, W, H), W, H)
    strip = rows_to_image(at.shade_strip_rows(STRIP_W, H), STRIP_W, H)
    canvas.paste(field, (PAD, PAD))
    canvas.paste(strip, (PAD + W + GAP, PAD))
    draw = ImageDraw.Draw(canvas)

    hue, saturation, _ = at.hex_to_hsv(picked)
    x = PAD + round(hue * (W - 1))
    y = PAD + round((1.0 - saturation) * (H - 1))

    if variant == "gradient_missing":
        # The state the user may be seeing: the field never got painted.
        draw.rectangle([PAD, PAD, PAD + W - 1, PAD + H - 1], fill=(255, 255, 255))
    if variant == "palette_gradient":
        # The box blending the palette's own three colours instead.
        blend = Image.new("RGB", (W, H))
        stops = [at.normalise_hex_colour(c) for c in PALETTE]
        for px in range(W):
            t = px / (W - 1) * (len(stops) - 1)
            left, right = int(t), min(len(stops) - 1, int(t) + 1)
            f = t - left
            a, b = _rgba(stops[left]), _rgba(stops[right])
            column = tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3))
            for py in range(H):
                blend.putpixel((px, py), column)
        canvas.paste(blend, (PAD, PAD))

    # Borders, exactly one pixel outside the artwork as the widget does.
    draw.rectangle([PAD - 1, PAD - 1, PAD + W, PAD + H], outline=(140, 150, 168))
    draw.rectangle([PAD + W + GAP - 1, PAD - 1, PAD + W + GAP + STRIP_W, PAD + H],
                   outline=(140, 150, 168))

    if variant == "solid_swatch":
        chip_w, chip_h = 44, 26
        chip = [PAD + 6, PAD + H - chip_h - 6, PAD + 6 + chip_w, PAD + H - 6]
        draw.rectangle(chip, fill=_rgba(picked), outline=(17, 24, 39))
    if variant == "filled_marker":
        draw.ellipse([x - MARKER_R + 2, y - MARKER_R + 2, x + MARKER_R - 2, y + MARKER_R - 2],
                     fill=_rgba(picked))
    if variant != "gradient_missing":
        draw.ellipse([x - MARKER_R, y - MARKER_R, x + MARKER_R, y + MARKER_R],
                     outline=(255, 255, 255), width=2)
        draw.ellipse([x - MARKER_R + 2, y - MARKER_R + 2, x + MARKER_R - 2, y + MARKER_R - 2],
                     outline=(17, 24, 39), width=1)
    if variant == "gradient_missing":
        draw.ellipse([x - MARKER_R, y - MARKER_R, x + MARKER_R, y + MARKER_R],
                     outline=(17, 24, 39), width=1)

    strip_y = PAD + round((1.0 - value) * (H - 1))
    sx0 = PAD + W + GAP
    draw.rectangle([sx0 - 5, strip_y - 5, sx0 + STRIP_W + 5, strip_y + 5],
                   outline=(255, 255, 255), width=2)
    draw.rectangle([sx0 - 3, strip_y - 3, sx0 + STRIP_W + 3, strip_y + 3],
                   outline=(17, 24, 39), width=1)
    return canvas


PALETTE = ("#1E3A8A", "#3B82F6", "#F8FAFC")
PICKED = at.hsv_to_hex(0.5, 0.667, 1.0)

PANELS = (
    ("A — a solid swatch of the picked colour inside the gradient box", "solid_swatch"),
    ("B — the marker ring itself filled with the picked colour", "filled_marker"),
    ("C — the gradient square does not paint (empty box)", "gradient_missing"),
    ("D — the box shows the palette's own colours as a gradient", "palette_gradient"),
)


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


def main(destination="gradient-options.png"):
    title_font = ImageFont.truetype(FONT_BOLD, 17)
    label_font = ImageFont.truetype(FONT, 13)
    note_font = ImageFont.truetype(FONT, 13)

    panel_w = PAD * 2 + W + GAP + STRIP_W
    panel_h = PAD * 2 + H
    margin, gutter, line_h = 24, 26, 18
    captions = [(wrap(caption, label_font, panel_w), variant) for caption, variant in PANELS]
    label_h = line_h * max(len(lines) for lines, _ in captions)

    width = margin * 2 + panel_w * 2 + gutter
    height = margin + 30 + 36 + (label_h + panel_h + gutter) * 2 + 26
    sheet = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, margin - 4),
              "Custom colour editor — what should the gradient box show?",
              font=title_font, fill=(23, 32, 51))
    subtitle = (f"Mock-up of the real widget (same geometry and colour maths), not a screenshot. "
                f"Picked colour here: {PICKED}.")
    for number, line in enumerate(wrap(subtitle, note_font, width - margin * 2)[:2]):
        draw.text((margin, margin + 22 + number * 17), line, font=note_font, fill=(90, 100, 120))

    for index, (lines, variant) in enumerate(captions):
        column, row = index % 2, index // 2
        x0 = margin + column * (panel_w + gutter)
        y0 = margin + 70 + row * (label_h + panel_h + gutter)
        for number, line in enumerate(lines):
            draw.text((x0, y0 + number * line_h), line, font=label_font, fill=(23, 32, 51))
        sheet.paste(draw_picker(PICKED, variant=variant), (x0, y0 + label_h))

    draw.text((margin, height - 22),
              "A and B can be combined; C is a bug — the field should always show the rainbow.",
              font=note_font, fill=(90, 100, 120))
    sheet.save(destination)
    print(f"wrote {destination} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gradient-options.png")
