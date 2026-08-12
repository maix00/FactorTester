"""Owner-only persistence for public report bindings."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def read_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "publications": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("public research registry is unreadable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or not isinstance(value.get("publications"), list)
    ):
        raise ValueError("public research registry is invalid")
    return value


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return value


@contextmanager
def locked_registry(root: Path) -> Iterator[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = root / ".write.lock"
    registry_path = root / "publications.json"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        value = read_registry(registry_path)
        yield value
        atomic_json(registry_path, value)
        registry_path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8") + b"\n"
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
