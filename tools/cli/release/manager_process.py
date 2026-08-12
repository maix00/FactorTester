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
    *,
    source_root: Path,
    port: int = 7998,
    python_executable: Path | None = None,
) -> dict[str, str | int]:
    source = source_root.expanduser().resolve()
    script = source / "scripts/worktree_flask_manager.py"
    if not script.is_file():
        raise ValueError("Manager source lacks its entrypoint")
    repository = _repository_root(source)
    data_root = repository.parent / "FactorTester"
    log_root = Path.home() / "Library/Logs/FactorTester"
    log_root.mkdir(parents=True, exist_ok=True)
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    python = (
        _validated_python_executable(python_executable)
        if python_executable is not None
        else _resolve_python_executable(plist)
    )
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    _unload_launch_agent(domain=domain, service=service, plist=plist)
    _stop_unmanaged_listener(port)
    _write_plist(
        plist,
        source=source,
        repository=repository,
        script=script,
        log=log_root / "manager.log",
        port=port,
        data_root=data_root,
        python_executable=python,
    )

    subprocess.run(["launchctl", "enable", service], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    subprocess.run(["launchctl", "kickstart", service], check=True)
    pid = _wait_for_listener(port)
    return {
        "label": LABEL,
        "pid": pid,
        "source_root": str(source),
        "repository_root": str(repository),
        "python_executable": str(python),
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
    data_root: Path,
    python_executable: Path,
) -> None:
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_executable),
            str(script),
            "--repo", str(repository),
            "--port", str(port),
            "--python", str(python_executable),
            "--data-root", str(data_root),
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


def _resolve_python_executable(plist: Path) -> Path:
    candidates: list[Path] = []
    try:
        payload = plistlib.loads(plist.read_bytes())
    except (FileNotFoundError, OSError, ValueError, plistlib.InvalidFileException):
        payload = {}
    arguments = payload.get("ProgramArguments") or []
    if isinstance(arguments, list):
        if "--python" in arguments:
            index = arguments.index("--python") + 1
            if index < len(arguments):
                candidates.append(Path(str(arguments[index])))
        if arguments:
            candidates.append(Path(str(arguments[0])))
    candidates.append(Path(sys.executable))
    observed: set[str] = set()
    for candidate in candidates:
        identity = str(candidate.expanduser())
        if identity in observed:
            continue
        observed.add(identity)
        if _is_python_interpreter(candidate):
            return candidate.expanduser()
    raise RuntimeError(
        "Manager restart requires a valid server Python runtime; "
        "the bundled FactorTester CLI is not a Python interpreter"
    )


def _validated_python_executable(candidate: Path) -> Path:
    value = candidate.expanduser()
    if not _is_python_interpreter(value):
        raise RuntimeError("Manager server Python runtime is unavailable")
    return value


def _is_python_interpreter(candidate: Path) -> bool:
    value = candidate.expanduser()
    if not value.is_file() or not os.access(value, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(value), "-c", "import sys; raise SystemExit(0)"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _unload_launch_agent(*, domain: str, service: str, plist: Path) -> None:
    subprocess.run(
        ["launchctl", "disable", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _launch_agent_loaded(service):
        return
    for command in (
        ["launchctl", "bootout", service],
        ["launchctl", "bootout", domain, str(plist)],
    ):
        subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not _launch_agent_loaded(service):
            return
        time.sleep(0.05)
    raise RuntimeError("previous Manager LaunchAgent did not unload")


def _launch_agent_loaded(service: str) -> bool:
    return subprocess.run(
        ["launchctl", "print", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


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
