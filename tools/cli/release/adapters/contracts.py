"""Strict declarative contract for one released client adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import urlparse


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ACTIONS = {"health", "start", "stop", "open"}


@dataclass(frozen=True, slots=True)
class AdapterAction:
    argv: tuple[str, ...]
    mode: str
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class AdapterContract:
    adapter_id: str
    version: str
    display_name: str
    ui_url: str
    actions: dict[str, AdapterAction]


def validate_adapter_contract(value: Any) -> AdapterContract:
    item = _object(value, "adapter contract")
    if set(item) != {
        "schema_version", "adapter_id", "version", "display_name", "ui",
        "actions",
    }:
        raise ValueError("adapter contract fields are invalid")
    if item.get("schema_version") != 1:
        raise ValueError("adapter contract schema_version is unsupported")
    adapter_id = _text(item.get("adapter_id"), "adapter_id")
    if not _IDENTIFIER.fullmatch(adapter_id):
        raise ValueError("adapter_id is invalid")
    version = _text(item.get("version"), "version")
    actions_value = _object(item.get("actions"), "actions")
    if not actions_value or not set(actions_value).issubset(_ACTIONS):
        raise ValueError("adapter actions are invalid")
    actions = {
        name: _action(name, action)
        for name, action in actions_value.items()
    }
    ui_url = _ui_url(item.get("ui"))
    return AdapterContract(
        adapter_id=adapter_id,
        version=version,
        display_name=_text(item.get("display_name"), "display_name"),
        ui_url=ui_url,
        actions=actions,
    )


def _action(name: str, value: Any) -> AdapterAction:
    item = _object(value, f"actions.{name}")
    if set(item) != {"argv", "mode", "timeout_seconds"}:
        raise ValueError(f"actions.{name} fields are invalid")
    argv_value = item.get("argv")
    if (
        not isinstance(argv_value, list)
        or not argv_value
        or not all(isinstance(part, str) and part for part in argv_value)
    ):
        raise ValueError(f"actions.{name}.argv must be a non-empty string array")
    executable = PurePosixPath(argv_value[0])
    if executable.is_absolute() or ".." in executable.parts:
        raise ValueError(f"actions.{name}.argv executable is unsafe")
    mode = _text(item.get("mode"), f"actions.{name}.mode")
    expected = "background" if name == "start" else "foreground"
    if mode != expected:
        raise ValueError(f"actions.{name}.mode must be {expected}")
    timeout = item.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise ValueError(f"actions.{name}.timeout_seconds must be an integer")
    if timeout < 1 or timeout > 300:
        raise ValueError(f"actions.{name}.timeout_seconds is out of range")
    return AdapterAction(
        argv=tuple(argv_value),
        mode=mode,
        timeout_seconds=timeout,
    )


def _ui_url(value: Any) -> str:
    if value is None:
        return ""
    item = _object(value, "ui")
    if set(item) != {"kind", "url"} or item.get("kind") != "web":
        raise ValueError("adapter ui fields are invalid")
    url = _text(item.get("url"), "ui.url")
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("adapter web UI must use a loopback URL")
    return url


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text
