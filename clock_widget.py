#!/usr/bin/env python3
"""Desktop Clock - a borderless, transparent clock that lives on your desktop.

Highlights
----------
* Frameless, no taskbar entry, no Alt+Tab entry.
* Pinned to the desktop layer so "Show desktop" (Win+D) does not hide it.
* Drag anywhere with the left mouse button; the position is remembered.
* Right-click for a small menu: Settings, seconds, world clocks, close.
* A built-in settings window (no JSON editing needed) with a live preview and
  eleven bundled, license-free "cargo industrial" typefaces - they travel
  inside the exe, so every machine renders the clock identically.
* Optional plain-JSON escape hatch: %APPDATA%\\DesktopClock\\config.json
* Runs on Windows without admin rights and needs no third-party packages.

Tested with Python 3.9+ (uses zoneinfo, so 3.9 or newer is required).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from zoneinfo import ZoneInfo

__version__ = "1.2.0"

APP_NAME = "DesktopClock"
IS_WINDOWS = sys.platform.startswith("win")

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    # --- look ------------------------------------------------------------- #
    "font_family": "Chakra Petch",      # any installed font or a bundled one
    "digit_size": 150,                  # height of the big digits, in pixels
    "caption_size": 13,                 # "hours / minutes / seconds" labels
    "world_size": 20,                   # world clock time size
    "date_size": 16,                    # date line size
    "gap": 10,                          # space between block rows (pixels)
    "text_color": "#FFFFFF",            # use "#000000" on a light wallpaper
    "caption_color": "#9C9C9C",
    "date_color": "#B4B4B4",
    "transparent_color": "#010101",     # becomes invisible - don't use for text
    # --- content ---------------------------------------------------------- #
    "show_captions": True,
    "show_seconds": True,
    "show_world_clocks": True,
    "show_date": True,
    "date_format": "%A, %d %B",         # strftime; "" hides the line
    "world_clocks": [
        ["Los Angeles", "America/Los_Angeles"],
        ["New York", "America/New_York"],
        ["London", "Europe/London"],
        ["Paris", "Europe/Paris"],
        ["Kyiv", "Europe/Kyiv"],
    ],
    # --- behaviour -------------------------------------------------------- #
    "keep_on_desktop": True,            # False = normal window floating on top
    "behind_icons": False,              # True = sink under the desktop icons
    "clock_24h": True,                  # False = 12-hour clock
    "position": None,                   # [x, y] - written automatically
}

CONFIG_DIR = Path(
    os.environ.get("APPDATA")
    or os.environ.get("XDG_CONFIG_HOME")
    or Path.home() / ".config"
) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"

FONT_FALLBACKS = [
    "Consolas", "Cascadia Mono", "Cascadia Code", "JetBrains Mono",
    "Fira Code", "Lucida Console", "DejaVu Sans Mono", "Courier New",
    "Courier", "Helvetica",
]

# --------------------------------------------------------------------------- #
# Bundled typefaces - "cargo industrial": squared, condensed, stencil-ish.
# The .ttf files ship in assets/fonts and are licensed under the SIL Open Font
# License (see assets/fonts/LICENSES.txt).  On Windows they are registered for
# this process only, so nothing is installed into the system font folder.
# --------------------------------------------------------------------------- #
BUNDLED_FONTS = [
    {
        "family": "Chakra Petch",
        "blurb": "Squared techno · the default",
        "files": ["ChakraPetch-Regular.ttf", "ChakraPetch-Bold.ttf"],
    },
    {
        "family": "Rajdhani",
        "blurb": "Condensed tech · shipping manifest",
        "files": ["Rajdhani-Regular.ttf", "Rajdhani-Bold.ttf"],
    },
    {
        "family": "Big Shoulders Display",
        "blurb": "Tall cargo stencil",
        "files": ["BigShouldersDisplay-Regular.ttf",
                  "BigShouldersDisplay-Bold.ttf"],
    },
    {
        "family": "Barlow Condensed",
        "blurb": "Industrial signage",
        "files": ["BarlowCondensed-Regular.ttf", "BarlowCondensed-Bold.ttf"],
    },
    {
        "family": "Teko",
        "blurb": "Very condensed · LED board",
        "files": ["Teko-Regular.ttf", "Teko-Bold.ttf"],
    },
    {
        "family": "Orbitron",
        "blurb": "Sci-fi wide · instrument panel",
        "files": ["Orbitron-Regular.ttf", "Orbitron-Bold.ttf"],
    },
    {
        "family": "Quantico",
        "blurb": "Military squared",
        "files": ["Quantico-Regular.ttf", "Quantico-Bold.ttf"],
    },
    {
        "family": "Oxanium",
        "blurb": "Machined techno",
        "files": ["Oxanium-Regular.ttf", "Oxanium-Bold.ttf"],
    },
    {
        "family": "Share Tech Mono",
        "blurb": "Terminal / CRT",
        "files": ["ShareTechMono-Regular.ttf"],
    },
    {
        "family": "JetBrains Mono",
        "blurb": "Clean coding monospace",
        "files": ["JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"],
    },
]

# Colour presets for the settings window: (label, text, captions, date)
COLOR_PRESETS = [
    ("Bone", "#EDE6D6", "#8C8578", "#B7AE9C"),
    ("White", "#FFFFFF", "#9C9C9C", "#B4B4B4"),
    ("Cargo", "#FF6A13", "#A9500F", "#D07B36"),
    ("Amber", "#FFB000", "#B07600", "#C89A3C"),
    ("Phosphor", "#6BFF8E", "#33A852", "#62C97C"),
    ("Ice", "#9FD8FF", "#5E8CA6", "#9BBFD4"),
]

FR_PRIVATE = 0x10

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _gdi32.AddFontResourceExW.argtypes = [
        wintypes.LPCWSTR, wintypes.UINT, wintypes.LPVOID]
    _gdi32.AddFontResourceExW.restype = ctypes.c_int
else:
    _gdi32 = None

_loaded_font_files: list[str] = []


def load_bundled_fonts() -> list[str]:
    """Make the fonts in assets/fonts usable by this process.

    Must run before the first Tk window is created: Tk caches its font list
    when the root window is built.  AddFontResourceExW(FR_PRIVATE) makes the
    fonts visible to this process only - no admin rights, no system install,
    and the fonts disappear again when the clock exits.
    """
    folder = resource_path("assets/fonts")
    if not folder.is_dir():
        return []
    loaded = []
    for ttf in sorted(folder.glob("*.ttf")):
        try:
            if _gdi32 is not None:
                if _gdi32.AddFontResourceExW(str(ttf), FR_PRIVATE, 0):
                    _loaded_font_files.append(str(ttf))
            # other platforms: the system must know the family already
            loaded.append(ttf.stem)
        except Exception:
            continue
    return loaded


def bundled_family_names() -> list[str]:
    return [font["family"] for font in BUNDLED_FONTS]

# --------------------------------------------------------------------------- #
# Win32 helpers (all no-ops on other platforms)
# --------------------------------------------------------------------------- #
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400
HWND_NOTOPMOST = -2
HWND_BOTTOM = 1
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
WM_SPAWN_WORKER = 0x052C

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.argtypes = [
        wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    _user32.SetWindowLongW.restype = wintypes.LONG
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL


def resource_path(relative: str) -> Path:
    """Path to a bundled file, both from source and from a PyInstaller exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def apply_window_icon(root: tk.Tk) -> None:
    ico = resource_path("assets/icon.ico")
    try:
        if IS_WINDOWS and ico.exists():
            root.iconbitmap(default=str(ico))
    except tk.TclError:
        pass
    try:
        png = resource_path("assets/icon.png")
        if png.exists():
            root._icon_image = tk.PhotoImage(master=root, file=str(png))  # keep ref
            root.iconphoto(True, root._icon_image)
    except tk.TclError:
        pass


