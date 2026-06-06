"""Supported mouse models and their HID parameters."""

from dataclasses import dataclass

__all__ = ["atk_mice", "MouseClass"]


@dataclass
class MouseClass:
    """HID device descriptor for a wireless mouse model.

    Attributes:
        model: Human-readable model name.
        vid: USB Vendor ID of the wireless dongle.
        pid_wireless: USB Product ID in wireless (2.4G) mode.
        pid_wired: USB Product ID in wired mode.
        usage_page: HID Usage Page for the battery-reporting collection.
        usage: HID Usage for the battery-reporting collection.
        vid_wired: USB Vendor ID in wired mode. Defaults to ``vid`` if omitted.
        battery_crc: CRC byte appended to the battery query Output Report (default 73).
    """
    model: str
    vid: int
    pid_wireless: int
    pid_wired: int
    usage_page: int
    usage: int
    vid_wired: int | None = None
    battery_crc: int = 73


atk_f1_ultimate = MouseClass(
    model="ATK F1 Ultimate",
    vid=0x373B, pid_wireless=0x1031, pid_wired=0x102E,
    usage_page=0xFF02, usage=0x0002,
)
vxe_mad_r = MouseClass(
    model="VXE MAD R",
    vid=0x373B, pid_wireless=0x104D, pid_wired=0x103F,
    usage_page=0xFF02, usage=0x0002,
)
vxe_mad_r_major_plus = MouseClass(
    model="VXE MAD R Major Plus",
    vid=0x373B, pid_wireless=0x1040, pid_wired=0x104C,
    usage_page=0xFF02, usage=0x0002,
)
vxe_r1_pro_max = MouseClass(
    model="VXE R1 Pro Max",
    vid=0x3554, pid_wireless=0xF58A, pid_wired=0xF58C,
    usage_page=0xFF02, usage=0x0002,
)
vxe_r1_se_plus = MouseClass(
    model="VXE R1 SE+",
    vid=0x3554, pid_wireless=0xF58E, pid_wired=0xF58F,
    usage_page=0xFF02, usage=0x0002,
)
vgn_f1_pro = MouseClass(
    model="VGN F1 Pro",
    vid=0x3554, pid_wireless=0xF503, pid_wired=0xF502,
    usage_page=0xFF02, usage=0x0002,
)
atk_a9_ultimate = MouseClass(
    model="ATK A9 Ultimate",
    vid=0x373B, pid_wireless=0x11D9, pid_wired=0x11B6,
    usage_page=0xFF02, usage=0x0002,
)
vgn_dragonfly_3_master = MouseClass(
    model="VGN Dragonfly 3 Master",
    vid=0x391D, pid_wireless=0x1A05, pid_wired=0xFB59,
    vid_wired=0x3554,
    usage_page=0xFF02, usage=0x0002,
    battery_crc=73,
)

atk_mice = [
    atk_f1_ultimate,
    atk_a9_ultimate,
    vxe_mad_r,
    vxe_mad_r_major_plus,
    vxe_r1_pro_max,
    vxe_r1_se_plus,
    vgn_f1_pro,
    vgn_dragonfly_3_master,
]
