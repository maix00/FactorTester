"""Domain-neutral visibility scopes for persisted UniqueNameObject records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

VisibilityScope = Literal[
    "public", "mine", "direct_subordinate", "shared_with_me",
]


@dataclass(frozen=True, slots=True)
class UniqueObjectVisibilityPolicy:
    own_owner_refs: frozenset[str]
    direct_subordinate_owner_refs: frozenset[str]
    shared_object_refs: frozenset[str]

    def __init__(
        self,
        *,
        own_owner_refs: Iterable[str],
        direct_subordinate_owner_refs: Iterable[str] = (),
        shared_object_refs: Iterable[str] = (),
    ) -> None:
        object.__setattr__(self, "own_owner_refs", _refs(own_owner_refs))
        object.__setattr__(
            self,
            "direct_subordinate_owner_refs",
            _refs(direct_subordinate_owner_refs),
        )
        object.__setattr__(self, "shared_object_refs", _refs(shared_object_refs))

    def scope_for(self, value: Mapping[str, Any]) -> VisibilityScope | None:
        owner_ref = str(value.get("owner_ref") or "").strip()
        ref = str(value.get("ref") or "").strip()
        if owner_ref in {"public", "$COMMON"}:
            return "public"
        if owner_ref in self.own_owner_refs:
            return "mine"
        if owner_ref in self.direct_subordinate_owner_refs:
            return "direct_subordinate"
        if ref and ref in self.shared_object_refs:
            return "shared_with_me"
        return None

    def can_view(self, value: Mapping[str, Any]) -> bool:
        return self.scope_for(value) is not None


def _refs(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        text for value in values if (text := str(value or "").strip())
    )


__all__ = ["UniqueObjectVisibilityPolicy", "VisibilityScope"]
