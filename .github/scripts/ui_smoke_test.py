"""Headless-ish UI smoke test for Windows CI.

Runs the real Tk application, checks that the bundled fonts are registered,
opens the settings window, applies a font and renders PNG screenshots of the
widget and of both settings tabs.

Usage:  python .github/scripts/ui_smoke_test.py [output-dir]
"""

from __future__ import annotations

import ctypes
import faulthandler
import io
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import tkinter as tk                       # noqa: E402
from tkinter import font as tkfont         # noqa: E402

import clock_widget as cw                  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "screenshots")


def _report(text: str) -> None:
    print(text, flush=True)
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "failure.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    for line in text.strip().splitlines()[-14:]:
        print(f"::error::{line[:900]}", flush=True)


def watchdog(seconds: float = 120.0) -> None:
    """Never let a hung Tk dialog stall a CI runner forever."""

    def dump() -> None:
        buffer = io.StringIO()
        buffer.write(f"UI smoke test hung for {seconds:.0f}s - stack dump:\n")
        faulthandler.dump_traceback(file=buffer, all_threads=True)
        _report(buffer.getvalue())
        sys.stdout.flush()
        os._exit(1)

    timer = threading.Timer(seconds, dump)
    timer.daemon = True
    timer.start()


# --------------------------------------------------------------------------- #
# Window capture (PrintWindow works even when the window is not on screen)
# --------------------------------------------------------------------------- #
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


def toplevel_hwnd(widget) -> int:
    user32 = ctypes.windll.user32
    hwnd = widget.winfo_id()
    parent = user32.GetParent(hwnd)
    return parent or hwnd


def capture(hwnd: int, path: Path) -> None:
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"window {hwnd} has no area")

    hdc_window = user32.GetWindowDC(hwnd)
    hdc = gdi32.CreateCompatibleDC(hdc_window)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    gdi32.SelectObject(hdc, bitmap)

    # 2 = PW_RENDERFULLCONTENT (needed for layered / offscreen windows)
    if not user32.PrintWindow(hwnd, hdc, 2):
        user32.PrintWindow(hwnd, hdc, 0)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height          # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0            # BI_RGB

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(hdc, bitmap, 0, height, buffer, ctypes.byref(info), 0)

    image = Image.frombuffer("RGBA", (width, height), buffer.raw,
                             "raw", "BGRA", 0, 1)
    image.convert("RGB").save(path)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(hwnd, hdc_window)
    print(f"  captured {path.name}  ({width}x{height})", flush=True)


