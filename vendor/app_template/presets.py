"""Palette presets — the ground/surface/text/status colours of a theme.

A preset does NOT define the accent ramp: that is derived at runtime from
one accent hex in tokens.build_tokens(), so any preset works with any
accent. "Nocturne" is the house look shared with the Houdini tools; the
others exist so the palette can be judged by looking at it rather than
argued about. Contrast was checked when these were designed: body text
clears 7:1 on its ground in every preset and both modes.
"""

from __future__ import annotations

PRESETS = {
    "nocturne": {
        "name": "Nocturne",
        "brand_accent": "#FF6600",
        "dark": {
            "BG": "#161826",
            "SURFACE": "#232532",
            "SURFACE_HOVER": "#2b2e3d",
            "TEXT": "#e9e9ed",
            "TEXT_70": "#a9aab4",
            "TEXT_55": "#8b8c96",
            "TEXT_45": "#75767f",
            "DIVIDER": "#33343f",
            "CODE_BG": "#12131d",
            "CODE_TEXT": "#e6e6ec",
            "SCROLL_HANDLE": "#3f424d",
            "SCROLL_HANDLE_HOVER": "#595d6c",
            "OK": "#6FCF8B",
            "ERROR": "#E5484D",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
        "light": {
            "BG": "#f2f3f7",
            "SURFACE": "#ffffff",
            "SURFACE_HOVER": "#e9ebf2",
            "TEXT": "#1c1e29",
            "TEXT_70": "#4c4e5a",
            "TEXT_55": "#6d6f7a",
            "TEXT_45": "#8a8b94",
            "DIVIDER": "#d9dbe4",
            "CODE_BG": "#eceef4",
            "CODE_TEXT": "#20222c",
            "SCROLL_HANDLE": "#c9ccd8",
            "SCROLL_HANDLE_HOVER": "#aeb2c2",
            "OK": "#188a4a",
            "ERROR": "#d13438",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
    },
    "graphite": {
        "name": "Graphite",
        "brand_accent": "#3D8FC4",
        "dark": {
            "BG": "#1a1a1a",
            "SURFACE": "#262626",
            "SURFACE_HOVER": "#2f2f2f",
            "TEXT": "#e8e8e8",
            "TEXT_70": "#ababab",
            "TEXT_55": "#8f8f8f",
            "TEXT_45": "#787878",
            "DIVIDER": "#343434",
            "CODE_BG": "#131313",
            "CODE_TEXT": "#e4e4e4",
            "SCROLL_HANDLE": "#424242",
            "SCROLL_HANDLE_HOVER": "#5c5c5c",
            "OK": "#62c98a",
            "ERROR": "#e5555b",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
        "light": {
            "BG": "#f0f0f0",
            "SURFACE": "#ffffff",
            "SURFACE_HOVER": "#e7e7e7",
            "TEXT": "#1e1e1e",
            "TEXT_70": "#4a4a4a",
            "TEXT_55": "#696969",
            "TEXT_45": "#8a8a8a",
            "DIVIDER": "#d6d6d6",
            "CODE_BG": "#e8e8e8",
            "CODE_TEXT": "#202020",
            "SCROLL_HANDLE": "#c4c4c4",
            "SCROLL_HANDLE_HOVER": "#a8a8a8",
            "OK": "#157a45",
            "ERROR": "#c22c30",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
    },
    "frost": {
        "name": "Frost",
        "brand_accent": "#5E81AC",
        "dark": {
            "BG": "#1e232d",
            "SURFACE": "#2a3040",
            "SURFACE_HOVER": "#333a4c",
            "TEXT": "#e5e9f0",
            "TEXT_70": "#aeb6c6",
            "TEXT_55": "#929bad",
            "TEXT_45": "#7b8392",
            "DIVIDER": "#343b49",
            "CODE_BG": "#171b23",
            "CODE_TEXT": "#e1e6ee",
            "SCROLL_HANDLE": "#3e4657",
            "SCROLL_HANDLE_HOVER": "#566076",
            "OK": "#a3be8c",
            "ERROR": "#d97781",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
        "light": {
            "BG": "#e9edf3",
            "SURFACE": "#fbfcfe",
            "SURFACE_HOVER": "#dee4ee",
            "TEXT": "#2e3440",
            "TEXT_70": "#454e60",
            "TEXT_55": "#5d6678",
            "TEXT_45": "#7d8698",
            "DIVIDER": "#d3d9e3",
            "CODE_BG": "#e1e6ef",
            "CODE_TEXT": "#262c38",
            "SCROLL_HANDLE": "#c3cad8",
            "SCROLL_HANDLE_HOVER": "#a5aec1",
            "OK": "#35703e",
            "ERROR": "#a3434d",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
    },
    "umber": {
        "name": "Umber",
        "brand_accent": "#C0762E",
        "dark": {
            "BG": "#241f1a",
            "SURFACE": "#302923",
            "SURFACE_HOVER": "#3a322b",
            "TEXT": "#e2d7c8",
            "TEXT_70": "#b4a897",
            "TEXT_55": "#9a8e7d",
            "TEXT_45": "#82766a",
            "DIVIDER": "#3f372e",
            "CODE_BG": "#1c1815",
            "CODE_TEXT": "#ded3c3",
            "SCROLL_HANDLE": "#473e34",
            "SCROLL_HANDLE_HOVER": "#61564a",
            "OK": "#95bf6e",
            "ERROR": "#e2685b",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
        "light": {
            "BG": "#f2eadd",
            "SURFACE": "#fbf6ee",
            "SURFACE_HOVER": "#eae1d2",
            "TEXT": "#2a231c",
            "TEXT_70": "#574c40",
            "TEXT_55": "#6f6152",
            "TEXT_45": "#8e8171",
            "DIVIDER": "#dfd3c2",
            "CODE_BG": "#ede3d4",
            "CODE_TEXT": "#2f2820",
            "SCROLL_HANDLE": "#cfc2b0",
            "SCROLL_HANDLE_HOVER": "#b3a491",
            "OK": "#436f26",
            "ERROR": "#b03c2c",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
    },
    "iausage": {
        "name": "IA Usage",
        # ia-usage's own navy is near-invisible on a dark ground, so it
        # ships a lighter, more saturated sibling for dark mode — the
        # reason brand_accent_dark exists at preset level at all.
        "brand_accent": "#2E4372",
        "brand_accent_dark": "#7C97E0",
        "dark": {
            # SURFACE is ia-usage's own card colour (#2B2B2E): in that app
            # the card floats straight on the desktop, so its "card" is a
            # surface, not a ground. BG is the ground derived under it.
            "BG": "#1e1e20",
            "SURFACE": "#2b2b2e",
            "SURFACE_HOVER": "#35353a",
            "TEXT": "#f2f2f2",
            "TEXT_70": "#cdcdd0",
            "TEXT_55": "#b8b8b8",
            "TEXT_45": "#909093",
            "DIVIDER": "#38383c",
            "CODE_BG": "#17171a",
            "CODE_TEXT": "#ededed",
            "SCROLL_HANDLE": "#414147",
            "SCROLL_HANDLE_HOVER": "#5a5a62",
            # the endpoints of ia-usage's own green/red meter bands, so a
            # status line and a full meter agree on what green and red are
            "OK": "#72d08f",
            "ERROR": "#ee8484",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
        "light": {
            "BG": "#ebebec",
            "SURFACE": "#fafafa",
            "SURFACE_HOVER": "#e0e0e2",
            "TEXT": "#1a1a1a",
            "TEXT_70": "#3f3f3f",
            "TEXT_55": "#555555",
            "TEXT_45": "#7a7a7a",
            "DIVIDER": "#d4d4d5",
            "CODE_BG": "#e4e4e5",
            "CODE_TEXT": "#1f1f1f",
            "SCROLL_HANDLE": "#c2c2c4",
            "SCROLL_HANDLE_HOVER": "#a5a5a8",
            # the same band colours darkened until they clear 4.5:1 on the
            # light ground (#2a7f4f/#ce3d3d measured 4.15/4.04)
            "OK": "#27774a",
            "ERROR": "#be3838",
            "CLOSE_HOVER": "#C42B1C",
            "CLOSE_PRESSED": "#8E2117",
        },
    },
}

DEFAULT_PRESET = "nocturne"

# one-line character notes, shown as tooltips in Settings
BLURBS = {
    "nocturne": "Deep indigo ground, Houdini orange. The house look.",
    "graphite": "Pure neutral grey — nothing tints your colour judgement.",
    "frost": "Cool desaturated blue-grey, Nord lineage. Calm.",
    "umber": "Warm near-black and cream. Softest; not for colour work.",
    "iausage": "Soft-white sheet or near-black card, navy accent. ia-usage.",
}


REQUIRED_KEYS = frozenset(PRESETS[DEFAULT_PRESET]["dark"])


def preset(key):
    return PRESETS.get(key) or PRESETS[DEFAULT_PRESET]


def validate(key):
    """Raise with a useful message instead of failing later inside an
    f-string in chrome_qss(), which is where a typo used to surface."""
    p = PRESETS[key]
    for field in ("name", "brand_accent", "dark", "light"):
        if field not in p:
            raise KeyError(f"preset '{key}' is missing '{field}'")
    for mode in ("dark", "light"):
        missing = REQUIRED_KEYS - set(p[mode])
        if missing:
            raise KeyError(
                f"preset '{key}' {mode} palette is missing: "
                f"{', '.join(sorted(missing))}")
    return True


def palette(key, dark):
    p = preset(key)
    return dict(p["dark" if dark else "light"])


def brand_accent(key, dark=False):
    """The preset's own "Original" accent.

    brand_accent_dark is optional and rare: only a brand colour that goes
    invisible on a dark ground needs one (see the iausage preset). Every
    other preset returns the same hex in both modes.
    """
    p = preset(key)
    if dark:
        return p.get("brand_accent_dark") or p["brand_accent"]
    return p["brand_accent"]
