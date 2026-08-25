"""Frontend projections for frozen ``UniqueNameObject`` records."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .object_identity import identity_registry


def frozen_object_choice(value: object) -> dict[str, Any]:
    """Expose one frozen object without confusing display and identity."""
    record = identity_registry.require(value)
    return {
        "value": record["ref"],
        "label": record["alias"],
        "record": deepcopy(record),
    }


def frozen_object_choices(values: list[object]) -> list[dict[str, Any]]:
    """Project a candidate list while preserving its backend order."""
    return [frozen_object_choice(value) for value in values]


__all__ = ["frozen_object_choice", "frozen_object_choices"]
