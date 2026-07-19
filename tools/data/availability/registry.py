"""Small factory registry for non-file availability connectors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


_CONNECTOR_FACTORIES: dict[str, Callable[[], Any]] = {}


def register_availability_connector(
    key: str,
    factory: Callable[[], Any],
) -> None:
    _CONNECTOR_FACTORIES[str(key)] = factory


def availability_connector(key: str) -> Any | None:
    factory = _CONNECTOR_FACTORIES.get(str(key))
    return factory() if factory is not None else None


def availability_connector_keys() -> tuple[str, ...]:
    return tuple(sorted(_CONNECTOR_FACTORIES))