def enable_dpi_awareness() -> None:
    """Make pixel sizes real pixels on scaled (125 %, 150 %, ...) displays."""
    if not IS_WINDOWS:
        return
    for call in (
        lambda: ctypes.WinDLL("shcore").SetProcessDpiAwareness(2),  # per-monitor
        lambda: ctypes.windll.user32.SetProcessDPIAware(),          # system-wide
    ):
        try:
            call()
            return
        except Exception:
            continue


def _wallpaper_worker() -> int | None:
    """Return the WorkerW window that sits behind the desktop icons."""
    progman = _user32.FindWindowW("Progman", None)
    if progman:
        _user32.SendMessageTimeoutW(
            progman, WM_SPAWN_WORKER, 0, 0, 0, 1000, ctypes.byref(ctypes.c_size_t()))
    found = []

    def _callback(hwnd, _lparam):
        if _user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            sibling = _user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if sibling:
                found.append(sibling)
            return False        # stop enumerating
        return True

    _user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    return found[0] if found else None


class DesktopLayer:
    """Keeps the Tk window glued to the desktop instead of floating on top."""

    def __init__(self, root: tk.Tk, behind_icons: bool = False):
        self.root = root
        self.behind_icons = behind_icons
        self.enabled = False
        self.hwnd = None
        self.parent = None
        if not IS_WINDOWS:
            return
        try:
            root.update_idletasks()
            self.hwnd = _user32.GetParent(root.winfo_id()) or root.winfo_id()
            # a real handle of our own, independent of later reparenting
            ex = _user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            # tool window -> no taskbar button and no Alt+Tab entry
            _user32.SetWindowLongW(
                self.hwnd, GWL_EXSTYLE,
                (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        except Exception:
            self.hwnd = None

    # -- public ---------------------------------------------------------- #
    def apply(self, enabled: bool) -> None:
        self.enabled = enabled and self.hwnd is not None
        if not IS_WINDOWS or self.hwnd is None:
            return
        try:
            if self.enabled:
                self._pin()
            else:
                self._unpin()
        except Exception:
            pass

    def keep(self) -> None:
        """Cheap periodic re-assert; Explorer likes to reset the z-order."""
        if not self.enabled:
            return
        try:
            if self.parent and not _user32.IsWindow(self.parent):
                self.parent = None          # Explorer restarted: re-parent
            self._pin()
        except Exception:
            pass

    # -- internals ------------------------------------------------------- #
    def _pin(self) -> None:
        if self.behind_icons:
            worker = _wallpaper_worker()
            if worker and self.parent != worker:
                _user32.SetParent(self.hwnd, worker)
                self.parent = worker
            if self.parent:
                return
        # Bottom of the top-level z-order: above the wallpaper, below every
        # normal window. Inserting *after* Progman would hide us behind the
        # desktop, which is why HWND_BOTTOM is used instead.
        _user32.SetWindowPos(
            self.hwnd, HWND_BOTTOM, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING)

    def _unpin(self) -> None:
        if self.parent:
            _user32.SetParent(self.hwnd, None)
            self.parent = None
        _user32.SetWindowPos(
            self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


# --------------------------------------------------------------------------- #
# Config handling
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
    except (OSError, ValueError) as exc:
        print(f"{APP_NAME}: could not read config ({exc}); using defaults",
              file=sys.stderr)
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"{APP_NAME}: could not save config ({exc})", file=sys.stderr)


def pick_font_family(requested: str, available: set[str]) -> str:
    lowered = {name.lower(): name for name in available}
    for candidate in [requested, *FONT_FALLBACKS]:
        if candidate and candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return "Courier"


# --------------------------------------------------------------------------- #
# Widget
# --------------------------------------------------------------------------- #
class ClockWidget:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root = root
        self.cfg = cfg
        self.tick = 0
        self._drag = None
        self._offset = [0, 0]              # position tracked ourselves (see drag)

        self.bg = cfg["transparent_color"]
        root.configure(bg=self.bg)

        family = pick_font_family(cfg["font_family"], set(tkfont.families(root)))
        # negative sizes = pixels, so the layout is DPI-independent
        self.f_digit = (family, -int(cfg["digit_size"]), "bold")
        self.f_caption = (family, -int(cfg["caption_size"]))
        self.f_world = (family, -int(cfg["world_size"]), "bold")
        self.f_date = (family, -int(cfg["date_size"]))

        self.frame = tk.Frame(root, bg=self.bg)
        self.frame.pack(ipadx=1, ipady=1)   # tiny padding keeps glyph edges clean

        self.layer = DesktopLayer(root, behind_icons=bool(cfg.get("behind_icons")))
        self.build()
        self._bind_events()
        self.update_clock()

    # -- layout ---------------------------------------------------------- #
    def build(self) -> None:
        for child in self.frame.winfo_children():
            child.destroy()
        cfg, bg = self.cfg, self.bg

        row = 0
        # date line
        if cfg["show_date"] and cfg["date_format"]:
            self.date_label = tk.Label(
                self.frame, text="", font=self.f_date,
                fg=cfg["date_color"], bg=bg, anchor="w")
            self.date_label.grid(row=row, column=0, columnspan=8, sticky="w",
                                 pady=(0, cfg["gap"] // 2))
            row += 1
        else:
            self.date_label = None

        # captions
        if cfg["show_captions"]:
            captions = [("HOURS", 0), ("MINUTES", 3)]
            if cfg["show_seconds"]:
                captions.append(("SECONDS", 6))
            for text, col in captions:
                tk.Label(self.frame, text=text, font=self.f_caption,
                         fg=cfg["caption_color"], bg=bg).grid(
                    row=row, column=col, columnspan=2, sticky="w")
            row += 1

        # digits: 0,1 = HH | 2 = colon | 3,4 = MM | 5 = colon | 6,7 = SS
        # Every digit sits in a cell as wide as the widest numeral, so the
        # clock never jitters - even with the proportional display fonts.
        self.digit_labels: list[tk.Label] = []
        self.colon_labels: list[tk.Label] = []
        probe = tkfont.Font(root=self.root, font=self.f_digit)
        cell_w = max(probe.measure(str(d)) for d in range(10))
        cell_h = probe.metrics("linespace") + 6      # room for the label border
        columns = 8 if cfg["show_seconds"] else 5
        for col in range(columns):
            if col in (2, 5):
                lbl = tk.Label(self.frame, text=":", font=self.f_digit,
                               fg=cfg["text_color"], bg=bg)
                lbl.grid(row=row, column=col)
                self.colon_labels.append(lbl)
            else:
                holder = tk.Frame(self.frame, bg=bg, width=cell_w, height=cell_h)
                holder.grid(row=row, column=col)
                holder.grid_propagate(False)
                lbl = tk.Label(holder, text="0", font=self.f_digit,
                               fg=cfg["text_color"], bg=bg)
                lbl.place(relx=0.5, rely=0.5, anchor="center")
                self.digit_labels.append(lbl)
        row += 1

        # world clocks
        self.world_labels: list[tuple[tk.Label, ZoneInfo]] = []
        if cfg["show_world_clocks"] and cfg["world_clocks"]:
            world = tk.Frame(self.frame, bg=bg)
            world.grid(row=row, column=0, columnspan=8, sticky="w",
                       pady=(cfg["gap"], 0))
            for i, entry in enumerate(cfg["world_clocks"]):
                name, tz_name = entry[0], entry[1]
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    print(f"{APP_NAME}: unknown timezone {tz_name!r}",
                          file=sys.stderr)
                    continue
                pad = (0, 34) if i < len(cfg["world_clocks"]) - 1 else (0, 0)
                tk.Label(world, text=name, font=self.f_caption,
                         fg=cfg["caption_color"], bg=bg, anchor="w").grid(
                    row=0, column=i, sticky="w", padx=pad)
                t = tk.Label(world, text="--:--", font=self.f_world,
                             fg=cfg["text_color"], bg=bg, anchor="w")
                t.grid(row=1, column=i, sticky="w", padx=pad)
                self.world_labels.append((t, tz))

        self.root.update_idletasks()
        self.layer.apply(cfg["keep_on_desktop"])

    # -- interaction ----------------------------------------------------- #
    def _bind_events(self) -> None:
        r = self.root
        r.bind("<ButtonPress-1>", self.start_drag)
        r.bind("<B1-Motion>", self.do_drag)
        r.bind("<ButtonRelease-1>", self.end_drag)
        r.bind("<Button-3>", self.popup_menu)
        self._bind_tree(r)

    def _bind_tree(self, widget) -> None:
        """`bind_all` would also catch the menu; bind every child instead."""
        for seq, handler in (
            ("<ButtonPress-1>", self.start_drag),
            ("<B1-Motion>", self.do_drag),
            ("<ButtonRelease-1>", self.end_drag),
            ("<Button-3>", self.popup_menu),
        ):
            widget.bind(seq, handler)
        for child in widget.winfo_children():
            self._bind_tree(child)

    def start_drag(self, event) -> None:
        self._drag = (event.x_root, event.y_root,
                      self.root.winfo_x(), self.root.winfo_y())
        self.root.after(120, self.layer.keep)   # a click may have raised us

    def do_drag(self, event) -> None:
        if not self._drag:
            return
        x0, y0, wx, wy = self._drag
        self._offset = [wx + event.x_root - x0, wy + event.y_root - y0]
        self.root.geometry(f"+{self._offset[0]}+{self._offset[1]}")

    def end_drag(self, event=None) -> None:
        if not self._drag:
            return
        self._drag = None
        self.cfg["position"] = list(self._offset)
        save_config(self.cfg)
        # dragging can raise the window; drop it back onto the desktop
        self.root.after(50, self.layer.keep)

    def popup_menu(self, event) -> None:
        if getattr(self, "_menu", None) is not None:
            self._menu.destroy()
        m = tk.Menu(self.root, tearoff=0)
        self._menu = m

        var_sec = tk.BooleanVar(value=self.cfg["show_seconds"])
        var_24 = tk.BooleanVar(value=self.cfg["clock_24h"])
        var_world = tk.BooleanVar(value=self.cfg["show_world_clocks"])
        var_desk = tk.BooleanVar(value=self.cfg["keep_on_desktop"])

        m.add_command(label="Settings…", command=self.open_settings)
        m.add_command(label="Reload settings", command=self.reload)
        m.add_separator()
        m.add_checkbutton(label="Seconds", variable=var_sec, command=lambda: (
            self.set("show_seconds", var_sec.get())))
        m.add_checkbutton(label="24-hour clock", variable=var_24, command=lambda: (
            self.set("clock_24h", var_24.get())))
        m.add_checkbutton(label="World clocks", variable=var_world, command=lambda: (
            self.set("show_world_clocks", var_world.get())))
        m.add_checkbutton(label="Stay on desktop", variable=var_desk, command=lambda: (
            self.set("keep_on_desktop", var_desk.get())))
        m.add_separator()
        m.add_command(label="Close", command=self.root.destroy)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def set(self, key: str, value) -> None:
        self.apply_settings({key: value})

    def apply_settings(self, values: dict) -> None:
        """Merge `values` into the config, save it and redraw the clock."""
        self.cfg.update(values)
        save_config(self.cfg)
        self.build()
        self._bind_events()
        self.update_clock()

    def reload(self) -> None:
        self.cfg = load_config()
        self.build()
        self._bind_events()
        self.update_clock()
        if getattr(self, "settings_win", None) is not None:
            self.settings_win.close()

    def open_settings(self) -> None:
        """Open the settings window (one instance at a time)."""
        existing = getattr(self, "settings_win", None)
        if existing is not None and existing.alive():
            existing.show()
            return
        self.settings_win = SettingsWindow(self)

    def open_config(self) -> None:
        save_config(self.cfg)
        try:
            if IS_WINDOWS:
                os.startfile(CONFIG_PATH)          # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{CONFIG_PATH}"')
            else:
                os.system(f'xdg-open "{CONFIG_PATH}" &')
        except Exception:
            pass

    # -- clock ----------------------------------------------------------- #
    def update_clock(self) -> None:
        now = datetime.now()

        if self.cfg["clock_24h"]:
            digits = now.strftime("%H%M%S" if self.cfg["show_seconds"] else "%H%M")
        else:
            digits = now.strftime("%I%M%S" if self.cfg["show_seconds"] else "%I%M")
        for lbl, ch in zip(self.digit_labels, digits):
            if lbl.cget("text") != ch:
                lbl.config(text=ch)

        if self.date_label is not None:
            text = now.strftime(self.cfg["date_format"])
            if self.date_label.cget("text") != text:
                self.date_label.config(text=text)

        for lbl, tz in self.world_labels:
            text = datetime.now(tz).strftime("%H:%M")
            if lbl.cget("text") != text:
                lbl.config(text=text)

        # Explorer occasionally re-stacks windows; re-assert every ~3 s.
        self.tick += 1
        if self.tick % 15 == 0:
            self.layer.keep()

        # wake up right after the next second boundary -> crisp second changes
        delay = 1000 - now.microsecond // 1000
        self.root.after(max(50, delay), self.update_clock)


# --------------------------------------------------------------------------- #
# Settings window
# --------------------------------------------------------------------------- #
UI_BG = "#0E0F10"
UI_PANEL = "#16181A"
UI_CARD = "#1C1F21"
UI_CARD_SEL = "#252A2D"
UI_LINE = "#2A2E31"
UI_TEXT = "#F1F2F3"
UI_MUTED = "#868D92"
UI_DIM = "#5F666A"
UI_ACCENT = "#FF6A13"
UI_ACCENT_TEXT = "#141414"

SETTINGS_W = 920
CARD_COLUMNS, CARD_HEIGHT = 3, 74
PREVIEW_H = 208


def ui_font_family(root) -> str:
    """First decent UI sans-serif that exists on this machine."""
    available = {name.lower(): name for name in tkfont.families(root)}
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text",
                 "Helvetica Neue", "DejaVu Sans", "Arial", "Helvetica"):
        if name.lower() in available:
            return available[name.lower()]
    return "TkDefaultFont"


class ThinScrollbar(tk.Canvas):
    """A 6 px accent thumb - the native Windows scrollbar is too loud."""

    def __init__(self, master, command, **kw):
        super().__init__(master, width=6, bg=UI_BG, highlightthickness=0,
                         bd=0, **kw)
        self._command = command
        self._first, self._last = 0.0, 1.0
        self._grab_offset = 0
        self._thumb = self.create_rectangle(0, 0, 6, 20, fill=UI_LINE,
                                            outline="")
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)

    # tk.Scrollbar protocol ------------------------------------------------
    def set(self, first, last) -> None:
        self._first, self._last = float(first), float(last)
        self._redraw()

    # internals -----------------------------------------------------------
    def _thumb_span(self):
        height = max(self.winfo_height(), 1)
        top = self._first * height
        bottom = max(self._last * height, top + 18)
        return top, min(bottom, height)

    def _redraw(self) -> None:
        top, bottom = self._thumb_span()
        self.coords(self._thumb, 1, top, 5, bottom)
        if self._last - self._first >= 0.999:
            self.itemconfigure(self._thumb, fill=UI_BG)      # nothing to scroll
        else:
            self.itemconfigure(self._thumb, fill=UI_LINE)

    def _press(self, event) -> None:
        top, bottom = self._thumb_span()
        if top <= event.y <= bottom:
            self._grab_offset = event.y - top
        else:
            self._grab_offset = (bottom - top) / 2
            self._move_to(event.y)

    def _drag(self, event) -> None:
        self._move_to(event.y)

    def _move_to(self, y: int) -> None:
        height = max(self.winfo_height(), 1)
        top, bottom = self._thumb_span()
        span = max(bottom - top, 1)
        first = (y - self._grab_offset) / height
        first = max(0.0, min(first, 1.0 - span / height))
        self._command("moveto", first)


class SettingsWindow:
    """A small, dark, industrial settings sheet for the clock."""

    def __init__(self, app: "ClockWidget"):
        self.app = app
        self.root = app.root
        self.draft = dict(app.cfg)
        self.ui = ui_font_family(self.root)
        self._cards: dict[str, list] = {}
        self._swatches: dict[str, tk.Frame] = {}
        self._swatch_colors: dict[str, str] = {}
        self._scales: dict[str, tk.Scale] = {}
        self._tick_id = None
        self._show_all = tk.BooleanVar(value=False)

        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.title(f"{APP_NAME} {__version__} · Settings")
        self.win.configure(bg=UI_BG)
        self.win.transient(self.root)
        self.win.resizable(False, False)
        apply_window_icon(self.win)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self._center()
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.deiconify()
        self.show()
        self._tick()

    # -- plumbing -------------------------------------------------------- #
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self) -> None:
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.attributes("-topmost", True)
            self.win.after(350, self._drop_topmost)
        except tk.TclError:
            pass
        self.win.focus_force()

    def _drop_topmost(self) -> None:
        try:
            self.win.attributes("-topmost", False)
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._tick_id is not None:
            try:
                self.win.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.app.settings_win = None

    def _center(self) -> None:
        self.win.update_idletasks()
        outer = self.win.winfo_children()[0]
        w = max(SETTINGS_W, outer.winfo_reqwidth())
        h = outer.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        x = max(0, min(x, self.win.winfo_screenwidth() - w - 20))
        y = max(0, min(y, self.win.winfo_screenheight() - h - 70))
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def f(self, size: int, bold: bool = False):
        return (self.ui, size, "bold") if bold else (self.ui, size)

    def _label(self, parent, text, size=9, color=UI_TEXT, bold=False, bg=UI_BG,
               **kw) -> tk.Label:
        return tk.Label(parent, text=text, font=self.f(size, bold), fg=color,
                        bg=bg, **kw)

    def _button(self, parent, text, command, primary=False, width=9):
        fg = UI_ACCENT_TEXT if primary else UI_TEXT
        bg = UI_ACCENT if primary else UI_CARD
        hover = "#FF7F35" if primary else UI_CARD_SEL
        btn = tk.Button(
            parent, text=text, command=command, font=self.f(9, primary),
            fg=fg, bg=bg, activeforeground=fg, activebackground=hover,
            relief="flat", bd=0, highlightthickness=0, width=width,
            cursor="hand2", padx=10, pady=7)
        btn.bind("<Enter>", lambda _e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda _e: btn.config(bg=bg))
        return btn

    # -- chrome ---------------------------------------------------------- #
    def _build(self) -> None:
        outer = tk.Frame(self.win, bg=UI_BG, padx=22, pady=18)
        outer.pack(fill="both", expand=True)

        # header
        head = tk.Frame(outer, bg=UI_BG)
        head.pack(fill="x")
        self._label(head, "DESKTOPCLOCK", size=9, bold=True,
                    color=UI_ACCENT).pack(side="left")
        self._label(head, f"  ·  SETTINGS  ·  v{__version__}", size=9,
                    color=UI_DIM).pack(side="left")
        self._label(head, "cargo industrial edition", size=8,
                    color=UI_DIM).pack(side="right")
        self._label(outer, "Pick a typeface for the desk clock. "
                           "Changes preview live; Apply saves them.",
                    size=9, color=UI_MUTED).pack(anchor="w", pady=(4, 14))

        # fake tabs
        tabs = tk.Frame(outer, bg=UI_BG)
        tabs.pack(fill="x")
        tk.Frame(outer, bg=UI_LINE, height=1).pack(fill="x")
        self._tab_buttons = {}
        self._tab_bars = {}

        def add_tab(key, label):
            cell = tk.Frame(tabs, bg=UI_BG, cursor="hand2")
            cell.pack(side="left", padx=(0, 4))
            lbl = self._label(cell, label, size=10, bold=True, color=UI_MUTED,
                              padx=14, pady=8)
            lbl.pack()
            bar = tk.Frame(cell, bg=UI_BG, height=2)
            bar.pack(fill="x")
            for widget in (cell, lbl):
                widget.bind("<Button-1>", lambda _e, k=key: self._show_tab(k))
            self._tab_buttons[key] = lbl
            self._tab_bars[key] = bar

        add_tab("font", "TYPE")
        add_tab("layout", "LAYOUT")

        # The pages are place()d on top of each other, so the container needs
        # an explicit height - it cannot derive one from overlapping children.
        self.pages = tk.Frame(outer, bg=UI_BG, height=470)
        self.pages.pack(fill="x", pady=(14, 0))
        self.pages.pack_propagate(False)
        self.page_font = tk.Frame(self.pages, bg=UI_BG)
        self.page_layout = tk.Frame(self.pages, bg=UI_BG)
        for page in (self.page_font, self.page_layout):
            page.place(x=0, y=0, relwidth=1, relheight=1)

        self._build_font_page(self.page_font)
        self._build_layout_page(self.page_layout)
        self._build_footer(outer)
        self._show_tab("font")

    def _show_tab(self, key: str) -> None:
        for name, lbl in self._tab_buttons.items():
            active = name == key
            lbl.config(fg=UI_TEXT if active else UI_MUTED)
            self._tab_bars[name].config(bg=UI_ACCENT if active else UI_BG)
        page = self.page_font if key == "font" else self.page_layout
        page.lift()

    def _build_footer(self, parent) -> None:
        tk.Frame(parent, bg=UI_LINE, height=1).pack(fill="x", pady=(16, 12))
        row = tk.Frame(parent, bg=UI_BG)
        row.pack(fill="x")
        self._label(row, f"{APP_NAME} {__version__}", size=8,
                    color=UI_DIM).pack(side="left")
        link = tk.Label(row, text="config.json", font=self.f(8, True),
                        fg=UI_MUTED, bg=UI_BG, cursor="hand2")
        link.pack(side="left", padx=(10, 0))
        link.bind("<Button-1>", lambda _e: self.app.open_config())
        link.bind("<Enter>", lambda _e: link.config(fg=UI_ACCENT))
        link.bind("<Leave>", lambda _e: link.config(fg=UI_MUTED))

        self.btn_apply = self._button(row, "Apply", self.apply, primary=True,
                                      width=8)
        self.btn_apply.pack(side="right")
        self._button(row, "Close", self.close, width=8).pack(
            side="right", padx=(0, 8))

    # -- font page ------------------------------------------------------- #
    def _build_font_page(self, page) -> None:
        preview = tk.Frame(page, bg=UI_PANEL, highlightthickness=1,
                           highlightbackground=UI_LINE, height=PREVIEW_H)
        preview.pack(fill="x")
        preview.pack_propagate(False)
        self._build_preview(preview)

        strip = tk.Frame(page, bg=UI_BG)
        strip.pack(fill="x", pady=(11, 8))
        self.lbl_list_title = self._label(strip, "BUNDLED TYPEFACES", size=8,
                                          bold=True, color=UI_DIM)
        self.lbl_list_title.pack(side="left")
        self.lbl_selected = self._label(
            strip, f"current · {self.draft['font_family']}", size=8,
            color=UI_ACCENT)
        self.lbl_selected.pack(side="left", padx=(10, 0))

        self.chk_all = tk.Checkbutton(
            page, text="  Show every font installed on this PC",
            variable=self._show_all, command=self._rebuild_list,
            font=self.f(8), fg=UI_MUTED, bg=UI_BG,
            activebackground=UI_BG, activeforeground=UI_TEXT,
            selectcolor=UI_CARD, bd=0, highlightthickness=0, anchor="w",
            cursor="hand2")
        self.chk_all.pack(anchor="w", pady=(0, 8))

        # scrollable card list
        holder = tk.Frame(page, bg=UI_BG)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, bg=UI_BG, highlightthickness=0, bd=0)
        self.scrollbar = ThinScrollbar(holder, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y", padx=(5, 2))
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_inner = tk.Frame(self.canvas, bg=UI_BG)
        self._list_window = self.canvas.create_window(
            (0, 0), window=self.list_inner, anchor="nw")
        self.list_inner.bind(
            "<Configure>", lambda _e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(
                self._list_window, width=e.width))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)

        self._rebuild_list()

    def _on_wheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step * 2, "units")

    def _build_preview(self, parent) -> None:
        grid = tk.Frame(parent, bg=UI_PANEL)
        grid.pack(expand=True)
        self.pv_date = self._label(grid, "", size=10, color=UI_MUTED,
                                   bg=UI_PANEL)
        self.pv_date.grid(row=0, column=0, columnspan=5, pady=(8, 0))

        self.pv_captions: list[tk.Label] = []
        self.pv_colon: list[tk.Label] = []
        self.pv_digits: list[tk.Label] = []
        for i, col in enumerate((0, 2, 4)):
            cap = self._label(grid, ("HOURS", "MINUTES", "SECONDS")[i],
                              size=7, color=UI_DIM, bg=UI_PANEL)
            cap.grid(row=1, column=col, padx=(0, 10), pady=(2, 0))
            self.pv_captions.append(cap)
            lbl = tk.Label(grid, text="00", bg=UI_PANEL, fg=UI_TEXT,
                           anchor="center")
            lbl.grid(row=2, column=col, padx=(0, 10), sticky="ew")
            self.pv_digits.append(lbl)
            if i < 2:
                cl = tk.Label(grid, text=":", bg=UI_PANEL, fg=UI_TEXT)
                cl.grid(row=2, column=col + 1, padx=(0, 10))
                self.pv_colon.append(cl)

        self.pv_world = self._label(grid, "", size=8, color=UI_DIM, bg=UI_PANEL)
        self.pv_world.grid(row=3, column=0, columnspan=5, pady=(8, 8))
        self._restyle_preview()

    def _restyle_preview(self) -> None:
        """Re-derive every preview font and colour from the current draft."""
        fam = self.draft["font_family"]
        # A miniature of the real widget: pixel sizes, roughly scaled down.
        big = -max(24, min(int(self.draft["digit_size"] * 0.62), 104))
        cap = -max(8, min(int(self.draft["caption_size"] * 0.95), 18))
        date = -max(9, min(int(self.draft["date_size"] * 0.95), 18))
        world = -max(9, min(int(self.draft["world_size"] * 0.8), 18))
        for lbl in self.pv_digits + self.pv_colon:
            lbl.config(font=(fam, big, "bold"),
                       fg=self.draft["text_color"])
        self.pv_date.config(font=(fam, date), fg=self.draft["date_color"])
        self.pv_world.config(font=(fam, world), fg=self.draft["text_color"])
        for cap_lbl in self.pv_captions:
            cap_lbl.config(font=(fam, cap), fg=self.draft["caption_color"])

    def _rebuild_list(self) -> None:
        for child in self.list_inner.winfo_children():
            child.destroy()
        self._cards.clear()
        self.canvas.yview_moveto(0)

        if self._show_all.get():
            families = sorted(
                (name for name in tkfont.families(self.root)
                 if not name.startswith("@")),
                key=lambda name: name.lower())
            self.lbl_list_title.config(text="ALL INSTALLED TYPEFACES")
        else:
            families = [font["family"] for font in BUNDLED_FONTS]
            self.lbl_list_title.config(text="BUNDLED TYPEFACES")
        blurbs = {font["family"]: font["blurb"] for font in BUNDLED_FONTS}

        for column in range(CARD_COLUMNS):
            self.list_inner.columnconfigure(column, weight=1, uniform="cards")
        for index, family in enumerate(families):
            self._add_card(family, blurbs.get(family, ""), index)
        self._refresh_selection()
        self._bind_wheel(self.list_inner)

    def _add_card(self, family: str, blurb: str, index: int) -> None:
        card = tk.Frame(self.list_inner, bg=UI_CARD, cursor="hand2",
                        highlightthickness=1, highlightbackground=UI_CARD,
                        height=CARD_HEIGHT)
        card.grid(row=index // CARD_COLUMNS, column=index % CARD_COLUMNS,
                  sticky="nsew", padx=(0, 7), pady=(0, 7))
        card.pack_propagate(False)
        card.grid_propagate(False)
        card.columnconfigure(0, weight=1)

        name = tk.Label(card, text=family, font=(family, 11), fg=UI_TEXT,
                        bg=UI_CARD, anchor="w")
        name.grid(row=0, column=0, sticky="w", padx=(11, 2), pady=(7, 0))
        sample = tk.Label(card, text="10:24", font=(family, 14, "bold"),
                          fg=UI_MUTED, bg=UI_CARD, anchor="e")
        sample.grid(row=0, column=1, sticky="e", padx=(0, 11), pady=(5, 0))
        sub = tk.Label(card, text=blurb or "installed", font=self.f(8),
                       fg=UI_DIM, bg=UI_CARD, anchor="w")
        sub.grid(row=1, column=0, columnspan=2, sticky="w",
                 padx=11, pady=(0, 7))

        parts = (card, name, sample, sub)
        self._cards[family] = [card, name, sample, sub]
        for widget in parts:
            widget.bind("<Button-1>", lambda _e, fam=family: self._pick(fam))
            widget.bind("<Enter>",
                        lambda _e, fam=family: self._hover(fam, True))
            widget.bind("<Leave>",
                        lambda _e, fam=family: self._hover(fam, False))
        self._bind_wheel(card)

    def _bind_wheel(self, widget) -> None:
        for child in widget.winfo_children():
            child.bind("<MouseWheel>", self._on_wheel)
            child.bind("<Button-4>", self._on_wheel)
            child.bind("<Button-5>", self._on_wheel)
            self._bind_wheel(child)
        widget.bind("<MouseWheel>", self._on_wheel)
        widget.bind("<Button-4>", self._on_wheel)
        widget.bind("<Button-5>", self._on_wheel)

    def _hover(self, family: str, entering: bool) -> None:
        if family == self.draft["font_family"]:
            return
        parts = self._cards.get(family)
        if not parts:
            return
        bg = UI_CARD_SEL if entering else UI_CARD
        for widget in parts:
            widget.config(bg=bg)

    def _pick(self, family: str) -> None:
        self.draft["font_family"] = family
        self.lbl_selected.config(text=f"current · {family}")
        self._restyle_preview()
        self._refresh_selection()
        for name, parts in self._cards.items():
            if name != family:
                for widget in parts:
                    widget.config(bg=UI_CARD)

    def _refresh_selection(self) -> None:
        current = self.draft["font_family"]
        for family, parts in self._cards.items():
            selected = family == current
            parts[0].config(
                highlightbackground=UI_ACCENT if selected else UI_CARD,
                bg=UI_CARD_SEL if selected else UI_CARD)
            for widget in parts[1:]:
                widget.config(bg=UI_CARD_SEL if selected else UI_CARD)
            parts[1].config(fg=UI_TEXT if selected else UI_MUTED)
            parts[2].config(fg=UI_ACCENT if selected else UI_DIM)

    # -- layout page ----------------------------------------------------- #
    def _build_layout_page(self, page) -> None:
        left = tk.Frame(page, bg=UI_BG, width=430)
        left.pack(side="left", fill="both", expand=True)
        left.pack_propagate(False)
        right = tk.Frame(page, bg=UI_BG)
        right.pack(side="left", fill="both", expand=True, padx=(34, 0))

        self._section(left, "SIZE")
        self._slider(left, "Digit height", "digit_size", 60, 280)
        self._slider(left, "Captions", "caption_size", 8, 30)
        self._slider(left, "Date line", "date_size", 8, 32)
        self._slider(left, "World clocks", "world_size", 10, 36)

        self._section(left, "COLOUR", top=20)
        swatch_row = tk.Frame(left, bg=UI_BG)
        swatch_row.pack(anchor="w", fill="x")
        for index, (name, text, caption, date) in enumerate(COLOR_PRESETS):
            self._swatch(swatch_row, name, text, caption, date, index)

        self._section(right, "SHOW")
        self._toggle(right, "Seconds", "show_seconds")
        self._toggle(right, "24-hour clock", "clock_24h")
        self._toggle(right, "Date line", "show_date")
        self._toggle(right, "Captions", "show_captions")
        self._toggle(right, "World clocks", "show_world_clocks")
        self._toggle(right, "Stay on desktop", "keep_on_desktop")

        self._section(right, "DATE LINE", top=18)
        self._label(right, "Any strftime pattern, e.g. %A, %d %B "
                           "or %d.%m.%Y", size=8, color=UI_DIM).pack(anchor="w")
        entry_row = tk.Frame(right, bg=UI_BG)
        entry_row.pack(fill="x", pady=(6, 0))
        self.date_entry = tk.Entry(
            entry_row, font=self.f(10), bg=UI_CARD, fg=UI_TEXT,
            insertbackground=UI_ACCENT, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=UI_LINE,
            highlightcolor=UI_ACCENT, width=24)
        self.date_entry.insert(0, self.draft["date_format"])
        self.date_entry.pack(side="left", ipady=6, ipadx=8)
        self.date_entry.bind("<KeyRelease>", self._date_changed)
        self._label(entry_row, "empty = hidden", size=8,
                    color=UI_DIM).pack(side="left", padx=(10, 0))

        self._section(right, "RESET", top=18)
        self._button(right, "Restore default look", self._reset_look,
                     width=22).pack(anchor="w")

    def _section(self, parent, text: str, top: int = 0) -> None:
        self._label(parent, text, size=8, bold=True, color=UI_DIM).pack(
            anchor="w", pady=(top, 8))

    def _date_changed(self, _event=None) -> None:
        self.draft["date_format"] = self.date_entry.get()
        self._preview_tick()

    def _reset_look(self) -> None:
        for key in ("font_family", "digit_size", "caption_size", "date_size",
                    "world_size", "text_color", "caption_color", "date_color",
                    "gap"):
            self.draft[key] = DEFAULT_CONFIG[key]
        for scale, key in self._scales.items():
            scale.set(self.draft[key])
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, self.draft["date_format"])
        self.lbl_selected.config(text=f"current · {self.draft['font_family']}")
        self._restyle_preview()
        self._refresh_selection()
        self._refresh_swatches()
        self._preview_tick()

    def _slider(self, parent, label: str, key: str, low: int, high: int) -> None:
        row = tk.Frame(parent, bg=UI_BG)
        row.pack(fill="x", pady=(0, 9))
        head = tk.Frame(row, bg=UI_BG)
        head.pack(fill="x")
        self._label(head, label, size=9, color=UI_MUTED, anchor="w").pack(
            side="left")
        value = self._label(head, str(self.draft[key]), size=9, bold=True,
                            color=UI_ACCENT, anchor="e")
        value.pack(side="right")

        def changed(raw):
            number = int(float(raw))
            self.draft[key] = number
            value.config(text=str(number))
            self._restyle_preview()

        scale = tk.Scale(row, from_=low, to=high, orient="horizontal",
                         command=changed, bg=UI_BG, fg=UI_TEXT,
                         troughcolor=UI_CARD, activebackground=UI_ACCENT,
                         highlightthickness=0, bd=0, relief="flat",
                         sliderrelief="flat", sliderlength=16, width=6,
                         showvalue=0, cursor="hand2")
        scale.set(self.draft[key])
        scale.pack(fill="x", pady=(1, 0))
        self._scales[key] = scale

    def _toggle(self, parent, label: str, key: str) -> None:
        var = tk.BooleanVar(value=bool(self.draft[key]))

        def changed():
            self.draft[key] = bool(var.get())
            self._preview_tick()

        chk = tk.Checkbutton(parent, text="  " + label, variable=var,
                             command=changed, font=self.f(9), fg=UI_TEXT,
                             bg=UI_BG, activebackground=UI_BG,
                             activeforeground=UI_TEXT, selectcolor=UI_CARD,
                             bd=0, highlightthickness=0, anchor="w",
                             cursor="hand2")
        chk.pack(anchor="w", pady=1)

    def _swatch(self, parent, name: str, text: str, caption: str,
                date: str, index: int) -> None:
        cell = tk.Frame(parent, bg=UI_BG, cursor="hand2",
                        highlightthickness=1, highlightbackground=UI_BG)
        cell.grid(row=0, column=index, padx=(0, 7))
        chip = tk.Frame(cell, bg=text, width=38, height=20,
                        highlightthickness=1, highlightbackground=UI_LINE)
        chip.pack(padx=5, pady=(5, 3))
        chip.pack_propagate(False)
        self._label(cell, name, size=7, color=UI_MUTED, bg=UI_BG).pack(
            pady=(0, 5))

        def pick(_event=None):
            self.draft.update(text_color=text, caption_color=caption,
                              date_color=date)
            self._restyle_preview()
            self._refresh_swatches()
            self._preview_tick()

        for widget in (cell, chip, *cell.winfo_children()):
            widget.bind("<Button-1>", pick)
        self._swatches[name] = cell
        self._swatch_colors[name] = text
        self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        current = str(self.draft.get("text_color", "")).upper()
        for name, cell in self._swatches.items():
            selected = self._swatch_colors.get(name, "").upper() == current
            cell.config(highlightbackground=UI_ACCENT if selected else UI_BG)

    # -- live preview ---------------------------------------------------- #
    def _tick(self) -> None:
        if not self.alive():
            return
        self._preview_tick()
        try:
            self._tick_id = self.win.after(1000, self._tick)
        except tk.TclError:
            pass

    def _preview_tick(self) -> None:
        if not self.alive():
            return
        now = datetime.now()
        clock = self.draft.get("clock_24h", True)
        fmt = "%H:%M:%S" if clock else "%I:%M:%S"
        parts = now.strftime(fmt).split(":")
        if not clock:
            parts[2] = parts[2][:2] + ("AM" if now.hour < 12 else "PM")
        for lbl, text in zip(self.pv_digits, parts):
            if lbl.cget("text") != text:
                lbl.config(text=text)

        # show / hide the seconds block
        with_seconds = bool(self.draft["show_seconds"])
        widgets = [(self.pv_digits[2], with_seconds),
                   (self.pv_colon[1], with_seconds),
                   (self.pv_captions[2], with_seconds),
                   (self.pv_digits[0], True), (self.pv_digits[1], True),
                   (self.pv_colon[0], True),
                   (self.pv_captions[0], bool(self.draft["show_captions"])),
                   (self.pv_captions[1], bool(self.draft["show_captions"]))]
        for widget, visible in widgets:
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

        if self.draft["show_date"] and self.draft["date_format"]:
            text = now.strftime(self.draft["date_format"])
        else:
            text = ""
        if self.pv_date.cget("text") != text:
            self.pv_date.config(text=text)

        if self.draft["show_world_clocks"] and self.draft["world_clocks"]:
            samples = []
            for entry in self.draft["world_clocks"][:3]:
                try:
                    samples.append(
                        f"{entry[0]} {datetime.now(ZoneInfo(entry[1])):%H:%M}")
                except Exception:
                    continue
            text = "   ·   ".join(samples)
        else:
            text = ""
        if self.pv_world.cget("text") != text:
            self.pv_world.config(text=text)

    # -- actions --------------------------------------------------------- #
    def apply(self) -> None:
        self.draft["date_format"] = self.date_entry.get()
        self.app.apply_settings(dict(self.draft))
        self.btn_apply.config(text="Applied ✓", bg="#22A559",
                              activebackground="#2CC066", fg="#FFFFFF")
        self.win.after(1400, self._reset_apply_button)

    def _reset_apply_button(self) -> None:
        try:
            self.btn_apply.config(text="Apply", bg=UI_ACCENT,
                                  activebackground="#FF7F35",
                                  fg=UI_ACCENT_TEXT)
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
LOG_PATH = CONFIG_DIR / "error.log"


