"""Bounded argv execution and process control for client adapters."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any

from .contracts import AdapterAction


MAX_ACTION_OUTPUT_BYTES = 64 * 1024


class AdapterActionRunner:
    def __init__(
        self,
        *,
        adapter_root: Path,
        adapter_id: str,
        binding: dict[str, str] | None = None,
    ) -> None:
        self.adapter_root = adapter_root
        self.adapter_id = adapter_id
        self.binding = binding or {}

    def foreground(
        self,
        action: AdapterAction,
        *,
        pid: int = 0,
        check: bool,
    ) -> dict[str, Any]:
        result = subprocess.run(
            self.command(action),
            cwd=self.adapter_root,
            env=self.environment(pid),
            capture_output=True,
            timeout=action.timeout_seconds,
            check=False,
        )
        stdout = _bounded_text(result.stdout)
        stderr = _bounded_text(result.stderr)
        if check and result.returncode:
            raise ValueError(
                f"adapter action failed ({result.returncode}): {stderr}"
            )
        return {
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": (
                len(result.stdout) > MAX_ACTION_OUTPUT_BYTES
                or len(result.stderr) > MAX_ACTION_OUTPUT_BYTES
            ),
        }

    def background(
        self,
        action: AdapterAction,
        *,
        log_path: Path,
    ) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                self.command(action),
                cwd=self.adapter_root,
                env=self.environment(0),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        time.sleep(0.1)
        if process.poll() is not None:
            raise ValueError(f"adapter start failed: {self.adapter_id}")
        return process.pid

    def command(self, action: AdapterAction) -> list[str]:
        executable = (self.adapter_root / action.argv[0]).resolve()
        if self.adapter_root.resolve() not in executable.parents:
            raise ValueError("adapter executable escapes its install root")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"adapter executable is unavailable: {executable}")
        return [str(executable), *action.argv[1:]]

    def environment(self, pid: int) -> dict[str, str]:
        allowed = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
        return {
            **{key: os.environ[key] for key in allowed if key in os.environ},
            "FACTORTESTER_ADAPTER_ID": self.adapter_id,
            "FACTORTESTER_ADAPTER_ROOT": str(self.adapter_root),
            "FACTORTESTER_ADAPTER_PID": str(pid or ""),
            **self.binding,
        }


def pid_alive(pid: int) -> bool:
    if pid < 2:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _bounded_text(value: bytes) -> str:
    return value[:MAX_ACTION_OUTPUT_BYTES].decode("utf-8", errors="replace")
