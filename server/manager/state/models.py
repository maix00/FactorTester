"""Small process and worktree records shared by Manager state domains."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    head: str
    label: str
    port: int


@dataclass
class ServiceBundle:
    api: object
    daemon: object
    socket_path: Path
    deployment_id: str


class ExternalProcess:
    """A process handle reconstructed after the Manager itself restarted."""

    def __init__(self, pid: int) -> None:
        self.pid = int(pid)

    def poll(self) -> int | None:
        try:
            os.kill(self.pid, 0)
        except (OSError, ProcessLookupError):
            return 1
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.pid, timeout)
            time.sleep(0.05)
        return 0
