"""Runtime FactorSet object interned by its immutable formula reference."""

from __future__ import annotations

from typing import Any

from tools.data.types import UniqueNameObject
from tools.factors.factor_set_identity import require_frozen_factor_set


class FactorSet(UniqueNameObject):
    ref_prefix = "factor-set:v2:"

    def __new__(cls, *, frozen_identity: dict[str, Any]):
        frozen = require_frozen_factor_set(frozen_identity)
        return UniqueNameObject.__new__(cls, frozen_identity=frozen)

    def __init__(self, *, frozen_identity: dict[str, Any]):
        if not hasattr(self, "members"):
            frozen = require_frozen_factor_set(frozen_identity)
            self.members = tuple(frozen["identity"]["members"])
            self.set_id = frozen["identity"]["set_id"]


__all__ = ["FactorSet"]
