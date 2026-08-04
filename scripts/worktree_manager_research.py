"""Static research UI and event fan-out for Worktree Manager 7998."""

from __future__ import annotations

import mimetypes
import threading
import time
from pathlib import Path
from typing import Iterable


WEB_ROOT = Path(__file__).resolve().with_name("worktree_manager_web")
KATEX_ROOT = Path(__file__).resolve().parents[1] / "apple" / "Resources" / "ThirdParty" / "KaTeX"


class PublicResearchEvents:
    """One process-local invalidation stream; report data remains on disk."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._revision = 0
        self._publications: set[str] = set()

    def notify(self, publication_ids: Iterable[str]) -> int:
        with self._condition:
            self._revision += 1
            self._publications.update(str(item) for item in publication_ids)
            self._condition.notify_all()
            return self._revision

    def wait(self, after: int, timeout: float = 20.0) -> tuple[int, set[str]]:
        with self._condition:
            if self._revision <= after:
                self._condition.wait(timeout)
            return self._revision, set(self._publications)

    def acknowledge(self, revision: int) -> None:
        with self._condition:
            if revision == self._revision:
                self._publications.clear()


def shell_bytes() -> bytes:
    return (WEB_ROOT / "research.html").read_bytes()


def static_file(relative: str) -> tuple[bytes, str]:
    value = relative.lstrip("/")
    if not value or ".." in value.split("/"):
        raise ValueError("static asset path is invalid")
    root = KATEX_ROOT if value.startswith("katex/") else WEB_ROOT
    path = root / value.removeprefix("katex/")
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("static asset was not found")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return resolved.read_bytes(), content_type


def sse_payload(revision: int, publication_ids: set[str]) -> bytes:
    import json
    return (
        f"id: {revision}\n"
        "event: report-generation\n"
        f"data: {json.dumps({'publication_ids': sorted(publication_ids)})}\n\n"
    ).encode("utf-8")


def heartbeat() -> bytes:
    return f": keepalive {int(time.time())}\n\n".encode("ascii")
