"""Origin Adapter registry for the 7997 byte stream."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from server.manager.objects.models import TransferObjectKind


class ObjectOriginRegistry:
    """Resolve an opaque transfer object without leaking domain logic to 7997."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, Callable[[object], Path]] = (),
        fallback: Callable[[object], Path] | None = None,
    ) -> None:
        self.adapters = {
            str(kind): resolver for kind, resolver in dict(adapters).items()
        }
        self.fallback = fallback

    def __call__(self, transfer) -> Path:
        kind = str(
            getattr(transfer, "object_kind", "")
            or TransferObjectKind.JOB_ARTIFACT.value
        )
        resolver = self.adapters.get(kind)
        if resolver is None:
            resolver = self.fallback
        if resolver is None:
            raise FileNotFoundError(f"no origin adapter for transfer object {kind}")
        return Path(resolver(transfer)).expanduser().resolve()


__all__ = ["ObjectOriginRegistry"]
