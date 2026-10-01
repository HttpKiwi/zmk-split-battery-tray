#!/usr/bin/env python3
"""Read left/right ZMK split battery % from the dongle vendor HID interface.

Discovers /dev/hidraw* the same way as bogamie/zmk-split-battery-tray:
VID:PID 1d50:615e + report descriptor Vendor Usage Page 0xFF00.

Prints one line for Quickshell / scripts:
  L: 85%  R: 90%  Status: AVAILABLE
or when the dongle is missing:
  Status: MISSING

Exit 0 always so bar widgets can poll safely.
"""

from __future__ import annotations

import argparse
import os
import select
import struct
import sys
import time
from pathlib import Path

VENDOR_ID = 0x1D50
PRODUCT_ID = 0x615E
REPORT_ID = 0x01
UNKNOWN = 0xFF
VENDOR_PREFIX = bytes([0x06, 0x00, 0xFF])
HIDRAW = Path("/sys/class/hidraw")


def expected_hid_id() -> str:
    return f"HID_ID=0003:{VENDOR_ID:08X}:{PRODUCT_ID:08X}"


def find_hidraw() -> Path | None:
    if not HIDRAW.is_dir():
        return None
    want = expected_hid_id()
    for node in sorted(HIDRAW.iterdir()):
        uevent = node / "device" / "uevent"
        desc = node / "device" / "report_descriptor"
        try:
            text = uevent.read_text(errors="ignore")
            if want not in text:
                continue
            prefix = desc.read_bytes()[:3]
            if prefix != VENDOR_PREFIX:
                continue
            return Path("/dev") / node.name
        except OSError:
            continue
    return None


def fmt(level: int) -> str:
    return "—" if level == UNKNOWN else f"{level}%"


def read_once(path: Path, timeout: float) -> tuple[int, int] | None:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                continue
            try:
                chunk = os.read(fd, 64)
            except BlockingIOError:
                continue
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 3:
                report_id, left, right = buf[0], buf[1], buf[2]
                buf = buf[3:]
                if report_id == REPORT_ID:
                    return left, right
        return None
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.4,
        help="seconds to wait for one HID report (default 0.4)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print {\"left\":n,\"right\":n,\"status\":\"…\"}",
    )
    args = parser.parse_args()

    path = find_hidraw()
    if path is None:
        if args.json:
            print('{"left":null,"right":null,"status":"MISSING"}')
        else:
            print("Status: MISSING")
        return 0

    levels = read_once(path, args.timeout)
    if levels is None:
        if args.json:
            print('{"left":null,"right":null,"status":"WAITING"}')
        else:
            print("Status: WAITING")
        return 0

    left, right = levels
    if args.json:
        def j(v: int):
            return "null" if v == UNKNOWN else str(v)

        print(f'{{"left":{j(left)},"right":{j(right)},"status":"AVAILABLE"}}')
    else:
        print(f"L: {fmt(left)}  R: {fmt(right)}  Status: AVAILABLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
