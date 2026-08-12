"""Host-level helpers used by the Manager composition root and state modules."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path


ISSUE_BRANCH_RE = re.compile(r"^fix/issue-(\d+)(?:-.*)?$")


def extract_issue_number(branch: str) -> int | None:
    match = ISSUE_BRANCH_RE.match(branch)
    return int(match.group(1)) if match else None


def write_owner_only_once(path: Path, value: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(descriptor, value.encode("ascii"))
    finally:
        os.close(descriptor)


def lan_ip() -> str:
    """Return a LAN address or ``localhost`` when discovery is unavailable."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.settimeout(0.0)
            connection.connect(("8.8.8.8", 1))
            return str(connection.getsockname()[0])
    except OSError:
        return "localhost"


def safe_name(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)
        or "worktree"
    )


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0
