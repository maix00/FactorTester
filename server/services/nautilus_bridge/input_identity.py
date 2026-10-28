"""Compact, immutable Bundle input identity for RunSpec planning."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from traderesearch_data.bundles import BundleManifest, bundle_content_fingerprint


@dataclass(frozen=True, slots=True)
class FrozenBundleInput:
    """Bundle/member/mapping identity frozen for one execution request."""

    authority: str
    owner: str
    device: str
    bundle_id: str
    bundle_version: str
    bundle_fingerprint: str
    mapping_version: str
    member_ids: tuple[str, ...]
    related_members: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "authority", "owner", "device", "bundle_id", "bundle_version",
            "bundle_fingerprint", "mapping_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"frozen input {name} must be a non-empty string")
        for name in ("member_ids", "related_members"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise TypeError(f"frozen input {name} must be a tuple of strings")
        if not self.member_ids or len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("frozen input members must be unique and non-empty")
        if not self.bundle_fingerprint.startswith("sha256:"):
            raise ValueError("frozen input Bundle fingerprint must be sha256")

    @property
    def input_ref(self) -> str:
        payload = json.dumps(
            {
                "authority": self.authority, "owner": self.owner,
                "device": self.device, "bundle_id": self.bundle_id,
                "bundle_version": self.bundle_version,
                "bundle_fingerprint": self.bundle_fingerprint,
                "mapping_version": self.mapping_version,
                "member_ids": list(self.member_ids),
                "related_members": list(self.related_members),
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return "source-input:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_ref": self.input_ref,
            "authority": self.authority,
            "owner": self.owner,
            "device": self.device,
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "bundle_fingerprint": self.bundle_fingerprint,
            "mapping_version": self.mapping_version,
            "member_ids": list(self.member_ids),
            "related_members": list(self.related_members),
        }


def frozen_bundle_input_from_dict(payload: dict[str, Any]) -> FrozenBundleInput:
    """Round-trip a frozen identity from persisted RunSpec/report JSON."""
    try:
        identity = FrozenBundleInput(
            authority=payload["authority"], owner=payload["owner"],
            device=payload["device"], bundle_id=payload["bundle_id"],
            bundle_version=payload["bundle_version"],
            bundle_fingerprint=payload["bundle_fingerprint"],
            mapping_version=payload["mapping_version"],
            member_ids=tuple(payload["member_ids"]),
            related_members=tuple(payload["related_members"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid frozen Bundle input payload") from exc
    if payload.get("input_ref") != identity.input_ref:
        raise ValueError("frozen Bundle input ref does not match its payload")
    return identity


def freeze_bundle_input(
    bundle: BundleManifest, *, member_ids: tuple[str, ...],
    authority: str, owner: str, device: str, mapping_version: str,
) -> FrozenBundleInput:
    """Freeze one exact Bundle member set without expanding the full catalog."""
    declared = {member.id for member in bundle.members}
    missing = set(member_ids) - declared
    if missing:
        raise ValueError(f"frozen input members are not in Bundle: {sorted(missing)}")
    related = tuple(sorted({
        item for member in bundle.members if member.id in member_ids
        for item in member.related_members
    }))
    return FrozenBundleInput(
        authority=authority, owner=owner, device=device,
        bundle_id=bundle.bundle_id, bundle_version=bundle.version,
        bundle_fingerprint=bundle_content_fingerprint(bundle),
        mapping_version=mapping_version, member_ids=tuple(member_ids),
        related_members=related,
    )
