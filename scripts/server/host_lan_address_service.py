#!/usr/bin/env python3
"""Install the host LAN address agent under the native service manager."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import platform
import subprocess
import sys
import tempfile
import time


def _service_name(snapshot: Path) -> str:
    digest = hashlib.sha256(str(snapshot.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"com.factortester.host-lan-address.{digest}"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _program_arguments(args: argparse.Namespace) -> list[str]:
    return [
        str(args.python.resolve()),
        str(args.agent.resolve()),
        "--output",
        str(args.snapshot.resolve()),
        "--interval",
        str(args.interval),
    ]


def _launchd_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{name}.plist"


def _start_launchd(args: argparse.Namespace, name: str) -> None:
    domain = f"gui/{os.getuid()}"
    path = _launchd_path(name)
    payload = plistlib.dumps(
        {
            "Label": name,
            "ProgramArguments": _program_arguments(args),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": str(args.log.resolve()),
            "StandardErrorPath": str(args.log.resolve()),
        },
        sort_keys=True,
    )
    args.log.parent.mkdir(parents=True, exist_ok=True)
    _run("launchctl", "bootout", f"{domain}/{name}", check=False)
    _atomic_write(path, payload)
    _run("launchctl", "bootstrap", domain, str(path))
    _run("launchctl", "kickstart", "-k", f"{domain}/{name}")


def _stop_launchd(args: argparse.Namespace, name: str) -> None:
    domain = f"gui/{os.getuid()}"
    path = _launchd_path(name)
    _run("launchctl", "bootout", f"{domain}/{name}", check=False)
    path.unlink(missing_ok=True)


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _systemd_path(name: str) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{name}.service"


def _start_systemd(args: argparse.Namespace, name: str) -> None:
    path = _systemd_path(name)
    command = " ".join(_systemd_quote(value) for value in _program_arguments(args))
    payload = (
        "[Unit]\n"
        "Description=FactorTester host LAN address agent\n\n"
        "[Service]\n"
        f"ExecStart={command}\n"
        "Restart=always\n"
        "RestartSec=2\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    ).encode("utf-8")
    _atomic_write(path, payload)
    _run("systemctl", "--user", "daemon-reload")
    _run("systemctl", "--user", "enable", "--now", path.name)


def _stop_systemd(args: argparse.Namespace, name: str) -> None:
    path = _systemd_path(name)
    _run("systemctl", "--user", "disable", "--now", path.name, check=False)
    path.unlink(missing_ok=True)
    _run("systemctl", "--user", "daemon-reload")


def _wait_for_fresh_snapshot(path: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if time.time() - path.stat().st_mtime < timeout:
                return
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    raise RuntimeError("host LAN address agent did not publish a fresh snapshot")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--agent", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    name = _service_name(args.snapshot)
    system = platform.system()
    if system == "Darwin":
        action = _start_launchd if args.action == "start" else _stop_launchd
    elif system == "Linux":
        action = _start_systemd if args.action == "start" else _stop_systemd
    else:
        raise RuntimeError(f"unsupported host service manager on {system}")
    action(args, name)
    if args.action == "start":
        _wait_for_fresh_snapshot(args.snapshot)
    else:
        args.snapshot.unlink(missing_ok=True)
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
