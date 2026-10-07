"""Render ``docs/colour-studio.png`` — the documentation preview of the studio.

The picture is produced from the very same colour functions the dialog uses
(``build_shade_ramp``, ``build_paint_basic_palette``, ``build_colour_hexagon``
and the hue × saturation maths behind :class:`ColourGradientPicker`), so it
always matches what the pickers actually offer. Run it from the repository root:

    python docs/render_colour_studio.py

It writes PNG data with nothing but the standard library, so it works on a
machine with no Pillow, no display and no Tk.
"""

import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auto_typer as at  # noqa: E402  (path set up above)

WIDTH, HEIGHT = 700, 384
BACKGROUND = "#0F172A"          # Cyberpunk-Neon-ish canvas behind the panels
PANEL = "#111C33"
TEXT = "#E2E8F0"
MUTED = "#7C8AA5"
OUTLINE = "#243352"
ACCENT = "#2B7FD4"
HIGHLIGHT_COLOUR = "#3B82F6"

_FONT = {
    " ": ("00000",) * 7,
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
}


class Image:
    """A tiny RGB canvas that can write a PNG with the standard library."""

    def __init__(self, width, height, background):
        self.width = width
        self.height = height
        red, green, blue = at.hex_to_rgb(background)
        self.pixels = bytearray(bytes((red, green, blue)) * (width * height))

    # -- drawing -------------------------------------------------------
    def pixel(self, x, y, colour):
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self.pixels[offset:offset + 3] = bytes(at.hex_to_rgb(colour))

    def rect(self, x0, y0, x1, y1, colour):
        red, green, blue = at.hex_to_rgb(colour)
        row = bytes((red, green, blue)) * max(0, x1 - x0)
        for y in range(max(0, y0), min(self.height, y1)):
            start = (y * self.width + max(0, x0)) * 3
            self.pixels[start:start + len(row)] = row

    def border(self, x0, y0, x1, y1, colour):
        self.rect(x0, y0, x1, y0 + 1, colour)
        self.rect(x0, y1 - 1, x1, y1, colour)
        self.rect(x0, y0, x0 + 1, y1, colour)
        self.rect(x1 - 1, y0, x1, y1, colour)

    def text(self, x, y, message, colour, scale=2):
        cursor = x
        for character in message.upper():
            glyph = _FONT.get(character)
            if glyph is None:
                cursor += 4 * scale
                continue
            for row, bits in enumerate(glyph):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        self.rect(cursor + column * scale, y + row * scale,
                                  cursor + (column + 1) * scale, y + (row + 1) * scale,
                                  colour)
            cursor += 6 * scale
        return cursor

    # -- output --------------------------------------------------------
    def save(self, path: Path):
        raw = bytearray()
        stride = self.width * 3
        for y in range(self.height):
            raw.append(0)
            raw.extend(self.pixels[y * stride:(y + 1) * stride])

        def chunk(tag, payload):
            return (struct.pack(">I", len(payload)) + tag + payload
                    + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                         + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                         + chunk(b"IEND", b""))


def draw_gradient(image, x, y, value=0.92):
    """The Paint-style hue × saturation field plus its brightness bar."""
    cell = at.GRADIENT_CELL
    for row in range(at.GRADIENT_ROWS):
        saturation = row / (at.GRADIENT_ROWS - 1)
        for column in range(at.GRADIENT_COLUMNS):
            hue = column / (at.GRADIENT_COLUMNS - 1)
            image.rect(x + column * cell, y + row * cell,
                       x + (column + 1) * cell, y + (row + 1) * cell,
                       at.hsv_to_hex(hue, saturation, value))
    field_width = at.GRADIENT_COLUMNS * cell
    bar_x = x + field_width + 8
    bar_width, bar_height = 26, at.GRADIENT_ROWS * cell
    for index in range(at.BRIGHTNESS_STEPS):
        step = bar_height / at.BRIGHTNESS_STEPS
        brightness = 1.0 - index / (at.BRIGHTNESS_STEPS - 1)
        image.rect(bar_x, y + int(index * step), bar_x + bar_width,
                   y + int((index + 1) * step),
                   at.hsv_to_hex(0.62, 0.85, brightness))
    image.border(bar_x, y, bar_x + bar_width, y + bar_height, OUTLINE)
    # crosshair for the selected colour
    hue, saturation, _ = at.hsv_from_hex(HIGHLIGHT_COLOUR)
    cx = x + int(hue * field_width)
    cy = y + int(saturation * bar_height)
    image.rect(cx - 7, cy - 7, cx + 8, cy - 5, "#FFFFFF")
    image.rect(cx - 7, cy + 6, cx + 8, cy + 8, "#FFFFFF")
    image.rect(cx - 7, cy - 7, cx - 5, cy + 8, "#FFFFFF")
    image.rect(cx + 6, cy - 7, cx + 8, cy + 8, "#FFFFFF")
    image.rect(cx - 5, cy - 5, cx + 6, cy + 6, "#111827")
    return field_width, bar_height


