"""Design tokens.

A palette preset (see presets.py) supplies the ground, surfaces, text
tiers and status colours; build_tokens() derives everything else from a
single accent hex — the hover/pressed/soft fills, the ink that goes on
top of the accent, and the window border. So any accent works with any
preset, and adding a preset never means hand-authoring a ramp.

Settings concepts (ORIGINAL sentinel, curated swatches) follow ia-usage.
"""

from __future__ import annotations

from .presets import DEFAULT_PRESET, PRESETS, palette

ORIGINAL_ACCENT = "ORIGINAL"

# Curated accent swatches offered in Settings, same set as ia-usage.
ACCENT_SWATCHES = [
    "#378ADD", "#7F77DD", "#1D9E75", "#D85A30", "#D4537E", "#639922",
    "#D64545", "#B37D0F", "#5B6472", "#127F9E", "#5457C9",
]

RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 14

FONT_STACK = '"Inter", "Segoe UI Variable Text", "Segoe UI", sans-serif'
MONO_STACK = '"Cascadia Code", "Consolas", monospace'

# Ink for an accent light enough to need dark text. No shipped accent is
# (the lightest is luminance 0.31 against a 0.4 threshold), so this only
# fires for a custom yellow/lime/cyan brand accent — untested insurance.
_DARK_INK = "#161826"

# Back-compat aliases from before presets existed. Copies, not the live
# preset dicts: a consumer that mutated these would otherwise corrupt
# Nocturne for the whole process. They are palettes only — no ramp.
DARK = dict(PRESETS[DEFAULT_PRESET]["dark"])
LIGHT = dict(PRESETS[DEFAULT_PRESET]["light"])


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(a, b, t):
    """Blend color a toward color b by fraction t (0..1)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def luminance(hex_color):
    """WCAG relative luminance."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def on_accent(accent_hex):
    """Ink color on top of the accent. Same pragmatic 0.4 threshold as
    ia-usage: strict WCAG picks black on saturated blue/purple backgrounds
    that everyone actually reads better in white."""
    return _DARK_INK if luminance(accent_hex) > 0.4 else "#ffffff"


def build_tokens(dark, accent_hex, preset=DEFAULT_PRESET):
    """Full token set for one preset + theme + accent combination."""
    t = palette(preset, dark)
    toward = "#ffffff" if dark else "#000000"
    t.update({
        "ACCENT": accent_hex,
        # readable-on-BG accent variants (tags, warnings, hover strokes)
        "ACCENT_300": mix(accent_hex, toward, 0.55 if dark else 0.35),
        "ACCENT_400": mix(accent_hex, toward, 0.30 if dark else 0.18),
        # pressed/hover fills for solid accent controls
        "ACCENT_600": mix(accent_hex, "#000000", 0.12),
        "ACCENT_700": mix(accent_hex, "#000000", 0.24),
        # soft accent-tinted fills against the ground
        "ACCENT_800": mix(accent_hex, t["BG"], 0.70),
        "ACCENT_900": mix(accent_hex, t["BG"], 0.82),
        "ON_ACCENT": on_accent(accent_hex),
        # the 1px ring around the window card: the divider lifted toward
        # the text colour so it separates from the desktop behind it
        "WINDOW_BORDER": mix(t["DIVIDER"], t["TEXT"], 0.18),
        "RADIUS_SM": RADIUS_SM,
        "RADIUS_MD": RADIUS_MD,
        "RADIUS_LG": RADIUS_LG,
        "FONT_STACK": FONT_STACK,
        "MONO_STACK": MONO_STACK,
    })
    return t
