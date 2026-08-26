# ia-usage — Reference Design Spec for a PySide6/Qt Reimplementation

Source of truth: `ia-usage` WPF app (`ClaudeUsageTray.Wpf`, .NET 8, MaterialDesignThemes 5.3.2, PerMonitorV2 DPI).
All `file:line` citations are relative to
`…/scratchpad/ia-usage/usage_tray_dotnet/ClaudeUsageTray.Wpf/`.
File aliases used throughout: `PW.xaml`/`PW.cs` = PopupWindow, `SX`/`SC` = StatsWindow, `CB` = ChartBuilder.cs,
`SWx`/`SWc` = SettingsWindow, `TH` = ThemeHelper.cs, `DH` = DwmHelper.cs, `AS` = AppSettings.cs,
`TW` = ToastWindow, `TMW` = TrayMenuWindow, `IF` = IconFactory.cs, `SI` = ServiceIcons.cs.

Target: a floating, always-on-top GPU/VRAM/CPU monitor in PySide6 with meters and a history graph.
Sections 1–3 describe the original. Section 4 is the port. Section 5 is where the port must diverge.

---

## 1. The look in one paragraph

A single soft-white (`#FAFAFA`) or near-black (`#2B2B2E`) **borderless card with a 16 px radius**, floating on
a black drop shadow at 22 % opacity and nothing else — no outline, no divider lines, no plate behind the
content. Inside, 20 px of padding and a strictly two-tone type system: a **12 px muted label on the left, a
12 px near-black value flush right**, and between the two rows a **9 px pill-shaped meter** whose track is a
theme-neutral 15 % gray (`#26808080`) and whose fill is a short horizontal gradient that changes hue by
threshold — green below 60 %, amber below 85 %, red above — so the card is read at a glance by colour, not by
number. Under each meter sits an 11 px grey caption; blocks are separated by 18 px of pure whitespace,
never a rule. Chrome is deliberately near-invisible: circular 26 px icon buttons with no fill until hovered
(then 8 % gray, `#14808080`), Segoe MDL2 glyphs at 10–14 px in the secondary text colour, and a footer line
of 11 px grey text ("Actualizado hace 3 min") balanced against two of those ghost buttons. Motion is minimal
and only ever on entry: bars grow from zero over 500 ms with a cubic ease-out, staggered 80 ms apart, so the
card "fills in" once and then sits still. The history chart follows the same rules — no axis spines, dashed
`{2,3}` gridlines at fixed 0/50/100 %, a 2.5 px accent polyline over a flat 16 %-alpha area fill, 9 px labels
at 0.6 opacity, and a hover readout that is bare text plus a 7 px dot, with no tooltip box at all.
The reference capture confirms the body of that: at rest the card reads as **content on a floating sheet**,
and a 0 %-usage meter renders as a bare empty track.

> **The capture is stale for the chrome.** `docs/captura.png` shows an empty top-right corner, but the
> current source *always* mounts Pin / Compact / Stats there (`PW.xaml:59-186`) and deliberately paints the
> Compact glyph in `text.primary` because the secondary gray "was too low-contrast to read as an icon"
> (`PW.cs:404-408`). Do not read the capture's blank corner as design intent — it predates those buttons.
> Only the popup's **Close** button is genuinely hidden at rest (`Visibility=Hidden` unless pinned).

Glyph sizes across the app run **10–20 px**, not 10–14: 10 (caption buttons), 11 (popup close), 14 (footer,
tray-menu rows, bell), 16 (settings card header), 20 (loading spinner).

---

## 2. TOKENS

### 2.1 Colour tokens — surfaces and text (all hardcoded literals, no theme resource involved)

| Token | Light | Dark | Source |
|---|---|---|---|
| `surface.card` | `#FAFAFA` | `#2B2B2E` | `PW.cs:312`, `PW.cs:1042`, `TW.xaml.cs:31-32`, `TMW.xaml.cs:51-52`, `SC:604-606` |
| `surface.card.standard` (opaque form) | `#FFFAFAFA` @ 100 % | `#FF2B2B2E` | `PW.cs:346-347`; default 100 % `AS:40` |
| `surface.card.blur` (acrylic tint, default 45 %) | `#97FAFAFA` | `#972B2B2E` | `PW.cs:328-329` |
| `text.primary` | `#1A1A1A` | `#F2F2F2` | `PW.cs:379-381`, `SC:608-610`, `TW.xaml.cs:34-35` |
| `text.secondary` | `#555555` | `#B8B8B8` | `PW.cs:383-385`, `SC:612-614`, `TMW.xaml.cs:57-58` |
| `text.primary.blurmode` | `#000000` | `#FFFFFF` | `PW.cs:380-381` (blur overrides both rows above) |
| `text.secondary.blurmode` | `#000000` | `#FFFFFF` | `PW.cs:384-385` |
| `meter.track` | `#26808080` (rgba 128,128,128,38 ≈ 15 %) | identical (NOT theme-conditional) | `PW.cs:712`, `PW.cs:813` |
| `overlay.hover` | `#14808080` (rgba 128,128,128,20 ≈ 8 %) | identical | `PW.xaml:74,100,124,181`, `SX:36`, `TMW.xaml.cs:19` |
| `divider.line` | `#22808080` (rgba 128,128,128,34) | identical | `TMW.xaml.cs:81-86` — **this literal exists only in the tray menu**; every other "divider" in the app is the theme-conditional MDIX `MaterialDesignDivider` (see §2.4) |
| `chart.grid` (also = dashboard card fill) | `#E2E2E2` | `#454548` | `SC:616-618`, reused `SC:662` |
| `chart.card.totals` | `#E6E6EF` | `#4C4C56` | `SC:624-626` |
| `chart.series.prompts` | `#8B5CF6` | `#8B5CF6` (single value, both themes) | `SC:639` |
| `shadow.color` | `#000000` (always — never theme-conditional) | identical | `PW.xaml:31` |
| `shadow.opacity` | 0.22 popup/toast/menu · 0.28 dialog+about · 0.30 date popup | identical | `PW.xaml:31`, `TW.xaml:15`, `TMW.xaml:26`, `AppDialogWindow.xaml:64`, `AboutWindow.xaml:75`, `SC:487` |
| `scrollfade` | `#00000000` → `#26000000` (top→bottom) | identical | `SWx:350-351` |
| `success` | `#2E8B57` | `#FFFFFF` (dark theme swaps to pure white) | `SWc:52` |

### 2.2 Colour tokens — accent

| Token | Light | Dark | Source |
|---|---|---|---|
| `accent.original` (default, sentinel `"ORIGINAL"`) | `#2E4372` | `#7C97E0` | `TH:11`, `TH:18`; sentinel `AS:54`, default `AS:36` |
| `accent.swatches[0..10]` | `#378ADD` `#7F77DD` `#1D9E75` `#D85A30` `#D4537E` `#639922` `#D64545` `#B37D0F` `#5B6472` `#127F9E` `#5457C9` | identical | `TH:20-24` |
| `accent.originalSwatchGradient` (picker chip art only) | `#2E8B57` @0 → `#D4A017` @0.55 → `#D64545` @1, diagonal (0,0)→(1,1) | identical | `SWc:488-490` |
| `accent.foreground` (text on accent) | computed: `L = 0.2126·lin(R)+0.7152·lin(G)+0.0722·lin(B)`, `lin(c)= c≤0.03928 ? c/12.92 : ((c+0.055)/1.055)^2.4`; `L > 0.4 → #000000 else #FFFFFF` | identical | `TH:89-110` |
| `accent.fill.chart` | accent @ opacity **0.16** → alpha **41** (`0x29`) | identical | `SC:629-630` |
| `accent.fill.chipSelected` | accent @ opacity **0.14** → alpha **36** (`0x24`) | identical | `SC:366-369, 401-404, 515-519` |

> All **13** accent values above (11 swatches + both Original variants) measure under 0.32 luminance, so
> `accent.foreground` resolves to `#FFFFFF` for every shipped accent — the source comment says exactly that:
> "every swatch in AccentSwatches plus both Original variants" (`TH:99-109`). The `0.4` threshold is
> deliberate, not WCAG's ~0.18.

### 2.3 Colour tokens — meter ramp (the signature of the design)

Applies when `AccentColor == "ORIGINAL"` (the default). Horizontal `LinearGradientBrush` from `(0,0)` to
`(1,0)` **relative to the FILL's bounding box**, so the ramp always spans the *current fill width*, not the
track. `CB:623-635`, applied `PW.cs:720`.

| Threshold | Start (left) | End (right) | Source |
|---|---|---|---|
| `percent < 60` | `#72D08F` | `#3F9E63` | `CB:626` |
| `60 ≤ percent < 85` | `#F3C36A` | `#D99420` | `CB:627-628` |
| `percent ≥ 85` | `#EE8484` | `#CE3D3D` | `CB:629-630` |

Flat override when a custom accent is picked (`TrayOrchestrator.cs:430`, `PW.cs:935-943`):
`lighter = min(255, channel + 40)` per channel; gradient `lighter → base`, same `(0,0)→(1,0)` axis.
Example for `#378ADD` → `#5FB2FF` → `#378ADD`.

### 2.4 Colour tokens inherited from MaterialDesignInXaml — UNRESOLVED, with port substitutes

MDIX 5.3.2 is not vendored in the tree; the literals behind these `DynamicResource` keys are **not
verifiable from source**. Do not guess them. Use the substitute column, which is derived from the app's own
verified hardcoded palette and reproduces the look.

| MDIX key | Where used | Port substitute (light / dark) — AUTHORITATIVE FOR THIS SPEC |
|---|---|---|
| `MaterialDesignPaper` | Settings/Dialog/About window + textbox bg (`SWx:9,212,323`) | `#FAFAFA` / `#2B2B2E` |
| `MaterialDesignCardBackground` | Settings card fill (`SWc:240`) | `#FFFFFF` / `#333336` |
| `MaterialDesignBody` | primary text (`SWx:10`) | `#1A1A1A` / `#F2F2F2` |
| `MaterialDesignBodyLight` | hints, card glyphs (`SWc:198,253`) | `#555555` / `#B8B8B8` |
| `MaterialDesignDivider` | 1 px borders, switch-off track, hover fills (`SWx:29,116,146,161,197,215,269`) | `#22808080` (both) |
| `MaterialDesign.Brush.Primary` | accent | `accent.original` (§2.2) |
| `MaterialDesign.Brush.Primary.Foreground` | text on accent | `#FFFFFF` (per §2.2 formula) |
| `MaterialDesignValidationErrorBrush` | error text in the popup (`PW.cs:642`) | `#D64545` (nearest verified red in-tree) |
| `MaterialDesignFont` | Settings window only (`SWx:11`) | see §2.5 — use `Segoe UI` |

### 2.5 Type scale

**Family.** No `FontFamily` is set for body text anywhere except `SettingsWindow` (`SWx:11` →
`MaterialDesignFont`, unresolved). Popup, Stats, Toast, TrayMenu, About and Dialog all inherit the WPF
default, which on Windows is **Segoe UI**. The only *literal* families in the whole tree are
`"Segoe MDL2 Assets"` (icon glyphs) and `"Consolas"` (About window monospace block, `AboutWindow.xaml:65`).
**Port decision: `Segoe UI` for all text, `Segoe MDL2 Assets` for glyphs, `Consolas` for monospace.**

Sizes are WPF DIPs (1 DIP = 1 logical px at 96 dpi) — 1:1 with Qt logical pixels. Point-size column given
because `QFont.setPointSizeF()` needs `pt = dip × 0.75`; prefer `setPixelSize(dip)`.

