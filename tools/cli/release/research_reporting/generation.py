"""One locked three-file generation publisher for local reports."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator

if os.name == "nt":  # pragma: no cover - exercised by Windows release CI.
    import msvcrt
else:
    import fcntl


@contextmanager
def report_workspace_lock(package_root: Path) -> Iterator[None]:
    package_root.mkdir(parents=True, exist_ok=True)
    lock_path = package_root / ".report.lock"
    created = not lock_path.exists()
    with lock_path.open("a+b") as handle:
        if created:
            lock_path.chmod(0o600)
        _lock(handle)
        try:
            yield
        finally:
            _unlock(handle)


def _lock(handle) -> None:
    if os.name == "nt":  # pragma: no cover - Windows release CI.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    if os.name == "nt":  # pragma: no cover - Windows release CI.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish_generation(
    targets: list[tuple[str, Path, bytes]],
) -> dict[str, bool]:
    """Stage changed targets, then publish or restore the complete old set."""
    staged: list[dict[str, Any]] = []
    changed = {name: False for name, _path, _payload in targets}
    try:
        for name, path, payload in targets:
            old_payload = path.read_bytes() if path.exists() else None
            if old_payload == payload:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            staged.append({
                "name": name,
                "path": path,
                "new": _stage(path, payload, ".report-new-"),
                "old": (
                    _stage(path, old_payload, ".report-old-")
                    if old_payload is not None else None
                ),
                "existed": old_payload is not None,
            })
        published: list[dict[str, Any]] = []
        try:
            for item in staged:
                os.replace(item["new"], item["path"])
                published.append(item)
                changed[item["name"]] = True
        except OSError:
            rollback_errors = []
            for item in reversed(published):
                try:
                    if item["existed"]:
                        os.replace(item["old"], item["path"])
                    else:
                        item["path"].unlink(missing_ok=True)
                    changed[item["name"]] = False
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise RuntimeError(
                    "report generation publish and rollback both failed"
                ) from rollback_errors[0]
            raise
        return changed
    finally:
        for item in staged:
            item["new"].unlink(missing_ok=True)
            if item["old"] is not None:
                item["old"].unlink(missing_ok=True)


def _stage(path: Path, payload: bytes, prefix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=prefix,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary
