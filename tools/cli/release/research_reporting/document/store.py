"""Atomic local storage for graph-independent report documents."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from .bindings import validate_bindings
from .model import validate_document


def load_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    file_path = Path(path)
    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取研究报告: {file_path}") from exc
    return validate_document(value)


def save_document(path: str | os.PathLike[str], document: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically replace one document, preserving old bytes on error."""
    value = validate_document(document)
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        temp = file_path.with_name(file_path.name + ".tmp")
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            temp.write_text(payload, encoding="utf-8")
            with temp.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, file_path)
            directory = file_path.parent
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp.exists():
                temp.unlink()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return value


def load_bindings(
    path: str | os.PathLike[str],
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    file_path = Path(path)
    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取报告绑定: {file_path}") from exc
    return validate_bindings(value, document)


def save_bindings(
    path: str | os.PathLike[str],
    bindings: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = validate_bindings(bindings, document)
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        temp = file_path.with_name(file_path.name + ".tmp")
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            temp.write_text(payload, encoding="utf-8")
            with temp.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, file_path)
            directory_fd = os.open(file_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp.exists():
                temp.unlink()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return value