| Role | Family | Size (DIP = Qt px) | pt | Weight | Colour | Source |
|---|---|---|---|---|---|---|
| Stats window title | Segoe UI | 15 | 11.25 | Medium (500) | text.primary | `SX:53`, `SC:641` |
| Settings/Dialog title | Segoe UI | 16 | 12 | Bold / Medium | text.primary | `SWc:18`, `AppDialogWindow.xaml:81` |
| Section/service title (full popup) | Segoe UI | 14 | 10.5 | Medium (500) | text.primary | `PW.cs:627` |
| Loading app name | Segoe UI | 14 | 10.5 | Medium | text.primary | `PW.cs:766-773` |
| Settings body label / radio / bullet | Segoe UI | 14 | 10.5 | Normal | text.primary | `SWc:19` |
| Calendar month / day count | Segoe UI | 14 | 10.5 | Medium / Bold | text.primary | `SC:779`, `SC:859` |
| Empty state, error, dialog message | Segoe UI | 13 | 9.75 | Normal | text.secondary | `PW.cs:744`, `PW.cs:636` |
| Toast message | Segoe UI | 13 | 9.75 | Normal | text.primary | `TW.xaml.cs:42-50` |
| Tray-menu row label | Segoe UI | 13 | 9.75 | Normal | text.primary | `TMW.xaml.cs:110-115` |
| Chart service header | Segoe UI | 13 | 9.75 | Medium | text.primary | `CB:513` |
| Segmented button text | Segoe UI | 13 | 9.75 | Normal | body / `#FFFFFF` when selected | `SWx:24` |
| **Metric label** | Segoe UI | **12** | 9 | Normal | **text.secondary** | `PW.cs:669` |
| **Percentage value** | Segoe UI | **12** | 9 | **Normal (explicit)** | **text.primary** | `PW.cs:672` |
| Service extra line | Segoe UI | 12 | 9 | Normal | text.secondary | `PW.cs:654` |
| Service title (compact) | Segoe UI | 12 | 9 | Normal | text.primary | `PW.cs:561` |
| Loading caption | Segoe UI | 12 | 9 | Normal | text.secondary | `PW.cs:778-785` |
| Range-chip text | Segoe UI | 12 | 9 | Medium sel / Normal | accent sel / text.secondary | `SC:374,410,523` |
| Settings hint / caption | Segoe UI | 12 | 9 | Normal | BodyLight | `SWc:20`, `SWc:244-255` |
| Chart empty-state | Segoe UI | 12 | 9 | Normal | text.secondary @0.7 | `CB:57` |
| **Caption under bar** ("Resets …") | Segoe UI | **11** | 8.25 | Normal | **text.secondary** | `PW.cs:689` |
| **Footer "Updated …"** | Segoe UI | **11** | 8.25 | Normal | **text.secondary** | `PW.cs:884` |
| Chart hover readout | Segoe UI | 11 | 8.25 | Medium | text.secondary | `CB:390-391` |
| Prompt-mode chip | Segoe UI | 11 | 8.25 | Medium act / Normal | `#8B5CF6` act / text.secondary | `SC:568` |
| Dashboard stat line / calendar day no. | Segoe UI | 11 | 8.25 | Normal | text.secondary | `SC:1079`, `SC:851` |
| Loading-more progress text | Segoe UI | 11 | 8.25 | Normal | text.secondary | `PW.cs:800-806` |
| Tray-menu section label | Segoe UI | 11 | 8.25 | Normal | text.secondary | `TMW.xaml.cs:69-77` |
| Compact row prefix / percent | Segoe UI | 10 | 7.5 | Normal | secondary / primary | `PW.cs:594`, `PW.cs:602` |
| Chart legend chip | Segoe UI | 10 | 7.5 | Normal | text.secondary | `CB:598` |
| Calendar weekday header | Segoe UI | 10 | 7.5 | Medium | text.secondary | `SC:807` |
| **Chart axis labels (X and Y)** | Segoe UI | **9** | 6.75 | Normal | text.secondary @0.65 (Y) / @0.6 (X) | `CB:108`, `CB:169` |
| Chart start-date label | Segoe UI | 9 | 6.75 | Normal | text.secondary @0.55 | `CB:123` |
| Chart prompt legend "(máx N)" | Segoe UI | 9 | 6.75 | Medium | `#8B5CF6` @0.85 | `CB:298`, `CB:356` |
| AI badge | Segoe UI | 9 | 6.75 | Bold | accent.foreground | `SWc:209-210` |
| Glyph — spinner (big) | Segoe MDL2 Assets | 20 | 15 | — | text.secondary | `PW.cs:848-856` |
| Glyph — settings card header | Segoe MDL2 Assets | 16 | 12 | — | BodyLight | `SWc:197` |
| Glyph — footer icon button | Segoe MDL2 Assets | 14 (×0.75 compact = 10.5) | 10.5 | — | text.secondary | `PW.cs:915` |
| Glyph — tray-menu row | Segoe MDL2 Assets | 14 | 10.5 | — | text.secondary | `TMW.xaml.cs:101` |
| Glyph — pin (emoji U+1F4CC) | (emoji) | 12 | 9 | — | primary/secondary | `PW.xaml:119` |
| Glyph — close (popup, U+E711) | Segoe MDL2 Assets | 11 | 8.25 | — | text.secondary | `PW.xaml:95` |
| Glyph — caption buttons (Stats, About) | Segoe MDL2 Assets | 10 | 7.5 | — | close = primary / maximize = secondary | `SX:57,60`, `SC:643,647`, `AboutWindow.xaml:22` |
| Glyph — caption button (Settings) | Segoe MDL2 Assets | 10 | 7.5 | — | `MaterialDesignBody` | `SWx:135-136` — **different box, see §3.18** |
| About: version line / changelog body | Segoe UI | 12.5 | 9.375 | Normal | Body @0.65 / @0.8 | `AboutWindow.xaml:84`, `AppDialogWindow.xaml:90-92` |
| About: monospace path box | Consolas | 11.5 | 8.625 | Normal | Body | `AboutWindow.xaml:66` |

