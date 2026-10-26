# Desktop Clock widget

A frameless, transparent digital clock that lives **on your Windows desktop** — behind
your windows, above your wallpaper, with no title bar and no taskbar button.

![The clock on a wallpaper](assets/preview_1280.png)

```
   MONDAY, 26 OCTOBER
   HOURS   MINUTES   SECONDS
    10  :   24   :     37
   LOS ANGELES   NEW YORK   LONDON   PARIS   KYIV
     21:24        00:24     05:24   06:24   07:24
```

Pure Python + Tkinter: no third-party runtime dependencies, no admin rights, no installer.
Single `.exe`, ~12 MB.

**New in v1.3** — **Orbitron is now the default typeface**, and picking a typeface
(or a size) in *Settings…* and pressing **Apply** changes the clock immediately.
In v1.2 the choice was saved but the clock kept its startup font until you
restarted it; that is fixed. Existing installs that never picked a typeface
switch to Orbitron automatically on first run — if you chose one yourself, your
choice is kept. Right-click → *Settings…* still opens the settings window (no
JSON editing) with a live preview and **ten bundled "cargo industrial"
typefaces** that travel inside the exe.

![The settings window](assets/settings.png)

---

## Get the EXE

**Option A — download the prebuilt binary**

1. Grab `DesktopClock.exe` from the [latest release](../../releases/latest) — direct link:
   [`releases/latest/download/DesktopClock.exe`](../../releases/latest/download/DesktopClock.exe).
2. Or open the [Actions tab](../../actions/workflows/build-windows-exe.yml), pick the newest
   green *Build Windows EXE* run and download the **DesktopClock-windows-x64** artifact.
3. Put `DesktopClock.exe` anywhere you like and double-click it.

The build runs on `windows-latest` with PyInstaller, so the file is a genuine
Windows executable (no console window).

**Option B — build it yourself**

```bat
build_exe.bat
```

Needs Python 3.9+ from python.org (the Microsoft Store build cannot be used with
PyInstaller). The script creates a venv, installs PyInstaller, and writes
`dist\DesktopClock.exe`.

---

## Using it

| Action | What happens |
| --- | --- |
| **Left-drag** anywhere on the clock | move it (position is remembered) |
| **Right-click** | menu: *Settings…*, reload, seconds on/off, 24-hour clock, world clocks, stay-on-desktop, close |
| `Esc`-free | there is no title bar, so close from the right-click menu |

The clock is pinned just above the wallpaper, so `Win + D` / *Show desktop* will not
hide it, and a full-screen window will cover it — it behaves like part of the wallpaper.

**Autostart with Windows:** `Win + R` → `shell:startup` → put a shortcut to
`DesktopClock.exe` in that folder.

---

## Settings

Right-click the clock → **Settings…**

Two tabs, everything previews live, **Apply** saves:

* **TYPE** — a miniature of the clock that re-renders the moment you click a
  typeface, plus a card list where every row is drawn in its own font.
  Tick *Show every font installed on this PC* to use any system font instead.
* **LAYOUT** — pixel sizes for digits / captions / date / world clocks, show-hide
  toggles, six colour presets, a free-form date pattern and a one-click
  *Restore default look*.

Esc closes the window, `config.json` is one click away in the footer.

### Bundled typefaces

These ship inside `assets/fonts` (and inside the exe). They are registered
*privately* for the process with `AddFontResourceExW(FR_PRIVATE)` — nothing is
installed into the Windows font folder, no admin rights, and they disappear when
the clock exits. All ten are licensed under the
[SIL Open Font License](assets/fonts/LICENSES.txt).

| Typeface | Character |
| --- | --- |
| **Orbitron** *(default)* | sci-fi wide instrument panel |
| Chakra Petch | squared techno |
| Rajdhani | condensed tech, shipping manifest |
| Big Shoulders Display | tall cargo stencil |
| Barlow Condensed | industrial signage |
| Teko | very condensed LED board |
| Quantico | military squared |
| Oxanium | machined techno |
| Share Tech Mono | terminal / CRT |
| JetBrains Mono | clean coding monospace |

