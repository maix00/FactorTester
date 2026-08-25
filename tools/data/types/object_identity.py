"""Shared frozen-identity envelope for every business object."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from threading import RLock
from typing import Any

IdentityValidator = Callable[[Mapping[str, Any]], dict[str, Any]]


class UniqueObjectIdentityRegistry:
    """Validate typed identities behind one small, domain-neutral interface."""

    def __init__(self) -> None:
        self._validators: dict[str, IdentityValidator] = {}
        self._classes: dict[str, type] = {}
        self._lock = RLock()

    def register(self, ref_prefix: str, validator: IdentityValidator) -> None:
        prefix = _prefix(ref_prefix)
        with self._lock:
            existing = self._validators.get(prefix)
            if existing is not None and existing is not validator:
                raise RuntimeError(f"identity validator already registered: {prefix}")
            self._validators[prefix] = validator

    def register_class(self, ref_prefix: str, object_class: type) -> None:
        prefix = _prefix(ref_prefix)
        with self._lock:
            existing = self._classes.get(prefix)
            if existing is not None and existing is not object_class:
                raise RuntimeError(f"identity class already registered: {prefix}")
            self._classes[prefix] = object_class

    def require(
        self, value: object, *, expected_class: type | None = None,
    ) -> dict[str, Any]:
        envelope = require_identity_envelope(value)
        prefix = self._prefix_for_ref(envelope["ref"])
        with self._lock:
            validator = self._validators.get(prefix)
            object_class = self._classes.get(prefix)
        if expected_class is not None and object_class not in {None, expected_class}:
            raise ValueError(
                f"frozen identity resolves to {object_class.__name__}, "
                f"not {expected_class.__name__}"
            )
        if validator is None:
            return envelope
        normalized = validator(envelope)
        return require_identity_envelope(normalized)

    def class_for_ref(self, value: object) -> type:
        prefix = self._prefix_for_ref(_text(value, "ref"))
        with self._lock:
            object_class = self._classes.get(prefix)
        if object_class is None:
            raise ValueError(f"no UniqueNameObject class is registered for {prefix}")
        return object_class

    def _prefix_for_ref(self, ref: str) -> str:
        with self._lock:
            matches = [prefix for prefix in self._validators | self._classes if ref.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError("ref has no unique registered identity prefix")
        return matches[0]


def require_identity_envelope(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("frozen identity must be an object")
    ref = _text(value.get("ref"), "ref")
    alias = _text(value.get("alias"), "alias")
    owner_ref = _text(value.get("owner_ref"), "owner_ref")
    if value.get("schema_version") != 2:
        raise ValueError("frozen identity must use schema version 2")
    identity = value.get("identity")
    if not isinstance(identity, Mapping):
        raise TypeError("frozen identity payload must be an object")
    normalized = deepcopy(dict(value))
    normalized.update({
        "schema_version": 2,
        "ref": ref,
        "alias": alias,
        "owner_ref": owner_ref,
        "identity": deepcopy(dict(identity)),
    })
    return normalized


def unique_frozen_identities(values: object) -> list[dict[str, Any]]:
    """Validate and deduplicate an ordered frozen-object collection by ref."""
    if not isinstance(values, (list, tuple)):
        raise TypeError("frozen identity collection must be an array")
    result: list[dict[str, Any]] = []
    by_ref: dict[str, dict[str, Any]] = {}
    for value in values:
        record = identity_registry.require(value)
        previous = by_ref.get(record["ref"])
        if previous is not None:
            if previous != record:
                raise ValueError(
                    "one ref is bound to different frozen records"
                )
            continue
        by_ref[record["ref"]] = record
        result.append(record)
    return result


def _text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _prefix(value: object) -> str:
    text = _text(value, "ref_prefix")
    if not text.endswith(":"):
        raise ValueError("ref_prefix must end with ':'")
    return text


identity_registry = UniqueObjectIdentityRegistry()


__all__ = [
    "UniqueObjectIdentityRegistry",
    "identity_registry",
    "require_identity_envelope",
    "unique_frozen_identities",
]