Opacity tokens applied to text (multiply the colour's alpha): `0.85` prompt legend (`CB:298,356`), `0.8`
changelog body (`AppDialogWindow.xaml:92`), `0.75` link-button hover (`SWx:78`, `AboutWindow.xaml:50`),
`0.7` chart empty message (`CB:56`), `0.65` Y labels (`CB:108`) / dialog app-name (`AppDialogWindow.xaml:78`)
/ About version (`AboutWindow.xaml:84`), `0.6` X labels (`CB:169`), `0.55` chart start-date (`CB:123`) /
About path label (`AboutWindow.xaml:94`), `0.5` disabled About link (`AboutWindow.xaml:53`), `0.45` unpinned
pin glyph (`PW.cs:419`), `0.4` calendar zero-count (`SC:862`) / disabled control (`SWx:46,172`), `0.35`
hidden legend chip (`CB:611`) / disabled calendar chevron (`SC:910`).

**Letter-spacing: none anywhere.** No `Typography` attached properties exist in the tree. Line-height is set
in exactly one place: dialog message `LineHeight=19` at 13 px, changelog `LineHeight=18` at 12.5 px
(`AppDialogWindow.xaml:84-93`).

### 2.6 Spacing scale

The design uses an irregular but small vocabulary. Treat these as the whole scale; do not invent values.

| Value (DIP) | Used for | Source |
|---|---|---|
| 2 | calendar cell margin; maximize-button right margin | `SC:871`, `SX:55` |
| 3 | dashboard stat-line bottom gap | `SC:1077` |
| 4 | footer top margin; extra-line top; compact bar-row top; segmented-button inner margin (→ 8 px gap); date-popup padding | `PW.cs:876`, `PW.cs:654`, `PW.cs:589`, `SWc:530`, `SC:486` |
| 5 | reset-caption top margin; settings label→hint gap | `PW.cs:689`, `SWc:715` |
| **6** | **bar top margin**; ChromeReserve (shadow gutter); compact card padding; compact icon gap; chip stack gap; loading-more label gap | `PW.cs:707`, `PW.cs:1262`, `PW.cs:185`, `PW.cs:557`, `SC:365` |
| 8 | header icon→name gap; screen-edge clamp; compact block gap; card header bottom (chart) | `PW.cs:623`, `PW.cs:1003`, `PW.cs:549`, `CB:508` |
| 10 | toast icon gap; dialog button gap; dashboard card right/bottom margin; settings card icon→title gap; tray-menu glyph gap; settings hint bottom | `TW.xaml.cs:39`, `AppDialogWindow.xaml:95`, `SC:1069`, `SWc:222`, `TMW.xaml.cs:103`, `SWc:250` |
| 12 | **section-header bottom gap (full popup)**; toast edge clamp; stats anchor gap | `PW.cs:618`, `TW.xaml.cs:78`, `SC:22` |
| **14** | **meter-row bottom gap**; settings slider group gap | `PW.cs:663`, `SWc:381` |
| 16 | loading header bottom; loading-more block bottom; scroll-fade height; settings card right/bottom margin; labelled-row text→control gap | `PW.cs:763`, `PW.cs:798`, `SWx:347`, `SWc:233`, `SWc:713` |
| **18** | **service-block bottom gap (full popup)**; settings switch-row rhythm; toast/menu shadow gutter | `PW.cs:616`, `SWc:260`, `TW.xaml:12` |
| **20** | **card padding (full popup)**; settings sub-section gap; chart service-block bottom | `PW.cs:185`, `SWc:264`, `CB:506` |
| 22 | settings sub-section gap (variant) | `SWc:559` |
| 24 | settings card padding; dialog padding | `SWc:236`, `AppDialogWindow.xaml:62` |
| 28 | settings body margin; settings footer horizontal margin | `SWx:336`, `SWx:359` |

### 2.7 Corner radii

| Token | Value | Source |
|---|---|---|
| `radius.card.popup` | **16** | `PW.xaml:29` |
| `radius.card.toast` / `tray-menu` / `dialog` / `about` | 14 | `TW.xaml:13`, `TMW.xaml:24`, `AppDialogWindow.xaml:62` |
| `radius.iconButton` | 13 on a 26×26 box → perfect circle | `PW.xaml:65,94,118,153`, `SX:31` |
| `radius.card.settings` | 12 | `SWc:236` |
| `radius.card.dashboard` | 10 | `SC:1067` |
| `radius.switch.track` / `.thumb` | 10.5 / 7.5 | `SWx:160,162` |
| `radius.chip` / `menuRow` / `button.primary` / `datePopup` | 8 | `SC:365`, `TMW.xaml.cs:122`, `SWx:96` |
| `radius.segmented` / `textbox` / `calendarCell` | 6 | `SWx:38,224`, `SC:872` |
| **`radius.meter`** | **height / 2 = 4.5** for the 9 px bar, **2** for the 4 px loading bar | `PW.cs:711`, `PW.cs:812` |
| `radius.slider.thumb` / `.track` | 3 / 2 | `SWx:278,260` |
| `radius.chartBar` | 1 (RadiusX = RadiusY) | `CB:346` |
| `radius.bellToggle` | 15 on a 30×30 box → circle | `SWx:190` |
| `radius.aiBadge` | 10 on a 20×20 box → circle | `SWc:204` |
| `radius.captionButton` (Settings/Dialog) | **0 — square, no `CornerRadius` at all** | `SWx:141` |
| `radius.aboutPathBox` | 6 | `AboutWindow.xaml:95` |

### 2.8 Shadow

| Surface | BlurRadius | ShadowDepth | Direction | Opacity | Colour | Gutter | Source |
|---|---|---|---|---|---|---|---|
| **Popup card (Standard mode)** | **10** | **2** | 270 (straight down) | **0.22** → alpha **56** | `#000000` | **6** | `PW.xaml:31`, `PW.cs:1262` |
| Popup card (Blur mode) | *none* — `Effect = null`, gutter 0, DWM rounding + acrylic instead | | | | | 0 | `PW.cs:340-341,368` |
| Toast | 20 | 5 | 270 | 0.22 → 56 | `#000000` | 18 | `TW.xaml:15` |
| Tray menu | 22 | 6 | 270 | 0.22 → 56 | `#000000` | 18 | `TMW.xaml:26` |
| Dialog / About | 24 | 6 | 270 | 0.28 → alpha **71** | `#000000` | 18 | `AppDialogWindow.xaml:64` |
| Date-picker popup | 16 | 2 | (default) | 0.30 → alpha **77** | `#000000` | — | `SC:487` |

WPF `Direction=270` with `ShadowDepth=d` ⇒ offset `(0, +d)` in screen coordinates. The date-picker popup's
`DropShadowEffect` sets no `Direction` at all, so it takes WPF's default **315°** (down-left), not 270.
The gutter is a transparent outer margin so the blur is not clipped by the window rect. Several **stale
comments still say 18 px** for the popup's gutter (`PW.cs:334`, `PW.cs:358`, `PW.cs:1269`, `PW.cs:1280`);
**the live constant is 6** (`PW.cs:1262`, and the changelog note at `PW.xaml:22` / `PW.cs:1258-1260`
records the shrink from 18 → 6). `DwmHelper` never mentions any gutter size.

### 2.9 Motion / durations

| Motion | Duration | Easing | Detail | Source |
|---|---|---|---|---|
| **Meter fill grow** | **500 ms** | Cubic **EaseOut** | `Width: 0 → target`, `BeginTime = 80 ms × barIndex` (cascade) | `PW.cs:1322-1343` |
| Meter fill — skip conditions | 0 ms | — | instant set when `AnimationsEnabled == false`, or when the key `"Service\|Label"` already shows this exact percent | `PW.cs:727-733`, `PW.cs:1328-1331` |
| Compact-mode toggle | 180 ms | Cubic EaseOut | `ContentHost.Opacity 0 → 1` | `PW.cs:267-278` |
| Window resize (content growth) | 220 ms | Cubic EaseOut | animates `Width`, `Height`, `Top` together; bottom edge pinned, card grows **upward** | `PW.cs:1191-1211` |
| Window resize (style-mode change) | 0 ms | — | deliberately instant to avoid tearing between margin/shadow/DWM state | `PW.cs:1226-1246` |
| Loading-more bar | 400 ms | Cubic EaseOut | `0 → contentWidth × ready/total` | `PW.cs:796-844` |
| Refresh-button spin | 800 ms/rev | linear | `RotateTransform` 0→360, `RepeatBehavior.Forever`, centre (0.5,0.5), button disabled meanwhile | `PW.cs:283-301` |
| Full-page loading spinner | 1100 ms/rev | linear | 0→360 forever, glyph `` at 20 px | `PW.cs:846-872` |
| Style-switch settle delay | 400 ms | — | wait before revealing after a Standard↔Blur switch | `PW.cs:1125,1174` |
| Toast visible | 6000 ms (`VisibleSeconds = 6`) | — | auto-close timer | `TW.xaml.cs:18`, `TW.xaml.cs:102` |
| Toast idle deferral | poll 1000 ms | — | if user idle ≥ 30 s (`IdleThresholdSeconds`, `TW.xaml.cs:17`) at show time, wait until idle < 2 s, *then* arm the 6 s timer | `TW.xaml.cs:90-126` |
| Stats resize re-render | debounce 150 ms | — | | `SC:131` |
| Tray hover poll | 200 ms | — | + user `HoverDelaySeconds` ∈ {0,1,2,3} | `TrayOrchestrator.cs:40,93` |
| Toast show/hide, tray menu open/close, switch toggle, chip selection, all chart drawing | **none** | — | verified absent — no `Storyboard` in those files | `TW.*`, `TMW.*`, `SWx:154-178`, `CB`, `SC` |

---

## 3. COMPONENT RECIPES

Notation: `W×H`, `padding = (L,T,R,B)`, `margin = (L,T,R,B)`. All values DIP.

### 3.1 Card / surface (the popup shell)

**Geometry.** Window: `WindowStyle=None`, `AllowsTransparency=True`, `Background=Transparent`,
`Topmost=True`, `ShowInTaskbar=False`, `ResizeMode=NoResize`, `SizeToContent=Manual` (`PW.xaml:5-12`).
Tree: `Grid RootGrid (margin 6)` → `Border RootBorder (CornerRadius 16 + DropShadow)` →
centred `Grid` → `StackPanel ContentHost (margin 20)` + 4 absolutely-positioned chrome buttons
(`PW.xaml:28-46`).

- Content column width `SingleColumnWidth = 288` (`PW.cs:17`); compact `190` (`PW.cs:64`).
- Card outer = `288 + 2×20 = 328`; window = `328 + 2×6 = **340**` (`PW.cs:1298-1307`).
- Compact card = `190 + 2×6 = 202`; window = **214**.
- Pre-show fallback size `320×160` (`PW.cs:976,1078`).
- Screen-edge clamp 8 px on all sides; opened at cursor X, bottom-anchored to `screenBottom − height − 8`
  (`PW.cs:1001-1009, 1022-1023`).

**Fill.**
- Standard: `surface.card` + `alpha = clamp(round(OpacityPercent/100 × 255), 0, 255)`; default 100 → `0xFF`.
- Blur: `surface.card` + `tintAlpha = clamp(235 − BlurPercent/100 × 185, 50, 235)` (byte truncation);
  default `BlurPercent = 45` → `235 − 83.25 = 151.75` → **151 (`0x97`)`. Range 0 %→235, 100 %→50.
  The same tint is *also* pushed to the OS acrylic via `SetWindowCompositionAttribute`
  (`AccentState = 4`, `GradientColor = (a<<24)|(B<<16)|(G<<8)|R` — **ABGR**, `DH:114-125`).

**States.**
- Rest: as above.
- Drag: whole card is a drag handle — left-button-down → `DragMove()` and auto-pin (`PW.cs:475-499`).
- No hover state, **no border at all** (`RootBorder` declares only `CornerRadius`; no `BorderBrush`/
  `BorderThickness` exists in the file), **no dividers** — separation is whitespace only.

### 3.2 Section header (service row, full layout)

`Grid` cols `[Auto][*]`, bottom margin **12** (`PW.cs:618-620`).
- Col 0: service icon, size **18**, `margin (0,0,8,0)`, vertically centred, tinted with `text.primary`
  when it is the vector variant (`PW.cs:622-624`, `SI:28-43`).
- Col 1: name, **14 px / Medium / `text.primary`**, vertically centred (`PW.cs:627`).
- Compact variant: icon **10.5**, gap **6**, name **12 px Normal** (`PW.cs:556-561`).
- Error variant: the meter rows are replaced by a wrapping **13 px** TextBlock in the error colour
  (`PW.cs:636-643`).
- Chart variant (Stats window): icon **16**, gap 8, name **13 px Medium** (`CB:509-513`).

### 3.3 Meter row (label + value + bar)

`StackPanel`, bottom margin **14** (`PW.cs:663`). Three stacked parts:

1. **Label/value line** — `Grid` cols `[*][Auto]`:
   - label, left, **12 px, `text.secondary`** (`PW.cs:669`);
   - value, right-aligned, text `"{percent}%"`, **12 px, weight Normal (explicit), `text.primary`**
     (`PW.cs:672`).
2. **Bar** — §3.4, `margin (0,6,0,0)`.
3. **Caption** (optional) — `"Resets {0}"` / `"Se reinicia {0}"` (`Strings.cs:95,282`), **11 px, `text.secondary`**,
   `margin (0,5,0,0)` (`PW.cs:686-689`). Countdown wording if the reset is < 1 day away, calendar wording
   otherwise.

Optional per-service **extra line** below all meters: 12 px, `text.secondary`, `margin (0,4,0,0)`
(`PW.cs:654`) — this is the "Créditos usados: 41,41 / 85,00 EUR" line in the capture.

**Compact meter row** — a single `Grid [22][*][30]`, `margin (0,4,0,0)`: prefix 10 px `text.secondary` |
bar 138 wide, still 9 px tall, same ramp | `"{pct}%"` 10 px right-aligned `text.primary`
(`PW.cs:583-607`). Failed service in compact: em-dash `"—"` 12 px `text.secondary` in col 2 (`PW.cs:569`).

### 3.4 The meter bar itself

`BuildProgressBar`, `PW.cs:704-740`.

| Property | Value |
|---|---|
| Container | `Grid`, `Height = 9`, `margin (0,6,0,0)` |
| Track | full-width `Border`, `CornerRadius = height/2 = 4.5`, `Background = #26808080` |
| Fill | `Border`, `CornerRadius = 4.5`, `HorizontalAlignment = Left`, initial `Width = 0` |
| Fill width | `clamp(percent,0,100)/100 × barWidth`; `barWidth` = 288 (full) / 138 (compact rows) |
| Minimum visible width | **none** — 0 % renders zero-width, i.e. a bare empty track (confirmed by the capture's Grok row) |
| Fill paint | ramp of §2.3, gradient axis `(0,0)→(1,0)` **in fill-local coordinates** |
| Cap style | both ends rounded via the 4.5 radius; at very low percent the fill degenerates to a lozenge |
| Animation | 500 ms Cubic EaseOut, `0 → target`, staggered `80 ms × index` |
| Loading-bar variant | `Height = 4`, radius 2, same track, fill = flat accent, 400 ms |

**No text is drawn inside the bar. No tick marks. No border.**

### 3.5 Caption text

11 px, `text.secondary`, no wrapping constraint in the meter caption; `margin (0,5,0,0)`.
Chart/settings captions: 12 px `text.secondary`, `TextWrapping = Wrap`. Chart empty-state: 12 px,
`Opacity 0.7`, centred, `MaxWidth = width − 32` (`CB:56-63`).

### 3.6 Footer strip

`Grid`, `margin (0,4,0,0)`, cols `[*][Auto]` (`PW.cs:876-878`).
- Left: template `"Updated {0}"` / `"Actualizado {0}"` (`Strings.cs:94,281`) filled with `TimeFormat.Ago()`
  (`TimeFormat.cs:99-107`), which supplies the "hace …"/"… ago" wording — the capture's
  "Actualizado hace 3 min" is the two combined, not a single literal. **11 px, `text.secondary`**,
  vertically centred; empty string when no timestamp (`PW.cs:880-886`).
- Right: horizontal stack — refresh button, then settings button (`PW.cs:889-895`).
- **No top border, no background, no divider.** It is just the last row of the content stack.

### 3.7 Icon button

Two variants, same visual language.

**A. Footer icon button** (`PW.cs:904-932`)

| | Value |
|---|---|
| Box | `30 × 30` (× 0.75 → `22.5 × 22.5` in compact) |
| Padding | 0; `margin (4,0,0,0)` between buttons |
| Background | transparent at rest |
| Glyph | `Segoe MDL2 Assets`, `14 × scale` px, `text.secondary` |
| Codepoints | **exactly two exist**: refresh `U+E72C` (`PW.cs:18`), settings `U+E713` (`PW.cs:19`). The footer builds these two buttons and nothing else (`PW.cs:889-895`). There is **no** about/exit glyph anywhere in the tree — the full MDL2 inventory in the whole app is `E711`, `E713`, `E72C`, `E8BB`, `E922`, `E923`. |
| Hover | MaterialDesignFlatButton hover (library-defined; **port as `#14808080` fill, radius = half the box**) |
| Pressed | not defined in-tree |
| Disabled | used only during a refresh spin; the button is disabled while the glyph rotates 360° / 800 ms |
| Focus | **not** suppressed — unlike the Settings styles, these inherit `MaterialDesignFlatButton` and never set `FocusVisualStyle = null` |

**B. Caption / chrome icon button** (`PW.xaml:59-186`, `SX:22-42`)

| | Value |
|---|---|
| Box | `26 × 26`; template root `Border CornerRadius = 13` → perfect circle |
| Background | `Transparent` at rest → `#14808080` on `IsMouseOver` |
| Pressed | **no pressed state defined** |
| Cursor | `Hand`. `FocusVisualStyle = null` on the **Stats/About** variants (`SX:26`, `AboutWindow.xaml:17`); the four **PopupWindow** chrome buttons (`PW.xaml:59,88,112,147`) do *not* set it |
| Anchoring | `HorizontalAlignment=Right, VerticalAlignment=Top`, fixed margins `(0,8,8,0)` pin, `(0,8,40,0)` compact, `(0,8,72,0)` stats, `(0,8,104,0)` close |
| Compact mode | `LayoutTransform = ScaleTransform(0.75, 0.75)`; right edges stay anchored |

Chrome glyph inventory:
- **Pin** (`ToggleButton`): emoji **U+1F4CC** at 12 px; checked → `RotateTransform(-40°, centre 7,7)`,
  colour `text.primary` @ 1.0; unchecked → `text.secondary` @ **0.45** (`PW.cs:418-419`).
- **Compact** (`ToggleButton`): `Viewbox 12×12` over a `Path`, fill `text.primary`. Material Symbols
  Outlined 24 dp geometry in the `0..960 / −960..0` space:
  collapse `M440-440v240h-80v-160H200v-80h240Zm160-320v160h160v80H520v-240h80Z`,
  expand `M200-200v-240h80v160h160v80H200Zm480-320v-160H520v-80h240v240h-80Z` (`PW.cs:395-403`).
- **Stats** (`Button`): three `Rectangle`s in a 14×12 grid, each `Width = 3`, `RadiusX = RadiusY = 1`,
  bottom-aligned, heights **5 / 9 / 12** at Left / Center / Right; fill `text.secondary`
  (`PW.xaml:66-69`, `PW.cs:435`). Deliberately vector so it recolours with the theme.
- **Close** (popup): `U+E711` @ 11 px, `text.secondary`; `Visibility = Hidden` (not Collapsed, so siblings
  never shift) unless pinned (`PW.cs:426,450`).
- **Close** (Stats/About): `U+E8BB` @ 10 px, `text.primary`. **Maximize**: `U+E922` ↔ restore `U+E923`
  @ 10 px, `text.secondary`. **No minimize button anywhere** (`SX:55-61`).

### 3.8 Pill / chip selector

Three instances share one recipe (`SC:358-385`, `SC:393-416`, `SC:508-537`):

| | Value |
|---|---|
| Container | `Border`, `CornerRadius = 8`, `padding (12,5,12,5)`, `margin (0,0,6,0)`, `Cursor = Hand` |
| Height | implicit: text line-height + 10 |
| Rest bg | `Transparent` |
| Selected bg | `accent` @ **0.14** (alpha 36) |
| Rest text | 12 px, Normal, `text.secondary` |
| Selected text | 12 px, **Medium**, `accent` |
| Border stroke | **none, in either state** |
| Hover / pressed | **no state defined** — the chip does not react until clicked |
| Disabled | not defined |

**Prompt-mode variant** (`SC:552-580`): `padding (10,4,10,4)`, `margin (6,0,0,0)`, text 11 px,
active colour `#8B5CF6`, active bg `#8B5CF6` @ 0.14.

**Segmented control** (`SWc:520-542`, `SWx:23-62`) — the "one of N" variant:
`UniformGrid Rows=1`, each button `Height = 36`, `FontSize = 13`, `CornerRadius = 6`,
`BorderThickness = 1` in divider colour, transparent fill, body text; inner margins of 4 on facing edges →
**8 px gap between segments**. Selected: background **and** border = accent, foreground hard-coded
`#FFFFFF` (deliberately not the computed foreground — comment `SWx:57-61`). Hover: `Opacity = 0.85`.
Disabled: `Opacity = 0.4`.

### 3.9 Toggle / checkbox

**FlatSwitch** (`SWx:154-178`) — the only switch in the app:

| Part | Off | On | Disabled |
|---|---|---|---|
| Track | `38 × 21`, `CornerRadius = 10.5`, fill = divider colour | fill = accent | whole control `Opacity = 0.4` |
| Thumb | `15 × 15`, `CornerRadius = 7.5`, `#FFFFFF`, left-aligned `margin (3,0,0,0)` | right-aligned `margin (0,0,3,0)` | — |
| Transition | **none — it snaps** | | |

**Bell toggle** (`SWx:180-207`): 30×30 circular hit area (`CornerRadius = 15`), transparent; glyph
`TextBlock` 14 px — off = **U+1F515** (🔕) in BodyLight, on = **U+1F514** (🔔) in accent; hover fill =
divider colour.

**Radio buttons**: stock, untemplated, 14 px label, `GroupName="PopupMode"`, margins `(0,0,0,12)` and
`(0,0,0,20)` (`SWc:329-330`). No custom look exists — port them as the segmented control instead.

**Labelled setting row** (`SWc:707-725`): `Grid [*][Auto]`; left = vertical stack, `margin (0,0,16,0)`,
vertically centred, label 14 px wrapping with `margin (0,0,0,5)`, optional 12 px hint below in BodyLight;
right = the control, vertically centred. **No indentation, no divider between rows** — vertical rhythm is
explicit `Border{Height=N}` spacers: **18** between switch rows, **12** in the compact sub-group, **20–22**
before a new labelled sub-section, **14** before a slider group.

### 3.10 Combobox

**There is no combobox in the source.** Selection is always a segmented control, a chip row, a radio pair or
a swatch grid. If the monitor app needs one (e.g. GPU device selector), synthesise it from verified tokens:

| | Value |
|---|---|
| Closed box | `Height = 36`, `CornerRadius = 6`, `BorderThickness = 1` divider, fill transparent, text 13 px `text.primary`, padding `(12,0,10,0)` |
| Chevron | `Segoe MDL2 Assets` `U+E70D` @ 10 px, `text.secondary`, right |
| Hover | fill `#14808080` |
| Open / popup | `Border` `CornerRadius = 8`, fill `surface.card`, `BorderThickness = 1` in `accent`, `padding 4`, shadow blur 16 / offset (0,2) / alpha 77 — copied verbatim from the date-picker popup (`SC:480-489`) |
| Item | `padding (12,7,12,7)`, `CornerRadius = 8`, 13 px `text.primary`; hover `#14808080`; selected bg `accent` @ 0.14, text `accent`, Medium |
| Disabled | `Opacity = 0.4` |

### 3.11 Primary / secondary button

| | Primary (`SWx:86-107`) | Secondary (`SWx:109-127`) | Link (`SWx:64-84`) |
|---|---|---|---|
| Height | 40 (dialog: 36) | 40 (dialog: 36) | auto |
| Width (footer use) | 120 | 120 | auto |
| Corner radius | 8 | 8 | — |
| Fill rest | `accent` | `Transparent` | none (bare content presenter) |
| Border | none | 1 px divider | none |
| Text | 14 px, `accent.foreground` (`#FFFFFF`) | 14 px, `text.primary` | 12 px, `accent` |
| Hover | `Opacity = 0.9` | fill = divider colour | `Opacity = 0.75` |
| Pressed | not defined | not defined | not defined |
| Disabled | `Opacity = 0.4` (via segmented convention) | same | same |
| Shadow | **none** | none | none |
| Focus ring | **none** — every Settings style sets `FocusVisualStyle = null` individually (`SWx:31,71,92,137,156,186,217,234,295`). The `{x:Type Control}` style at `SWx:19-21` is **not** a global sweep: WPF's implicit lookup keys on the concrete type (`Button`, `ToggleButton`), never on the `Control` base, so that entry applies to nothing. | | |

### 3.12 Tooltip

**The app defines no styled tooltip.** Two things stand in for one:

1. **Chart hover readout** (`CB:379-398`) — *bare text plus a dot, no plate*:
   - dot: `Ellipse 7×7`, fill = accent, `margin (anchorX − 3.5, anchorY − 3.5, 0, 0)`, collapsed at rest;
   - text: 11 px **Medium**, `text.secondary`, `margin (clamp(anchorX − 16, 0, width − 60), max(0, anchorY − 18), 0, 0)`;
   - **no background, no border, no radius, no shadow, no crosshair line**;
   - both collapse on `MouseLeave`.
2. **Native OS tooltips**, unstyled, on far more than the tray icon: all four popup chrome buttons
   (`PW.cs:175-178`), both footer buttons (`PW.cs:890,894`), and the Stats maximize button
   (`SX:56`, retargeted per state at `SC:648`).

Port recommendation if a real tooltip is needed: `Border CornerRadius = 8`, fill `surface.card`, no border,
shadow blur 16 / offset (0,2) / `#00000026`, padding `(10,6,10,6)`, text 11 px `text.primary`.
Flag this as **synthesised, not extracted**.

### 3.13 Chart (history graph)

Everything below is `CB` unless noted. The chart is drawn as absolutely-positioned children of a `Grid`
(per-child `Margin` + `HorizontalAlignment=Left, VerticalAlignment=Top`); there is no `Canvas`.

**Plot box.**
```
padTop = 18, padBottom = 16, padLeft = 30, padRight = 16        (CB:75)
plotWidth  = max(1, width  - 30 - 16)
plotHeight = max(1, height - 18 - 16)
baselineY  = padTop + plotHeight                                 (CB:88)
host.Height = height + barsHeight                                (CB:90)
barsHeight = 16 when the prompt-bars legend is present (PromptBarsLegendHeight, CB:318)
MinChartHeight = 90 (SC:21)
```

**Coordinate mapping.**
```
x         = padLeft + plotWidth * ((t - minTime).seconds / max(1, span.seconds))     (CB:118,183)
y_usage   = padTop  + plotHeight * (1 - clamp(percent, 0, 100)/100)                  (CB:184)
y_second  = padTop  + plotHeight * (1 - clamp(delta/seriesMax, 0, 1))                (CB:261-266)
barHeight = max(1.5, 22 * clamp(delta/seriesMax, 0, 1))   # PromptBarsMaxHeight = 22 (CB:313,334)
```

**Z-order** (`Children.Add` order): area+line group → horizontal gridlines + Y labels (so gridlines draw
**over** the fill) → start-date label → vertical gridlines + X labels → second series → hover dot + label.

**Axes.** **No axis spines are ever drawn** — neither X nor Y. Only dashed gridlines.

| Element | Spec |
|---|---|
| Y ticks | **hardcoded `[0, 50, 100]`** — no nice-number algorithm, scale is always 0–100 % (`CB:93`) |
| Horizontal gridline | `Line X1=padLeft, X2=width−padRight, Y1=Y2=y`, stroke = `chart.grid`, `StrokeThickness = 1`, `StrokeDashArray = {2,3}` (`CB:96-104`) |
| Y label | `"{pct}%"`, 9 px, `text.secondary` @ **0.65**, `Width = padLeft − 4 = 26`, `TextAlignment = Right`, `margin (0, y − 6, 0, 0)` (`CB:105-113`) |
| Vertical gridline | `X1=X2=x, Y1=padTop, Y2=baselineY + barsHeight` (deliberately extends through the bars strip), same stroke/dash (`CB:152-159`) |
| X tick interval | span ≤ 30 h → 1 h, format `"HH:mm"`, label box 30 px; span ≤ 12 d → 1 day, `"d MMM"`, box 36; else 7 days, `"d MMM"`, box 36 (`CB:136-140`) |
| X tick origin | cursor snapped to the local hour boundary (sub-day) or local midnight (day+), then advanced one interval before the first line (`CB:145-147`) |
| X label | 9 px, `text.secondary` @ **0.6**, `TextAlignment = Center`, `margin (x − boxW/2, baselineY + barsHeight + 3, 0, 0)` (`CB:166-174`) |
| X label suppression | drawn only if `x − lastLabelX ≥ 32` **and** `x ≤ width − padRight − 16` (`CB:142,164`) |
| Range-start label | `minTime.ToString("d MMM")`, 9 px @ **0.55**, `margin (padLeft, 0, 0, 0)` — top-left corner (`CB:120-126`) |
| Plot background | **none** — the window background shows through |

**Series 1 — usage (area + line).**
- Line: `Path` over a `PathGeometry` of straight `LineSegment`s. **Explicitly not smoothed** — Catmull-Rom
  was tried twice and rejected because uneven time gaps made the spline loop (`CB:637-652`). Port it as a
  plain polyline with visible corners.
- `Stroke = accent`, `StrokeThickness = **2.5**`, `StrokeLineJoin = Round`,
  `StrokeStartLineCap = StrokeEndLineCap = Round` (`CB:196-204`). **No point markers.**
- Area: clone the line figure, append `LineTo(lastX, baselineY)`, `LineTo(firstX, baselineY)`,
  `IsClosed = true`; `Fill = accent @ 0.16` (alpha 41), **no stroke, flat — not a gradient** (`CB:190-194`).

**Series 2 — secondary metric (`#8B5CF6`).** Two exclusive modes:
- *Line mode*: `StrokeThickness = 1.75`, `StrokeDashArray = {4,2}`, round joins/caps, only when ≥ 2 points;
  every point gets `Ellipse 5×5` fill `#8B5CF6`, `margin (x−2.5, y−2.5, 0, 0)` (`CB:271-292`).
- *Bar mode (default)*: values first bucketed **per local clock hour** and summed (`CB:484-493`);
  `barWidth = clamp(plotWidth / max(1, count) × 0.6, 2, 10)`;
  `Rectangle W=barWidth, H=barHeight, Fill = #8B5CF6 (opaque), RadiusX=RadiusY=1,
  margin (x − barWidth/2, baselineY − barHeight, 0, 0)` — bars grow **upward from the usage chart's own
  0 % baseline, never below it** (`CB:327-350`).
- Legend text: `"prompts (máx {N})"`, 9 px **Medium**, `#8B5CF6` @ 0.85; line mode → top-right,
  `margin (0,0,padRight,0)`; bar mode → below baseline, `margin (0, baselineY + 2, padRight, 0)`.

**Event markers.** `TextBlock "✨" (U+2728)`, 13 px, `margin (x − 7, y − 20, 0, 0)`, `IsHitTestVisible=false`,
added into the usage group. Its `y` snaps to the Y of the nearest screen point by `|Δx|` (`CB:217-228`).

**Hover.** Host `Background = Transparent` purely so empty pixels hit-test (`CB:377`). Nearest point chosen
by **|Δx| only** (`CB:409-417`). Event-marker snapping tolerance **7 px** (`CB:402`); inside it the anchor
moves to the marker and the text becomes `"✨ Reset"`. Text composition:
`("✨ Reset" | "{percent}%") + " · {N} prompts"` (`CB:432-439`). Readout styling per §3.12.
**No crosshair, no vertical rule, no tooltip plate.**

**Legend** (`CB:587-616`), emitted only when a second series exists:
horizontal stack, `margin (0,6,0,0)`; each chip = horizontal stack, `margin (0,0,14,0)`, `Cursor = Hand`,
containing `Ellipse 8×8` (a **circle**, not a square) `margin (0,0,5,0)` + `TextBlock` 10 px
`text.secondary`. Click toggles the series' visibility and sets **both** dot and text `Opacity` to
**0.35** when hidden, **1.0** when shown.

**Empty state** (`< 2 points`, `CB:48-65`): a `Grid` of exactly `width × height` with a centred
`TextBlock`, 12 px, `text.secondary` @ 0.7, `TextWrapping = Wrap`, `TextAlignment = Center`,
`MaxWidth = width − 32`.

**Viewport / zoom** (desktop only): `ScrollViewer` `Width = viewportWidth`,
`Height = chartHeight + extra`, horizontal scrollbar Auto, vertical Disabled; the wheel is swallowed and
converted to a zoom step (`onZoom(sign(delta)); e.Handled = true`, `CB:553-557`).
`chartWidth = viewportWidth × zoom`, `zoom ∈ [1.0, 4.0]` step **0.25** (`SC:41-43, 151, 703`).

### 3.14 Toast

`ToastWindow.xaml` / `.cs`.

| | Value |
|---|---|
| Window | frameless, `AllowsTransparency=True`, transparent bg, `Topmost`, `ShowInTaskbar=False`, `SizeToContent=WidthAndHeight`, manual placement |
| Shell | outer `Grid margin 18` (shadow gutter) → `Border CornerRadius = 14`, fill `surface.card`, shadow blur 20 / offset (0,5) / alpha 56 |
| Content | horizontal stack, `margin (16,14,16,14)`: icon **20×20**, `margin (0,0,10,0)`, vertically centred; message `TextBlock` **13 px**, `text.primary`, `TextWrapping = Wrap`, `MaxWidth = 260`, vertically centred |
| Placement | bottom-right of the work area under the cursor: `Left = screenRight − W − 12`, `Top = screenBottom − H − 12 − stackOffset`, `stackOffset = openCount × (H + 10)` — stacks upward, 10 px gap |
| Dismiss | whole card is click-to-dismiss; auto-close after **6000 ms** |
| Idle rule | if the user has been idle ≥ 30 s at show time, poll every 1 s and only arm the 6 s timer once idle < 2 s |
| Animation | **none** — verified absent |
| Gotcha | the window is parked at `(-10000,-10000)` and positioned in the `Loaded` handler, because `Measure()` on a never-shown window returns `0×0` for the first toast of a process |

### 3.15 Tray-style menu row (useful as a generic list-row recipe)

`Border CornerRadius = 8`, `padding (12,7,12,7)` (left padding **30** when indented), transparent,
`Cursor = Hand`; inner `Grid [Auto][*]`: glyph `Segoe MDL2 Assets` 14 px `text.secondary`
`margin (0,0,10,0)`, label 13 px `text.primary`. Hover → `#14808080`; leave → transparent.
**No pressed state, no transition.** Section label: 11 px `text.secondary`, `margin (12,8,12,2)`.
Separator: `Border Height = 1`, `margin (8,6,8,6)`, `Background = #22808080`.
The menu shell itself: `Grid margin 18` → `Border CornerRadius = 14, MinWidth = 200` + shadow (§2.8),
inner `StackPanel margin 6` (`TMW.xaml:23-28`).

### 3.16 Slider (`FlatSlider`, `SWx:232-288`) — the transparency/refresh control

Fully templated; no MDIX slider survives. Everything is pinned by explicit top margins rather than
`VerticalAlignment`, because `Track` hands its children *its own* arranged height (see the two long
comments at `SWx:238-253`).

| Part | Value |
|---|---|
| Root | `Grid Height = 24` (`SWx:254`); style `Height = 24` (`SWx:233`) |
| Filled track (decrease) | `Border Height = 4`, `CornerRadius = 2`, `margin (0,10,0,0)`, fill `accent` (`SWx:260`) |
| Remaining track (increase) | identical box, fill = divider colour (`SWx:269`) |
| Thumb | `Border 10 × 20`, `CornerRadius = 3`, `margin (0,2,0,0)`, fill `accent` (`SWx:278`) |
| Centreline math | `(24−4)/2 = 10` for the track, `(24−20)/2 = 2` for the thumb — both anchored from the top |
| Tick marks / value bubble | **none** |

Sliders always ship paired with a `TextBox` showing the numeric value (`BuildPercentSliderRow`), never
alone. Port note: Qt's `QSlider` groove/handle sub-controls reach this exactly via QSS — no custom paint
needed, unlike the meter.

### 3.17 Colour swatch (`ColorSwatchButton`, `SWx:290-312`)

The accent picker is a grid of these; §3.10 refers to it but never specified it.

| | Value |
|---|---|
| Box | `28 × 28`, `HorizontalAlignment = Left`, `Cursor = Hand` |
| Fill | `Ellipse` filled with the swatch brush (`Background`) — for "Original" that brush is the 3-stop diagonal gradient of §2.2 |
| Selected | a **second** `Ellipse` ring: `Stroke = MaterialDesignBody`, `StrokeThickness = 2`, `margin = −4` (so it sits *outside* the 28 px disc → 36 px outer), `Opacity 0 → 1`, driven by `Tag == "Selected"` |
| Hover / pressed / disabled | **none defined** |

There are `AccentSwatches.Length + 1 = 12` buttons (`SWc:34`): the 11 literal swatches plus the Original
gradient chip.

### 3.18 Window caption button — Settings / Dialog variant (`CaptionButton`, `SWx:129-152`)

**This is a third icon-button recipe, not the §3.7B circle.** Do not merge them.

| | Value | vs §3.7B |
|---|---|---|
| Box | `42 × 40` | 26 × 26 |
| Corner radius | **none — square** | 13 (circle) |
| Rest bg | `Transparent` | `Transparent` |
| Hover bg | `MaterialDesignDivider` | `#14808080` |
| Glyph | `Segoe MDL2 Assets` 10 px, `MaterialDesignBody` (= `text.primary`) | 10–11 px, primary/secondary |
| Codepoint | close `U+E8BB` (`SWx:329`) | — |

It sits inside a 40 px-tall `WindowChrome` caption strip (`SWx:14`, `SWx:318`), with the title at 15 px
Medium and an 18 px app icon at `margin (0,0,10,0)` (`SWx:325-327`). Stats' caption strip is **36** tall
(`SX:18`, `SX:47`) with `margin (20,0,10,0)` (`SX:52`).

### 3.19 Calendar heat cell (`SC:832-880`) — the one place the design does use tint + outline

The Stats calendar view contradicts §2.1's "no outline" rule, deliberately.

| | Value |
|---|---|
| Cell | `Border`, `CornerRadius = 6`, `margin 2`, `padding (4,6,4,6)`, `MinHeight = 54` (`SC:872-875`) |
| Fill | `accent` at `Opacity = clamp(0.14 + intensity × 0.66, 0.14, 0.8)` where `intensity = count / maxCount`; **`0.0` (fully transparent) when `count == 0`** (`SC:847`) |
| Border | `1 px` in `chart.grid`; **`1.5 px` in `accent` for today** (`SC:877-878`) |
| Day number | 11 px `text.secondary`, centred (`SC:852`) |
| Count | 14 px, Bold when > 0 / Normal + `Opacity 0.4` and the text `"–"` when 0 (`SC:859-862`) |
| Month header | 14 px Medium `text.primary`, centred (`SC:779`), between two `‹ ›` chevrons — plain text, **16 px Bold**, `text.primary` enabled / `text.secondary` @ `Opacity 0.35` disabled (`SC:907-910`) |
| Weekday header | 10 px Medium `text.secondary`, uppercase, `margin (0,0,0,6)` (`SC:807`) |

The `0.14 → 0.8` accent ramp is a real design token and the only *continuous* alpha scale in the app —
it shares its floor (`0.14`) with the selected-chip fill of §3.8 on purpose.

---

## 4. QT / PySide6 TRANSLATION NOTES

### 4.0 Global setup

```python
import sys, ctypes, winreg
from PySide6.QtCore import Qt, QPointF, QRectF, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient, QPen, QBrush,
                           QFont, QFontDatabase, QGuiApplication)
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsDropShadowEffect

# Per-monitor DPI: Qt6 is PerMonitorV2-aware by default on Windows, but the default rounding
# policy snaps 125%/150% to integers and will make the 9px bar and 1px gridlines land wrong.
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)   # MUST run before QApplication()
app = QApplication(sys.argv)
```

**Unit mapping.** 1 WPF DIP == 1 Qt logical pixel. Every number in §2/§3 is used verbatim in Qt logical
coordinates. **Do not convert to points.** Always size fonts with `QFont.setPixelSize(int)` — using
`setPointSizeF()` silently applies a ×0.75 factor and every label comes out 25 % small.
Where a value is fractional (bar radius 4.5, stroke 2.5, dot offsets 3.5) keep it a float and draw with
`QPainterPath`/`QRectF`, never `QRect`.

### 4.1 Card / surface → frameless translucent window + shadow

```python
class Card(QWidget):
    def __init__(self):
        super().__init__(None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)                 # Tool == ShowInTaskbar=False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._body = QWidget(self)                # <- the actual 16px-radius card
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)   # ChromeReserve
        lay.addWidget(self._body)

        sh = QGraphicsDropShadowEffect(self._body)
        sh.setBlurRadius(10)          # WPF BlurRadius
        sh.setOffset(0, 2)            # ShadowDepth=2, Direction=270 -> straight down
        sh.setColor(QColor(0, 0, 0, 56))          # 0.22 * 255
        self._body.setGraphicsEffect(sh)
```

`_body` paints itself (do **not** try to get a 16 px radius out of QSS `border-radius` on a translucent
top-level — Qt clips the *widget rect*, not the painted shape, and the shadow effect is ignored on a
top-level window):

```python
def paintEvent(self, e):                 # on _body
    p = QPainter(self)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0xFA, 0xFA, 0xFA, alpha))     # or 0x2B,0x2B,0x2E in dark
    p.drawRoundedRect(QRectF(self.rect()), 16.0, 16.0)
```

**Gotchas.**
- `QGraphicsDropShadowEffect` on a top-level window does nothing. It must live on a **child** widget inside
  a translucent parent — exactly mirroring the WPF `RootGrid margin 6` → `RootBorder` structure. Keep the
  6 px gutter or the blur is clipped.
- `WA_TranslucentBackground` + a `QGraphicsEffect` forces software rasterisation of that subtree. For a
  monitor updating at 1 Hz this is free; if you ever animate the whole card, drop the effect and paint the
  shadow yourself with 3–4 concentric `drawRoundedRect` passes at decreasing alpha.
- Dragging: implement `mousePressEvent` → store `event.globalPosition().toPoint() - frameGeometry().topLeft()`,
  `mouseMoveEvent` → `self.move(...)`. Qt 6.5+ can also use `self.windowHandle().startSystemMove()`, which
  is smoother and matches WPF's `DragMove()`.

### 4.2 DWM: rounded corners, dark title bar, acrylic

```python
DWMWA_USE_IMMERSIVE_DARK_MODE   = 20      # payload 1 = dark titlebar, 0 = light
DWMWA_WINDOW_CORNER_PREFERENCE  = 33
DWMWCP_DEFAULT, DWMWCP_DONOTROUND, DWMWCP_ROUND = 0, 1, 2

def _dwm(hwnd: int, attr: int, value: int) -> None:
    v = ctypes.c_int(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.wintypes.HWND(hwnd), ctypes.c_uint(attr),
        ctypes.byref(v), ctypes.sizeof(v))          # size is always 4

hwnd = int(self.winId())
_dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND)   # Standard mode
_dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if is_dark else 0)  # only for real-titlebar windows
```

**The critical gotcha, ported verbatim from the source's own hard-won comment (`DH:23-41`,
`PW.cs:355-370`):** DWM rounds the **HWND rectangle**, not your painted card. In Standard mode the HWND is
6 px larger on every side (the shadow gutter), so `DWMWCP_ROUND` produces a visible rounded *rectangle
halo* around your soft shadow. Therefore:

- Standard/shadow mode → **explicitly** set `DWMWCP_DONOTROUND (1)`. Do not rely on the default; the
  preference persists on the HWND across resizes and mode switches.
- Acrylic/blur mode → gutter margin `0`, no shadow effect, `DWMWCP_ROUND (2)`.
- **Re-issue the whole DWM block after `show()`** — the state can be lost during the show/fade
  (`PW.cs:1034-1052`). In Qt: `QTimer.singleShot(0, self._reapply_dwm)` inside `showEvent`.
- `winId()` is only valid after the window has a native handle; call it after `show()` or force it with
  `self.winId()` once (which creates the handle) before the first `_dwm` call.
- Corner *radius* is not settable through DWM — there is no radius argument. The 16 px look is yours to
  paint; DWM's `ROUND` is ~8 px and will fight it. **Recommendation for the monitor: never use
  `DWMWCP_ROUND`; always paint the radius yourself and keep `DWMWCP_DONOTROUND`.**

Acrylic (only if you want the blur variant):
```python
class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]
class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

ACCENT_ENABLE_ACRYLICBLURBEHIND = 4      # ACCENT_DISABLED = 0
WCA_ACCENT_POLICY = 19
tint_alpha = max(50, min(235, int(235 - blur_pct / 100.0 * 185)))   # 45% -> 151
r, g, b = (0xFA, 0xFA, 0xFA) if not is_dark else (0x2B, 0x2B, 0x2E)
gradient = (tint_alpha << 24) | (b << 16) | (g << 8) | r            # ABGR, not ARGB!
```
Wrap every DWM/composition call in `try/except` — these are undocumented or Win11-only APIs and the source
swallows all failures by design.

### 4.3 Dark-mode detection

```python
def system_is_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            v, t = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return t == winreg.REG_DWORD and int(v) == 0     # dark iff int and == 0
    except OSError:
        return False        # any failure -> light, matching ThemeHelper.cs:118-131
```
Live changes: Qt 6.5+ emits `QGuiApplication.styleHints().colorSchemeChanged`; the source instead re-reads
on every render and **never caches an `isDark` flag** — copy that, it removes a whole class of stale-theme
bugs. For a background watcher, `RegNotifyChangeKeyValue` on that key in a `QThread`.

### 4.4 Meter bar → custom `QWidget.paintEvent`

Do **not** use `QProgressBar` + QSS: you cannot get a per-value gradient whose axis is the *fill* rect, and
the chunk's rounded caps behave differently across styles.

```python
RAMP = ((60, "#72D08F", "#3F9E63"), (85, "#F3C36A", "#D99420"), (101, "#EE8484", "#CE3D3D"))

class Meter(QWidget):
    def __init__(self):
        super().__init__(); self.setFixedHeight(9); self._pct = 0.0; self._draw = 0.0

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        h = 9.0; r = h / 2.0                       # radius == height/2
        full = QRectF(0, 0, self.width(), h)
        p.setBrush(QColor(128, 128, 128, 38))      # #26808080
        p.drawRoundedRect(full, r, r)

        w = max(0.0, min(100.0, self._draw)) / 100.0 * self.width()
        if w <= 0.0:
            return                                  # 0% == bare track, no minimum width
        for limit, c0, c1 in RAMP:
            if self._pct < limit:
                break
        g = QLinearGradient(0.0, 0.0, w, 0.0)      # axis spans the FILL, not the track
        g.setColorAt(0.0, QColor(c0)); g.setColorAt(1.0, QColor(c1))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
```

**Gotchas.**
- WPF's `(0,0)→(1,0)` gradient is *relative to bounding box*; Qt's `QLinearGradient` is in absolute
  coordinates by default. Either build it from the fill width as above, or use
  `g.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)` and pass `0,0 → 1,0` — but then it is
  the widget's box, which is wrong. **Use absolute, fill-derived coordinates.**
- Antialiasing must be on or the 4.5 px cap ends look chewed. On a 125 % display with `PassThrough`
  rounding, the widget height 9 becomes 11.25 device px; that is fine because you draw in logical units.
- Threshold selection uses the **target** percentage, not the animated draw value — otherwise the bar
  changes hue mid-animation. That is what the source does (colour is chosen once at build time,
  `PW.cs:720`, before the width animation starts).

**Animation.**
```python
anim = QVariantAnimation(self)
anim.setStartValue(0.0); anim.setEndValue(pct)
anim.setDuration(500)
anim.setEasingCurve(QEasingCurve.Type.OutCubic)
anim.valueChanged.connect(lambda v: (setattr(meter, "_draw", v), meter.update()))
QTimer.singleShot(80 * index, anim.start)        # 80 ms cascade
```
Skip the animation entirely (set `_draw = pct; update()`) when animations are disabled **or when this meter
already displays this exact value** — the source keys that check on `"Service|Label"` (`PW.cs:727-733`).
For a live monitor this second rule is what stops the bar re-cascading every poll; see §5.

### 4.5 Meter row, section header, footer → layouts + QSS

Pure layout work; use `QGridLayout`/`QHBoxLayout` with exact margins. QSS for the text:

```css
QWidget#Card            { background: transparent; }         /* painted in paintEvent */
QLabel[role="section"]  { font-family:"Segoe UI"; font-size:14px; font-weight:500; color:#1A1A1A; }
QLabel[role="label"]    { font-family:"Segoe UI"; font-size:12px; color:#555555; }
QLabel[role="value"]    { font-family:"Segoe UI"; font-size:12px; color:#1A1A1A;
                          qproperty-alignment:'AlignRight | AlignVCenter'; }
QLabel[role="caption"]  { font-family:"Segoe UI"; font-size:11px; color:#555555; }
QLabel[role="footer"]   { font-family:"Segoe UI"; font-size:11px; color:#555555; }
```
Dark theme swaps `#1A1A1A→#F2F2F2`, `#555555→#B8B8B8`. Generate the sheet from a token dict rather than
maintaining two literal sheets, and call `style().unpolish(w); style().polish(w)` after
`setProperty("role", …)` changes or the selector will not re-evaluate.

`font-size:14px` in QSS **is** logical px in Qt6 — it matches the DIP table 1:1. This is the one place where
px-vs-pt does not bite you.

### 4.6 Icon button

```python
btn = QToolButton()
btn.setFixedSize(26, 26)
btn.setCursor(Qt.CursorShape.PointingHandCursor)
btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # app has no focus rings at all
f = QFont("Segoe MDL2 Assets"); f.setPixelSize(11); btn.setFont(f)
btn.setText("")
```
```css
QToolButton[chrome="true"] { border:none; border-radius:13px; background:transparent; color:#555555; }
QToolButton[chrome="true"]:hover { background:rgba(128,128,128,20); }   /* #14808080 */
QToolButton[chrome="true"]:pressed { background:rgba(128,128,128,20); } /* no pressed state in source */
QToolButton[chrome="true"]:disabled { color:#555555; }
```
**Gotchas.**
- `border-radius` on a QToolButton works only if a background is actually painted; with
  `background:transparent` at rest the radius is invisible, which is correct — it only shows on hover.
- `Segoe MDL2 Assets` must be requested by exact family name; verify with
  `"Segoe MDL2 Assets" in QFontDatabase.families()` and fall back to `Segoe Fluent Icons` (Win11) whose
  codepoints for `E711/E72C/E713/E8BB/E922` are compatible.
- Hidden-but-reserving-space (the WPF `Visibility.Hidden` trick for the close button) →
  `w.setVisible(False)` **collapses** in Qt layouts. Use a `QSizePolicy` with
  `setRetainSizeWhenHidden(True)`.
- The stats glyph is three bars, not a font glyph — draw it in `paintEvent`:
  three `QRectF(x, bottom-h, 3, h)` with `drawRoundedRect(..., 1, 1)`, heights `5/9/12` at x = 0 / 5.5 / 11
  inside a 14×12 box, brush = `text.secondary`.

### 4.7 Pill / chip selector and segmented control

```css
QPushButton[chip="true"] {
    border:none; border-radius:8px; padding:5px 12px; background:transparent;
    font-family:"Segoe UI"; font-size:12px; color:#555555;
}
QPushButton[chip="true"]:checked {
    background:rgba(46,67,114,36);          /* accent @ 0.14 -> alpha 36 */
    color:#2E4372; font-weight:500;
}
QPushButton[seg="true"] {
    border:1px solid rgba(128,128,128,34); border-radius:6px; min-height:36px;
    background:transparent; font-size:13px; color:#1A1A1A;
}
QPushButton[seg="true"]:checked { background:#2E4372; border-color:#2E4372; color:#FFFFFF; }
QPushButton[seg="true"]:hover   { }   /* source has no chip hover; segmented uses Opacity 0.85 */
QPushButton[seg="true"]:disabled{ color:rgba(26,26,26,102); border-color:rgba(128,128,128,20); }
```
Use a `QButtonGroup(exclusive=True)` with `setCheckable(True)`. The accent alpha must be recomputed
whenever the accent changes — build the sheet from an f-string over the token dict.
`Opacity 0.85 / 0.4` have no QSS equivalent; either bake the alpha into the colour literals (preferred, it
composites identically over an opaque card) or attach a `QGraphicsOpacityEffect` (avoid — one effect per
widget is expensive and breaks subpixel text AA).

### 4.8 Toggle switch

No Qt built-in matches; subclass `QAbstractButton` and paint:

```python
def paintEvent(self, e):
    p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ACCENT) if self.isChecked() else QColor(128,128,128,34))
    p.drawRoundedRect(QRectF(0, 0, 38, 21), 10.5, 10.5)
    x = 38 - 3 - 15 if self.isChecked() else 3
    p.setBrush(QColor(0xFF, 0xFF, 0xFF))
    p.drawRoundedRect(QRectF(x, 3, 15, 15), 7.5, 7.5)
```
`setFixedSize(38, 21)`. Disabled → paint everything through a 0.4 alpha multiplier (or
`p.setOpacity(0.4)` at the top). **The source has no thumb transition — it snaps.** Adding a 120 ms
`OutCubic` slide is a defensible deviation; note it if you do.

### 4.9 Combobox

`QComboBox` + QSS reaches the §3.10 spec except the popup shadow. Set
`view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)` and
`setAttribute(Qt.WA_TranslucentBackground)` on the popup window, then give the view's container a
`QGraphicsDropShadowEffect(blur=16, offset=(0,2), color=QColor(0,0,0,77))`. The drop-down arrow:
`QComboBox::drop-down { border:none; width:22px; }` plus
`QComboBox::down-arrow { image:none; }` and draw the `U+E70D` glyph as a right-aligned child `QLabel`,
because `image:` needs a resource and this app ships no arrow asset.

### 4.10 Chart

Use one `QWidget` with a `paintEvent`, not `QtCharts` and not `pyqtgraph` — both bring their own axis
spines, tick algorithms, margins and default palettes, and every one of those must then be fought back to
the spec (fixed 0/50/100 ticks, no spines, `{2,3}` dashes, 0.6-opacity 9 px labels).

```python
def paintEvent(self, e):
    p = QPainter(self)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    W, H = self.width(), self.height()
    padL, padR, padT, padB = 30, 16, 18, 16
    pw, ph = max(1, W - padL - padR), max(1, H - padT - padB)
    base = padT + ph

    # 1. area + line first (gridlines draw OVER the fill, matching CB z-order)
    pts = [QPointF(padL + pw * fx, padT + ph * (1 - min(max(v,0),100)/100.0))
           for fx, v in samples]
    line = QPainterPath(pts[0])
    for q in pts[1:]:
        line.lineTo(q)                       # straight segments only, no smoothing
    area = QPainterPath(line)
    area.lineTo(pts[-1].x(), base); area.lineTo(pts[0].x(), base); area.closeSubpath()
    p.fillPath(area, QColor(accent.red(), accent.green(), accent.blue(), 41))   # 0.16
    pen = QPen(accent, 2.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.strokePath(line, pen)

    # 2. gridlines
    gp = QPen(QColor(GRID), 1.0)
    gp.setDashPattern([2, 3])                # Qt dash units are multiples of pen width -> 1:1 with WPF
    p.setPen(gp)
    for pct in (0, 50, 100):
        y = padT + ph * (1 - pct / 100.0) + 0.5      # +0.5 so a 1px line lands on a pixel
        p.drawLine(QPointF(padL, y), QPointF(W - padR, y))
```

**Gotchas.**
- **Half-pixel offset.** With antialiasing on, a 1 px line at an integer coordinate straddles two pixels and
  renders as two half-intensity rows. Add `+0.5` to gridline coordinates (or disable AA for the gridline
  pass only). The 2.5 px series line does not need it.
- **Dash pattern units.** `QPen.setDashPattern` is in multiples of the pen width, and WPF's
  `StrokeDashArray` is too — with width 1 the `{2,3}` and `{4,2}` arrays transfer literally. If you change
  the stroke width, divide the pattern by it.
- **Text opacity.** Do not use `p.setOpacity()` for the 0.6/0.65 axis labels while also drawing shapes;
  set the pen colour's alpha instead (`QColor(0x55,0x55,0x55, int(0.6*255)) == alpha 153`), which keeps
  text antialiasing correct.
- **Y-label box.** `padLeft − 4 = 26` px wide, right-aligned, vertically centred on the gridline
  (WPF used `margin (0, y − 6, 0, 0)` for a 9 px line). In Qt: `p.drawText(QRectF(0, y - 8, 26, 16), Qt.AlignRight | Qt.AlignVCenter, txt)`.
- **devicePixelRatio.** If you cache the plot into a `QPixmap`, create it as
  `QPixmap(int(W*dpr), int(H*dpr))`, then `pm.setDevicePixelRatio(dpr)` where
  `dpr = self.devicePixelRatioF()`, and paint into it in *logical* units. Forgetting
  `setDevicePixelRatio` gives a crisp-but-quarter-sized chart on a 200 % display.
- **Hover.** `self.setMouseTracking(True)`; in `mouseMoveEvent` pick the nearest sample by `|Δx|` only,
  store the anchor, `self.update()`. Draw the 7×7 dot with
  `p.drawEllipse(QPointF(ax, ay), 3.5, 3.5)` and the bare 11 px Medium label at
  `(clamp(ax - 16, 0, W - 60), max(0, ay - 18))`. No box, no crosshair.
- **Wheel-to-zoom.** `def wheelEvent(self, e): self.zoom(1 if e.angleDelta().y() > 0 else -1); e.accept()` —
  and make sure any ancestor `QScrollArea` does not also scroll (accepting the event is enough).

### 4.11 Toast

`QWidget` with the §4.1 flags plus `Qt.WindowType.WindowDoesNotAcceptFocus`. Position after `show()` using
`QGuiApplication.screenAt(QCursor.pos()).availableGeometry()` — Qt's `availableGeometry()` already excludes
the taskbar, so no DPI division is needed (the WPF code divides by `dpiX/dpiY` because `SystemParameters`
returns physical pixels; **do not port that division**). Stack with a module-level counter and
`H + 10` spacing. `QTimer.singleShot(6000, self.close)`. Idle time:
```python
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
```
`GetLastInputInfo` + `GetTickCount` → seconds idle.

### 4.12 Tooltip

If you keep Qt's native tooltip: `QToolTip` respects
`QApplication.setStyleSheet('QToolTip { background:#FAFAFA; color:#1A1A1A; border:none; padding:6px 10px; font-family:"Segoe UI"; font-size:11px; }')`
but **QToolTip ignores `border-radius` on Windows** (it is a native-shaped window). For the rounded look
you must build a frameless `QWidget` tooltip yourself, using §4.1's structure.

### 4.13 Theme switching

Keep a single `TOKENS: dict[str, str]` per theme and rebuild the app stylesheet on change:
`app.setStyleSheet(build_qss(tokens))`. Custom-painted widgets read the dict directly in `paintEvent`;
call `w.update()` on all of them. Mirror the source's single fan-out point
(`TrayOrchestrator.ApplyTheme`, `:426-438`): theme → accent → per-window push → repaint, one function,
called from both the settings preview and the real save.

---

## 5. WHAT TO DEVIATE ON

A literal port of a 340 px tray popup into an always-on-top GPU/VRAM/CPU monitor is wrong in eight specific
places. Each item below states the original value, why it breaks, and the recommended adaptation.

**1. Fixed 288 px content column → resizable width.**
Original: `SingleColumnWidth = 288`, window locked at 340, `ResizeMode = NoResize`, size recomputed from
`DesiredSize` (`PW.cs:17, 1298-1307`). A monitor lives on screen for hours and users will want it narrow
(a strip) or wide (with the chart). **Adapt:** make the card width user-resizable with
`min-width 220, preferred 300, max 560`; let the meter stretch (`QSizePolicy.Expanding`) and keep the
label/value row as `[stretch][hug]`. Keep the 20 px padding and 9 px bar height fixed — those carry the
look; the width does not.

**2. The 500 ms staggered fill cascade → entry only, never on refresh.**
Original: every render animates each bar `0 → target`, 80 ms apart (`PW.cs:1322-1343`), with a
"same value" guard. That guard exists because the popup renders on demand; a monitor renders **every
second**, so a literal port would either re-cascade constantly (nauseating) or be suppressed by the guard
for every unchanged value and jump for every changed one. **Adapt:** run the 500 ms/80 ms cascade **once**,
on first paint. Afterwards drive the bar with a short **150 ms `OutCubic` tween from the previous value to
the new one**, and skip the tween entirely when `|Δ| < 1 %` or when the poll interval is < 250 ms.
Keep `AnimationsEnabled = false` as a real setting (`AS:37`) that hard-disables all of it.

**3. Bottom-anchored, grow-upward window animation → drop it.**
Original: on content growth the window animates `Width`/`Height`/`Top` over 220 ms with the bottom edge
pinned to `_maxBottom` (`PW.cs:1191-1211`) because it opens from the taskbar. A free-floating monitor has no
such anchor, and an animated `setGeometry` on an always-on-top translucent window causes visible tearing and
fights the user's drag. **Adapt:** resize instantly (the source itself does exactly this for style changes,
`PW.cs:1226-1246`, and documents why). Anchor from whichever corner is nearest the current screen edge.