# --------------------------------------------------------------------------- #
def pump(root: tk.Tk, seconds: float = 1.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def check_fonts() -> None:
    families = {name.lower(): name for name in tkfont.families()}
    missing = [f["family"] for f in cw.BUNDLED_FONTS
               if f["family"].lower() not in families]
    print(f"  bundled families visible to Tk: "
          f"{len(cw.BUNDLED_FONTS) - len(missing)}/{len(cw.BUNDLED_FONTS)}")
    if missing:
        raise AssertionError(f"bundled fonts not registered: {missing}")

    # the family must really resolve, not silently fall back to a default
    for entry in cw.BUNDLED_FONTS:
        probe = tkfont.Font(family=entry["family"], size=-80)
        actual = probe.actual("family")
        assert actual.lower() == entry["family"].lower(), (
            f"{entry['family']} resolved to {actual!r}")


def check_glyphs(root: tk.Tk) -> None:
    """Digits must actually differ from the fallback font's digits."""
    fallback = tkfont.Font(family="NoSuchFontForSure", size=-100)
    for entry in cw.BUNDLED_FONTS:
        font = tkfont.Font(family=entry["family"], size=-100, weight="bold")
        width = font.measure("10:24:37")
        assert width > 50, f"{entry['family']} measures only {width}px"
        assert font.measure("1024") != fallback.measure("1024"), (
            f"{entry['family']} is not rendering")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    watchdog(180.0)
    cw.enable_dpi_awareness()
    cw.load_bundled_fonts()

    print("font registration")
    root = tk.Tk()
    root.withdraw()
    check_fonts()
    check_glyphs(root)
    root.destroy()

    print("building the clock")
    cfg = cw.load_config()
    cfg["font_family"] = cw.BUNDLED_FONTS[0]["family"]
    cfg["position"] = [80, 80]
    root = cw.tk.Tk()
    root.report_callback_exception = cw.log_callback_error
    root.title(cw.APP_NAME)
    root.overrideredirect(True)
    root.configure(bg=cfg["transparent_color"])
    try:
        root.attributes("-transparentcolor", cfg["transparent_color"])
    except tk.TclError:
        pass
    root.geometry("+80+80")

    app = cw.ClockWidget(root, cfg)
    pump(root, 1.2)
    assert app.digit_labels, "the clock has no digit labels"
    assert len(app.digit_labels) == 6, len(app.digit_labels)
    print(f"  clock window: {root.winfo_width()}x{root.winfo_height()}")
    assert 100 < root.winfo_width() < 3000

    print("opening settings")
    app.open_settings()
    pump(root, 1.0)
    settings = app.settings_win
    assert settings is not None and settings.alive()
    width = settings.win.winfo_width()
    height = settings.win.winfo_height()
    print(f"  settings window: {width}x{height}")
    screen_h = settings.win.winfo_screenheight()
    assert 520 < width < 1400, width
    assert 400 < height <= screen_h - 40, (height, screen_h)
    assert len(settings._cards) == len(cw.BUNDLED_FONTS), len(settings._cards)
    rows = max(int(c.grid_info()["row"]) for c in settings.list_inner.winfo_children()) + 1
    print(f"  cards: {len(settings._cards)} in {rows} rows")
    assert rows <= 4, rows
    visible = settings.canvas.winfo_height()
    print(f"  visible list height: {visible}px (compact={settings.compact})")
    assert visible >= settings.px(146), visible

    # a card whose content is taller than the card would be silently clipped
    for family, parts in settings._cards.items():
        card, name, sample, sub = parts
        card.update_idletasks()
        needed = (name.winfo_reqheight() + sub.winfo_reqheight()
                  + 7 + 7 + 2 + 4)
        assert needed <= card.winfo_height(), (
            f"{family}: content {needed}px > card {card.winfo_height()}px")

    # the preview digits must fit inside the preview panel
    panel = settings.pv_digits[0].master.master
    pump(root, 0.2)
    bottom = max(lbl.winfo_y() + lbl.winfo_height()
                 for lbl in settings.pv_digits + settings.pv_colon)
    print(f"  preview content: {bottom}px in a {panel.winfo_height()}px panel")
    assert bottom <= panel.winfo_height(), (bottom, panel.winfo_height())
    capture(toplevel_hwnd(settings.win), OUT / "settings-fonts.png")

    print("scroll list with the wheel")
    settings._on_wheel(type("E", (), {"delta": -120, "num": None})())
    pump(root, 0.2)
    settings.canvas.yview_moveto(0)
    pump(root, 0.2)

    print("picking Orbitron")
    settings._pick("Orbitron")
    pump(root, 0.4)
    assert settings.draft["font_family"] == "Orbitron"
    assert settings.lbl_selected.cget("text").endswith("Orbitron")
    capture(toplevel_hwnd(settings.win), OUT / "settings-fonts-orbitron.png")

    print("layout tab")
    settings._show_tab("layout")
    pump(root, 0.4)
    capture(toplevel_hwnd(settings.win), OUT / "settings-layout.png")

    print("date format + colour + slider")
    settings.date_entry.delete(0, "end")
    settings.date_entry.insert(0, "%d.%m.%Y  ·  W%V")
    settings._date_changed()
    pump(root, 0.3)
    assert settings.draft["date_format"].startswith("%d.%m.%Y")
    settings._swatches["Cargo"].winfo_children()[0].event_generate("<Button-1>")
    pump(root, 0.3)
    assert settings.draft["text_color"] == "#FF6A13", settings.draft["text_color"]
    settings._scales["digit_size"].set(180)
    pump(root, 0.3)
    assert settings.draft["digit_size"] == 180
    capture(toplevel_hwnd(settings.win), OUT / "settings-layout-cargo.png")
    settings._reset_look()
    pump(root, 0.3)
    assert settings.draft["text_color"] == "#FFFFFF"
    assert settings.draft["font_family"] == cw.DEFAULT_CONFIG["font_family"]
    settings._show_tab("font")
    settings._pick("Orbitron")
    pump(root, 0.2)

    print("applying")
    settings.apply()
    pump(root, 0.6)
    assert app.cfg["font_family"] == "Orbitron", app.cfg["font_family"]
    assert cw.load_config()["font_family"] == "Orbitron"

    print("all installed fonts list")
    settings._show_all.set(True)
    settings._rebuild_list()
    pump(root, 0.8)
    assert len(settings._cards) > 20, len(settings._cards)
    settings._show_all.set(False)
    settings._rebuild_list()
    pump(root, 0.3)

    settings.close()
    pump(root, 0.3)
    assert app.settings_win is None

    print("size sliders")
    app.apply_settings({"font_family": "Teko", "digit_size": 210,
                        "show_seconds": False})
    pump(root, 0.8)
    assert len(app.digit_labels) == 4, len(app.digit_labels)
    capture(toplevel_hwnd(root), OUT / "clock-teko-noseconds.png")

    app.apply_settings({"font_family": "Chakra Petch", "digit_size": 150,
                        "show_seconds": True})
    pump(root, 0.8)
    capture(toplevel_hwnd(root), OUT / "clock-chakra.png")

    print("compact / high-DPI geometry")
    for screen_h, screen_w, dpi in ((768, 1366, 96), (1080, 1920, 144)):
        settings2 = cw.SettingsWindow(app)
        settings2.win.winfo_screenheight = lambda h=screen_h: h
        settings2.win.winfo_screenwidth = lambda w=screen_w: w
        settings2.dpi_scale = dpi / 96.0
        settings2.compact = screen_h < 900
        settings2.preview_factor = 0.44 if settings2.compact else 0.62
        settings2.list_height = 246 if settings2.compact else cw.CARD_LIST_H
        settings2.canvas.configure(height=settings2.px(settings2.list_height))
        settings2._restyle_preview()
        settings2._fit_pages()
        settings2._center()
        pump(root, 0.5)
        h = settings2.win.winfo_height()
        rows_visible = settings2.canvas.winfo_height()
        print(f"  {screen_w}x{screen_h} @{dpi} dpi -> window {h}px, "
              f"list {rows_visible}px")
        assert rows_visible >= 140, rows_visible
        assert h <= screen_h - 30, (h, screen_h)
        capture(toplevel_hwnd(settings2.win), OUT / f"settings-{screen_h}p.png")
        settings2.close()
        pump(root, 0.2)

    print("menu")
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Settings…", command=app.open_settings)
    menu.add_command(label="Close", command=root.destroy)
    app._menu = menu
    assert app._menu.index("end") == 1
    menu.destroy()

    root.destroy()
    print("OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _report(traceback.format_exc())
        sys.exit(1)