def draw_shade_ramp(image, x, y, colour=HIGHLIGHT_COLOUR):
    """The tints-and-shades ramp that sits under every studio tab."""
    hue, saturation, value = at.hsv_from_hex(colour)
    ramp = at.build_shade_ramp(hue, saturation, value)
    swatch_w, swatch_h, gap = 24, 20, 2
    for index, step in enumerate(ramp):
        left = x + index * (swatch_w + gap)
        image.rect(left, y, left + swatch_w, y + swatch_h, step)
        image.border(left, y, left + swatch_w, y + swatch_h, OUTLINE)
    middle = len(ramp) // 2
    left = x + middle * (swatch_w + gap)
    image.border(left - 1, y - 1, left + swatch_w + 1, y + swatch_h + 1, TEXT)
    return len(ramp) * (swatch_w + gap) - gap, swatch_h


def draw_swatch_board(image, x, y):
    """Paint's 48 basic colours, four rows of twelve."""
    board = at.build_paint_basic_palette()
    swatch_w, swatch_h, gap = 20, 17, 3
    for index, colour in enumerate(board):
        row, column = divmod(index, at.PAINT_SWATCH_COLUMNS)
        left = x + column * (swatch_w + gap)
        top = y + row * (swatch_h + gap)
        image.rect(left, top, left + swatch_w, top + swatch_h, colour)
        image.border(left, top, left + swatch_w, top + swatch_h, OUTLINE)
    width = at.PAINT_SWATCH_COLUMNS * (swatch_w + gap) - gap
    height = at.PAINT_SWATCH_ROWS * (swatch_h + gap) - gap
    return width, height


def draw_hexagon(image, x, y, size=13):
    """The honeycomb tab, rasterised by nearest hexagon centre."""
    cells = at.build_colour_hexagon()
    centres = [(at.hexagon_centre(cell.q, cell.r, size), cell.colour) for cell in cells]
    xs = [point[0] for point, _ in centres]
    ys = [point[1] for point, _ in centres]
    width = int(max(xs) - min(xs) + 2 * size)
    height = int(max(ys) - min(ys) + 2 * size)
    for row in range(height):
        for column in range(width):
            px, py = column + min(xs) - size, row + min(ys) - size
            best, colour = None, None
            for (cx, cy), cell_colour in centres:
                distance = (cx - px) ** 2 + (cy - py) ** 2
                if best is None or distance < best:
                    best, colour = distance, cell_colour
            if best is not None and math.sqrt(best) <= size * 0.998:
                image.pixel(x + column, y + row, colour)
    image.border(x, y, x + width, y + height, OUTLINE)
    return width, height


def main():
    image = Image(WIDTH, HEIGHT, BACKGROUND)
    image.rect(12, 12, WIDTH - 12, HEIGHT - 12, PANEL)
    image.border(12, 12, WIDTH - 12, HEIGHT - 12, OUTLINE)
    image.text(24, 24, "colour studio", ACCENT, 2)

    left, right = 24, 380
    label_y, content_y = 54, 68

    image.text(left, label_y, "gradient", MUTED, 1)
    draw_gradient(image, left, content_y)
    image.text(right, label_y, "hexagon", MUTED, 1)
    draw_hexagon(image, right + 6, content_y, size=10)

    lower_y, lower_content = 256, 270
    image.text(left, lower_y, "tints & shades", MUTED, 1)
    draw_shade_ramp(image, left, lower_content)
    image.text(right, lower_y, "48 basic colours", MUTED, 1)
    draw_swatch_board(image, right, lower_content)

    image.save(Path(__file__).resolve().parent / "colour-studio.png")
    print("wrote docs/colour-studio.png")


if __name__ == "__main__":
    main()
