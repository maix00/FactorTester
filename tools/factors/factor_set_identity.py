"""Formula-addressed identity adapter for FactorSet objects."""

from __future__ import annotations

import hashlib
import json
import re
from base64 import urlsafe_b64encode
from collections.abc import Mapping, Sequence
from typing import Any

from tools.data.types.object_identity import (
    identity_registry,
    require_identity_envelope,
)
from tools.factors.formula_identity import (
    require_factor_reference,
    require_frozen_factor,
)

_DIGEST = re.compile(r"^[A-Za-z0-9_-]{43}$")


def freeze_factor_set_identity(
    *, owner_ref: str, set_id: str, alias: str,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    frozen_members = _members(members)
    payload = _set_payload(
        owner_ref=owner_ref,
        set_id=set_id,
        member_refs=[item["ref"] for item in frozen_members],
    )
    return {
        "schema_version": 2,
        "ref": build_factor_set_reference(
            owner_ref=payload["owner_ref"],
            set_id=payload["set_id"],
            member_refs=payload["member_refs"],
        ),
        "alias": _text(alias, "alias"),
        "owner_ref": payload["owner_ref"],
        "identity": {
            "set_id": payload["set_id"],
            "member_fingerprint": payload["member_fingerprint"],
            "members": frozen_members,
        },
    }


def require_frozen_factor_set(value: object) -> dict[str, Any]:
    return identity_registry.require(value)


def is_factor_set_reference(value: object) -> bool:
    try:
        require_factor_set_reference(value)
    except ValueError:
        return False
    return True


def require_factor_set_reference(value: object) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 3 or parts[:2] != ["factor-set", "v2"] or not _DIGEST.fullmatch(parts[2]):
        raise ValueError("reference must use factor-set:v2:<identity_digest>")
    return text


def build_factor_set_reference(
    *, owner_ref: object, set_id: object, member_refs: Sequence[str],
) -> str:
    return "factor-set:v2:" + _digest(_set_payload(
        owner_ref=owner_ref, set_id=set_id, member_refs=member_refs,
    ))


def factor_set_identity_payload(
    *, owner_ref: object, set_id: object, member_refs: Sequence[str],
) -> dict[str, Any]:
    return _set_payload(
        owner_ref=owner_ref, set_id=set_id, member_refs=member_refs,
    )


def verify_factor_set_reference(
    value: object, *, owner_ref: object, set_id: object,
    member_refs: Sequence[str],
) -> dict[str, Any]:
    payload = _set_payload(
        owner_ref=owner_ref, set_id=set_id, member_refs=member_refs,
    )
    if require_factor_set_reference(value) != build_factor_set_reference(
        owner_ref=payload["owner_ref"],
        set_id=payload["set_id"],
        member_refs=payload["member_refs"],
    ):
        raise ValueError("factor-set reference does not match its frozen identity")
    return payload


def _validate_factor_set_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    envelope = require_identity_envelope(value)
    fields = envelope["identity"]
    members = _members(fields.get("members"))
    payload = _set_payload(
        owner_ref=envelope["owner_ref"],
        set_id=fields.get("set_id"),
        member_refs=[item["ref"] for item in members],
    )
    expected = build_factor_set_reference(
        owner_ref=payload["owner_ref"],
        set_id=payload["set_id"],
        member_refs=payload["member_refs"],
    )
    if require_factor_set_reference(envelope["ref"]) != expected:
        raise ValueError("factor-set ref does not match its frozen members")
    if fields.get("member_fingerprint") != payload["member_fingerprint"]:
        raise ValueError("factor-set member fingerprint is invalid")
    envelope["identity"] = {
        "set_id": payload["set_id"],
        "member_fingerprint": payload["member_fingerprint"],
        "members": members,
    }
    return envelope


def _members(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ValueError("factor-set members must be complete frozen factor records")
    members = [require_frozen_factor(item) for item in value]
    refs = [item["ref"] for item in members]
    if len(refs) != len(set(refs)):
        raise ValueError("factor-set members must be unique")
    return sorted(members, key=lambda item: item["ref"])


def _set_payload(
    *, owner_ref: object, set_id: object, member_refs: Sequence[str],
) -> dict[str, Any]:
    owner = _text(owner_ref, "owner_ref")
    identifier = _text(set_id, "set_id")
    refs = sorted(require_factor_reference(value) for value in member_refs)
    if not refs:
        raise ValueError("factor-set members must be non-empty")
    if len(refs) != len(set(refs)):
        raise ValueError("factor-set members must be unique")
    return {
        "owner_ref": owner,
        "set_id": identifier,
        "member_fingerprint": hashlib.sha256(
            json.dumps(refs, separators=(",", ":")).encode()
        ).hexdigest(),
        "member_refs": refs,
    }


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()
    return urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")


def _text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


identity_registry.register("factor-set:v2:", _validate_factor_set_envelope)


__all__ = [
    "build_factor_set_reference",
    "factor_set_identity_payload",
    "freeze_factor_set_identity",
    "is_factor_set_reference",
    "require_factor_set_reference",
    "require_frozen_factor_set",
    "verify_factor_set_reference",
]
