#!/usr/bin/env python3
"""Desktop Clock - a borderless, transparent clock that lives on your desktop.

Highlights
----------
* Frameless, click-through-on-empty-space, no taskbar entry, no Alt+Tab entry.
* Pinned to the desktop layer so "Show desktop" (Win+D) does not hide it.
* Drag anywhere with the left mouse button; the position is remembered.
* Right-click for a small menu (seconds, world clocks, settings, close).
* All look-and-feel settings live in one JSON file:
      %APPDATA%\\DesktopClock\\config.json
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

APP_NAME = "DesktopClock"
IS_WINDOWS = sys.platform.startswith("win")

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    # --- look ------------------------------------------------------------- #
    "font_family": "Consolas",          # any installed font, monospace looks best
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
        self.digit_labels: list[tk.Label] = []
        self.colon_labels: list[tk.Label] = []
        columns = 8 if cfg["show_seconds"] else 5
        for col in range(columns):
            if col in (2, 5):
                lbl = tk.Label(self.frame, text=":", font=self.f_digit,
                               fg=cfg["text_color"], bg=bg)
                lbl.grid(row=row, column=col)
                self.colon_labels.append(lbl)
            else:
                lbl = tk.Label(self.frame, text="0", font=self.f_digit,
                               fg=cfg["text_color"], bg=bg)
                lbl.grid(row=row, column=col)
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

        m.add_command(label="Edit settings file",
                      command=self.open_config)
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
        self.cfg[key] = value
        save_config(self.cfg)
        self.build()
        self._bind_events()
        self.update_clock()

    def reload(self) -> None:
        self.cfg = load_config()
        self.build()
        self._bind_events()
        self.update_clock()

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


def main() -> None:
    sys.excepthook = report_crash
    enable_dpi_awareness()
    cfg = load_config()
    if not CONFIG_PATH.exists():
        save_config(cfg)

    root = tk.Tk()
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
