"""System tray battery indicator for ATK / VXE / VGN wireless mice.

Polls the mouse HID Output Report (17 B) every ``poll_rate`` seconds,
displays the battery percentage as a tray icon coloured by charge level,
and plays a blinking animation while charging.
"""

import ctypes
import logging
import os
import sys
import threading
import time
import winreg
from datetime import datetime, timedelta

import hid
import wx
from PIL import Image, ImageDraw, ImageFont
from wx.adv import NotificationMessage, TaskBarIcon

import models

ctypes.windll.shcore.SetProcessDpiAwareness(2)
logging.basicConfig(level=logging.INFO)

# ── Colours ────────────────────────────────────────────────────────
RED    = (255, 0, 0)     # battery < 10 %
GREEN  = (71, 255, 12)   # (charging animation icons only)
BLUE   = (91, 184, 255)  # battery ≥ 30 % / disconnected fallback
YELLOW = (255, 255, 0)   # 10–29 %

# ── User settings ───────────────────────────────────────────────────
poll_rate = 15                       # seconds between polls (wireless)
foreground_color = BLUE              # colour when no device is connected
background_color = (0, 0, 0, 0)      # RGBA – transparent
font = "consola.ttf"                 # last-resort font file name

# ── Voltage → percent lookup (from VGN firmware) ────────────────────
# 21 thresholds spanning 3 050 mV … 4 110 mV in ~5 % steps.
VOLTAGE_TABLE = [
    3050, 3420, 3480, 3540, 3600, 3660, 3720, 3760, 3800, 3840,
    3880, 3920, 3940, 3960, 3980, 4000, 4020, 4040, 4060, 4080, 4110,
]


def voltage_to_level(voltage: int, charging: bool) -> int:
    """Convert a battery voltage (mV) to a percentage (0‑100)."""
    if voltage >= VOLTAGE_TABLE[-1]:
        return 99 if charging else 100

    idx = -1
    for i, v in enumerate(VOLTAGE_TABLE):
        if voltage < v:
            idx = i
            break

    if idx <= 0:
        return 0

    prev_v = VOLTAGE_TABLE[idx - 1]
    step = (VOLTAGE_TABLE[idx] - prev_v) / 5
    level = round((voltage - prev_v) / step + (idx - 1) * 5)

    if level in (0, 15):
        level += 1    # firmware reports 0 % / 15 % as 1 step too low on some models

    return min(level, 100)


def get_resource(relative_path: str) -> str:
    """Resolve a path relative to the script (or PyInstaller bundle)."""
    try:
        base_path = sys._MEIPASS          # PyInstaller temp directory
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def save_reg(data: str) -> None:
    """Persist the last-full-charge timestamp in the registry."""
    with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, "SOFTWARE") as soft:
        with winreg.CreateKey(soft, "ATK_Tray") as key:
            winreg.SetValueEx(key, "FullchargeDate", 0, winreg.REG_SZ, data)


def get_reg(name: str, reg_path: str) -> datetime | None:
    """Read a persisted timestamp from the registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
            value = winreg.QueryValueEx(key, name)[0]
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
    except OSError:
        return None


# ── Autostart helpers ───────────────────────────────────────────────

RUN_KEY = R"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ATK_tray"


def is_autostart_enabled() -> bool:
    """Check if autostart entry exists in the registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except OSError:
        return False


def enable_autostart() -> None:
    """Add this exe to HKCU\\...\\Run for automatic startup."""
    exe_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')


