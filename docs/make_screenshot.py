"""Regenerate docs/screenshot.png -- the image at the top of the README.

    python docs\make_screenshot.py

Offscreen, with invented process names and readings. Deliberately not a
grab of a live desktop: this is a public repo, and a real screenshot
publishes whatever happened to be running, how much memory the machine
has and which GPU is in it.

Like the icon, the picture is generated rather than hand-captured, so it
cannot drift away from the app it is supposed to show.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
# Its own settings folder: rendering the shot must never read, and never
# write, the real card's preferences.
os.environ["LOCALAPPDATA"] = os.path.join(HERE, "_shot_appdata")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
os.environ["SUPERVISOR_BRIDGE"] = "0"

sys.path.insert(0, PROJECT)
from monitor.template import ensure_on_path

ensure_on_path()

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QGuiApplication, QColor, QPainter, QPixmap

QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from app_template import create_app
from monitor.overlay import Overlay
from monitor import metrics as M, breakdown as bd

GB = 1024 ** 3

SAMPLE = {"gpu_name": "RTX 5090", "mem_used": 21840.0, "mem_total": 32607.0,
          "util": 87.0, "temp": 68.0, "temp_tlimit": 22.0, "power": 431.0,
          "power_limit": 575.0, "fan": 58.0, "clock": 2745.0,
          "clock_max": 3090.0, "cpu": 46.0, "cpu_freq": 4712.0,
          "ram_used": 39114.0, "ram_total": 65418.0}

VRAM_ROWS = [
    bd.Entry("blender", int(9.4 * GB), [11]),
    bd.Entry("houdinifx", int(4.8 * GB), [12]),
    bd.Entry("dwm", int(1.1 * GB), [13]),
]
RAM_ROWS = [
    bd.Entry("chrome", int(6.2 * GB), list(range(28))),
    bd.Entry("Memory Compression", int(4.1 * GB), [4]),
    bd.Entry("blender", int(3.7 * GB), [11]),
    bd.Entry("Code", int(2.4 * GB), list(range(9))),
    bd.Entry("houdinifx", int(2.1 * GB), [12]),
    bd.Entry("svchost", int(1.3 * GB), list(range(60))),
    bd.Entry("explorer", int(0.9 * GB), [7]),
]
CPU_ROWS = [
    bd.Entry("blender", 31.0, [11]),
    bd.Entry("houdinifx", 9.4, [12]),
    bd.Entry("chrome", 5.6, list(range(28))),
]

ctx = create_app("GPU Monitor", brand_accent="#2E4372",
                 brand_accent_dark="#7C97E0")
ctx.settings["preset"] = "iausage"
ctx.settings["hover_glow"] = False
ctx.settings["theme"] = "dark"
ctx.settings["show"] = dict(M.DEFAULT_SHOW)
for key, value in (("opacity", 100), ("width", 300), ("locked", False),
                   ("compact", False), ("animations", False),
                   ("threshold_colors", True), ("interval_ms", 1000),
                   ("always_on_top", True), ("centre_on_start", False)):
    ctx.settings.data.setdefault(key, value)
ctx.theme.apply()

ov = Overlay(ctx.settings, ctx.theme)
ov._pointer_held = lambda: False
ov.show()
ov.move(24, 24)
ov.on_sample(SAMPLE)


def settle(ms=200):
    import time
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        ctx.app.processEvents()


settle()
ov.show_breakdown("vram")
ov.show_breakdown("ram", additive=True)
ov.show_breakdown("cpu", additive=True)
settle()
for kind, rows in (("vram", VRAM_ROWS), ("ram", RAM_ROWS), ("cpu", CPU_ROWS)):
    ov._panels[kind].set_entries(kind, rows)
settle(400)

windows = [ov] + [ov._panels[k] for k in ("vram", "ram", "cpu")]
rects = [w.frameGeometry() for w in windows]
left = min(r.left() for r in rects)
top = min(r.top() for r in rects)
right = max(r.right() for r in rects)
bottom = max(r.bottom() for r in rects)

pad = 26
canvas = QPixmap(right - left + 1 + pad * 2, bottom - top + 1 + pad * 2)
canvas.fill(QColor("#38414f"))
painter = QPainter(canvas)
for widget, rect in zip(windows, rects):
    widget.render(painter, QPoint(rect.left() - left + pad,
                                  rect.top() - top + pad))
painter.end()

out = os.path.join(HERE, "screenshot.png")
canvas.save(out)
print(out, canvas.width(), "x", canvas.height())
for k in ("vram", "ram", "cpu"):
    p = ov._panels[k]
    print(f"  {k:5s} at {p.x()},{p.y()}  {p.width()}x{p.height()}")
