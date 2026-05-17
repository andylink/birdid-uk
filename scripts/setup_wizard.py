#!/usr/bin/env python3
"""
BirdID-UK setup wizard.

Interactively configures the essential settings in config.toml, including
microphone selection and a live level test.

Run after install.sh (venv must be active so sounddevice is available):

    source venv/bin/activate
    python scripts/setup_wizard.py
"""

import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.toml"
CONFIG_EXAMPLE = REPO_ROOT / "config.toml.example"
INSTALL_SH = REPO_ROOT / "install.sh"

RECORD_SECONDS = 3
SAMPLE_RATE = 48000

# ── ANSI helpers ──────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _tty_input(prompt: str) -> str:
    """Read a line from /dev/tty so the wizard works even when stdin is piped."""
    if sys.stdin.isatty():
        return input(prompt)
    # Piped stdin — fall back to /dev/tty
    try:
        with open("/dev/tty") as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty.readline().rstrip("\n")
    except OSError:
        return ""


def ask(prompt: str, default: str = "", validator=None) -> str:
    """Prompt for input; return stripped answer or default on empty."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            raw = _tty_input(f"  {prompt}{suffix}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
        value = raw if raw else default
        if validator:
            result = validator(value)
            if result is True:
                return value
            print(f"  {RED}[!]{RESET} {result}")
        else:
            return value


def ask_yn(prompt: str, default: str = "y") -> bool:
    """Ask a yes/no question."""
    opts = "Y/n" if default.lower() == "y" else "y/N"
    while True:
        try:
            raw = _tty_input(f"  {prompt} [{opts}]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
        value = raw if raw else default.lower()
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print(f"  {RED}[!]{RESET} Please enter y or n.")


def section(title: str):
    print()
    print(f"  {BOLD}{CYAN}── {title}{RESET}")
    print()


def info(msg: str):
    print(f"  {GREEN}[+]{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}[!]{RESET} {msg}")


def err(msg: str):
    print(f"  {RED}[✗]{RESET} {msg}")


# ── Validators ────────────────────────────────────────────────────────────────

def validate_timezone(tz: str):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return True
    except Exception:
        return (
            f"Unknown timezone '{tz}'.  Use an IANA name such as 'Europe/London'.\n"
            "  Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )


def validate_lat(s: str):
    try:
        v = float(s)
    except ValueError:
        return "Enter a decimal number, e.g. 52.5"
    if -90 <= v <= 90:
        return True
    return "Latitude must be between -90 and 90."


def validate_lon(s: str):
    try:
        v = float(s)
    except ValueError:
        return "Enter a decimal number, e.g. -1.5"
    if -180 <= v <= 180:
        return True
    return "Longitude must be between -180 and 180."


# ── Device listing ────────────────────────────────────────────────────────────

def list_input_devices():
    """Return [(device_index, name, max_input_channels, default_samplerate), ...]
    for all devices that have at least one input channel.
    Returns None if sounddevice is not available."""
    try:
        import sounddevice as sd
    except ImportError:
        return None

    result = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            result.append(
                (i, dev["name"], int(dev["max_input_channels"]), int(dev["default_samplerate"]))
            )
    return result


def select_device(devices: list) -> tuple:
    """Print a table of input devices and let the user pick one.
    Returns (device_index, device_name)."""
    print(f"  {'#':<5}  {'Device name':<46} {'Ch':>3}  {'Default rate'}")
    print(f"  {'─'*5}  {'─'*46} {'─'*3}  {'─'*12}")
    for row_n, (dev_i, name, ch, sr) in enumerate(devices, start=1):
        print(f"  {row_n:<5}  {name:<46} {ch:>3}  {sr}")
    print()

    def _validate(s: str):
        try:
            n = int(s)
        except ValueError:
            return "Enter the row number."
        if 1 <= n <= len(devices):
            return True
        return f"Enter a number between 1 and {len(devices)}."

    choice = ask(f"Choose microphone (1–{len(devices)})", default="1", validator=_validate)
    dev_i, name, _ch, _sr = devices[int(choice) - 1]
    return dev_i, name


# ── Microphone test ───────────────────────────────────────────────────────────

def rms_dbfs(audio) -> float:
    """RMS level in dBFS for a float32 numpy array."""
    import numpy as np
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    if rms < 1e-10:
        return -100.0
    return 20.0 * math.log10(rms)


def level_bar(db: float, width: int = 40) -> str:
    """ASCII bar chart for a dBFS value (scale: −60 → 0)."""
    clamped = max(-60.0, min(0.0, db))
    filled = round((clamped + 60.0) / 60.0 * width)
    bar = "█" * filled + "░" * (width - filled)
    if db > -3:
        colour = RED
    elif db > -20:
        colour = GREEN
    else:
        colour = YELLOW
    return f"{colour}{bar}{RESET}  {db:+.1f} dBFS"


def test_microphone(device_index: int, device_name: str) -> bool:
    """Record RECORD_SECONDS of audio, show the level, offer playback.
    Returns True if the level looks healthy."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        warn("sounddevice/numpy not importable — skipping mic test.")
        return True

    print()
    info(f"Recording {RECORD_SECONDS} s from '{device_name}'…")
    print(f"  {YELLOW}Make some noise near the microphone!{RESET}")
    print()

    try:
        recording = sd.rec(
            int(RECORD_SECONDS * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device_index,
        )
        for remaining in range(RECORD_SECONDS, 0, -1):
            print(f"\r  {YELLOW}●{RESET} Recording… {remaining}s  ", end="", flush=True)
            time.sleep(1)
        print(f"\r  {GREEN}●{RESET} Recording complete.      ")
        sd.wait()
    except Exception as exc:
        err(f"Recording failed: {exc}")
        warn("Check the device index and ensure the microphone is connected.")
        return False

    db = rms_dbfs(recording)
    print(f"  Level:  {level_bar(db)}")
    print()

    healthy = True
    if db < -60:
        warn("Very low signal — is the microphone connected and unmuted?")
        warn("Try 'alsamixer' to unmute the capture channel, or pick a different device.")
        healthy = False
    elif db > -3:
        warn("Signal is very loud and may clip.  Reduce the input gain in alsamixer.")
    else:
        info("Audio level looks good.")

    # Playback ─────────────────────────────────────────────────────────────────
    print()
    if ask_yn("Play back the recording to check audio quality?", default="y"):
        try:
            info("Playing back…")
            sd.play(recording, samplerate=SAMPLE_RATE)
            sd.wait()
            info("Playback complete.")
        except Exception as exc:
            warn(f"Playback failed (normal on a headless server with no audio output): {exc}")

    return healthy


# ── Config patching ───────────────────────────────────────────────────────────

def patch_config(path: Path, patches: dict):
    """Replace whole lines in a TOML file using regex.

    patches = {regex_pattern: replacement_line}
    Each pattern is applied once (first match) in MULTILINE mode.
    """
    text = path.read_text()
    for pattern, replacement in patches.items():
        new_text, n = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
        if n == 0:
            warn(f"Could not find pattern in config.toml: {pattern!r}")
        text = new_text
    path.write_text(text)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print(f"  {BOLD}BirdID-UK — Setup Wizard{RESET}")
    print("  ─────────────────────────────────────────────")
    print("  Configures the essential settings in config.toml.")
    print("  Press Enter to accept the value shown in [brackets].")

    # Ensure config.toml exists ────────────────────────────────────────────────
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE.exists():
            shutil.copy(CONFIG_EXAMPLE, CONFIG_PATH)
            info("Created config.toml from example.")
        else:
            err("config.toml not found and config.toml.example is missing.")
            sys.exit(1)

    # ── 1 / 5  Station details ─────────────────────────────────────────────────
    section("1 / 5  Station details")

    station_name = ask("Station name (shown in the dashboard)", default="My Garden")
    timezone = ask(
        "Timezone (IANA name)",
        default="Europe/London",
        validator=validate_timezone,
    )

    # ── 2 / 5  Location ───────────────────────────────────────────────────────
    section("2 / 5  Location")

    print("  Used for accurate sunrise/sunset calculations (nocturnal species filter).")
    print()
    print(f"  {DIM}How to find your coordinates:{RESET}")
    print(f"  {DIM}  1. Open Google Maps  →  https://maps.google.com{RESET}")
    print(f"  {DIM}  2. Right-click your location on the map{RESET}")
    print(f"  {DIM}  3. Click the coordinates shown at the top of the menu{RESET}")
    print(f"  {DIM}     (e.g. 52.4862, -1.8904) — they are now on your clipboard{RESET}")
    print()

    lat = ask("Latitude  (decimal degrees, e.g.  52.5)", default="52.5", validator=validate_lat)
    lon = ask("Longitude (decimal degrees, e.g. -1.5)", default="-1.5", validator=validate_lon)

    # ── 3 / 5  Microphone selection ───────────────────────────────────────────
    section("3 / 5  Microphone selection")

    devices = list_input_devices()
    device_index = 0
    device_name = "default (system)"

    if devices is None:
        warn("sounddevice is not importable.")
        warn("Make sure the project venv is active:  source venv/bin/activate")
        warn("Skipping device selection — edit 'device' in config.toml manually.")
    elif not devices:
        warn("No input devices found.")
        warn("Connect a microphone and re-run the wizard, or set 'device' manually.")
    else:
        print("  Available input devices:\n")
        device_index, device_name = select_device(devices)
        info(f"Selected device {device_index}: {device_name}")

    # ── 4 / 5  Microphone test ────────────────────────────────────────────────
    section("4 / 5  Microphone test")

    if devices:
        if ask_yn(f"Test microphone '{device_name}' now?", default="y"):
            test_microphone(device_index, device_name)
        else:
            info("Skipping mic test.")
    else:
        info("No devices found — skipping mic test.")

    # ── 5 / 5  Write config ───────────────────────────────────────────────────
    section("5 / 5  Writing configuration")

    lat_f = float(lat)
    lon_f = float(lon)

    # Escape station_name for TOML (replace " with \")
    safe_station = station_name.replace("\\", "\\\\").replace('"', '\\"')
    safe_timezone = timezone.replace("\\", "\\\\").replace('"', '\\"')

    patches = {
        # Match the whole line (handles inline comments and trailing spaces)
        r'^timezone\s*=.*$':      f'timezone     = "{safe_timezone}"',
        r'^station_name\s*=.*$':  f'station_name = "{safe_station}"',
        r'^lat\s*=.*$':           f'lat = {lat_f}',
        r'^lon\s*=.*$':           f'lon = {lon_f}',
        r'^device\s*=.*$':        f'device = {device_index}',
    }
    patch_config(CONFIG_PATH, patches)

    info("config.toml updated with:")
    info(f"  station_name = \"{station_name}\"")
    info(f"  timezone     = \"{timezone}\"")
    info(f"  lat          = {lat_f}")
    info(f"  lon          = {lon_f}")
    info(f"  device       = {device_index}")

    # ── Systemd ───────────────────────────────────────────────────────────────
    print()
    if ask_yn(
        "Install as a background service (auto-starts at boot)?",
        default="n",
    ):
        info(f"Running: bash {INSTALL_SH} --systemd")
        result = subprocess.run(["bash", str(INSTALL_SH), "--systemd"])
        if result.returncode != 0:
            warn("Systemd install reported an error — check the output above.")
        else:
            info("Service installed.")
            info("Start now with:  sudo systemctl start birddetector.target")
            info("View logs with:  journalctl -u birddetector-capture -f")
    else:
        info("Skipping systemd setup.")
        info("Add it later with:  bash install.sh --systemd")

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print("  ─────────────────────────────────────────────")
    print(f"  {BOLD}{GREEN}Setup complete!{RESET}")
    print()
    print("  To start the detector + dashboard:")
    print(f"    source {REPO_ROOT}/venv/bin/activate")
    print(f"    python {REPO_ROOT}/main.py")
    print()
    print("  Then open the dashboard in any browser on your network:")
    print("    http://<this-machine-ip>:8080")
    print()
    print(f"  {DIM}Find the IP with:  hostname -I{RESET}")
    print()


if __name__ == "__main__":
    main()
