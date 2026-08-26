"""App settings — JSON in %LOCALAPPDATA%/<AppName>/settings.json.

Same contract as ia-usage's AppSettings: load never fails (corrupt file
falls back to defaults), save is atomic (temp + replace) so a force-kill
mid-write can never truncate the file.
"""

from __future__ import annotations

import json
import os


DEFAULTS = {
    "preset": "nocturne",       # palette preset, see presets.PRESETS
    "theme": "system",          # "system" | "light" | "dark"
    "accent": "ORIGINAL",       # ORIGINAL sentinel or "#RRGGBB"
    "hover_glow": True,         # cursor-following light on buttons
}


class Settings:
    def __init__(self, app_name):
        self.app_name = app_name
        self.path = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            app_name, "settings.json")
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            # utf-8-sig: tolerate the BOM that Notepad/PowerShell often add
            with open(self.path, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass  # missing or corrupt file -> defaults

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data
