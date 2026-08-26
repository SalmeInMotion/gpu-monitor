"""Draw the GPU Monitor icon, and pack it into a multi-resolution .ico.

    python ico\\make_icon.py --sheet     candidates, side by side, for choosing
    python ico\\make_icon.py --build     write GPU_Monitor.ico

Drawn rather than painted-over-a-photo on purpose: an icon has to survive
being 16px in a taskbar, and every shape here is proportional to the
canvas, so each size in the .ico is *redrawn* at that size instead of
being a blurry downsample of the 256 one.

Colours are the app's own — the ia-usage ramp from monitor/meter.py and
the brand navy from gpu_monitor.py — so the icon and the card cannot
drift apart.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

# straight out of monitor/meter.py and gpu_monitor.py
GREEN = ("#72d08f", "#3f9e63")
AMBER = ("#f3c36a", "#d99420")
RED = ("#ee8484", "#ce3d3d")
ACCENT = ("#9db0ea", "#7C97E0")
BRAND_NAVY = "#2E4372"

PLATE_TOP = "#39415c"
PLATE_BOTTOM = "#1c2030"
TRACK = (255, 255, 255, 38)

SS = 4                       # supersample factor


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _plate(size, top=PLATE_TOP, bottom=PLATE_BOTTOM, radius=0.22):
    """The rounded tile everything sits on, with a soft vertical gradient."""
    grad = Image.new("RGB", (1, size))
    a, b = _rgb(top), _rgb(bottom)
    for y in range(size):
        grad.putpixel((0, y), _lerp(a, b, y / max(1, size - 1)))
    grad = grad.resize((size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius), fill=255)

    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate.paste(grad, (0, 0), mask)
    return plate


def _overlay(img, paint):
    """Draw something translucent so it blends instead of punching a hole.

    PIL only alpha-blends ink when the target is RGB; on an RGBA image a
    fill carrying alpha simply *replaces* the pixel. The 15%-white meter
    track came out as a 15%-opaque hole through the whole icon — which
    looks like a grey rail on a dark desktop and a white slab on a light
    one, the giveaway being that it changed with the wallpaper.
    """
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    paint(ImageDraw.Draw(layer, "RGBA"))
    img.alpha_composite(layer)


def _bar(img, draw, x0, y0, x1, y1, fraction, colors, track=True):
    """One pill meter: translucent track, rounded fill, flat two-stop blend."""
    h = y1 - y0
    if track:
        _overlay(img, lambda dd: dd.rounded_rectangle(
            (x0, y0, x1, y1), radius=h // 2, fill=TRACK))
    width = (x1 - x0) * fraction
    if width < h:                     # never thinner than its own cap
        width = h
    draw.rounded_rectangle((x0, y0, x0 + width, y1), radius=h // 2,
                           fill=_rgb(colors[1]))
    # a lighter top half, standing in for the app's gradient
    draw.rounded_rectangle((x0, y0, x0 + width, y0 + h * 0.52),
                           radius=h // 2, fill=_rgb(colors[0]))


def meters(size, detail=True):
    """Three pill meters — literally what the card shows."""
    S = size * SS
    img = _plate(S)
    d = ImageDraw.Draw(img, "RGBA")

    pad = S * 0.19
    bar_h = S * 0.135
    gap = (S - 2 * pad - 3 * bar_h) / 2
    rows = ((0.74, GREEN), (0.46, ACCENT), (0.90, AMBER))
    for i, (fraction, colors) in enumerate(rows):
        y0 = pad + i * (bar_h + gap)
        _bar(img, d, pad, y0, S - pad, y0 + bar_h, fraction, colors)
    return img.resize((size, size), Image.LANCZOS)


def _pins(d, x0, x1, S, count=3, pin_len=0.085, pin_w=0.052, spread=0.30):
    """The die's legs — same three a side on every concept that has them.

    The body is always square, drawn from (x0, x0) to (x1, x1), so one set
    of offsets serves all four edges. Each leg overlaps the body by its own
    width, which is what keeps the joint from showing a seam once the whole
    thing is downsampled.
    """
    body = x1 - x0
    pl, pw = S * pin_len, S * pin_w
    colour = _rgb(ACCENT[1])
    for i in range(count):
        mid = (x0 + x1) / 2 + (i - (count - 1) / 2) * body * spread
        d.rounded_rectangle((mid - pw / 2, x0 - pl, mid + pw / 2, x0 + pw),
                            radius=pw / 2, fill=colour)
        d.rounded_rectangle((mid - pw / 2, x1 - pw, mid + pw / 2, x1 + pl),
                            radius=pw / 2, fill=colour)
        d.rounded_rectangle((x0 - pl, mid - pw / 2, x0 + pw, mid + pw / 2),
                            radius=pw / 2, fill=colour)
        d.rounded_rectangle((x1 - pw, mid - pw / 2, x1 + pl, mid + pw / 2),
                            radius=pw / 2, fill=colour)


def chip(size, detail=True):
    """A die with pins — the universal "this is silicon" shape."""
    S = size * SS
    img = _plate(S)
    d = ImageDraw.Draw(img, "RGBA")

    body = S * 0.50
    x0 = (S - body) / 2
    x1 = x0 + body
    if detail:
        _pins(d, x0, x1, S)

    d.rounded_rectangle((x0, x0, x1, x1), radius=body * 0.20,
                        fill=_rgb(BRAND_NAVY),
                        outline=_rgb(ACCENT[1]), width=int(S * 0.022))
    bar_h = body * 0.16
    inner = body * 0.16
    _bar(img, d, x0 + inner, (x0 + x1) / 2 - bar_h / 2,
         x1 - inner, (x0 + x1) / 2 + bar_h / 2, 0.72, GREEN, track=True)
    return img.resize((size, size), Image.LANCZOS)


def gauge(size, detail=True):
    """A dial: one number, read at a glance, from across the room."""
    S = size * SS
    img = _plate(S)
    d = ImageDraw.Draw(img, "RGBA")

    pad = S * 0.24
    box = (pad, pad, S - pad, S - pad)
    thickness = int(S * 0.115)
    _overlay(img, lambda dd: dd.arc(box, start=135, end=405,
                                    fill=(255, 255, 255, 46), width=thickness))
    d.arc(box, start=135, end=135 + 270 * 0.72, fill=_rgb(GREEN[1]),
          width=thickness)
    d.arc(box, start=135, end=135 + 270 * 0.40, fill=_rgb(GREEN[0]),
          width=thickness)
    if detail:
        r = S * 0.055
        cx, cy = S / 2, S / 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_rgb(ACCENT[1]))
    return img.resize((size, size), Image.LANCZOS)


def chip_meters(size, detail=True):
    """The two ideas at once: a die whose face is the card's meters."""
    S = size * SS
    img = _plate(S)
    d = ImageDraw.Draw(img, "RGBA")

    # Slightly tighter body than the plain chip's face would suggest: the
    # legs are the same three a side, and at 0.62 the outer pair ran into
    # the plate's rounded corner.
    body = S * 0.58
    x0 = (S - body) / 2
    x1 = x0 + body
    if detail:
        _pins(d, x0, x1, S)

    d.rounded_rectangle((x0, x0, x1, x1), radius=body * 0.22,
                        fill=(20, 24, 36, 255),
                        outline=_rgb(ACCENT[1]), width=int(S * 0.020))
    inner = body * 0.17
    bar_h = body * 0.155
    gap = bar_h * 0.72
    total = 2 * bar_h + gap
    top = (x0 + x1) / 2 - total / 2
    _bar(img, d, x0 + inner, top, x1 - inner, top + bar_h, 0.78, GREEN)
    _bar(img, d, x0 + inner, top + bar_h + gap, x1 - inner,
         top + 2 * bar_h + gap, 0.48, AMBER)
    return img.resize((size, size), Image.LANCZOS)


