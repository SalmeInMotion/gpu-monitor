"""Offscreen functional pass: data, colour ramp, menu, prefs round-trip.

    python tests\\functional.py

Opens no window and never touches the real settings: LOCALAPPDATA is
redirected into a scratch folder beside this file, so it can run while
the real GPU Monitor is up.
"""
import os
import sys

import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(HERE, "_scratch_appdata")
# Hermetic: the run below saves settings, and inheriting them from the
# previous run made compact mode leak into checks that assume it is off.
shutil.rmtree(SCRATCH, ignore_errors=True)
os.environ["LOCALAPPDATA"] = SCRATCH
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
os.environ["SUPERVISOR_BRIDGE"] = "0"

sys.path.insert(0, os.path.dirname(HERE))
from monitor.template import ensure_on_path

ensure_on_path()

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from app_template import create_app
from monitor.overlay import Overlay
from monitor.prefs import PreferencesDialog
from monitor import metrics as M

SAMPLE = {"gpu_name": "RTX 5090", "mem_used": 21840.0, "mem_total": 32607.0,
          "util": 94.0, "temp": 71.0, "temp_tlimit": 18.0, "power": 486.0,
          "power_limit": 575.0, "fan": 62.0, "clock": 2790.0,
          "clock_max": 3090.0, "cpu": 38.0, "cpu_freq": 4712.0,
          "ram_used": 39114.0, "ram_total": 65418.0}

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails.append(label)


ctx = create_app("GPU Monitor", brand_accent="#2E4372",
                 brand_accent_dark="#7C97E0")
ctx.settings["preset"] = "iausage"
ctx.settings["hover_glow"] = False
ctx.settings["show"] = dict(M.DEFAULT_SHOW)
ctx.settings["theme"] = "dark"
# what gpu_monitor.apply_defaults() guarantees before the overlay exists
for key, value in (("opacity", 100), ("width", 300), ("locked", False),
                   ("compact", False), ("animations", True),
                   ("threshold_colors", True), ("interval_ms", 1000)):
    ctx.settings.data.setdefault(key, value)
ctx.theme.apply()
ov = Overlay(ctx.settings, ctx.theme)
ov.show()


def settle(n=4):
    for _ in range(n):
        ctx.app.processEvents()


print("\n-- data --")
ov.on_sample(SAMPLE)
settle()
check("vram value", ov._rows["vram"].value.text() == "67%",
      ov._rows["vram"].value.text())
check("vram caption", ov._rows["vram"].caption.text() == "21 / 32 GB",
      ov._rows["vram"].caption.text())
check("temp ceiling from tlimit",
      ov._rows["temp"].caption.text() == "throttles at 89°C",
      ov._rows["temp"].caption.text())
check("gpu header takes adapter name",
      ov._headers["gpu"].label.text() == "RTX 5090")
check("fan hidden by default", not ov._rows["fan"].isVisible())

print("\n-- ramp vs accent --")
quota = ov._bar_colors(M.BY_KEY["vram"], 0.67)
load = ov._bar_colors(M.BY_KEY["gpu"], 0.94)
check("vram at 67% is amber", quota == ("#f3c36a", "#d99420"), str(quota))
check("gpu at 94% is not red", load[1].lower() != "#ce3d3d", str(load))
red = ov._bar_colors(M.BY_KEY["vram"], 0.91)
check("vram at 91% is red", red == ("#ee8484", "#ce3d3d"), str(red))
ctx.settings["threshold_colors"] = False
check("thresholds off -> accent everywhere",
      ov._bar_colors(M.BY_KEY["vram"], 0.91) == load, "")
ctx.settings["threshold_colors"] = True

print("\n-- no data --")
dead = {k: None for k in SAMPLE}
ov.on_sample(dead)
settle()
check("gpu error shown", ov._errors["gpu"].isVisible())
check("rows hidden while erroring", not ov._rows["vram"].isVisible())
ov.on_sample(SAMPLE)
settle()
check("recovers after data returns",
      ov._rows["vram"].isVisible() and not ov._errors["gpu"].isVisible())

print("\n-- zero readings --")
zero = dict(SAMPLE, util=0.0, fan=0.0, mem_used=0.0, cpu=0.0)
ov.on_sample(zero)
settle()
check("0% still reads 0%, not --", ov._rows["gpu"].value.text() == "0%",
      ov._rows["gpu"].value.text())
check("0% bar keeps a sliver", ov._rows["gpu"].meter._value == 0.0)
ov.on_sample(SAMPLE)
settle()

print("\n-- a GPU with no thermal sensor (AMD / Intel fallback) --")
# What the Windows-counter backend produces: utilisation and video
# memory, nothing else. The four rows it cannot measure must go away
# rather than sit there reading "--" forever.
amd = dict.fromkeys(SAMPLE)
amd.update(gpu_name="Radeon 8060S", mem_used=32370.0, mem_total=98304.0,
           util=3.0, cpu=11.0, cpu_freq=3800.0,
           ram_used=14000.0, ram_total=32360.0)
partial = Overlay(ctx.settings, ctx.theme)
# Must be shown: children of a window that was never shown all report
# isVisible() False, which would make the "row is gone" checks below pass
# without proving anything.
partial.show()
partial.on_sample(amd)
for _ in range(4):
    ctx.app.processEvents()
