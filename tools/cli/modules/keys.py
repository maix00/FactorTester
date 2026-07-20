"""CLI key adapters for server-registered module keys."""

from __future__ import annotations

BACKTEST_BACKEND_KEY = "group_test"
BACKTEST_PUBLIC_KEY = "backtest"

_BACKEND_TO_PUBLIC_KEYS = {
    BACKTEST_BACKEND_KEY: BACKTEST_PUBLIC_KEY,
}
_PUBLIC_TO_BACKEND_KEYS = {value: key for key, value in _BACKEND_TO_PUBLIC_KEYS.items()}


def public_module_key(key: str) -> str:
    """Return the CLI command key for a backend module key."""
    if "/" not in key:
        return _BACKEND_TO_PUBLIC_KEYS.get(key, key)
    head, tail = key.split("/", 1)
    return f"{_BACKEND_TO_PUBLIC_KEYS.get(head, head)}/{tail}"


def backend_module_key(key: str) -> str:
    """Return the backend module key for a CLI command key."""
    if "/" not in key:
        return _PUBLIC_TO_BACKEND_KEYS.get(key, key)
    head, tail = key.split("/", 1)
    return f"{_PUBLIC_TO_BACKEND_KEYS.get(head, head)}/{tail}"