**4. 0 % renders a bare track → give it a floor.**
Original: `Width = 0` at 0 %, no minimum (`PW.cs:726`) — visible in the capture's Grok row. For a *quota*
that is honest. For a *live* metric, an idle GPU at 0–2 % becomes indistinguishable from "no data" and the
meter looks broken. **Adapt:** clamp the fill to `max(3.0, w)` px whenever the widget has a valid reading,
and reserve genuinely-zero-width for a "no signal" state (which should instead show the track at 50 % alpha
plus an em-dash where the value goes, reusing the compact-mode `"—"` convention, `PW.cs:569`).

**5. The green/amber/red ramp inverts meaning for a hardware monitor.**
Original semantics: percent = *quota consumed*, so red at ≥ 85 % means "you are nearly out" (`CB:623-635`).
For GPU utilisation, 95 % is *good* — it is the load you paid for. Red there trains the user to ignore red.
**Adapt, per metric:**
- **VRAM used %** and **CPU/GPU temperature**: keep the ramp exactly as specified — running out of VRAM is
  the same failure shape as running out of quota.
- **GPU / CPU utilisation**: use the **flat accent** path instead (`FlatGradient`, `PW.cs:935-943`:
  `lighter = min(255, ch + 40)` → base). This code path already exists in the design; you are choosing it
  per-metric rather than globally. Reserve the red band only for a genuine alarm you define
  (e.g. thermal throttle), and when it fires, use `#EE8484 → #CE3D3D` unchanged so the alarm colour is
  consistent with the rest of the family.
