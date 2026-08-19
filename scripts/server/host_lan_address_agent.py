"""Publish the host's current physical-LAN addresses for Docker Manager.

The Manager container cannot inspect the host network namespace reliably.
This host-side agent resolves the active hardware route without assuming an
interface name, then writes a short-lived snapshot into the mounted state root.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable


Command = tuple[str, ...]
Runner = Callable[[Command], str]
SNAPSHOT_SCHEMA_VERSION = 1

WINDOWS_DISCOVERY_SCRIPT = r"""
$routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Sort-Object RouteMetric, InterfaceMetric
$result = foreach ($route in $routes) {
  $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
  if ($null -eq $adapter -or -not $adapter.HardwareInterface) { continue }
  if ($adapter.Status -ne 'Up') { continue }
  Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 `
    -ErrorAction SilentlyContinue |
    Where-Object { $_.AddressState -eq 'Preferred' } |
    Select-Object -First 1 IPAddress
}
$result | ConvertTo-Json -Compress
""".strip()


def _run(command: Command) -> str:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _lan_address(value: object) -> str | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        return None
    if address.version == 4:
        shared = ipaddress.ip_network("100.64.0.0/10")
        if not address.is_private and address not in shared:
            return None
    elif address not in ipaddress.ip_network("fc00::/7"):
        return None
    return address.compressed


def _macos_addresses(run: Runner) -> list[str]:
    hardware = run(("networksetup", "-listallhardwareports"))
    devices = re.findall(r"^Device:\s*(\S+)\s*$", hardware, re.MULTILINE)
    route = run(("route", "-n", "get", "default"))
    match = re.search(r"^\s*interface:\s*(\S+)\s*$", route, re.MULTILINE)
    default_device = match.group(1) if match else ""
    ordered = ([default_device] if default_device in devices else []) + [
        device for device in devices if device != default_device
    ]
    values = {
        address
        for device in ordered
        if (address := _lan_address(run(("ipconfig", "getifaddr", device))))
    }
    return sorted(values)


def _json_list(raw: str) -> list[dict[str, object]]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _linux_physical_interface(device: str, run: Runner) -> bool:
    links = _json_list(run(("ip", "-json", "link", "show", "dev", device)))
    if not links:
        return False
    link = links[0]
    link_info = link.get("linkinfo")
    kind = str(link_info.get("info_kind") or "") if isinstance(link_info, dict) else ""
    # VLANs and bonds can be legitimate LAN uplinks. Network tunnels and
    # container-only links cannot be advertised to ordinary LAN clients.
    return not kind or kind in {"bond", "vlan"}


def _linux_addresses(run: Runner) -> list[str]:
    routes = sorted(
        _json_list(run(("ip", "-json", "route", "show", "default"))),
        key=lambda item: int(item.get("metric") or 0),
    )
    values: set[str] = set()
    for route in routes:
        device = str(route.get("dev") or "").strip()
        if not device or not _linux_physical_interface(device, run):
            continue
        records = _json_list(run(("ip", "-json", "addr", "show", "dev", device)))
        for record in records:
            info_values = record.get("addr_info")
            if not isinstance(info_values, list):
                continue
            for info in info_values:
                if not isinstance(info, dict) or info.get("family") != "inet":
                    continue
                if str(info.get("scope") or "") != "global":
                    continue
                address = _lan_address(info.get("local"))
                if address is not None:
                    values.add(address)
    return sorted(values)


def _windows_addresses(run: Runner) -> list[str]:
    records = _json_list(run((
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        WINDOWS_DISCOVERY_SCRIPT,
    )))
    return sorted({
        address
        for record in records
        if (address := _lan_address(record.get("IPAddress"))) is not None
    })


def discover_lan_addresses(
    *,
    system: str | None = None,
    run: Runner = _run,
) -> list[str]:
    selected = str(system or platform.system())
    if selected == "Darwin":
        return _macos_addresses(run)
    if selected == "Linux":
        return _linux_addresses(run)
    if selected == "Windows":
        return _windows_addresses(run)
    return []


def write_snapshot(
    output: Path,
    addresses: Iterable[str],
    *,
    observed_at: float | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "observed_at": time.time() if observed_at is None else float(observed_at),
        "addresses": sorted({
            address
            for value in addresses
            if (address := _lan_address(value)) is not None
        }),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def watch(output: Path, *, interval: float) -> None:
    while True:
        write_snapshot(output, discover_lan_addresses())
        time.sleep(max(1.0, float(interval)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.once:
        write_snapshot(args.output, discover_lan_addresses())
        return 0
    watch(args.output, interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
