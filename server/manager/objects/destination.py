"""Destination Adapter registry for verified 7997 object uploads."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping


class ObjectDestinationRegistry:
    """Dispatch one committed staging file to its domain owner."""

    def __init__(
        self,
        adapters: Mapping[str, Callable[[object, Path], object]],
    ) -> None:
        self.adapters = dict(adapters)

    def __call__(self, context, staged_path: Path) -> Path:
        adapter = self.adapters.get(str(context.transfer.object_kind))
        if adapter is None:
            return staged_path
        value = adapter(context, staged_path)
        return Path(value).expanduser().resolve() if value is not None else staged_path


__all__ = ["ObjectDestinationRegistry"]