Document the per-metric choice in the UI (a legend or the metric label), otherwise two bars of different
colour at the same percentage read as a bug.

**6. Chart Y axis hardcoded to 0/50/100 → keep for %, break for the rest.**
Original: `foreach (var pct in new[] { 0, 50, 100 })`, scale always 0–100 (`CB:93`). Correct for
utilisation and VRAM-%. Wrong for absolute VRAM (GB), temperature (°C), clocks (MHz), power (W).
**Adapt:** keep the three-gridline rhythm — it is a strong part of the look — but compute the ticks as
`0 / max/2 / max` with `max` snapped to a nice number (1/2/5×10ⁿ) and held for at least 30 s of hysteresis
so the axis does not twitch. Keep the label format at 9 px / 0.65 opacity / 26 px right-aligned box, and
keep the 3-tick count fixed. Never add a fourth gridline; the density is the design.

**7. Per-hour bucketing and hour/day/week tick strategy → sub-minute.**
Original x-tick ladder starts at 1 hour and the second series buckets to the local clock hour
(`CB:136-140, 484-493`), because usage quotas move over days. A hardware monitor's window is 60 s to 10 min.
**Adapt:** replace the ladder with `≤ 2 min → 15 s ticks "mm:ss"`, `≤ 20 min → 1 min "HH:mm"`,
`≤ 3 h → 15 min "HH:mm"`, else fall back to the original hour/day rungs. Keep `minLabelSpacing = 32` px and
the `x ≤ width − padRight − 16` suppression rule verbatim — they are what stop the axis crowding.
Drop the bucketing entirely and plot raw samples; with a ring buffer capped at
`plotWidth` samples the polyline never exceeds one point per pixel.

