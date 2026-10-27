"""Engine-neutral installed Bundle metadata. Discovery never imports plugins."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MODULE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
KINDS = frozenset({"market_data", "instrument_definitions", "historical_rules", "settlement_data"})
MAX_MANIFEST_BYTES = 1_048_576
MAX_BUNDLES = 256
MAX_INVENTORY_BYTES = 16 * MAX_MANIFEST_BYTES

@dataclass(frozen=True, slots=True)
class ProductBinding:
    product_ref: str
    member_id: str
    source_product_ref: str

@dataclass(frozen=True, slots=True)
class UpdatePolicy:
    mode: str
    revision_policy: str
    max_staleness_seconds: int | None
    replay_policy: str

@dataclass(frozen=True, slots=True)
class BundleMember:
    id: str
    kind: str
    data_type: str
    frequency: str | None
    related_members: tuple[str, ...]
    update_policy: UpdatePolicy
    integrations: tuple[tuple[str, str], ...]

@dataclass(frozen=True, slots=True)
class BundleManifest:
    bundle_id: str
    version: str
    label: str
    provisioner: str
    execution_location: str
    entrypoints: tuple[str, ...]
    members: tuple[BundleMember, ...]
    product_bindings: tuple[ProductBinding, ...]


def _object(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name}: invalid fields")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name}: invalid text")
    return value


def _id(value: Any, name: str) -> str:
    value = _text(value, name)
    if not _ID.fullmatch(value):
        raise ValueError(f"{name}: invalid identifier")
    return value


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > 10_000:
        raise ValueError(f"{name}: invalid array")
    return value


def parse_bundle_manifest(value: Any) -> BundleManifest:
    root = _object(value, {"schema_version", "bundle_id", "version", "label", "provisioner", "execution_location", "entrypoints", "members", "product_bindings"}, "bundle")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("unsupported bundle schema_version")
    if not isinstance(root["provisioner"], str) or not isinstance(root["execution_location"], str) or root["provisioner"] not in {"platform", "user"} or root["execution_location"] not in {"server", "client"}:
        raise ValueError("invalid Bundle provisioner or execution_location")
    entrypoints = tuple(_text(item, "entrypoint") for item in _array(root["entrypoints"], "entrypoints"))
    if len(set(entrypoints)) != len(entrypoints) or any(not _MODULE.fullmatch(item) for item in entrypoints):
        raise ValueError("invalid or duplicate module entrypoint")
    members = []
    for raw in _array(root["members"], "members"):
        item = _object(raw, {"id", "kind", "data_type", "frequency", "related_members", "integrations", "update_policy"}, "member")
        if not isinstance(item["kind"], str) or item["kind"] not in KINDS:
            raise ValueError("unknown member kind")
        frequency = None if item["frequency"] is None else _id(item["frequency"], "frequency")
        if item["kind"] != "market_data" and frequency is not None:
            raise ValueError("non-market members cannot declare a Bar frequency")
        data_type = _id(item["data_type"], "data_type")
        if item["kind"] == "market_data" and data_type == "bar" and frequency is None:
            raise ValueError("Bar member requires frequency")
        policy = _object(item["update_policy"], {"mode", "revision_policy", "max_staleness_seconds", "replay_policy"}, "update policy")
        if not isinstance(policy["mode"], str) or policy["mode"] not in {"immutable_snapshot", "mutable_history", "live_stream"}:
            raise ValueError("invalid source update mode")
        if not isinstance(policy["revision_policy"], str) or policy["revision_policy"] not in {"content_digest", "provider_revision", "unversioned"}:
            raise ValueError("invalid source revision policy")
        if not isinstance(policy["replay_policy"], str) or policy["replay_policy"] not in {"frozen_input", "recorded_stream", "not_declared"}:
            raise ValueError("invalid source replay policy")
        staleness = policy["max_staleness_seconds"]
        if staleness is not None and (type(staleness) is not int or staleness < 0):
            raise ValueError("invalid source staleness budget")
        if policy["mode"] == "immutable_snapshot" and policy["revision_policy"] == "unversioned":
            raise ValueError("immutable snapshot requires verifiable revision")
        if policy["mode"] == "live_stream" and policy["replay_policy"] == "frozen_input":
            raise ValueError("live source replay requires a recorded stream")
        update_policy = UpdatePolicy(policy["mode"], policy["revision_policy"], staleness, policy["replay_policy"])
        integrations = item["integrations"]
        if not isinstance(integrations, dict):
            raise ValueError("integrations must be an object")
        parsed_integrations = []
        for name, target in integrations.items():
            _id(name, "integration")
            module, separator, symbol = _text(target, "integration entrypoint").partition(":")
            if not separator or not _MODULE.fullmatch(module) or not _MODULE.fullmatch(symbol):
                raise ValueError("invalid integration entrypoint")
            parsed_integrations.append((name, target))
        members.append(BundleMember(_id(item["id"], "member.id"), item["kind"], data_type, frequency,
                                    tuple(_id(ref, "related member") for ref in _array(item["related_members"], "related_members")), update_policy, tuple(sorted(parsed_integrations))))
    ids = {member.id for member in members}
    if not members or len(ids) != len(members):
        raise ValueError("empty or duplicate Bundle members")
    for member in members:
        if len(set(member.related_members)) != len(member.related_members) or member.id in member.related_members or not set(member.related_members) <= ids:
            raise ValueError("invalid Bundle member relationship")
    bindings = []
    seen = set()
    for raw in _array(root["product_bindings"], "product_bindings"):
        item = _object(raw, {"product_ref", "member_id", "source_product_ref"}, "product binding")
        binding = ProductBinding(_text(item["product_ref"], "product_ref"), _id(item["member_id"], "member_id"), _text(item["source_product_ref"], "source_product_ref"))
        key = (binding.member_id, binding.source_product_ref)
        if binding.member_id not in ids or key in seen:
            raise ValueError("unknown member or duplicate source product binding")
        seen.add(key)
        bindings.append(binding)
    return BundleManifest(_id(root["bundle_id"], "bundle_id"), _text(root["version"], "version"), _text(root["label"], "label"), root["provisioner"], root["execution_location"], entrypoints, tuple(members), tuple(bindings))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def discover_bundle_manifests(root: Path) -> tuple[BundleManifest, ...]:
    """Inspect one metadata level; no module imports, data probes or activation."""
    root = root.resolve(strict=True)
    paths = sorted(root.glob("*/bundle.json"))
    if len(paths) > MAX_BUNDLES:
        raise ValueError("installed Bundle inventory exceeds limit")
    result = []
    seen = set()
    total_bytes = 0
    for path in paths:
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("Bundle manifest escapes installation root")
        with path.open("rb") as handle:
            data = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ValueError("Bundle manifest exceeds size limit")
        total_bytes += len(data)
        if total_bytes > MAX_INVENTORY_BYTES:
            raise ValueError("Bundle inventory exceeds total metadata size limit")
        manifest = parse_bundle_manifest(json.loads(data, object_pairs_hook=_unique_object))
        if manifest.bundle_id in seen:
            raise ValueError(f"duplicate installed Bundle id: {manifest.bundle_id}")
        seen.add(manifest.bundle_id)
        result.append(manifest)
    return tuple(result)
