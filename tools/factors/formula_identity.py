"""Single business boundary for formula-addressed factor identities.

References are deliberately opaque.  Business code must carry the complete
frozen record and use this module to validate it; aliases are never decoded
from a reference string.
"""

from __future__ import annotations

import hashlib
import json
import re
from base64 import urlsafe_b64encode
from collections.abc import Mapping
from typing import Any

from tools.data.types.object_identity import (
    identity_registry,
    require_identity_envelope,
)

_DIGEST = re.compile(r"^[A-Za-z0-9_-]{43}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_FACTOR_FIELDS = (
    "family_ref",
    "family_alias",
    "family_formula_fingerprint",
    "self_formula_fingerprint",
)


def freeze_factor_identity(
    *,
    owner_ref: str,
    family_alias: str,
    factor_alias: str,
    family_formula_fingerprint: str,
    self_formula_fingerprint: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sole frozen Factor record accepted by business code."""
    identity = factor_identity_payload(
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=factor_alias,
        family_formula_fingerprint=family_formula_fingerprint,
        self_formula_fingerprint=self_formula_fingerprint,
    )
    parameters = dict(params or {})
    ref = build_factor_reference(**identity)
    return {
        "schema_version": 2,
        "ref": ref,
        "alias": identity["factor_alias"],
        "owner_ref": identity["owner_ref"],
        "identity": {
            "family_ref": build_factor_family_reference(
                owner_ref=identity["owner_ref"],
                family_alias=identity["family_alias"],
                family_formula_fingerprint=identity["family_formula_fingerprint"],
            ),
            "family_alias": identity["family_alias"],
            "family_formula_fingerprint": identity["family_formula_fingerprint"],
            "self_formula_fingerprint": identity["self_formula_fingerprint"],
            "params": parameters,
        },
    }


def freeze_factor_family_identity(
    *, owner_ref: str, family_alias: str,
    family_formula_fingerprint: str,
) -> dict[str, Any]:
    identity = factor_family_identity_payload(
        owner_ref=owner_ref,
        family_alias=family_alias,
        family_formula_fingerprint=family_formula_fingerprint,
    )
    return {
        "schema_version": 2,
        "ref": build_factor_family_reference(**identity),
        "alias": identity["family_alias"],
        "owner_ref": identity["owner_ref"],
        "identity": {
            "family_formula_fingerprint": identity[
                "family_formula_fingerprint"
            ],
        },
    }


def require_frozen_factor(value: object) -> dict[str, Any]:
    """Validate and normalize one complete v2 record without v1 fallback."""
    return identity_registry.require(value)


def require_frozen_factor_family(value: object) -> dict[str, Any]:
    return identity_registry.require(value)


def _validate_factor_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    value = require_identity_envelope(value)
    fields = value["identity"]
    if any(not fields.get(key) for key in _FACTOR_FIELDS):
        raise ValueError("factor identity must be a complete frozen record")
    identity = factor_identity_payload(
        owner_ref=value["owner_ref"],
        family_alias=fields["family_alias"],
        factor_alias=value["alias"],
        family_formula_fingerprint=fields["family_formula_fingerprint"],
        self_formula_fingerprint=fields["self_formula_fingerprint"],
    )
    if str(value["ref"]) != build_factor_reference(**identity):
        raise ValueError("factor ref does not match the frozen formula identity")
    expected_family = build_factor_family_reference(
        owner_ref=identity["owner_ref"],
        family_alias=identity["family_alias"],
        family_formula_fingerprint=identity["family_formula_fingerprint"],
    )
    if str(fields["family_ref"]) != expected_family:
        raise ValueError("family_ref does not match the frozen formula identity")
    params = fields.get("params") or {}
    if not isinstance(params, Mapping):
        raise TypeError("factor params must be an object")
    return {
        "schema_version": 2,
        "ref": str(value["ref"]),
        "alias": identity["factor_alias"],
        "owner_ref": identity["owner_ref"],
        "identity": {
            "family_ref": expected_family,
            "family_alias": identity["family_alias"],
            "family_formula_fingerprint": identity[
                "family_formula_fingerprint"
            ],
            "self_formula_fingerprint": identity[
                "self_formula_fingerprint"
            ],
            "params": dict(params),
        },
    }


def _validate_factor_family_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    envelope = require_identity_envelope(value)
    fingerprint = envelope["identity"].get("family_formula_fingerprint")
    identity = factor_family_identity_payload(
        owner_ref=envelope["owner_ref"],
        family_alias=envelope["alias"],
        family_formula_fingerprint=fingerprint,
    )
    expected = build_factor_family_reference(**identity)
    if require_factor_family_reference(envelope["ref"]) != expected:
        raise ValueError("factor family ref does not match its formula identity")
    envelope["identity"] = {
        "family_formula_fingerprint": identity[
            "family_formula_fingerprint"
        ],
    }
    return envelope


def is_factor_reference(value: object) -> bool:
    try:
        require_factor_reference(value)
    except ValueError:
        return False
    return True


def require_factor_reference(value: object) -> str:
    return _require_reference(value, kind="factor")


def is_factor_family_reference(value: object) -> bool:
    try:
        require_factor_family_reference(value)
    except ValueError:
        return False
    return True


def require_factor_family_reference(value: object) -> str:
    return _require_reference(value, kind="factor-family")


def factor_identity_payload(
    *, owner_ref: object, family_alias: object, factor_alias: object,
    family_formula_fingerprint: object, self_formula_fingerprint: object,
) -> dict[str, str]:
    return {
        "factor_alias": _text(factor_alias, "factor_alias"),
        "family_alias": _text(family_alias, "family_alias"),
        "family_formula_fingerprint": _fingerprint(
            family_formula_fingerprint, "family_formula_fingerprint",
        ),
        "owner_ref": _text(owner_ref, "owner_ref"),
        "self_formula_fingerprint": _fingerprint(
            self_formula_fingerprint, "self_formula_fingerprint",
        ),
    }


def build_factor_reference(**identity: object) -> str:
    return "factor:v2:" + _digest(factor_identity_payload(**identity))


def build_factor_family_reference(
    *, owner_ref: object, family_alias: object,
    family_formula_fingerprint: object,
) -> str:
    return "factor-family:v2:" + _digest(factor_family_identity_payload(
        owner_ref=owner_ref,
        family_alias=family_alias,
        family_formula_fingerprint=family_formula_fingerprint,
    ))


def factor_family_identity_payload(
    *, owner_ref: object, family_alias: object,
    family_formula_fingerprint: object,
) -> dict[str, str]:
    return {
        "family_alias": _text(family_alias, "family_alias"),
        "family_formula_fingerprint": _fingerprint(
            family_formula_fingerprint, "family_formula_fingerprint",
        ),
        "owner_ref": _text(owner_ref, "owner_ref"),
    }


def verify_factor_reference(value: object, **identity: object) -> dict[str, str]:
    payload = factor_identity_payload(**identity)
    if require_factor_reference(value) != build_factor_reference(**payload):
        raise ValueError("factor reference does not match its frozen identity")
    return payload


def verify_factor_family_reference(
    value: object, **identity: object,
) -> dict[str, str]:
    payload = factor_family_identity_payload(**identity)
    if require_factor_family_reference(value) != build_factor_family_reference(**payload):
        raise ValueError("factor family reference does not match its frozen identity")
    return payload


def _require_reference(value: object, *, kind: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 3 or parts[:2] != [kind, "v2"] or not _DIGEST.fullmatch(parts[2]):
        raise ValueError(f"reference must use {kind}:v2:<identity_digest>")
    return text


def _text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _fingerprint(value: object, field: str) -> str:
    text = _text(value, field).lower()
    if not _FINGERPRINT.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 fingerprint")
    return text


def _digest(value: Mapping[str, str]) -> str:
    payload = json.dumps(
        dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()
    return urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")


identity_registry.register("factor:v2:", _validate_factor_envelope)
identity_registry.register("factor-family:v2:", _validate_factor_family_envelope)


__all__ = [
    "build_factor_family_reference",
    "build_factor_reference",
    "factor_family_identity_payload",
    "factor_identity_payload",
    "freeze_factor_family_identity",
    "freeze_factor_identity",
    "is_factor_family_reference",
    "is_factor_reference",
    "require_factor_family_reference",
    "require_factor_reference",
    "require_frozen_factor",
    "require_frozen_factor_family",
    "verify_factor_family_reference",
    "verify_factor_reference",
]