CONCEPTS = {"meters": meters, "chip": chip, "gauge": gauge,
            "chipmeters": chip_meters}

# What Windows actually asks for, smallest first. Each is redrawn, and the
# three smallest drop the pins and the hub — detail that turns to mud.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
DETAIL_FROM = 32


def build(concept, path=None):
    fn = CONCEPTS[concept]
    frames = [fn(s, detail=s >= DETAIL_FROM) for s in ICO_SIZES]
    path = path or os.path.join(HERE, "GPU_Monitor.ico")
    frames[-1].save(path, format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES],
                    append_images=frames[:-1])
    return path


def sheet(path=None):
    """Every concept at 256, with its own 48/32/16 beside it."""
    names = list(CONCEPTS)
    cell, pad = 256, 24
    strip = 48 + 32 + 16 + 24
    w = pad + len(names) * (cell + strip + pad)
    h = pad + cell + pad + 34
    img = Image.new("RGBA", (w, h), (22, 22, 26, 255))
    d = ImageDraw.Draw(img)
    for i, name in enumerate(names):
        x = pad + i * (cell + strip + pad)
        img.alpha_composite(CONCEPTS[name](cell), (x, pad))
        y = pad
        for s in (48, 32, 16):
            img.alpha_composite(
                CONCEPTS[name](s, detail=s >= DETAIL_FROM), (x + cell + 12, y))
            y += s + 14
        d.text((x + 4, pad + cell + 10), name, fill=(210, 210, 216))
    path = path or os.path.join(HERE, "_candidates.png")
    img.save(path)
    return path


if __name__ == "__main__":
    if "--build" in sys.argv:
        which = sys.argv[sys.argv.index("--build") + 1] \
            if len(sys.argv) > sys.argv.index("--build") + 1 else "chipmeters"
        print(build(which))
    else:
        print(sheet())