def report_crash(exc_type, exc, tb) -> None:
    """A windowed exe has no console, so never die silently."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        if IS_WINDOWS:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"DesktopClock hit an error and must close.\n\n"
                f"{exc_type.__name__}: {exc}\n\nDetails: {LOG_PATH}",
                "DesktopClock", 0x10)
        else:
            print(text, file=sys.stderr)
    except Exception:
        pass


def log_callback_error(exc_type, exc, tb) -> None:
    """Tk callback exceptions: write to error.log instead of a modal dialog."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass
    print(text, file=sys.stderr)


def main() -> None:
    sys.excepthook = report_crash
    enable_dpi_awareness()
    # Fonts must be registered before Tk builds its font table.
    load_bundled_fonts()
    cfg = load_config()
    if not CONFIG_PATH.exists():
        save_config(cfg)

    root = tk.Tk()
    root.report_callback_exception = log_callback_error
    root.title(APP_NAME)
    apply_window_icon(root)
    root.overrideredirect(True)              # no title bar, no taskbar button
    root.configure(bg=cfg["transparent_color"])
    try:
        # Windows only: the key colour becomes fully transparent
        root.attributes("-transparentcolor", cfg["transparent_color"])
    except tk.TclError:
        pass

    x, y = cfg["position"] or (100, 100)
    root.geometry(f"+{int(x)}+{int(y)}")

    app = ClockWidget(root, cfg)
    root.after(400, app.layer.keep)
    root.mainloop()


if __name__ == "__main__":
    main()