**8. Chrome that is invisible at rest → make one affordance permanent.**
Original: close is `Visibility.Hidden` unless pinned and the pin sits at 0.45 opacity (`PW.cs:418-419, 450`).
(The reference capture shows an *empty* top-right corner, but that capture predates Pin/Compact/Stats — see
the note in §1; the live build renders all three, and Compact is deliberately full-contrast `text.primary`,
`PW.cs:404-408`. So only Close is genuinely hidden.) Acceptable for a popup
that dies when you move the mouse away; hostile for a window that never closes itself. **Adapt:** keep the
26 px circle / `#14808080`-on-hover recipe unchanged, but render the button row at **`opacity 0.35` at rest,
1.0 on card hover, with a 120 ms fade** — and keep the close button permanently mounted (using
`setRetainSizeWhenHidden(True)` so nothing shifts). Keep the whole-card drag handle (`PW.cs:475-499`); it is
the single best interaction in the original and costs nothing.

**Two further small adaptations, lower stakes:**

- **Compact mode's 0.75 `LayoutTransform`** (`PW.cs:196-200`) scales *whole widget trees*, which Qt does not
  do cleanly (`QGraphicsView` or `QTransform` on a proxy widget both cost more than they are worth).
  Reimplement compact mode as a **second token set** — padding 20→6, icon 18→10.5, title 14 Medium→12
  Normal, block gap 18→8, footer glyphs 14→10.5 — applied by swapping the stylesheet and calling
  `setFixedHeight`/`setContentsMargins`. Same numbers, no transform.