### config.json (optional)

Everything is mirrored to one JSON file, created on first run:

```
%APPDATA%\DesktopClock\config.json
```

Edit it and pick *Reload settings* — nothing needs recompiling.

| Key | Default | Meaning |
| --- | --- | --- |
| `font_family` | `"Orbitron"` | a bundled family or any installed font |
| `config_version` | `2` | internal — migrates changed defaults between releases; leave it alone |
| `digit_size` | `150` | height of the big digits in pixels (DPI-independent) |
| `caption_size` / `world_size` / `date_size` | `13` / `20` / `16` | text sizes |
| `gap` | `10` | vertical space between rows |
| `text_color` | `"#FFFFFF"` | use `"#000000"` on a light wallpaper |
| `caption_color` / `date_color` | `"#9C9C9C"` / `"#B4B4B4"` | label colours |
| `transparent_color` | `"#010101"` | chroma-key colour, becomes invisible — never use it for text |
| `show_captions` | `true` | the *hours / minutes / seconds* row |
| `show_seconds` | `true` | show the seconds block |
| `show_date` | `true` | date line above the clock |
| `date_format` | `"%A, %d %B"` | any `strftime` pattern, `""` hides it |
| `show_world_clocks` | `true` | the city row |
| `world_clocks` | 5 cities | `[["Label", "IANA/Timezone"], ...]` — see the [tz database list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) |
| `clock_24h` | `true` | `false` for AM/PM style hours |
| `keep_on_desktop` | `true` | `false` = a normal window floating above other windows |
| `behind_icons` | `false` | `true` = sink *under* the desktop icons (they overlap the clock) |
| `position` | `null` | `[x, y]`, maintained automatically |

Example — big black Cargo clock for a light wallpaper, one world clock:

```json
{
  "font_family": "Teko",
  "text_color": "#FF6A13",
  "caption_color": "#A9500F",
  "date_color": "#D07B36",
  "digit_size": 220,
  "world_clocks": [["Tokyo", "Asia/Tokyo"]]
}
```

---

## How it works

* `overrideredirect(True)` removes the frame; `-transparentcolor #010101` makes that exact
  shade fully see-through, so only the glyphs remain.
* The window is pushed to the **bottom of the top-level z-order** (`HWND_BOTTOM`), so it
  sits above the wallpaper and under every normal window, and it is re-asserted every ~3 s
  (and after each drag) because Explorer and window activation keep rearranging things.
  Setting `behind_icons: true` instead re-parents it onto the **WorkerW** window, i.e.
  underneath the desktop icons.
* It also carries `WS_EX_TOOLWINDOW`, so it never appears in the taskbar or Alt+Tab.
* Redraws are aligned to the next second boundary instead of a fixed 200 ms timer, so the
  seconds change exactly when your system clock does.
* `zoneinfo` + the bundled `tzdata` package means world clocks work on Windows, which
  ships without an IANA timezone database.
* Bundled fonts are registered per-process *before* the first Tk window exists, because
  Tk snapshots its font table when the root window is created.

## Files

```
clock_widget.py                        the whole app (~1300 lines)
build_exe.bat                          local one-click build
requirements.txt                       tzdata (bundled into the exe)
.github/workflows/build-windows-exe.yml  UI test + builds/uploads the exe
assets/icon.ico, assets/icon.png       app icon
assets/fonts/*.ttf                     ten bundled OFL typefaces + LICENSES.txt
.github/scripts/ui_smoke_test.py       Windows UI test (screenshots in CI)
```

## Notes / limitations

* Windows only for the desktop-pinning and transparency tricks; on Linux/macOS the
  window still runs, but without chroma-key transparency.
* If *Show desktop icons* is off, Explorer may not create the WorkerW window; the app then
  falls back to bottom-of-z-order placement (still visible, still covered by windows).
* If the app ever fails to start, a dialog appears and the full traceback is written to
  `%APPDATA%\DesktopClock\error.log` — attach that file to an issue.
* Tray icon: not included — the widget is meant to be forgotten about. Close it from the
  right-click menu.
