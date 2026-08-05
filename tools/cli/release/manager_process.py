"""LaunchAgent lifecycle for the local Manager control plane."""

from __future__ import annotations

import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time


LABEL = "com.gtht.factortester.manager"


def restart_manager_process(
    *, source_root: Path, port: int = 7998,
) -> dict[str, str | int]:
    source = source_root.expanduser().resolve()
    script = source / "scripts/worktree_flask_manager.py"
    if not script.is_file():
        raise ValueError("Manager source lacks its entrypoint")
    repository = _repository_root(source)
    log_root = Path.home() / "Library/Logs/FactorTester"
    log_root.mkdir(parents=True, exist_ok=True)
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    _write_plist(
        plist,
        source=source,
        repository=repository,
        script=script,
        log=log_root / "manager.log",
        port=port,
    )

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    subprocess.run(
        ["launchctl", "bootout", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _stop_unmanaged_listener(port)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    subprocess.run(["launchctl", "enable", service], check=True)
    subprocess.run(["launchctl", "kickstart", service], check=True)
    pid = _wait_for_listener(port)
    return {
        "label": LABEL,
        "pid": pid,
        "source_root": str(source),
        "repository_root": str(repository),
    }


def _repository_root(source: Path) -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=source,
        text=True,
    ).strip()
    common_path = Path(common).resolve()
    return common_path.parent if common_path.name == ".git" else common_path


def _write_plist(
    path: Path,
    *,
    source: Path,
    repository: Path,
    script: Path,
    log: Path,
    port: int,
) -> None:
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            str(script),
            "--repo", str(repository),
            "--port", str(port),
            "--no-browser",
        ],
        "WorkingDirectory": str(source),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=".manager-", suffix=".plist", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _stop_unmanaged_listener(port: int) -> None:
    process = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    for raw in process.stdout.splitlines():
        if not raw.isdigit():
            continue
        pid = int(raw)
        command = subprocess.check_output(
            ["ps", "-ww", "-p", str(pid), "-o", "command="], text=True,
        )
        if "scripts/worktree_flask_manager.py" not in command:
            raise RuntimeError(f"port {port} is owned by an unknown process")
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not _listener_pid(port):
            return
        time.sleep(0.05)
    raise RuntimeError("previous Manager listener did not exit")


def _wait_for_listener(port: int, timeout: float = 30) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = _listener_pid(port)
        if pid:
            time.sleep(0.25)
            if _listener_pid(port) == pid:
                return pid
        time.sleep(0.05)
    raise RuntimeError("Manager LaunchAgent did not become healthy")


def _listener_pid(port: int) -> int | None:
    process = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = process.stdout.splitlines()
    return int(value[0]) if value and value[0].isdigit() else None
