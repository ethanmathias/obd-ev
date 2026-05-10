#!/usr/bin/env python3
"""
OBD adapter auto-pair / auto-bind.

Two modes:
  * Default (boot):     find any *already-paired* ELM327-like adapter and bind
                        it to /dev/rfcomm0. Fast, idempotent, no scanning.
  * --discover:         scan for new ELM327-like adapters, pair + trust the
                        first one found, then bind. Used during imaging or
                        when a participant swaps adapters.

Why two modes: Bluetooth scanning is slow and unreliable in the car; we want
boot to be deterministic. Discovery is a deliberate, manual step.
"""
from __future__ import annotations

import argparse
import os
import pty
import re
import select
import subprocess
import sys
import time
from typing import List, Optional, Tuple

OBD_NAME_RE = re.compile(r"(ELM327|OBDII|OBD-II|OBD2|V-?LINK|VEEPEAK|KONNWEI)", re.I)
COMMON_PINS = ["1234", "0000", "6789"]


def run(cmd: List[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def parse_devices(out: str) -> List[Tuple[str, str]]:
    devices = []
    for line in out.splitlines():
        m = re.match(r"Device\s+([0-9A-F:]{17})\s+(.*)", line.strip(), re.I)
        if m:
            devices.append((m.group(1), m.group(2)))
    return devices


def list_paired() -> List[Tuple[str, str]]:
    return parse_devices(run(["bluetoothctl", "devices", "Paired"]).stdout)


def find_obd(devices: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    for mac, name in devices:
        if OBD_NAME_RE.search(name):
            return mac, name
    return None


def already_bound_to(mac: str) -> bool:
    out = run(["rfcomm", "show", "0"]).stdout + run(["rfcomm", "show"]).stdout
    return mac.lower() in out.lower()


def is_paired(mac: str) -> bool:
    out = run(["bluetoothctl", "info", mac]).stdout
    return "Paired: yes" in out


def bind(mac: str, channel: int = 1) -> None:
    run(["rfcomm", "release", "0"])
    r = run(["rfcomm", "bind", "0", mac, str(channel)])
    if r.returncode != 0:
        raise RuntimeError(f"rfcomm bind failed: {r.stderr.strip()}")


def bluetoothctl_script(commands: List[str], timeout: int = 30) -> str:
    """Drive bluetoothctl interactively. Brittle but works without dbus deps."""
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    script = "\n".join(commands) + "\nquit\n"
    try:
        out, _ = proc.communicate(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out


def bluetoothctl_pair_session(
    mac: str,
    pin: Optional[str],
    timeout: int = 30,
) -> Tuple[bool, str]:
    """Run pairing through a PTY so bluetoothctl prompts behave interactively."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        text=False,
        close_fds=True,
    )
    os.close(slave)

    out = ""

    def send(line: str) -> None:
        os.write(master, f"{line}\n".encode())

    def read_available(wait: float = 0.2) -> str:
        chunk = ""
        while True:
            ready, _, _ = select.select([master], [], [], wait)
            if not ready:
                return chunk
            try:
                data = os.read(master, 4096)
            except OSError:
                return chunk
            if not data:
                return chunk
            chunk += data.decode(errors="replace")
            wait = 0

    try:
        send("power on")
        send(f"agent {'KeyboardOnly' if pin else 'NoInputNoOutput'}")
        send("default-agent")
        send(f"remove {mac}")  # clear failed/stale attempts before retrying
        time.sleep(1)
        out += read_available()
        send(f"pair {mac}")

        deadline = time.monotonic() + timeout
        sent_pin = False
        while time.monotonic() < deadline:
            out += read_available()
            lower = out.lower()
            if "pairing successful" in lower or is_paired(mac):
                send(f"trust {mac}")
                time.sleep(0.5)
                out += read_available()
                return True, out
            if "failed to pair" in lower or "authenticationfailed" in lower:
                return False, out
            if "confirm passkey" in lower:
                send("yes")
                out = ""
                continue
            if pin and not sent_pin and (
                "request pin code" in lower
                or "enter pin code" in lower
                or "pin code" in lower
                or "passkey" in lower
            ):
                send(pin)
                sent_pin = True
                out = ""
                continue
            time.sleep(0.2)
        out += read_available()
        return is_paired(mac), out
    finally:
        try:
            send("quit")
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)


def try_pair(mac: str, pin: Optional[str] = None, timeout: int = 20) -> bool:
    ok, _ = bluetoothctl_pair_session(mac, pin, timeout=timeout)
    return ok


def discover_and_pair(
    scan_seconds: int = 20,
    pins: Optional[List[str]] = None,
) -> Tuple[str, str]:
    print(f"Scanning {scan_seconds}s for OBD adapters...", file=sys.stderr)
    bluetoothctl_script([
        "power on", "agent on", "default-agent",
        "scan on",
        f"!sleep {scan_seconds}",  # bluetoothctl ignores !; we sleep below
    ], timeout=scan_seconds + 5)
    # Just sleep ourselves - the scan above kicks off discovery.
    subprocess.run(["bluetoothctl", "--timeout", str(scan_seconds), "scan", "on"],
                   capture_output=True)

    found = find_obd(parse_devices(run(["bluetoothctl", "devices"]).stdout))
    if not found:
        raise RuntimeError("no OBD adapter found in scan")

    mac, name = found
    print(f"Found {name} at {mac}, pairing...", file=sys.stderr)

    print("  trying no-PIN pairing", file=sys.stderr)
    if try_pair(mac):
        return mac, name

    pin_list = pins or COMMON_PINS
    for pin in pin_list:
        if try_pair(mac, pin):
            return mac, name
        print(f"  PIN {pin} did not work, trying next", file=sys.stderr)
        time.sleep(1)

    raise RuntimeError(f"could not pair {mac} with no-PIN or PINs {pin_list}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true",
                    help="scan + pair a new adapter (run during imaging)")
    ap.add_argument("--scan-seconds", type=int, default=20)
    ap.add_argument("--pin", action="append",
                    help="PIN to try when pairing; can be repeated")
    args = ap.parse_args()

    if args.discover:
        mac, name = discover_and_pair(args.scan_seconds, args.pin)
    else:
        match = find_obd(list_paired())
        if not match:
            print("no paired OBD adapter found; run with --discover", file=sys.stderr)
            return 2
        mac, name = match

    if already_bound_to(mac):
        print(f"{name} ({mac}) already bound to /dev/rfcomm0")
        return 0

    bind(mac)
    print(f"bound {name} ({mac}) to /dev/rfcomm0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
