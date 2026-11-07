#!/usr/bin/env python3
"""Asks the TV to sleep and wake with your active hours, over HDMI. Runs once a minute, and only acts when the hours change over, so a TV you've switched on yourself stays on."""
import datetime as dt
import glob
import json
import os
import subprocess
from pathlib import Path

RUN = Path(os.environ.get("THESEUS_WALL_RUN", "/run/theseus-wall"))


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def wanted(display, now):
    """'on' or 'off', or None if no hours are set. The same sum as the page, including hours that cross midnight."""
    if not isinstance(display, dict) or not display.get("on") or not display.get("off"):
        return None
    start, end = minutes(display["on"]), minutes(display["off"])
    t = now.hour * 60 + now.minute
    inside = start <= t < end if start <= end else t >= start or t < end
    return "on" if inside else "off"


def tell_tv(state):
    """A TV or monitor that doesn't answer just stays as it is, and the page is black either way."""
    for device in glob.glob("/dev/cec*"):
        try:
            subprocess.run(["cec-ctl", "-d", device, "--playback"], capture_output=True, timeout=10)
            subprocess.run(["cec-ctl", "-d", device, "--to", "0", "--image-view-on" if state == "on" else "--standby"], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass


def main(now=None):
    try:
        display = json.loads((RUN / "wall.json").read_text()).get("display")
        state = wanted(display, now or dt.datetime.now())
    except (OSError, ValueError, AttributeError):
        return
    if state is None:
        return
    remembered = RUN / "power-state"
    try:
        if remembered.read_text() == state:
            return
    except OSError:
        pass
    remembered.write_text(state)
    tell_tv(state)


if __name__ == "__main__":
    main()