check("vram and usage survive", partial._rows["vram"].isVisible()
      and partial._rows["gpu"].isVisible())
check("unmeasurable rows are dropped, not left showing --",
      not partial._rows["temp"].isVisible()
      and not partial._rows["power"].isVisible())
check("no error line: the GPU block does have data",
      not partial._errors["gpu"].isVisible())
check("adapter name still reaches the header",
      partial._headers["gpu"].label.text() == "Radeon 8060S",
      partial._headers["gpu"].label.text())
check("cpu and ram unaffected", partial._rows["cpu"].isVisible()
      and partial._rows["ram"].isVisible())
partial.deleteLater()

print("\n-- lifetime and geometry regressions --")
from PySide6.QtCore import QVariantAnimation

meter = ov._rows["vram"].meter
for i in range(20):                       # 20 ticks with a moving value
    ov.on_sample(dict(SAMPLE, mem_used=10000.0 + i * 400))
    settle(1)
check("one animation per meter, not one per tween",
      len(meter.findChildren(QVariantAnimation)) == 1,
      str(len(meter.findChildren(QVariantAnimation))))

fan_row = ov._rows["fan"]
ctx.settings["show"] = dict(M.DEFAULT_SHOW, fan=True)
ov.reload_layout()
ov.on_sample(SAMPLE)
settle()
check("captionless row is not taller than a captioned one",
      fan_row.sizeHint().height() < ov._rows["vram"].sizeHint().height(),
      f"fan={fan_row.sizeHint().height()} "
      f"vram={ov._rows['vram'].sizeHint().height()}")
ctx.settings["show"] = dict(M.DEFAULT_SHOW)
ov.reload_layout()
settle()

fresh = Overlay(ctx.settings, ctx.theme)
gap = fresh.body.itemAt(1).spacerItem().sizeHint().height()
check("block gap is set before the window is ever shown", gap == 18, str(gap))
fresh.deleteLater()

ov.on_sample(dict(SAMPLE, gpu_name="RTX A6000 Ada Generation"))
settle()
head = ov._headers["gpu"]
free = ov.card.width() - 40 - ov.chrome.width() - 8
check("a long adapter name is elided clear of the chrome",
      head.label.text() != head._full and head.sizeHint().width() <= free + 2,
      f"{head.label.text()!r} w={head.sizeHint().width()} free={free}")
ov.on_sample(SAMPLE)
settle()

print("\n-- memory breakdown: grouping, threshold, order --")
from PySide6.QtCore import QPoint, QPointF, QRect
from monitor import breakdown as bd
from monitor.processes import ProcessPanel

MB = 1024 * 1024
fake = {10: 900 * MB, 11: 700 * MB, 12: 100 * MB, 13: 600 * MB, 14: 20 * MB}
fake_names = {10: "big.exe", 11: "big.exe", 12: "big.exe",
              13: "csrss.exe", 14: "tiny.exe"}
rows = bd._collect(fake, fake_names)
check("processes of one exe are grouped",
      [e.name for e in rows] == ["big", "csrss"], str([e.name for e in rows]))