- **The blur/acrylic mode** (`AccentState = 4`, tint alpha `235 − pct/100 × 185`) is a legacy undocumented
  API that Microsoft has degraded twice and that costs real GPU time on a permanently-visible window.
  Ship **Standard mode only** for the monitor, and expose the existing `PopupOpacityPercent` 1–100 slider
  (`AS:40`) as the single transparency control — it maps directly to the card fill's alpha
  (`clamp(round(pct/100 × 255), 0, 255)`, `PW.cs:346-347`) and needs no OS call at all.

---

## Verification

Adversarial audit of this document against `ClaudeUsageTray.Wpf` and `docs/captura.png`. Every literal
below was grepped in the tree; nothing was accepted on the strength of the prose.

### Checked and CONFIRMED correct (sample, ~70 literals)

- **Surfaces / text**: `#FAFAFA` / `#2B2B2E` (`PW.cs:312`, `SC:605-606`, `TW.xaml.cs:31-32`,
  `TMW.xaml.cs:51-52`), `#1A1A1A` / `#F2F2F2`, `#555555` / `#B8B8B8`, blur-mode pure black/white override
  (`PW.cs:379-385`), `#E2E2E2` / `#454548` (`SC:617-618`) and its reuse as the dashboard card fill
  (`SC:662`), `#E6E6EF` / `#4C4C56` (`SC:625-626`), `#8B5CF6` (`SC:639`, single value both themes),
  `#2E8B57` / white success (`SWc:52`), scroll-fade `#00000000`→`#26000000` (`SWx:350-351`).
