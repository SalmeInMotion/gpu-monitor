# GPU Monitor — working rules

## File names are load-bearing. Never rename, never move.

Ivan has **shortcuts** (desktop, taskbar, Start menu, possibly a startup
entry) pointing at the paths below. A rename or a move silently breaks
every one of them: the shortcut still exists, still looks fine, and opens
nothing — or worse, opens something else.

This already happened once, on 2026-08-16: `gpu_monitor.py` was renamed to
`gpu_monitor_old.py` and `GPU_Monitor.bat` was repointed at the old tkinter
script. The result looked exactly like "the good version disappeared" —
launching the shortcut brought up the old ugly card, and the modern one
seemed lost. It was never lost; only its name had changed.

So, when changing any file here:

- **Overwrite in place.** Same path, same name. Editing content is fine;
  changing the name is not.
- **Back it up first**, into `_backups\<name>.<YYYYMMDD-HHMM>.bak` inside
  the project (the folder already exists and is in use). The `.bak` tail
  keeps a backed-up `.py` from ever being importable by accident.
- **Never** introduce `*_old.py`, `*_new.py`, `*_v2.py` or a `legacy/`
  folder as a way of keeping an older copy. That is what `_backups\` is
  for. A second `.py` that looks launchable is exactly the trap above.
- If a rename ever seems genuinely necessary, **ask Ivan first** — he has
  to re-point the shortcuts by hand.

## What each file is

| Path | What it is |
|---|---|
| `GPU_Monitor.bat` | The launcher every shortcut points at. Must keep launching `gpu_monitor.py`. |
| `gpu_monitor.py` | **The app.** PySide6 card on the shared Windows template — the modern, good-looking one. |
| `monitor\` | Its package: metrics, sampler, meter, overlay, prefs, instance. |
| `vram_monitor_config.json` | **Not orphaned.** The old tkinter config. `migrate_legacy()` in `gpu_monitor.py` reads it once, on first run, to carry over metrics/position/opacity/lock. Leave it. |

The original tkinter implementation (`vram_monitor.py`) was deleted by Ivan
on 2026-08-16, once the PySide6 version fully replaced it. Do not
resurrect it and do not add a fallback path to it.

## Single instance

Opening GPU Monitor while it is already running must **not** open a second
card — it surfaces the existing one. `monitor\instance.py` holds a
`QLocalServer` named pipe; a later launch finds it, pokes it, and exits
before building any window, and the running card calls
`Overlay.raise_to_front()`.

Consequence when testing: **launching the app twice is not a way to get a
second window.** If a stale card seems stuck, kill its process — a fresh
launch will just re-raise the one already alive.

## Start with Windows

`monitor\autostart.py` owns an `HKCU\...\CurrentVersion\Run` entry named
`GPU Monitor`. Three rules it exists to enforce:

- **The registry is the only source of truth.** Never mirror it into
  `settings.json`: the entry can be removed from Task Manager, msconfig
  or regedit behind the app's back, and the copy would then sit in
  Preferences claiming the opposite.
- **Applied on Save, not on toggle.** Everything else in the dialog rides
  the base class's "Cancel restores the settings dict"; a registry write
  cannot, so it waits for `_save()`. Cancel must leave the entry alone.
- **Task Manager's disable flag outlives the entry.** Re-adding the Run
  value for a name the user once switched off in Startup apps looks like
  it worked and changes nothing — hence `is_blocked()` and the flag
  deletion in `set_enabled()`.

Tests point the module at a scratch value name (`autostart.VALUE_NAME` is
resolved at call time for exactly this reason), so a run never touches the
real entry. Keep it that way.

## The card that wanders off

Reported as "sometimes I find it in a remote corner, practically hidden in
the taskbar". Nothing in the app moves it — **Windows** does, whenever the
display layout changes (a monitor sleeping, a game switching resolution,
an RDP session, a DPI change). Ivan has three screens at mixed scaling
with gaps between them, so there is plenty of dead space to land in.

What made it *stick* was ours: `_user_moved` turned on at the first drag
and never off again, so every later shove by the desktop was written to
`settings.json` as though he had put it there. Three things now hold:

- **Only a pointer-driven move is saved.** `moveEvent` also asks
  `_pointer_held()`, which reads the physical button through
  `GetAsyncKeyState` — Qt's cached state is not usable here, because
  `startSystemMove` hands the drag to a Windows modal loop.
- **`_keep_in_view()` runs every tick** and nudges the card back when less
  than `MIN_VISIBLE` of it is on working desktop. It stands down while the
  pointer is down, so it can never fight a drag.
- **A rescue keeps the monitor.** `_nudged_into_view` clamps inside the
  screen the card overlaps most — and when it overlaps *none*, the
  **nearest** one. That last clause is not a nicety: with no overlap every
  screen ties, `max()` returns the first, and a card lost 17px under the
  left monitor's taskbar came back on the primary. A single-screen unit
  test passed this happily; only the live app showed it. The regression
  test now carries all three of his real screens, primary first.

## Opening in the middle of the main screen

`centre_on_start` (on by default) makes the card open centred on whatever
Windows currently calls the primary screen. Three things it must keep
doing:

- **Ask every time.** Monitor count and which one is primary both change;
  nothing may be cached from a previous run.
- **Work in logical pixels.** Ivan's main panel is 3840x2160 at 150%,
  which Qt reports — and `move()` expects — as 2560x1440. Halving the
  physical numbers puts the card off the bottom right.
- **Wait for the real size.** The layout reaches its height in stages
  (measured 136x374 at construction, 374 at the first `_fit`, 494 once
  readings arrive). Centring on an early one left the card 60px low, so
  `_centre_pending` keeps re-centring until two fits agree on the height.

While it is on, a drag only lasts the session — the next launch re-centres.
Ivan is happy with that ("no hace falta que la posición se guarde entre
arranques"), on one condition: **once the card is open, nothing may move
it again until the next launch.** Two things enforce it, and both are
easy to undo by accident:

- `mousePressEvent` clears `_centre_pending`. The centre-up converges over
  the first second or so, and the first readings can land after he has
  already grabbed the card; without this a late `_fit` snatches it back to
  the middle from where he just dropped it.
- `_keep_in_view()` **nudges and never re-centres**, even with this option
  on. Sliding a lost card the shortest way back onto the desktop is the
  least that leaves it reachable; teleporting it to another monitor over a
  passing display glitch is exactly the "it moved on its own" complaint
  this was all meant to end.

There is exactly **one** exception to "nothing moves it until the next
launch", added on 2026-08-20: launching GPU Monitor while it is already
running re-centres the card. Opening an app you already have open is how
Ivan asks "where did the window go?" — which is what happened here. His
card had opened centred at 09:03, and by the time he asked it was at
-1253,1107 on the left-hand monitor, put there by `_keep_in_view` after
Windows shoved it off the desktop four separate times in one day. So
`raise_to_front()` now calls `centre_on_main(remember=False)` when the
preference is on, instead of merely raising a card he cannot find.

With the preference **off** it still only rescues a genuinely stranded
card: that position is one he chose, and a stray double-click on the
shortcut must not throw it away.

## Force-killing loses the last drag

`_persist_position` runs 600ms after the last move, and `closeEvent` runs
it again. `taskkill` / `Stop-Process` skips both, so a drag made in the
last moment before a forced restart is simply gone. This looked exactly
like "settings stopped saving" during a session of repeated restarts —
the file was hours stale while the app's memory was current. It is not a
bug; close the app properly when the position matters.

## Do not confuse a taskbar with an unplugged monitor

`Overlay._on_a_live_screen()` checks `screen.geometry()`, deliberately not
`availableGeometry()`. It answers "is that monitor still plugged in", and
a card parked over the taskbar is still visible and draggable. Using the
available area instead threw away a position Ivan had chosen (top-left at
y=1617 on a screen whose available area ended at 1601) and yanked the card
to 60,60 on the next launch. There is a regression test with his real
screen geometry.

## The icon is generated, not hand-drawn

`ico\GPU_Monitor.ico` is the **output** of `ico\make_icon.py`. Do not edit
the .ico in an image editor — change the script and re-run
`python ico\make_icon.py --build chipmeters`. It takes its colours from
`monitor\meter.py` and `gpu_monitor.py`, so the icon cannot drift away
from the card it stands for.

Two things it does on purpose, both of which look like fussiness until
they bite:

- **Every size in the .ico is redrawn at that size**, not downsampled from
  the 256. Pins and rails disappear into mud otherwise; below 32px they
  are dropped deliberately (`DETAIL_FROM`).
- **Translucent fills go through `_overlay()`.** PIL only alpha-blends ink
  onto RGB targets; on an RGBA image a fill with alpha *replaces* the
  pixel, so the meter track came out as a see-through slot that looked
  grey on a dark desktop and white on a light one.

Windows needs telling twice that this is not Python: `setWindowIcon` for
what Qt paints, and `SetCurrentProcessExplicitAppUserModelID` (in
`claim_shell_identity()`, before the first window) for how the shell files
and groups it. Neither implies the other.

## Testing

`python tests\functional.py` — offscreen, no pytest, no window. It
redirects `LOCALAPPDATA` to a scratch folder, so it is safe to run while
the real monitor is up. It must stay at ALL PASS.

For live checks use the Supervisor bridge rather than asking Ivan to click
things; the app attaches automatically via the template's `create_app()`.

## It is a git repo now, and it is public

`https://github.com/SalmeInMotion/gpu-monitor`, `main`, public, created
2026-08-26. The working copy at `C:\IA\Tools\Apps\GPU_Monitor` **is** the
repo — there is no separate clone. So a change here is a change to a
published tool: commit it and push it, rather than leaving the two to
drift.

