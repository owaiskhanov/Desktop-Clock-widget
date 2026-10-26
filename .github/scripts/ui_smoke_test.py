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
import json
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


def capture(hwnd: int, path: Path, width: int = 0, height: int = 0) -> None:
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    if not (width and height):
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


def capture_widget(widget, path: Path) -> None:
    """Capture a Tk Toplevel at its logical size.

    PrintWindow reports device pixels, so on a scaled screen the image would
    disagree with the geometry the layout was computed from.  Cropping to the
    logical size keeps the screenshots comparable across DPIs.
    """
    widget.update_idletasks()
    capture(toplevel_hwnd(widget), path,
            width=widget.winfo_width(), height=widget.winfo_height())


# --------------------------------------------------------------------------- #
def pump(root: tk.Tk, seconds: float = 1.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def check_config_and_defaults() -> None:
    """Orbitron is the default; untouched v1 configs migrate, others don't."""
    assert cw.DEFAULT_CONFIG["font_family"] == "Orbitron"
    assert cw.BUNDLED_FONTS[0]["family"] == "Orbitron"
    assert cw.DEFAULT_CONFIG["config_version"] == cw.CONFIG_VERSION == 2
    orig_dir, orig_path = cw.CONFIG_DIR, cw.CONFIG_PATH
    try:
        cw.CONFIG_DIR = OUT
        cw.CONFIG_PATH = OUT / "migration-test-config.json"
        # a v1.2-era config still on the old default -> Orbitron, persisted
        cw.CONFIG_PATH.write_text(json.dumps(
            {"font_family": "Chakra Petch", "digit_size": 150}),
            encoding="utf-8")
        cfg = cw.load_config()
        assert cfg["font_family"] == "Orbitron", cfg["font_family"]
        assert cfg["digit_size"] == 150
        saved = json.loads(cw.CONFIG_PATH.read_text(encoding="utf-8"))
        assert saved["font_family"] == "Orbitron"
        assert saved["config_version"] == 2
        # a v1 config where the user picked a font themselves is left alone
        cw.CONFIG_PATH.write_text(json.dumps({"font_family": "Teko"}),
                                  encoding="utf-8")
        assert cw.load_config()["font_family"] == "Teko"
        # re-picking the old default after migrating must stick
        cw.CONFIG_PATH.write_text(json.dumps(
            {"font_family": "Chakra Petch", "config_version": 2}),
            encoding="utf-8")
        assert cw.load_config()["font_family"] == "Chakra Petch"
        cw.CONFIG_PATH.unlink(missing_ok=True)
    finally:
        cw.CONFIG_DIR, cw.CONFIG_PATH = orig_dir, orig_path


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
    (OUT / "failure.txt").unlink(missing_ok=True)
    watchdog(180.0)
    cw.enable_dpi_awareness()
    cw.load_bundled_fonts()

    print("config defaults + migration")
    check_config_and_defaults()

    print("font registration")
    root = tk.Tk()
    root.withdraw()
    check_fonts()
    check_glyphs(root)
    root.destroy()

    print("building the clock")
    cfg = cw.load_config()
    # start from a NON-default face so that "Apply -> Orbitron" below is a
    # real change of the rendered font, not a no-op
    cfg["font_family"] = "Rajdhani"
    cfg["digit_size"] = cw.DEFAULT_CONFIG["digit_size"]
    cfg["show_seconds"] = True
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
    assert app.f_digit[0] == "Rajdhani", app.f_digit
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
    capture_widget(settings.win, OUT / "settings-fonts.png")

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
    capture_widget(settings.win, OUT / "settings-fonts-orbitron.png")

    print("layout tab")
    settings._show_tab("layout")
    pump(root, 0.4)
    capture_widget(settings.win, OUT / "settings-layout.png")

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
    capture_widget(settings.win, OUT / "settings-layout-cargo.png")
    settings._reset_look()
    pump(root, 0.3)
    assert settings.draft["text_color"] == "#FFFFFF"
    assert settings.draft["font_family"] == cw.DEFAULT_CONFIG["font_family"]
    settings._show_tab("font")
    settings._pick("Orbitron")
    pump(root, 0.2)

    print("applying")
    width_before = root.winfo_width()
    settings.apply()
    pump(root, 0.6)
    assert app.cfg["font_family"] == "Orbitron", app.cfg["font_family"]
    assert cw.load_config()["font_family"] == "Orbitron"
    # Regression (v1.2): Apply saved the config but the clock kept rendering
    # the startup font until a restart.  Assert on what is actually drawn:
    assert app.f_digit[0] == "Orbitron", app.f_digit
    assert app.f_caption[0] == "Orbitron", app.f_caption
    assert app.f_world[0] == "Orbitron", app.f_world
    assert app.f_date[0] == "Orbitron", app.f_date
    rendered = tkfont.Font(
        font=app.digit_labels[0].cget("font")).actual("family")
    assert rendered == "Orbitron", rendered
    width_after = root.winfo_width()
    print(f"  clock width {width_before}px (Rajdhani) -> "
          f"{width_after}px (Orbitron)")
    assert width_after > width_before + 100, (width_before, width_after)

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

    print("wider default font stays on screen")
    screen_w = root.winfo_screenwidth()
    root.geometry(f"+{screen_w - 60}+40")
    pump(root, 0.3)
    app.apply_settings({"font_family": "Orbitron", "digit_size": 150,
                        "show_seconds": True})
    pump(root, 0.5)
    right = root.winfo_x() + root.winfo_width()
    print(f"  clock right edge {right} on a {screen_w}px screen")
    assert right <= screen_w + 2, (right, screen_w)
    capture(toplevel_hwnd(root), OUT / "clock-orbitron.png")
    root.geometry("+80+80")
    pump(root, 0.2)

    print("size sliders")
    app.apply_settings({"font_family": "Teko", "digit_size": 210,
                        "show_seconds": False})
    pump(root, 0.8)
    assert len(app.digit_labels) == 4, len(app.digit_labels)
    capture(toplevel_hwnd(root), OUT / "clock-teko-noseconds.png")

    app.apply_settings({"font_family": "Chakra Petch", "digit_size": 150,
                        "show_seconds": True})
    pump(root, 0.8)
    assert app.f_digit[0] == "Chakra Petch", app.f_digit
    assert app.f_digit[1] == -150, app.f_digit
    capture(toplevel_hwnd(root), OUT / "clock-chakra.png")

    print("compact / high-DPI geometry")
    # Emulate other machines by faking the screen size and the DPI *before*
    # the dialog is built, exactly as the real app would see them.
    real_fpixels = root.winfo_fpixels
    real_screen = root.winfo_screenheight
    for screen_h, screen_w, dpi in ((768, 1366, 96), (1080, 1920, 144)):
        root.winfo_fpixels = lambda what, d=dpi: (
            d if what == "1i" else real_fpixels(what))
        root.winfo_screenheight = lambda h=screen_h: h
        settings2 = cw.SettingsWindow(app)
        settings2.win.winfo_screenheight = lambda h=screen_h: h
        settings2.win.winfo_screenwidth = lambda w=screen_w: w
        settings2._center()
        pump(root, 0.5)
        h = settings2.win.winfo_height()
        w = settings2.win.winfo_width()
        list_h = settings2.canvas.winfo_height()
        print(f"  {screen_w}x{screen_h} @ {dpi/96:.0%} -> window {w}x{h}, "
              f"list {list_h}px, scale {settings2.dpi_scale:.2f}")
        assert list_h >= 140, list_h
        assert h <= screen_h - 30, (h, screen_h)
        assert w <= screen_w - 20, (w, screen_w)
        if w <= root.winfo_screenwidth() and h <= root.winfo_screenheight():
            capture_widget(settings2.win, OUT / f"settings-{screen_h}p.png")
        settings2.close()
        pump(root, 0.2)
    root.winfo_fpixels = real_fpixels
    root.winfo_screenheight = real_screen

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
