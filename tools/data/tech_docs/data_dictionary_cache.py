from __future__ import annotations

from pathlib import Path
from typing import Any

from .datadict_scan import build_data_dictionary, data_dictionary_to_dict

_CACHE_PAYLOAD: dict[str, Any] | None = None
_CACHE_STATE: tuple[tuple[str, int], ...] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _scan_roots() -> tuple[Path, ...]:
    root = _repo_root()
    return (
        root / "Settings.py",
        root / "tools",
        root / "Factors",
        root / "sources",
    )


def _iter_tracked_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in _scan_roots():
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".pyi"}
        )
    return tuple(sorted(files))


def _build_cache_state() -> tuple[tuple[str, int], ...]:
    return tuple(
        (str(path), path.stat().st_mtime_ns)
        for path in _iter_tracked_files()
    )


def invalidate_data_dictionary_cache() -> None:
    global _CACHE_PAYLOAD, _CACHE_STATE
    _CACHE_PAYLOAD = None
    _CACHE_STATE = None


def load_data_dictionary_cache() -> dict[str, Any]:
    global _CACHE_PAYLOAD, _CACHE_STATE
    state = _build_cache_state()
    if _CACHE_PAYLOAD is not None and _CACHE_STATE == state:
        return _CACHE_PAYLOAD
    _CACHE_PAYLOAD = data_dictionary_to_dict(build_data_dictionary())
    _CACHE_STATE = state
    return _CACHE_PAYLOAD