- **Fixed alphas**: meter track `#26808080` (`PW.cs:712`, `PW.cs:813`) and hover `#14808080`
  (`PW.xaml:74,100,124,181`, `SX:36`, `AboutWindow.xaml:28`, `TMW.xaml.cs:19`) really are theme-independent.
- **Accent**: `#2E4372` / `#7C97E0` (`TH:11,18`), all 11 swatches verbatim (`TH:20-24`), the `IdealForeground`
  linearisation and the `> 0.4` threshold (`TH:89-110`), the Original chip gradient
  `#2E8B57 → #D4A017 @0.55 → #D64545`, diagonal (`SWc:482-490`).
- **Meter ramp**: `#72D08F→#3F9E63` / `#F3C36A→#D99420` / `#EE8484→#CE3D3D` at `<60 / <85 / else`
  (`CB:627-629`), gradient axis `(0,0)→(1,0)`, flat-accent `+40` per channel (`PW.cs:938-942`).
- **Geometry**: bar height 9 / radius 4.5 / top margin 6 (`PW.cs:706-711`), loading bar 4 / radius 2
  (`PW.cs:808-817`), `SingleColumnWidth = 288` (`PW.cs:17`), compact 190 → bar 138 (`PW.cs:64,583-585`),
  `ChromeReserve = 6` → 340 / 214 px windows (`PW.cs:1262,1298-1307`), card padding 20 / compact 6
  (`PW.cs:185`), block gaps 18 / 14 / 12 / 5 / 4 (`PW.cs:616,663,618,689,654`), radius 16 (`PW.xaml:29`),
  26×26 chrome at radius 13 with margins 8 / 40 / 72 / 104 (`PW.xaml:59-153`), 30×30 footer buttons
  (`PW.cs:923-924`).
- **Shadows**: 10/2/270/0.22 popup, 20/5 toast, 22/6 menu, 24/6/0.28 dialog+about, 16/2/0.3 date popup.
- **Motion**: 500 ms + 80 ms cascade OutCubic (`PW.cs:1334-1341`), 180 / 220 / 400 / 400 / 800 / 1100 ms
  (`PW.cs:274,1206,833,1125,294,866`), 150 ms Stats debounce (`SC:131`), 200 ms hover poll
  (`TrayOrchestrator.cs:40,93`).
- **Chart**: pads 18/16/30/16 (`CB:75`), fixed `[0,50,100]` ticks (`CB:93`), dash `{2,3}` and `{4,2}`,
  stroke 2.5 / 1.75, area alpha 0.16, Y label box `padLeft−4 = 26` at 0.65, X at 0.6, start-date 0.55,
  `minLabelSpacing = 32` and the `x ≤ width−padRight−16` suppression (`CB:142,164`), hover dot 7 px and
  7 px reset tolerance (`CB:379-402`), label offsets `clamp(x−16, 0, w−60)` / `max(0, y−18)` (`CB:440`),
  bar `clamp(plotWidth/n × 0.6, 2, 10)` and `max(1.5, 22 × …)` (`CB:313,335,340`), legend dot 8 px /
  faded 0.35 (`CB:597,611`), zoom `[1.0, 4.0]` step `0.25` (`SC:41-43,151`), `MinChartHeight = 90` (`SC:21`).
- **DWM / composition**: `20`, `33`, `DONOTROUND = 1`, `ROUND = 2` (`DH:8-11`), `AccentState 4` /
  `Disabled 0` (`DH:73-74`), `WCA_ACCENT_POLICY = 19` (`DH:88`), and the **ABGR** packing
  `(a<<24)|(B<<16)|(G<<8)|R` (`DH:121`).
- **Settings keys** (all real, all with the stated defaults): `AccentColor` = `"ORIGINAL"` (`AS:36,54`),
  `AnimationsEnabled = true` (`AS:37`), `PopupWindowStyleMode = Standard` (`AS:38`),
  `PopupOpacityPercent = 100` (`AS:40`), `PopupBlurPercent = 45` (`AS:42`), `HoverDelaySeconds` (`AS:33`),
  `PopupCompactMode` / `CompactShow*` (`AS:48-52`). Tint alpha `clamp(235 − pct/100 × 185, 50, 235)` → 151
  at 45 % (`PW.cs:328`).
- **captura.png**: every element in it is specified — card + shadow, 18 px service icons (Claude/Grok PNG,
  ChatGPT tinted vector, `SI:28-43`), 12 px label / 12 px right-flush percent, 9 px bar, 11 px reset
  caption, the 12 px "Créditos usados" extra line, the 11 px footer text and exactly two ghost buttons,
  and Grok's genuinely zero-width 0 % fill. No component visible in the capture is missing from the spec.

### CORRECTED in place

1. **§3.7A codepoints — invented.** "about `U+E946`, exit `U+E7E8`" appear **nowhere** in the tree. The
   footer defines two glyphs only (`PW.cs:18-19`) and builds two buttons (`PW.cs:889-895`). Replaced with
   the real full MDL2 inventory: `E711`, `E713`, `E72C`, `E8BB`, `E922`, `E923`.
2. **§2.2 — "12 accent values" → 13.** 11 swatches + both Original variants; `TH:105-108` says exactly that.
3. **§2.8 — wrong citation for the stale gutter comment.** `DH:23-34` is `DisableRoundedCorners`' doc
   comment and never mentions 18 px. The stale 18s live at `PW.cs:334, 358, 1269, 1280`.
4. **§2.8 — date-picker shadow direction.** `SC:487` sets no `Direction`, so it is WPF's default **315°**,
   not the 270° every other shadow uses. Spec said "(default)" without saying what that is.
5. **§2.9 — Toast duration cited the wrong line.** `TW.xaml.cs:17` is `IdleThresholdSeconds = 30`;
   `VisibleSeconds = 6` is line 18.
6. **§3.6 / §3.3 — string template invented.** The resource is `"Actualizado {0}"` / `"Updated {0}"`
   (`Strings.cs:94,281`); "hace"/"ago" comes from `TimeFormat.Ago` (`TimeFormat.cs:99-107`).
7. **§3.11 / §3.7B — "no focus rings anywhere, globally (`SWx:19-21`)" over-claimed.** That entry is a
   *keyed* `{x:Type Control}` style; WPF implicit lookup keys on the concrete type, so it applies to
   nothing. Each Settings style sets `FocusVisualStyle` itself; PopupWindow's four chrome buttons and its
   `MaterialDesignFlatButton` footer buttons never do.
8. **§3.12 — native-tooltip inventory undercounted.** ToolTips exist on all four popup chrome buttons
   (`PW.cs:175-178`), both footer buttons, and the Stats maximize button.
9. **§2.5 — opacity token list incomplete and one row conflated.** Added `0.8`, `0.75`, `0.65`, `0.55`
   (About), `0.5`, with per-value citations. Split the "caption buttons (Stats/About/**Settings**)" row:
   Settings' is a different control (see 12 below). Added About/Dialog's 12.5 px and 11.5 px Consolas rows.
10. **§1 — glyph size range.** "10–14 px" → **10–20 px** (16 px settings card header, 20 px spinner exist).
11. **§1 / §5.8 — the capture is stale, not evidence of intent.** `captura.png` shows an empty top-right
    corner, but Pin/Compact/Stats are unconditionally mounted (`PW.xaml:59-186`) and Compact is
    deliberately painted in `text.primary` *because* secondary gray "was too low-contrast"
    (`PW.cs:404-408`). Only Close is genuinely hidden at rest. Both passages rewritten.
12. **Missing components added** as §3.16–§3.19: **slider** (`FlatSlider`, 24 tall / 4 px track radius 2 /
    10×20 thumb radius 3, `SWx:232-288`), **colour swatch** (28 px disc + −4 margin 2 px ring,
    `SWx:290-312`), **Settings/Dialog caption button** (42×40, **square**, hover = divider — a third icon
    recipe the spec had folded into §3.7B's 26 px circle, `SWx:129-152`), and the **calendar heat cell**
    with its `clamp(0.14 + intensity × 0.66, 0.14, 0.8)` accent ramp, `1.5 px` accent "today" outline and
    `MinHeight 54` (`SC:832-880`) — a real continuous alpha scale and a real outline, both of which §2.1's
    "no outline anywhere" framing had silently excluded.
13. **§2.6 spacing table** — `4` cited a non-existent "slider top gap" (the slider's 4 is a *track height*,
    its margins are 10 and 2); replaced with the segmented-button inner margin (`SWc:530`) and the
    date-popup padding (`SC:486`). `16` cited `PW.cs:772` (a `Foreground` line) instead of `PW.cs:763`.
    Extra real uses of `10` and `16` added.
14. **§2.7 radii** — added `bellToggle 15`, `aiBadge 10`, `aboutPathBox 6`, and `captionButton 0 (square)`.
15. **§2.1** — qualified `divider.line`: `#22808080` is a tray-menu-only literal, while every other divider
    is the theme-conditional MDIX resource. Split `shadow.color` from `shadow.opacity` (0.22 / 0.28 / 0.30).

### Theme-conditional audit

Checked every token the spec reports as a single value. `meter.track`, `overlay.hover`, the 11 accent
swatches, the Original-chip gradient, the meter ramp, `#8B5CF6`, the switch thumb `#FFFFFF`, the segmented
selected foreground `#FFFFFF`, and `shadow.color` `#000000` are all genuinely theme-independent in source —
the spec is right on each. The one real conflation was `divider.line` (fixed, item 15): the app's actual
divider in every window except the tray menu is `MaterialDesignDivider`, which *is* theme-conditional; the
spec's `#22808080` is a port substitute, not the shipped value in either theme.

### Remaining uncertain / not verifiable

- **MDIX 5.3.2 literals** (§2.4) stay unresolved — the package is not vendored. The substitute column is
  still an authored approximation, not extracted. `MaterialDesignDivider` in particular is used for real
  1 px borders where a flat `#22808080` will read differently in dark mode than the library value.
- **`Segoe UI` as the inherited default** is a Windows platform fact, not a literal in this tree; only
  `Segoe MDL2 Assets` and `Consolas` are written down.
- **Pressed states** genuinely do not exist for any control — the spec's "not defined" is accurate, but it
  means the port has to invent them.
- **Line citations drift by ±1–2** in a handful of places (mostly `SC:` and `SWc:` rows pointing at the
  `{` or the property one line either side of the value). Spot-checked ~40; all landed inside the right
  construct. Not exhaustively renumbered — treat citations as "this member of this object", not as exact.
- **`AboutWindow.xaml.cs` changelog rendering** (`Opacity 0.8` at `:55`) and `IconFactory` (the generated
  tray/app icon) are not covered by any section; neither affects the popup port.