def disable_autostart() -> None:
    """Remove the autostart registry entry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except OSError:
        pass  # already removed


def format_timedelta(delta: timedelta) -> str:
    """Pretty-print a timedelta, e.g. ``2 days, 05:33:00``."""
    days = delta.days
    total_seconds = int(delta.total_seconds()) - days * 86400
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days} days, {hours:02d}:{minutes:02d}:{seconds:02d}"


def detect_mouse() -> models.MouseClass | None:
    """Return the first supported mouse found on the USB bus."""
    for m in models.atk_mice:
        wireless = hid.enumerate(m.vid, m.pid_wireless)
        wired_vid = m.vid_wired if m.vid_wired is not None else m.vid
        wired = hid.enumerate(wired_vid, m.pid_wired)
        if wireless or wired:
            logging.info("Detected model: %s", m.model)
            return m
    return None


def get_battery(mouse: models.MouseClass) -> tuple[int, bool] | None:
    """Query the mouse battery via Output Report → Input Report.

    Returns ``(percent, charging)`` or ``None`` on failure.
    Up to 3 attempts; each attempt opens the device fresh.
    """
    try:
        device_path = get_device_path(mouse)
    except RuntimeError as e:
        logging.warning("get_device_path failed: %s", e)
        return None

    report = bytearray(17)
    report[0] = 8          # HID Report ID
    report[1] = 4          # command = BatteryLevel
    report[16] = mouse.battery_crc

    for attempt in range(3):
        try:
            device = hid.Device(path=device_path)
        except Exception as e:
            logging.warning("[attempt %d] open failed: %s", attempt + 1, e)
            time.sleep(0.5)
            continue

        try:
            try:
                device.write(bytes(report))
            except Exception as e:
                logging.warning("[attempt %d] write failed: %s", attempt + 1, e)
                time.sleep(0.5)
                continue

            try:
                res = device.read(17, timeout=1000)
            except Exception as e:
                logging.warning("[attempt %d] read failed: %s", attempt + 1, e)
                time.sleep(0.5)
                continue
        finally:
            device.close()

        if not res or len(res) < 10:
            logging.warning("[attempt %d] short (%d B)", attempt + 1, len(res) if res else 0)
            time.sleep(0.5)
            continue

        # Wire format (aligned with VGN firmware receivedData):
        #   res[0]  = reportId (8)
        #   res[1]  = command  (4)
        #   res[6]  = raw battery %  (receivedData[5])
        #   res[7]  = charging flag   (receivedData[6])
        #   res[8:10] = voltage (mV, big-endian)
        raw_level = res[6]
        charging = res[7] == 1
        voltage = (res[8] << 8) | res[9]

        if voltage > 0:
            level = voltage_to_level(voltage, charging)
        else:
            logging.info("Voltage=0, skipping (device may be switching modes)")
            return None

        logging.info("Raw=%d %%  V=%d mV  →  %d %%  Charging=%s",
                     raw_level, voltage, level, charging)
        return level, charging

    logging.warning("All 3 attempts failed")
    return None


def get_device_path(mouse: models.MouseClass) -> str:
    """Resolve the HID device path for *mouse* (wireless first, then wired)."""
    device_list = hid.enumerate(mouse.vid, mouse.pid_wireless)
    if not device_list:
        wired_vid = mouse.vid_wired if mouse.vid_wired is not None else mouse.vid
        device_list = hid.enumerate(wired_vid, mouse.pid_wired)
        if not device_list:
            raise RuntimeError(
                f"Device not found: ({mouse.vid:04X}:{mouse.pid_wireless:04X} "
                f"or {wired_vid:04X}:{mouse.pid_wired:04X})"
            )
    for d in device_list:
        if d["usage_page"] == mouse.usage_page and d["usage"] == mouse.usage:
            return d["path"]
    raise RuntimeError(
        f"No matching usage for {mouse.model}. "
        f"Available: {[(d.get('usage_page'), d.get('usage')) for d in device_list]}"
    )


# ── Icon helpers ────────────────────────────────────────────────────

def _get_font_size(text: str) -> int:
    """Return a font size (px) that fits 1‑3 digit text into a 256×256 icon."""
    if len(text) == 3:
        return 150
    if len(text) == 2:
        return 220
    return 220     # 1 digit or unexpected


def _pil_to_wx(image: Image.Image) -> wx.Bitmap:
    """Convert a Pillow RGBA image to a wxPython bitmap."""
    w, h = image.size
    return wx.Bitmap.FromBufferRGBA(w, h, image.tobytes())


def create_icon(text: str, color: tuple[int, int, int],
                font_name: str) -> wx.Bitmap:
    """Render *text* with a bold outlined font onto a 256×256 RGBA icon."""
    image = Image.new("RGBA", (256, 256), background_color)
    draw = ImageDraw.Draw(image)
    size = _get_font_size(text)

    # Font priority: Segoe UI Bold → Consolas Bold → user font → Pillow default
    try:
        fnt = ImageFont.truetype("segoeuib.ttf", size)
    except Exception:
        try:
            fnt = ImageFont.truetype("consolab.ttf", size)
        except Exception:
            try:
                fnt = ImageFont.truetype(font_name, size)
            except Exception:
                fnt = ImageFont.load_default()

    # Centre the text using its bounding box
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (256 - tw) // 2 - bbox[0]
    y = (256 - th) // 2 - bbox[1] - 10

    # Dark outline + coloured fill for legibility at tray size
    outline = (0, 0, 0, 180)
    draw.text((x, y), text, font=fnt, fill=outline,
              stroke_width=3, stroke_fill=outline)
    draw.text((x, y), text, font=fnt, fill=color,
              stroke_width=1, stroke_fill=color)
    return _pil_to_wx(image)


# ── wxPython UI ─────────────────────────────────────────────────────

class MyTaskBarIcon(TaskBarIcon):
    """Windows system tray icon with popup menu."""

    def __init__(self, frame: "MyFrame") -> None:
        super().__init__()
        self.frame = frame
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.OnClick)

    def CreatePopupMenu(self) -> wx.Menu:
        menu = wx.Menu()
        self.item_autostart = wx.MenuItem(menu, wx.ID_ANY, "Run at startup", kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU, self.OnToggleAutostart, id=self.item_autostart.GetId())
        item_reset = wx.MenuItem(menu, wx.ID_ANY, "Reset timer")
        self.Bind(wx.EVT_MENU, self.OnResetTimer, id=item_reset.GetId())
        item_exit = wx.MenuItem(menu, wx.ID_ANY, "Exit")
        self.Bind(wx.EVT_MENU, self.OnTaskBarExit, id=item_exit.GetId())
        menu.Append(self.item_autostart)
        menu.AppendSeparator()
        menu.Append(item_reset)
        menu.Append(item_exit)
        self.sync_autostart_check()
        return menu

    def OnTaskBarExit(self, event: wx.MenuEvent) -> None:
        self.Destroy()
        self.frame.Destroy()

    def OnResetTimer(self, event: wx.MenuEvent) -> None:
        """Manually reset the 'time since last full charge' counter."""
        self.frame.full_charge_date = datetime.now()
        save_reg(self.frame.full_charge_date.strftime("%d.%m.%Y %H:%M:%S"))
        logging.info("Reset full charge date → %s", self.frame.full_charge_date)

    def OnClick(self, event: wx.TaskBarIconEvent) -> None:
        """Left-click: force a battery refresh if last read failed."""
        if self.frame.read_failed:
            self.frame.show_battery()

    def OnToggleAutostart(self, event: wx.MenuEvent) -> None:
        """Toggle autostart registry entry."""
        if self.item_autostart.IsChecked():
            enable_autostart()
        else:
            disable_autostart()

    def sync_autostart_check(self) -> None:
        """Sync the menu checkmark with the registry state."""
        self.item_autostart.Check(is_autostart_enabled())


class MyFrame(wx.Frame):
    """Hidden top-level window that owns the tray icon and worker threads."""

    def __init__(self, parent: wx.Window | None, title: str) -> None:
        super().__init__(parent, title=title, pos=(-1, -1), size=(290, 280))
        self.SetSize(350, 250)
        self.tray_icon = MyTaskBarIcon(self)
        self.tray_icon.SetIcon(create_icon(" ", foreground_color, font), "")
        self.full_charge_date = get_reg("FullchargeDate", R"SOFTWARE\ATK_Tray")
        self.battery_str = ""       # currently displayed value ("-", "95", …)
        self.wired = False          # True while charging cable is connected
        self.read_failed = False    # True when last battery read attempt failed
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Centre()
        self.mouse = detect_mouse()

        if self.mouse is None:
            self.battery_str = "-"
            self.tray_icon.SetIcon(
                create_icon("-", foreground_color, font), "No Mouse Detected")
        else:
            self.notification = NotificationMessage(
                title=self.mouse.model, message="Charged 100%")
            self.notification.SetFlags(wx.ICON_INFORMATION)
            self.notification.UseTaskBarIcon(self.tray_icon)
            self.animation_thread = threading.Thread(
                target=self.charge_animation, daemon=True)
            self.thread = threading.Thread(
                target=self.thread_worker, daemon=True)
            self.thread.start()

    def get_tooltip(self) -> str:
        """Build the hover tooltip (model name + time since last full charge)."""
        if self.full_charge_date:
            delta = datetime.now() - self.full_charge_date
            return self.mouse.model + f"\n{format_timedelta(delta)}"
        return self.mouse.model if self.mouse else "No Mouse"

    def OnClose(self, event: wx.CloseEvent) -> None:
        """Hide the settings window instead of destroying it."""
        if self.IsShown():
            self.Hide()

    def thread_worker(self) -> None:
        """Main polling loop.

        Normal wireless: ``poll_rate`` seconds.
        Charging:         1 second (to drive the animation).
        Disconnected:     3 seconds (fast re‑detect) × 5, then poll_rate.
        Mode switch:      3 seconds (one accelerated cycle).
        """
        self.fullcharged = False
        fail_count = 0
        while True:
            prev_wired = self.wired

            self.show_battery()

            if self.read_failed:
                fail_count += 1
                wait = 3 if fail_count <= 5 else poll_rate
            elif prev_wired and not self.wired:
                fail_count = 0
                wait = 3               # just unplugged – speed up once
            else:
                fail_count = 0
                wait = 1 if self.wired else poll_rate

            time.sleep(wait)

    def show_battery(self) -> None:
        """Read the battery and update the tray icon / tooltip."""
        if self.mouse is None:
            self.read_failed = True
            self.battery_str = "-"
            self.tray_icon.SetIcon(
                create_icon("-", foreground_color, font), "No Mouse Detected")
            return

        result = get_battery(self.mouse)

        if result is None:
            self.read_failed = True
            if hasattr(self, "animation_thread") and self.animation_thread.is_alive():
                self.stop_animation = True
                self.animation_thread.join()
            # Keep last known battery icon — don't overwrite with "-"
            return

        battery, wired = result
        self.read_failed = False
        self.battery_str = str(battery)
        self.wired = wired

        # Colour by charge level
        if battery >= 30:
            clr = BLUE
        elif battery >= 10:
            clr = YELLOW
        else:
            clr = RED

        # ── Charging state machine ──
        if wired and battery < 100:
            # Charging in progress → blink animation
            self.fullcharged = False
            self.stop_animation = False
            if not self.animation_thread.is_alive():
                self.animation_thread = threading.Thread(
                    target=self.charge_animation, daemon=True)
                self.animation_thread.start()
            return

        if battery == 100 and wired:
            # Fully charged on cable → solid blue battery icon + notify once
            self.stop_animation = True
            if self.animation_thread.is_alive():
                self.animation_thread.join()
            self.tray_icon.SetIcon(
                wx.Icon(get_resource(R".\icons\battery_100.ico")),
                self.get_tooltip())
            if not self.fullcharged:
                self.fullcharged = True
                self.notification.Show(
                    timeout=wx.adv.NotificationMessage.Timeout_Auto)
            return

        if battery == 100 and not wired:
            # Fully charged wireless → record timestamp, blue icon
            if self.fullcharged:
                self.full_charge_date = datetime.now()
                save_reg(self.full_charge_date.strftime("%d.%m.%Y %H:%M:%S"))
                logging.info("Reset full charge date → %s", self.full_charge_date)
            self.fullcharged = False
            self.stop_animation = True
            self.tray_icon.SetIcon(
                wx.Icon(get_resource(R".\icons\battery_100.ico")),
                self.get_tooltip())
            return

        # ── Normal wireless discharge → coloured numeric icon ──
        self.fullcharged = False
        self.stop_animation = True
        if self.animation_thread.is_alive():
            self.animation_thread.join()
        self.tray_icon.SetIcon(
            create_icon(self.battery_str, clr, font), self.get_tooltip())

    def charge_animation(self) -> None:
        """Loop 0 % → 50 % → 100 % icons while ``stop_animation`` is False."""
        while not self.stop_animation:
            self.tray_icon.SetIcon(
                wx.Icon(get_resource(R".\icons\battery_0.ico")),
                self.get_tooltip())
            time.sleep(0.5)
            self.tray_icon.SetIcon(
                wx.Icon(get_resource(R".\icons\battery_50.ico")),
                self.get_tooltip())
            time.sleep(0.5)
            self.tray_icon.SetIcon(
                wx.Icon(get_resource(R".\icons\battery_100.ico")),
                self.get_tooltip())
            time.sleep(0.5)


class MyApp(wx.App):
    """wxPython application entry point."""

    def OnInit(self) -> bool:
        frame = MyFrame(None, title="ATK Tray settings")
        frame.Show(False)
        self.SetTopWindow(frame)
        return True


def main() -> None:
    app = MyApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