check("the group sums every instance, small ones included",
      rows[0].value == 1700 * MB, str(rows[0].value // MB))
check("it carries every pid it summed", sorted(rows[0].pids) == [10, 11, 12],
      str(rows[0].pids))
check("under 512 MB never reaches the list",
      all(e.value >= bd.HIDE_BELOW_BYTES for e in rows) and "tiny" not in
      [e.name for e in rows])
check("biggest first", [e.value for e in rows] == sorted(
      [e.value for e in rows], reverse=True))

# Regression: a stray comment once swallowed half this set, and the only
# symptom was that csrss quietly became selectable.
for critical in ("csrss", "smss", "wininit", "winlogon", "services",
                 "lsass", "svchost", "dwm", "system"):
    check(f"{critical} is protected", critical in bd.PROTECTED)
check("an ordinary app is not protected", "chrome" not in bd.PROTECTED)
check("the protected flag reaches the entry", rows[1].protected)

import os as _os
check("terminate refuses our own process",
      bd.terminate([_os.getpid()]) == (0, 0, 1))

print("\n-- usage breakdowns: percentages, 5% threshold --")
usage = {20: 40.0, 21: 12.0, 22: 3.0, 23: 6.0}
usage_names = {20: "houdinifx.exe", 21: "houdinifx.exe",
               22: "idle.exe", 23: "dwm.exe"}
urows = bd._collect(usage, usage_names, bd.HIDE_BELOW_PERCENT)
check("percentages group and sum like bytes do",
      urows[0].name == "houdinifx" and urows[0].value == 52.0,
      str([(e.name, e.value) for e in urows]))
check("under 5% is dropped", "idle" not in [e.name for e in urows])
check("6% is kept", "dwm" in [e.name for e in urows])
check("a percentage formats as one", bd.fmt_value(bd.KIND_CPU, 52.0) == "52%",
      bd.fmt_value(bd.KIND_CPU, 52.0))
check("a small one keeps a decimal", bd.fmt_value(bd.KIND_GPU, 6.4) == "6.4%",
      bd.fmt_value(bd.KIND_GPU, 6.4))
check("bytes still format as bytes",
      bd.fmt_value(bd.KIND_VRAM, 2 * 1024 ** 3) == "2.0 GB",
      bd.fmt_value(bd.KIND_VRAM, 2 * 1024 ** 3))
check("each kind states its own threshold",
      (bd.fmt_threshold(bd.KIND_RAM), bd.fmt_threshold(bd.KIND_CPU))
      == ("512 MB", "5%"),
      str((bd.fmt_threshold(bd.KIND_RAM), bd.fmt_threshold(bd.KIND_CPU))))

# CPU time is a running total: the percentage is the difference between
# two readings over the wall time between them, divided by the cores.
import os as _os
cores = _os.cpu_count() or 1
# Scaled to the machine running the test, so it always exercises the
# real path: a fixed delta reads 3% on 32 threads and 25% on 4, and the
# 5% floor would swallow it on one of them.
window = 2.0
busy = int(0.25 * window * cores * 1e7)      # a quarter of the machine
before = (100.0, {30: 0, 31: 0}, {})
after = (100.0 + window, {30: busy, 31: 0},
         {30: "busy.exe", 31: "lazy.exe"})
cpu_rows = bd.cpu_entries(before, after)
check("cpu% is of the whole machine, not of one core",
      len(cpu_rows) == 1 and abs(cpu_rows[0].value - 25.0) < 0.01,
      f"{cpu_rows[0].value:.2f}% of {cores} threads" if cpu_rows else "no rows")
check("a process that used no time is not listed",
      "lazy" not in [e.name for e in cpu_rows])
check("no baseline means no invented percentages",
      bd.cpu_entries(None, after) == [])
check("two readings at the same instant are refused",
      bd.cpu_entries((100.0, {}, {}), (100.0, {}, {})) == [])

print("\n-- the process panel --")
panel = ProcessPanel(ctx.theme, ctx.settings, bd.KIND_RAM)
panel.open_at(QRect(200, 200, 312, 494))
settle()
panel.set_entries(bd.KIND_RAM, rows)
settle()
check("panel lists what it was given", panel.list.topLevelItemCount() == 2)
check("panel titles itself with the row's own word",
      panel.title.text() == "RAM", panel.title.text())
check("panel totals what it lists", panel.total.text() == bd.fmt_value(bd.KIND_RAM,
      sum(e.value for e in rows)), panel.total.text())
check("End is disabled with nothing chosen", not panel.btn_end.isEnabled())

panel.list.topLevelItem(1).setSelected(True)      # csrss, protected
settle()
check("a protected row does not stay selected",
      not panel.list.topLevelItem(1).isSelected())
check("and it is not in what End would touch",
      not any(e.protected for e in panel._selected_entries()))
check("...so End stays disabled", not panel.btn_end.isEnabled())

panel.list.topLevelItem(0).setSelected(True)      # big, ordinary
settle()
check("an ordinary row selects", panel.list.topLevelItem(0).isSelected())
check("End enables for it", panel.btn_end.isEnabled())
check("End would only touch the unprotected pids",
      sorted(p for e in panel._selected_entries() for p in e.pids) == [10, 11, 12])
check("the 512 MB rule is stated in the panel",
      "512 MB" in panel.hint.text(), panel.hint.text())
panel.close()

print("\n-- several panels at once --")
ov._pointer_held = lambda: False
ov.move(20, 20)
for key in list(ov._panels):
    ov._panels[key].close()
settle()

ov.show_breakdown(bd.KIND_RAM)
settle()
check("plain opens one", set(ov._panels) == {bd.KIND_RAM}, str(set(ov._panels)))

ov.show_breakdown(bd.KIND_CPU)
settle()
check("plain replaces it rather than adding",
      set(ov._panels) == {bd.KIND_CPU}, str(set(ov._panels)))

ov.show_breakdown(bd.KIND_RAM, additive=True)
settle()
check("Shift adds to what is open",
      set(ov._panels) == {bd.KIND_CPU, bd.KIND_RAM}, str(set(ov._panels)))
from monitor.processes import GUTTER as _GUT, STACK_GAP as _GAP


def card_rect(panel):
    """What you actually see: the window minus its transparent shadow
    room. Window rects overlap by design; painted cards must not."""
    return panel.frameGeometry().adjusted(_GUT, _GUT, -_GUT, -_GUT)


first, second = ov._panels[bd.KIND_CPU], ov._panels[bd.KIND_RAM]
check("the new one lands under the other",
      card_rect(second).top() > card_rect(first).bottom(),
      f"{card_rect(second).top()} vs {card_rect(first).bottom()}")
check("and in the same column", second.x() == first.x(),
      f"{second.x()} vs {first.x()}")
check("with exactly the gap the constant says",
      card_rect(second).top() - card_rect(first).bottom() - 1 == _GAP,
      f"{card_rect(second).top() - card_rect(first).bottom() - 1} vs {_GAP}")

# Tracking is checked on a stack that fits: a panel clamped against a
# screen edge cannot follow the card further that way, and staying on
# screen is the behaviour that wins there.
tops = {k: p.y() for k, p in ov._panels.items()}
ov.move(ov.x(), ov.y() + 15)
settle()
check("the whole stack follows the master card",
      all(p.y() == tops[k] + 15 for k, p in ov._panels.items()),
      str({k: (tops[k], p.y()) for k, p in ov._panels.items()}))

ov.show_breakdown(bd.KIND_GPU, additive=True)
settle()
check("Shift again makes three", len(ov._panels) == 3, str(set(ov._panels)))
third = ov._panels[bd.KIND_GPU]
# On this 800x800 offscreen screen a third panel cannot fit under the
# second, so it wraps to a new column. Either way its painted card must
# not land on top of the one before it.
check("a third panel never overlaps the second",
      not card_rect(third).intersects(card_rect(second)),
      f"{card_rect(third)} vs {card_rect(second)}")

print("\n-- the stack re-flows as panels grow --")
# The bug Ivan reported: each panel is placed while it still says
# "Reading...", then grows when its rows land, so positions computed once
# leave gaps of three different sizes.
def column_gaps(panels):
    """Gaps between consecutive panels *in the same column*. A stack that
    wraps has no meaningful gap across the break."""
    out = []
    for above, under in zip(panels, panels[1:]):
        if card_rect(under).left() == card_rect(above).left():
            out.append(card_rect(under).top() - card_rect(above).bottom() - 1)
    return out


stacked = ov._stacked_panels()
gaps = column_gaps(stacked)
check("every visible gap is the same", len(set(gaps)) <= 1, str(gaps))
check("and it is the one the constant names",
      gaps and all(g == _GAP for g in gaps), f"{gaps} vs {_GAP}")

# growing the top panel must push the ones under it, not overlap them
before_tops = [p.y() for p in ov._stacked_panels()[1:]]
stacked[0].setFixedHeight(stacked[0].height() + 60)
settle()
after = ov._stacked_panels()
regaps = column_gaps(after)
check("a panel growing re-lays the ones below it",
      bool(regaps) and all(g == _GAP for g in regaps), str(regaps))
check("which actually moved them",
      [p.y() for p in after[1:]] != before_tops or not before_tops,
      f"{[p.y() for p in after[1:]]} vs {before_tops}")
stacked[0].setMinimumHeight(0)
stacked[0].setMaximumHeight(16777215)

ov.show_breakdown(bd.KIND_RAM, additive=True)
settle()
check("Shift on an open one takes it back out",
      set(ov._panels) == {bd.KIND_CPU, bd.KIND_GPU}, str(set(ov._panels)))

ov.show_breakdown(bd.KIND_CPU)
settle()
check("a plain double-click collapses the stack to that one",
      set(ov._panels) == {bd.KIND_CPU}, str(set(ov._panels)))

ov.show_breakdown(bd.KIND_CPU)
settle()
check("and closes the last one", ov._panels == {}, str(set(ov._panels)))
del ov._pointer_held
ov._save_timer.stop()

print("\n-- the panel is a satellite of the card --")
# Through the overlay's own panel, not a loose one: the following is
# wired in Overlay.moveEvent, so a standalone instance proves nothing.
# Near the top-left, and small steps: follow() clamps to the screen so a
# followed panel can never end up unreachable, and the offscreen screen
# here is only 800x800 -- a big jump would hit that clamp, not a bug.
# _pointer_held() reads the *physical* mouse button, so a click of Ivan's
# while this runs would arm the position save and leave the timer active
# for the drag test further down. Pinned false for the moves below.
ov._pointer_held = lambda: False
ov.move(20, 20)
ov.show_breakdown(bd.KIND_RAM)
settle()
sat = ov._panels[bd.KIND_RAM]
check("the card owns a panel once opened", sat is not None and sat.isVisible())
check("it has a close button of its own", sat.btn_close.isVisible())
first = sat.pos()

ov.move(ov.x() + 40, ov.y() + 30)
settle()
check("moving the card takes it along",
      sat.pos() == first + QPoint(40, 30),
      f"{sat.pos()} vs {first + QPoint(40, 30)}")

# dragging the panel itself takes it out of the stack and re-sets where
# it rides from then on. The press is what marks it: a bare move() is
# also what the stack itself does, and must not read as a hand-drag.
from PySide6.QtGui import QMouseEvent as _QME
from PySide6.QtWidgets import QApplication as _QApp
_c = QPointF(sat.width() / 2, 8)
_QApp.sendEvent(sat, _QME(_QME.Type.MouseButtonPress, _c,
                          QPointF(sat.mapToGlobal(_c.toPoint())),
                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
check("a press on the panel takes it out of the stack", not sat.stacked)
sat.move(sat.x() - 60, sat.y() + 20)
settle()
moved = sat.pos()
ov.move(ov.x() + 25, ov.y())
settle()
check("a hand-placed panel keeps its new offset",
      sat.pos() == moved + QPoint(25, 0), f"{sat.pos()} vs {moved + QPoint(25, 0)}")

ctx.settings["opacity"] = 50
ov.apply_theme()
check("it inherits the card's transparency", sat._fill.alpha() == 128,
      str(sat._fill.alpha()))
ctx.settings["opacity"] = 100
ov.apply_theme()
check("...and follows it back to opaque", sat._fill.alpha() == 255)

ov.show_breakdown(bd.KIND_RAM)
settle()
check("the same word again closes it", bd.KIND_RAM not in ov._panels)
ov.show_breakdown(bd.KIND_RAM)
settle()
check("and opens it again", bd.KIND_RAM in ov._panels)
ov._panels[bd.KIND_RAM].btn_close.click()
settle()
check("the close button closes it", bd.KIND_RAM not in ov._panels)
del ov._pointer_held
ov._save_timer.stop()


print("\n-- opening it: double-click, on the word, not the bar --")
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

vram_label = ov._rows["vram"].label
check("all four measurable rows are interactive",
      all(ov._rows[k].label._interactive for k in ("vram", "ram", "gpu", "cpu")))
check("a row with no breakdown is not",
      not ov._rows["temp"].label._interactive)
check("the bar itself is no longer a target",
      not hasattr(ov._rows["vram"].meter, "_interactive"))
check("the word is only as wide as the word",
      vram_label.width() < ov._rows["vram"].width() // 2,
      f"label={vram_label.width()} row={ov._rows['vram'].width()}")

opened = []
vram_label.activated.connect(lambda: opened.append("vram"))

def send(widget, kind):
    centre = QPointF(widget.width() / 2, widget.height() / 2)
    glob = QPointF(widget.mapToGlobal(centre.toPoint()))
    QApplication.sendEvent(widget, QMouseEvent(
        kind, centre, glob, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

send(vram_label, QMouseEvent.Type.MouseButtonPress)
send(vram_label, QMouseEvent.Type.MouseButtonRelease)
settle()
check("a single click does nothing", opened == [], str(opened))

send(vram_label, QMouseEvent.Type.MouseButtonDblClick)
settle()
check("a double click opens it", opened == ["vram"], str(opened))

dragged = []
vram_label.drag_requested.connect(lambda: dragged.append(1))
send(vram_label, QMouseEvent.Type.MouseButtonPress)
far = QPointF(vram_label.width() / 2 + 40, vram_label.height() / 2)
QApplication.sendEvent(vram_label, QMouseEvent(
    QMouseEvent.Type.MouseMove, far,
    QPointF(vram_label.mapToGlobal(far.toPoint())),
    Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
settle()
check("dragging off the word still moves the card", dragged == [1], str(dragged))


print("\n-- context menu --")
menu = ov.build_menu()
labels = [a.text() for a in menu.actions() if a.text()]
check("context menu lists every metric",
      all(m.label in labels for m in M.METRICS), str(labels))
check("context menu has opacity/compact/lock/prefs/quit",
      all(t in " | ".join(labels) for t in
          ("Opacity", "Compact layout", "Lock position", "Preferences", "Quit")))
checked = {a.text(): a.isChecked() for a in menu.actions() if a.isCheckable()}
check("menu mirrors current visibility",
      checked.get("Fan") is False and checked.get("VRAM") is True,
      str(checked))
menu.deleteLater()

print("\n-- metric toggle --")
before = ov.height()
ov._toggle_metric("power", False)
settle()
after = ov.height()
check("hiding a metric shrinks the card", after < before, f"{before} -> {after}")
ov._toggle_metric("power", True)
settle()
check("showing it again restores the height", ov.height() == before,
      f"{ov.height()} vs {before}")

print("\n-- opacity --")
ov.set_opacity(60)
settle()
check("opacity reaches the card fill", ov.card._fill.alpha() == 153,
      str(ov.card._fill.alpha()))
ov.set_opacity(100)

print("\n-- always on top --")
check("chrome has an always-on-top button", hasattr(ov, "btn_top"))
check("defaults on: flag set and button checked",
      bool(ov.windowFlags() & Qt.WindowStaysOnTopHint) and ov.btn_top.isChecked())
aot_menu = ov.build_menu()
aot_items = [a.text() for a in aot_menu.actions() if a.isCheckable()]
check("context menu offers Always on top", "Always on top" in aot_items,
      str(aot_items))
aot_menu.deleteLater()
wid_before = int(ov.winId())
ctx.settings["always_on_top"] = False
ov.apply_always_on_top()
settle()
check("off unchecks the button", not ov.btn_top.isChecked())
ctx.settings["always_on_top"] = True
ov.apply_always_on_top()
settle()
check("on rechecks the button", ov.btn_top.isChecked())
# The flicker fix: toggling must NOT re-create the native window, which is
# what setWindowFlag()+show() used to do. A stable winId proves it does not.
check("toggling keeps the same native handle (no flicker)",
      int(ov.winId()) == wid_before, f"{ov.winId()} vs {wid_before}")

# The reassert must yield to our own transient windows, or it climbs back
# over its own tooltip / menu / dialog (the reported bug). Spy on the OS
# call to prove the guard skips it while a popup is open.
from PySide6.QtWidgets import QMenu
from PySide6.QtCore import QPoint
seen = []
_orig_set = ov._set_topmost
ov._set_topmost = lambda on: seen.append(on)
ov._reassert_topmost()
check("reasserts topmost when nothing of ours is open", seen == [True], str(seen))
pm = QMenu()
pm.addAction("x")
pm.popup(QPoint(0, 0))          # non-blocking; becomes the active popup
settle()
seen.clear()
ov._reassert_topmost()
check("does not re-raise over an open popup", seen == [], str(seen))
pm.close()
pm.deleteLater()
settle()
ov._set_topmost = _orig_set

print("\n-- single instance --")
from monitor.instance import SingleInstance
# A key of its own, so this never collides with a real GPU Monitor pipe.
guard_a = SingleInstance("GPU Monitor Test", ctx.app)
check("first launch owns the server", guard_a.is_primary())
poked = []
guard_a.activated.connect(lambda: poked.append(True))
guard_b = SingleInstance("GPU Monitor Test", ctx.app)
check("a second launch defers instead of owning a server too",
      not guard_b.is_primary())
settle(8)
check("the running instance is poked to surface", poked == [True], str(poked))
guard_a._server.close()

print("\n-- raise to front --")
# always_on_top is True here (restored just above), so no deferred drop fires.
seen2 = []
_orig_top = ov._set_topmost
ov._set_topmost = lambda on: seen2.append(on)
ov.move(-10000, -10000)                    # strand it off every live screen
ov.raise_to_front()
check("a stranded card is pulled back on screen",
      ov._on_a_live_screen(ov.pos()), str(ov.pos()))
check("raise_to_front lifts it to the topmost band", seen2 == [True], str(seen2))
ov._set_topmost = _orig_top

print("\n-- saved position vs the taskbar strip --")
# Ivan's real arrangement, and the real position that was thrown away: the
# card's top-left sat 16px below the available area of the left monitor —
# inside the taskbar strip, still visible and draggable — and the launch
# after that yanked it to 60,60.
from PySide6.QtCore import QRect as _QRect, QPoint as _QPoint
import monitor.overlay as _OV


class _FakeScreen:
    def __init__(self, geo, avail, name="fake"):
        self._geo, self._avail, self._name = geo, avail, name

    def geometry(self):
        return self._geo

    def availableGeometry(self):
        return self._avail

    def name(self):
        return self._name


class _FakeGuiApp:
    """Ivan's real three-monitor layout, primary first — the order matters.

    A single fake screen hid a bug: with nothing overlapping, "the screen
    it overlaps most" is a tie, and max() silently returns the first entry.
    The live card therefore came back on the primary instead of the
    monitor it had fallen off. Keep all three here.
    """

    # U32G3X is his 3840x2160 main panel, which Qt reports as 2560x1440
    # because it runs at 150%. Everything here is in those logical pixels,
    # exactly as Qt hands them over and as move() expects them back.
    @staticmethod
    def screens():
        return [_FakeScreen(_QRect(0, 0, 2560, 1440),
                            _QRect(0, 0, 2560, 1392), "U32G3X"),
                _FakeScreen(_QRect(-2560, 582, 1707, 1067),
                            _QRect(-2560, 582, 1707, 1019), "display"),
                _FakeScreen(_QRect(3840, -395, 1152, 2048),
                            _QRect(3840, -395, 1152, 2000), "Q27G4")]

    @staticmethod
    def primaryScreen():  # noqa: N802 - Qt naming
        return _FakeGuiApp.screens()[0]


_real_gui_app = _OV.QGuiApplication
_OV.QGuiApplication = _FakeGuiApp
try:
    check("a card parked over the taskbar is still on-screen",
          ov._on_a_live_screen(_QPoint(-1462, 1617)))
    check("a card fully inside the desktop is on-screen",
          ov._on_a_live_screen(_QPoint(-2000, 700)))
    check("a card on an unplugged monitor is not",
          not ov._on_a_live_screen(_QPoint(-9000, -9000)))
    # The reported bug: something other than a drag shoves the card under
    # the taskbar of the left monitor, and it is never seen again.
    lost = _QRect(-1462, 1617, 226, 262)
    check("a card under the taskbar counts as lost",
          ov._visible_fraction(lost) < _OV.MIN_VISIBLE,
          f"{ov._visible_fraction(lost):.2f}")
    home = ov._nudged_into_view(lost)
    check("it is nudged back onto the same monitor, not to 60,60",
          -2560 <= home.x() <= -853 and home != _QPoint(60, 60),
          str((home.x(), home.y())))
    check("and fully inside that screen's working area",
          ov._visible_fraction(_QRect(home, lost.size())) == 1.0,
          f"{ov._visible_fraction(_QRect(home, lost.size())):.2f}")
    check("it keeps the x it was left at, only the y is rescued",
          home.x() == -1462 and home.y() < 1617, str((home.x(), home.y())))
    # a card merely hanging off an edge is the user's business
    edge = _QRect(-1000, 1300, 226, 262)
    check("a card parked half off an edge is left alone",
          ov._visible_fraction(edge) >= _OV.MIN_VISIBLE,
          f"{ov._visible_fraction(edge):.2f}")

    print("\n-- centre on the main screen --")
    was_centring = ctx.settings.get("centre_on_start")
    ov.centre_on_main(remember=False)
    settle()
    size = ov.size()
    want = ((2560 - size.width()) // 2, (1440 - size.height()) // 2)
    check("lands on the middle of the primary screen",
          (ov.pos().x(), ov.pos().y()) == want,
          f"{(ov.pos().x(), ov.pos().y())} want {want}")
    check("which is fully on that screen",
          ov._visible_fraction(ov.geometry()) == 1.0)
    # The trap: his main panel is 3840x2160 at 150%. Halving the physical
    # numbers would put the card at 1920,1080 — off the bottom-right of a
    # 2560x1440 logical desktop.
    check("uses logical pixels, not the 3840x2160 physical ones",
          ov.pos().x() < 1920 and ov.pos().y() < 1080,
          str((ov.pos().x(), ov.pos().y())))

    ctx.settings["centre_on_start"] = True
    ov.move(-2400, 1500)          # bottom-left screen, under its taskbar
    before_rescue = ov._visible_fraction(ov.geometry())
    ov._pointer_held = lambda: False      # no drag in progress
    ov._keep_in_view()
    check("mid-session a lost card is nudged, never re-centred",
          (ov.pos().x(), ov.pos().y()) != want and ov.pos().x() < 0,
          f"{(ov.pos().x(), ov.pos().y())} was {before_rescue:.2f} visible")
    check("and it ends up fully visible",
          ov._visible_fraction(ov.geometry()) == 1.0,
          f"{ov._visible_fraction(ov.geometry()):.2f} size={ov.width()}x{ov.height()}")
    del ov._pointer_held

    ov.move(4000, 300)
    ov._restore_position()
    check("startup honours the centring preference",
          (ov.pos().x(), ov.pos().y()) == want,
          str((ov.pos().x(), ov.pos().y())))

    ctx.settings["centre_on_start"] = False
    ctx.settings["pos"] = [300, 400]
    ov._restore_position()
    check("with it off, the saved position is used again",
          (ov.pos().x(), ov.pos().y()) == (300, 400),
          str((ov.pos().x(), ov.pos().y())))

    # Launching the app you already have open is how "where did the window
    # go?" gets asked, so with centring on the poke re-centres rather than
    # merely raising a card that is hidden in a corner.
    _top_stub = ov._set_topmost
    ov._set_topmost = lambda on: None
    ctx.settings["centre_on_start"] = True
    ov.move(-2400, 900)                    # off on the left-hand monitor
    ov.raise_to_front()
    check("re-launching while already open re-centres the card",
          (ov.pos().x(), ov.pos().y()) == want,
          str((ov.pos().x(), ov.pos().y())))

    # With centring off the position is his; a stray double-click on the
    # shortcut must not throw it away.
    ctx.settings["centre_on_start"] = False
    ov.move(300, 400)
    ov.raise_to_front()
    check("with centring off, a second launch leaves a good position alone",
          (ov.pos().x(), ov.pos().y()) == (300, 400),
          str((ov.pos().x(), ov.pos().y())))
    ov._set_topmost = _top_stub
    ctx.settings["centre_on_start"] = was_centring

    # The startup path centres twice: once from __init__ on a layout that
    # has not settled, then again from the first _fit with the real size.
    ov.move(4000, 300)
    ov._centre_pending = True
    ov._last_fit_height = -1
    ov._fit()
    check("the deferred re-centre lands on the true middle",
          (ov.pos().x(), ov.pos().y()) == want,
          str((ov.pos().x(), ov.pos().y())))
    check("it keeps trying while the card is still growing",
          ov._centre_pending)
    ov._fit()
    check("and stops once two fits agree on the height",
          not ov._centre_pending)

    # Grabbing the card outranks the opening centre-up: a _fit arriving
    # late must not snatch it back to the middle.
    ov._centre_pending = True
    ov._last_fit_height = -1
    ctx.settings["locked"] = False
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QPointF, QEvent
    ov.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(10, 10), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    check("a drag cancels the pending centre-up", not ov._centre_pending)
    ov.move(4000, 300)
    ov._fit()
    check("so a later fit leaves the card where he dropped it",
          (ov.pos().x(), ov.pos().y()) == (4000, 300),
          str((ov.pos().x(), ov.pos().y())))
    ov._user_moved = False

    centre_menu = ov.build_menu()
    check("the right-click menu offers Centre on main screen",
          "Centre on main screen" in [a.text() for a in centre_menu.actions()])
    centre_menu.deleteLater()
finally:
    _OV.QGuiApplication = _real_gui_app

print("\n-- only a real drag is remembered --")
# Windows moving the window must not be written to disk as if Ivan had
# dragged it there; that is what made a one-off shove permanent.
entry_pos = ctx.settings.get("pos")
ov._user_moved = True                      # he dragged it earlier this session
held = {"down": False}
ov._pointer_held = lambda: held["down"]
ov.move(1234, 567)                         # the desktop re-homing the card
settle()
ctx.app.processEvents()
check("an unprompted move does not arm the save",
      not ov._save_timer.isActive())
check("and the saved position is untouched",
      ctx.settings.get("pos") == entry_pos, str(ctx.settings.get("pos")))
held["down"] = True
ov.move(321, 654)                          # a real drag
settle()
check("a pointer-driven move does arm the save", ov._save_timer.isActive())
ov._persist_position()
check("which then records where it finished",
      ctx.settings.get("pos") == [321, 654], str(ctx.settings.get("pos")))
del ov._pointer_held
ctx.settings["pos"] = entry_pos
ov._user_moved = False

print("\n-- autostart --")
from monitor import autostart
# Point the whole module at a scratch value name: every check below writes
# to HKCU\...\Run under a name Windows startup will never act on, so the
# real "GPU Monitor" entry is never read, written or deleted by a test run.
REAL_AUTOSTART_NAME = autostart.VALUE_NAME
autostart.VALUE_NAME = "GPU Monitor FunctionalTest"
real_before = autostart.registered_command(REAL_AUTOSTART_NAME)
try:
    autostart.set_enabled(False)          # scratch entry from a crashed run
    check("starts out disabled", not autostart.is_enabled())
    cmd = autostart.launch_command()
    check("command uses pythonw, not python",
          "pythonw.exe" in cmd.lower(), cmd)
    check("command points at this gpu_monitor.py",
          cmd.endswith('gpu_monitor.py"') and "GPU_Monitor" in cmd, cmd)
    check("both halves of the command are quoted", cmd.count('"') == 4, cmd)

    check("enabling reports success", autostart.set_enabled(True))
    check("enabling registers the entry", autostart.is_enabled())
    check("registered command is the one we build",
          autostart.registered_command() == cmd)
    check("a fresh entry is not stale", not autostart.is_stale())

    dlg_auto = PreferencesDialog(ctx.settings, ctx.theme, ov)
    check("dialog reads the checkbox from the registry, not settings",
          dlg_auto._chk_autostart.isChecked())
    check("autostart is not mirrored into settings.json",
          "autostart" not in ctx.settings.data, str(list(ctx.settings.data)))
    dlg_auto._set_autostart(False)
    dlg_auto.reject()
    settle()
    check("Cancel leaves the registry alone", autostart.is_enabled())
    dlg_auto.deleteLater()

    dlg_auto2 = PreferencesDialog(ctx.settings, ctx.theme, ov)
    dlg_auto2._set_autostart(False)
    dlg_auto2._save()
    settle()
    check("Save applies the change", not autostart.is_enabled())
    dlg_auto2.deleteLater()

    # A stale entry is the silent failure this guards: the path it names
    # is gone, so Windows starts nothing and the box still looks ticked.
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as k:
        winreg.SetValueEx(k, autostart.VALUE_NAME, 0, winreg.REG_SZ,
                          r'"C:\gone\pythonw.exe" "C:\gone\gpu_monitor.py"')
    check("a moved interpreter reads as stale", autostart.is_stale())
    dlg_stale = PreferencesDialog(ctx.settings, ctx.theme, ov)
    check("the dialog says so rather than looking fine",
          "repair" in dlg_stale._autostart_hint.text().lower(),
          dlg_stale._autostart_hint.text())
    dlg_stale._save()
    settle()
    check("Save repairs it without being re-ticked",
          autostart.registered_command() == cmd and not autostart.is_stale())
    dlg_stale.deleteLater()
finally:
    autostart.set_enabled(False)          # never leave the scratch entry
    leftover = autostart.registered_command()
    autostart.VALUE_NAME = REAL_AUTOSTART_NAME
check("scratch entry cleaned up", leftover is None, str(leftover))
check("the real startup entry was never touched",
      autostart.registered_command(REAL_AUTOSTART_NAME) == real_before,
      str(autostart.registered_command(REAL_AUTOSTART_NAME)))

print("\n-- preferences round-trip --")
entry = dict(ctx.settings.data)
dlg = PreferencesDialog(ctx.settings, ctx.theme, ov)
dlg.changed.connect(lambda: (ov.apply_theme(), ov.reload_layout()))
dlg._set_metric("fan", True)
dlg._set_flag("compact", True)
dlg._set_opacity(55)
dlg._set_width(420)
settle()
check("live preview: fan appears", ov._rows["fan"].isVisible())
check("live preview: compact on", ov._compact())
dlg.reject()
settle()
check("cancel restores fan", ctx.settings["show"]["fan"] == entry["show"]["fan"],
      str(ctx.settings["show"]["fan"]))
check("cancel restores compact", ctx.settings["compact"] == entry["compact"])
check("cancel restores opacity", ctx.settings["opacity"] == entry["opacity"],
      str(ctx.settings["opacity"]))
check("cancel restores width", ctx.settings["width"] == entry["width"])
check("overlay follows the restore", not ov._compact() and
      not ov._rows["fan"].isVisible())

ctx.settings["pos"] = [111, 222]
dlg_pos = PreferencesDialog(ctx.settings, ctx.theme, ov)
ctx.settings["pos"] = [333, 444]          # the card was dragged meanwhile
dlg_pos.reject()
check("cancel does not revert the card's position",
      ctx.settings["pos"] == [333, 444], str(ctx.settings.get("pos")))

dlg2 = PreferencesDialog(ctx.settings, ctx.theme, ov)
dlg2.changed.connect(lambda: (ov.apply_theme(), ov.reload_layout()))
dlg2._set_flag("compact", True)
dlg2._save()
settle()
check("save keeps the change", ctx.settings["compact"] is True)
ctx.settings["compact"] = False
ov.reload_layout()
settle()

print("\n-- theme switch --")
for mode in ("light", "dark", "system"):
    ctx.settings["theme"] = mode
    ctx.theme.apply()
    settle()
check("survives theme switching", True)
check("card fill follows the preset surface",
      ov.card._fill.name() in ("#fafafa", "#2b2b2e"), ov.card._fill.name())

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