Deliberately not tracked (see `.gitignore`): `_backups\`,
`tests\_scratch_appdata\`, `_tip.png`, and `vram_monitor_config.json` —
that last one is Ivan's own leftover config, it carries his window
position, and `migrate_legacy()` only ever reads it on his machine.

`CLAUDE.md` *is* tracked, on purpose: the rules above are what stop the
next session breaking his shortcuts, and they are worth as much to a
clone as to this copy.

## Two GPU backends, and why rows disappear

`monitor\sampler.py` prefers `nvidia-smi` and falls back to
`monitor\gpu_pdh.py`, which reads the Windows performance counters Task
Manager itself uses. The fallback is chosen **once**: a first blank
answer from nvidia-smi means there is no NVIDIA driver here, and paying
for a failed process spawn every second for the rest of the session buys
nothing.

What the fallback can and cannot do:

- **Can**: utilisation (per engine, reported the way Task Manager does it
  — the busiest engine *type*, not the sum, so 90% 3D and 40% copy reads
  90) and video memory used.
- **Cannot**: temperature, power, fan, clocks. Windows publishes none of
  them; they need NVML or ADL.

Hence `Overlay._has_sensor()`: a metric that has never once produced a
reading is left out of the card entirely, rather than shown as a row
reading `--` forever. Four dead rows say "broken"; a missing row says
"not measurable here". A metric that *has* read before and then drops out
keeps its row and shows `--`, because that really is a dropout.

Two traps `gpu_pdh.py` already paid for:

- **PDH entry points need `restype`.** Without it ctypes returns a signed
  32-bit int, so `PDH_MORE_DATA` (0x800007D2) arrives as -2147481134 and
  every status comparison is wrong. It looked exactly like "this machine
  has no GPU counters" on a machine with 869 of them.
- **`Win32_VideoController.AdapterRAM` saturates at 4 GB.** The real
  figure is `HardwareInformation.qwMemorySize` under the display class
  key. On the AMD box that is the difference between reporting 4 GB and
  the true 96 GB.

## It also runs on AI-cachofo

Installed 2026-08-26 at the same path, `C:\IA\Tools\Apps\GPU_Monitor`, as
a clone of the repo. Update it with `git pull`, not by copying files.

- That machine has **no NVIDIA GPU** — a Radeon 8060S with a 96 GB UMA
  carve-out — so it always runs the counter backend, and the
  temperature/power/fan/clock rows never appear there. That is correct,
  not a fault.
- Autostart is on: the same `HKCU\...\Run` entry, written by
  `monitor\autostart.py`.
- The **Supervisor bridge is installed there** too (copied 2026-08-26 to
  `C:\IA\Tools\Claude\Supervisor\bridge`, the same path as here), so a
  card on that machine can be read and driven live exactly as on
  chofostation. It is a plain copy of a repo that has no remote, so it
  does not update itself: re-copy the `bridge\` folder when the bridge
  gains something. Verified on arrival with a throwaway Qt app rather
  than by restarting Ivan's card -- `attach()` only reports failures to
  stderr, which does not exist under pythonw, so a broken install is
  completely silent.
- **An SSH shell is session 0.** A GUI launched from there gets an
  invisible window station: the process runs and logs fine, but nothing
  appears on the desktop. To put the card on his actual screen, create a
  scheduled task with `/it` (interactive token), run it, delete it.

## app_template is resolved, never hardcoded

`monitor\template.py` finds it, in this order: `GPU_MONITOR_TEMPLATE`,
then `C:\IA\Tools\Windows\Template`, then the bundled `vendor\`. Both the
entry point and the test suite go through it — they each used to carry
their own copy of that path, which is how the tests came to work on his
machine and nowhere else.

`vendor\app_template` is a **copy**, taken from the shared template. The
shared one deliberately wins wherever it exists, so a fix to the template
reaches this app without re-vendoring; refresh the copy (and commit it)
when the template gains something this app needs.

## Double-clicking a row's name: who is using it, and ending them

The trigger is a **double-click on the row's name** -- VRAM, RAM, GPU
usage or CPU (`Metric.breakdown`; `RowLabel` in `monitor\meter.py`), not
a click on the bar. Ivan asked for both halves of that: a deliberate
gesture, on a named counter, so there is no way to end up reading the
wrong one -- which is also why the panel is titled with that same word
rather than a synonym of it. The label carries no layout stretch, so the
target is exactly as wide as the text looks; `monitor\processes.py` is
the panel, `monitor\breakdown.py` the data behind it, both grouped per
executable, sorted descending, with everything under the kind's
threshold left out -- Ivan's numbers, 512 MB and 5%, and the reason the
panel's total never matches the bar.

Four things here are load-bearing, and three of them cost a measurement
to find:

- **`GPU Process Memory\Local Usage`, never `Dedicated Usage`.** The
  obvious counter is wrong: it counts committed address space, and
  measured 46 GB of "per-process VRAM" against an adapter really holding
  5.6 GB — QuickLook alone claimed 24.9 GB. `Local Usage` is what is
  resident in the adapter and sums to just under its own figure, the gap
  being driver allocations that belong to no process.
- **One adapter, chosen by usage.** Instance names carry a LUID and this
  machine has three adapters (the GPU, a virtual display, a render-only
  device); the same process appears once per adapter it has touched.
  `PdhGpu._resolve_luid()` picks the busiest and both the bar and the
  list speak only for it. `sample()` used to sum all three, which put
  ~700 MB of somebody else's memory on the bar.
- **`monitor\winproc.py` exists for one reason: speed.**
  `psutil.process_iter(["memory_info"])` opens a handle per process and
  measured **1574 ms** for 461 processes — a visible freeze every time
  the panel refreshed. `NtQuerySystemInformation` returns the whole table
  in one call: **17 ms**, byte-identical figures (verified against psutil
  process by process). The psutil path is still there as a fallback if
  the struct ever stops matching.
- **Swallowing the press is what makes the double-click possible.**
  Let it through and the window starts its system move on the *first*
  press, so the second click never arrives. `RowLabel` holds the press,
  hands the drag back through `drag_requested` -> `Overlay.begin_drag()`
  if the pointer travels more than `DRAG_SLOP`, and otherwise does
  nothing until `mouseDoubleClickEvent`.

### The usage kinds: GPU and CPU, in percent

Same panel, same gesture, threshold 5% instead of 512 MB (Ivan's numbers
both times). `Metric.breakdown` is a plain bool now and **the kind is the
metric's own key** — `vram`, `ram`, `gpu`, `cpu` — so there is one
vocabulary, the panel titles itself from `Metric.label`, and adding a
fifth breakdown means setting one flag.

`Entry.value` is bytes for the memory kinds and a percentage for the
usage ones; `breakdown.fmt_value(kind, v)` and `fmt_threshold(kind)` are
what know which. Do not reintroduce `Entry.bytes`.

- **CPU comes from the same NT call as memory.** `winproc.snapshot()`
  returns `KernelTime + UserTime` per process alongside the working set,
  and a percentage is the difference between two snapshots over the wall
  time between them, **divided by the core count** — so the rows are on
  the card's own 0-100 scale and roughly add up to its CPU meter. Per
  *core* instead, one busy thread would read 100% on a 32-thread box.
- **The first CPU request pays 300ms.** A running total needs a baseline;
  `SamplerWorker._cpu_breakdown` sleeps once on the sampler thread when
  it has none (or one older than 10s), then keeps the reading so every
  later refresh differences over the panel's own 2s cadence. That sleep
  delays a card tick and nothing the user is looking at.
- **GPU per process is aggregated like the adapter figure**: within one
  process, sum its instances per engine type and take the busiest type.
  Summing across types would let a process doing 90% 3D and 40% copy
  report 130%.
- The panel's total is always **less than the bar**, and that is correct:
  everything under the threshold is missing from it, plus, on VRAM, the
  driver's own allocations. Measured live: card 41% CPU, panel 30%.

**The test suite reads the physical mouse.** `Overlay._pointer_held()`
calls `GetAsyncKeyState`, so any test that moves the card must pin it
(`ov._pointer_held = lambda: False`) or a click of Ivan's mid-run arms
the position-save timer and fails a later check. That is exactly how the
satellite block made "an unprompted move does not arm the save" flaky.

### Several panels at once

Plain double-click **replaces** whatever is open; **Shift + double-click
adds**, stacking the new panel under the ones already there. Both
gestures toggle the kind they name: plain because a second double-click
on the only open panel closes it (the behaviour that was there first),
Shift because otherwise a stack could only be taken apart one X at a
time.

- **A panel is one kind for its whole life.** `ProcessPanel(theme,
  settings, kind)`. The old design mutated `self.kind` on a single shared
  window, which cannot survive four of them being open.
- **The overlay owns the collection**, `Overlay._panels`, keyed by kind.
  A panel emits `closed(kind)` from its own `closeEvent` so the overlay
  can forget it; nothing else removes entries, so closing by X, by
  gesture or by the card shutting down all take the same path.
- **The stack is re-laid, not placed once.** `Overlay._reflow_stack()`
  runs on every *visible* panel's `resized`, on open, on close and on a
  card move -- deferred through a 16ms timer and idempotent, see the
  ping-pong section below.
  Placing each panel once at open time is what gave Ivan three different
  gaps: a panel is short while it says "Reading..." and grows when its
  rows land, so whatever was under it kept the spacing of a size that no
  longer existed. Closing one also closes the hole it left.
- **STACK_GAP is measured between what you can see.** Each window carries
  `GUTTER` of transparent shadow room on every side, so two windows have
  to *overlap* by `2*GUTTER - STACK_GAP` for the painted cards to sit
  `STACK_GAP` apart. And `QRect.bottom()` is the last pixel inside the
  rect, not the edge after it -- forgetting the `+ 1` puts the cards one
  pixel closer than the constant says. Any test here must measure the
  card rects (`frameGeometry().adjusted(GUTTER, GUTTER, -GUTTER,
  -GUTTER)`), never the window rects, which overlap by design.
- **Leaving the stack is a press, not a move.** `mousePressEvent` sets
  `stacked = False`, because that is the only gesture that can move a
  panel by hand. Inferring it from `moveEvent` instead looked right and
  was not: `show()` emits a moveEvent too, so every panel fell out of the
  stack the instant it opened, and they all piled up at the same spot.
- **Stacking wraps to a new column** when nothing fits below
  (`_place(..., below=...)`). Clamping instead would drop the new panel
  on top of the one above and hide both. A test comparing gaps must skip
  the pair that straddles the wrap.
- **A panel clamped against a screen edge stops following the card**
  that way. That is the intended trade: staying on screen beats tracking.
  A test that moves the card must therefore use a stack that fits, or it
  is asserting against the clamp rather than against `follow()`.

### The panel is a satellite, not a window of its own

Reported as "se queda abierta y no puedo moverla ni cerrarla". Four
things answer that, and the first two are easy to undo by accident:

- **It travels with the card.** `Overlay.moveEvent` calls
  `ProcessPanel.follow()`, which re-places it at a stored offset from the
  card's top-left. Ivan had dragged the card to another monitor and left
  the panel behind on the first one.
- **Dragging the panel re-sets that offset.** The panel is frameless, so
  its own background is the drag handle (`mousePressEvent` ->
  `startSystemMove`), and `moveEvent` recomputes the offset for any move
  that was not `follow()`'s own -- which is what the `_following` flag is
  for. Without it, following would immediately overwrite the offset it
  had just used.
- **`follow()` clamps to the screen.** A panel riding a card that moves
  to a screen edge would otherwise end up unreachable, which is the same
  trap `_keep_in_view` exists for on the card.
- **It inherits the card's fill alpha**, so the two read as one surface.
  `Overlay.apply_theme` pushes that down; the panel does not read the
  opacity setting on its own timer.

Double-clicking the same word again closes it -- that always worked, and
Ivan still could not find it, hence the **X button**. Both stay: the
toggle for whoever knows, the X for whoever does not.

### The 0ms ping-pong: one core per open panel

2026-08-27. Symptom: with any breakdown panel open the app pinned one
core (measured 84-106%), and once Preferences was open it would not
close — not by its buttons, not by `WM_CLOSE`. Ivan was stuck with a
modal dialog he could not answer.

Cause, and it is two lines: `_sync_button` scheduled
`_drop_protected_selection` on a `QTimer.singleShot(0, ...)`, and that
clean-up ended by calling `_sync_button` back — with `_clearing` already
reset in its `finally`. Each re-armed the other, forever, at zero delay.

The fix that matters is the **early return**: `_drop_protected_selection`
now does nothing and calls nobody when there is no stuck row. The
scheduling stays unconditional, and has to: during
`itemSelectionChanged` Qt has not yet marked the row as selected, so
asking "is there anything to clean?" at that moment always answers no and
the row stays highlighted. Chain length is now at most
sync → drop → sync → drop(nothing) → stop.

**Why it took so long to find, so the next session does not repeat it:**

- **Instance-level wrappers do not intercept anything Qt calls.**
  `panel.paintEvent = wrapper` never fires: PySide resolves virtuals on
  the *class*. And `timer.timeout.connect(self._do_reflow)` captures the
  bound method at connect time, so `ov._do_reflow = wrapper` misses every
  call too. Both made the app look idle while it burned. Patch the class,
  or measure something else.
- **Pumping the loop from `/py` hides a GUI-thread spin.** A probe that
  runs `while ...: app.processEvents()` is competing with the very loop
  it is trying to observe; the queue looks empty because the probe is
  draining it.
- **Sleeping on the GUI thread hides it too.** Reading per-thread CPU
  from *inside* the app via a `/py` that sleeps 1.5s reports the main
  thread at 0%, because the spin cannot run while the probe holds the
  thread. Read `psutil.Process(pid).threads()` from **outside**.
- **What actually located it** was bisection, not instrumentation: close
  panels one at a time and measure CPU from outside. Zero panels 0.4%,
  any panel ~90%. Then the decisive observation — a panel that is
  `hide()`-den still burns, a `close()`-d one does not. Widgets do not
  care about hiding; **timers do not stop until closeEvent stops them**.
  That pointed straight at a timer rather than at painting or layout.

Two more things were hardened in the same pass, because they were
plausible suspects and were genuinely fragile:

- `_reflow_stack` is deferred through a **16ms** timer, not 0ms, and
  `_do_reflow` is **idempotent**: it builds the whole plan, compares it
  with the last one applied, and returns without touching a window when
  they match. Any future feedback loop dies the moment two passes agree.
- The layout is computed arithmetically from the panels' own heights and
  **never reads a position back**. `frameGeometry()` right after `move()`
  is still the previous rect on Windows, so a stack laid out from it
  never settled.

### "python" is not an answer: naming the generic hosts

2026-08-27. Ivan, looking at the card on AI-cachofo: "en vram veo que el
tragon es python con 30gb, pero eso es muy generico". It was ComfyUI --
`C:\ComfyUI\main.py --listen 127.0.0.1 --port 8188` -- and on
chofostation the same row was 13 GB across **51** unrelated processes.
Grouping by executable is right for `chrome`; for an interpreter it
merges everything the machine is doing into one useless total.

So `breakdown.GENERIC_HOSTS` (python, pythonw, node, electron, java,
powershell, cmd...) are grouped by **what they were told to run**, read
off the command line by `describe(pid, host)`, and the row is named
`ComfyUI (python)`. The host stays in parentheses on purpose: the name
you recognise first, without lying about what the process is.

- **The cost is nothing, and that was worth measuring first.**
  `psutil.Process(pid).cmdline()` is a PEB read: **0.03 ms** per process,
  2 ms for all 75 hosts on this machine, against `ram_entries()`'s 22 ms
  total. That is why there is no cache -- and no cache means no eviction
  bug when pids are recycled.
- **Resolution happens inside `_collect`**, where the per-pid values
  still exist. Doing it afterwards cannot work: an `Entry` has only the
  *sum* and a list of pids, so there is no way to split it back apart.
- **`_label_from_path` returns None rather than a shrug.** A relative
  `main.py` yields nothing, and it has to say so, or `describe` never
  reaches the next candidate -- the virtualenv path that says ComfyUI.

Four candidates, in this order, each one paying for itself:

1. **What the command line names** (`-m` module, `-jar`, or the first
   bare argument).
2. **`argv[0]`**, the interpreter as invoked. Not the same as (3):
   ComfyUI Desktop is launched through the project's own `.venv` while
   its real image lives in a shared `standalone-env`, which named the row
   `standalone-env (python)` until argv[0] went in front of it.
3. **`proc.exe()`**, for anything launched by absolute path.
4. Nothing -- keep the plain host name.

**Not the working directory.** It was in the list and it produced
`Tools (powershell)` for an interactive shell sitting in `C:\IA\Tools`.
An interactive shell is a shell; saying so is the honest answer, and the
row is better off unchanged.

Three traps already paid for, all found by running it against the real
process table rather than by reasoning about it:

- **`-c` is code, not a path.** Without `_INLINE_CODE`, the text of
  `python -c "..."` was split on its slashes and a fragment of the
  program became the row's name. `-X utf8` and `-cp <classpath>` are the
  same shape and are in `_TAKES_SOMETHING_ELSE`.
- **A label that repeats the host is not an answer.**
  `WindowsPowerShell (powershell)` and `Python311 (python)` both came out
  of a live machine. `_tells_us_something()` rejects any label containing
  the host's name, plus bare version numbers like `v1.0`.
- **`C:\Windows` names an installation, not a project**, so
  `_is_the_systems_own()` skips those paths entirely.

#### Reading a command line is a privilege question, not an API question

The feature shipped working on chofostation and doing **nothing** on
AI-cachofo -- the machine it was written for. Same code, same user, same
30 GB row still called `python`. Three layers had to come off:

1. **psutil reads the target's PEB**, which needs `PROCESS_VM_READ`. An
   ordinary process does not get that over an elevated one. Replaced with
   `winproc.command_line()`:
   `NtQueryInformationProcess(ProcessCommandLineInformation, 60)`, which
   the kernel answers on a `PROCESS_QUERY_LIMITED_INFORMATION` handle,
   plus `CommandLineToArgvW` to split it. Verified against psutil on all
   87 generic hosts here: identical argv, same 23 ms.
2. **That was still denied**, `ERROR_ACCESS_DENIED` from `OpenProcess`
   itself. Same user is not enough: an **elevated** process's descriptor
   grants the *Administrators* group, and an ordinary token carries that
   group as **deny-only**, so no handle is issued at all. This is the same
   reason Task Manager needs elevating to show details of elevated
   processes.
3. **WMI is not a way round it.** Its provider runs as SYSTEM, which is
   why it looks like one -- but from the unelevated card
   `Win32_Process.CommandLine` returns the **empty string**, rc=0, no
   error. Tested from inside the card's own process; do not re-litigate
   this.

So it stops there. `winproc.denied(pid)` tells the two failures apart --
refused versus simply gone -- and such a row keeps the host's name and
carries `OUT_OF_REACH` as its tooltip. Elevating a monitor to name one
row is a bad trade, and a row that explains itself beats one that just
looks broken.

**How this was found, because the shortcut is not obvious:** the card
answers `/py` on the Supervisor bridge, so the question "what does the
*running app* see?" is one call away -- and the answer (`AccessDenied`
from inside, success from an SSH shell) is what named elevation as the
difference. An SSH session gets the user's **full** token; a scheduled
task with `/it`, like the card, gets the filtered one. Never conclude
from an SSH probe that the app can read something.

#### svchost: the same problem, the opposite treatment

Added 2026-08-27 on Ivan's "quiero ver que servicios son". It is
deliberately **not** in `GENERIC_HOSTS`, and it must not be: the shape of
the data decides this, so measure before changing it. On chofostation
svchost is **93 processes holding 1.9 GB, the biggest 82 MB and the
median 15 MB** -- so splitting it per service the way python is split
would put every single piece under the 512 MB threshold and the whole
1.9 GB row would **vanish**. Strictly worse than the generic name.

So the row stays whole and `_name_services()` fills its tooltip instead:
the services inside it, biggest first, `MAX_SERVICES_LISTED` of them plus
"and N more" -- never a silent truncation.

- **`winproc.services_by_pid()`** is `OpenSCManagerW` +
  `EnumServicesStatusExW(SC_ENUM_PROCESS_INFO)`: every running service
  with the pid hosting it, one call, **9 ms**, and it needs only
  `SC_MANAGER_ENUMERATE_SERVICE`, which ordinary users have. No
  elevation, unlike everything in the section above.
- **Display names, not keys.** "Windows Update" over "wuauserv": this is
  for looking at.
- **`_collect` keeps a `contrib` map** of (value, pid) per group, because
  ranking the services needs the per-process figures that grouping throws
  away. It is discarded as soon as the naming is done.
- **One process, one service -> the service is the row**: `MsMpEng`
  becomes *Microsoft Defender Antivirus Service (MsMpEng)*.
- **Never rename a protected row.** `Entry.protected` reads the *name*,
  so renaming `svchost` after one of its services would quietly make it
  selectable and killable. There is a test for exactly this.
- **The command line wins** where a row has both. A resolved generic host
  says what it is running; the service note only fills an empty detail.
- The panel had to change too: a protected row used to *replace* its
  tooltip with "Windows needs this one", which would have thrown away the
  one list that matters most. It appends now.

### Ending processes: what protects Ivan from this

- `breakdown.PROTECTED` is the list of names that are shown but never
  selectable, because ending them takes Windows down. **A stray comment
  once swallowed half that set** — `smss`, `csrss` and `wininit` ended up
  inside a trailing `#` — and the only symptom was csrss quietly becoming
  selectable. There is now a test naming each critical process
  individually; keep it that way.
- **`ItemIsSelectable` only stops the user.** `setSelected()` from code
  ignores it, leaving a row that looks armed while `selectedItems()`
  excludes it. `_drop_protected_selection()` clears that, and it has to
  run on a `QTimer.singleShot(0, ...)`: done inside
  `itemSelectionChanged`, Qt is still mid-update and re-applies the
  selection right after.
- `terminate()` refuses our own pid, refuses protected names, and refuses
  anything it cannot even name (`AccessDenied` reading `.name()` means a
  Windows process) — reported as *skipped*, not as a failure the user
  might try to fix by running as admin.
- There is a **confirmation dialog**, where Task Manager has none. This
  list groups, so one row can be fifty processes, and unsaved work has no
  undo.
