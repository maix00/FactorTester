"""Strict, source-free manifest contract for one local data-source plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_KINDS = {"external_connector", "user_source"}
_STATUSES = {"ready", "not_probed", "unavailable", "disabled"}


@dataclass(frozen=True, slots=True)
class LocalSourceProduct:
    product_ref: str
    alias: str
    display_name: str
    class_path: str
    product_kind: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocalSourceManifest:
    source_id: str
    source_name: str
    source_kind: str
    provider_kind: str
    version: str
    connector: dict[str, str]
    availability: dict[str, Any]
    members: tuple[dict[str, Any], ...]
    categories: tuple[dict[str, Any], ...]
    products: tuple[LocalSourceProduct, ...]


def validate_local_source_manifest(value: Any) -> LocalSourceManifest:
    item = _object(value, "source manifest")
    expected = {
        "schema_version", "managed_by", "source_id", "source_name",
        "source_kind", "provider_kind", "version", "connector",
        "availability", "members", "categories", "products",
    }
    if set(item) != expected:
        raise ValueError("local source manifest fields are invalid")
    if item.get("schema_version") != 1:
        raise ValueError("local source manifest schema_version is unsupported")
    if item.get("managed_by") != "factortester-client":
        raise ValueError("local source manifest owner is invalid")
    source_id = _identifier(item.get("source_id"), "source_id")
    source_kind = _text(item.get("source_kind"), "source_kind")
    if source_kind not in _SOURCE_KINDS:
        raise ValueError("local source_kind is unsupported")
    connector = _connector(item.get("connector"))
    availability = _availability(item.get("availability"))
    members = _array(item.get("members"), "members")
    products = _array(item.get("products"), "products")
    if not members or not products:
        raise ValueError("local source members and products cannot be empty")
    parsed_members = tuple(_member(member) for member in members)
    parsed_products = tuple(_product(product) for product in products)
    aliases = [product.alias for product in parsed_products]
    if len(set(aliases)) != len(aliases):
        raise ValueError("local source product aliases must be unique")
    return LocalSourceManifest(
        source_id=source_id,
        source_name=_text(item.get("source_name"), "source_name"),
        source_kind=source_kind,
        provider_kind=_identifier(item.get("provider_kind"), "provider_kind"),
        version=_text(item.get("version"), "version"),
        connector=connector,
        availability=availability,
        members=parsed_members,
        categories=tuple(
            _category(category)
            for category in _array(item.get("categories"), "categories")
        ),
        products=parsed_products,
    )


def _connector(value: Any) -> dict[str, str]:
    item = _object(value, "connector")
    if set(item) != {"entrypoint", "probe_mode", "credential_store"}:
        raise ValueError("local source connector fields are invalid")
    entrypoint = _text(item.get("entrypoint"), "connector.entrypoint")
    path = PurePosixPath(entrypoint)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError("local source connector entrypoint is unsafe")
    if item.get("probe_mode") != "explicit":
        raise ValueError("local source connector probe_mode must be explicit")
    if item.get("credential_store") != "keychain":
        raise ValueError("local source credentials must use Keychain")
    return {key: str(item[key]) for key in item}


def _availability(value: Any) -> dict[str, Any]:
    item = _object(value, "availability")
    if set(item) != {"status", "available_product_refs"}:
        raise ValueError("local source availability fields are invalid")
    status = _text(item.get("status"), "availability.status")
    if status not in _STATUSES:
        raise ValueError("local source availability status is invalid")
    refs = _array(item.get("available_product_refs"), "available_product_refs")
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("available_product_refs must contain references")
    return {"status": status, "available_product_refs": list(refs)}


def _member(value: Any) -> dict[str, Any]:
    item = _object(value, "member")
    if set(item) != {
        "id", "label", "timezone", "time_columns", "data_columns",
        "data_mode",
    }:
        raise ValueError("local source member fields are invalid")
    mode = _object(item.get("data_mode"), "data_mode")
    if set(mode) != {
        "id", "title_zh", "available", "sampling_mode", "frequency",
        "data_kind", "market_depth", "delivery_mode",
    }:
        raise ValueError("local source data_mode fields are invalid")
    if not isinstance(mode.get("available"), bool):
        raise ValueError("local source data_mode.available must be boolean")
    for field in (
        "id", "title_zh", "sampling_mode", "data_kind", "market_depth",
        "delivery_mode",
    ):
        _text(mode.get(field), f"data_mode.{field}")
    frequency = mode.get("frequency")
    if frequency is not None and not isinstance(frequency, str):
        raise ValueError("local source data_mode.frequency is invalid")
    return {
        "id": _identifier(item.get("id"), "member.id"),
        "label": _text(item.get("label"), "member.label"),
        "timezone": str(item.get("timezone") or ""),
        "time_columns": _string_map(item.get("time_columns"), "time_columns"),
        "data_columns": _string_map(item.get("data_columns"), "data_columns"),
        "data_mode": dict(mode),
    }


def _product(value: Any) -> LocalSourceProduct:
    item = _object(value, "product")
    if set(item) != {
        "product_ref", "alias", "display_name", "class_path",
        "product_kind", "metadata",
    }:
        raise ValueError("local source product fields are invalid")
    class_path = _text(item.get("class_path"), "product.class_path")
    path = PurePosixPath(class_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("local source product class_path is invalid")
    return LocalSourceProduct(
        product_ref=_text(item.get("product_ref"), "product.product_ref"),
        alias=_identifier(item.get("alias"), "product.alias"),
        display_name=_text(item.get("display_name"), "product.display_name"),
        class_path=class_path,
        product_kind=_identifier(item.get("product_kind"), "product.product_kind"),
        metadata=_object(item.get("metadata"), "product.metadata"),
    )


def _category(value: Any) -> dict[str, Any]:
    item = _object(value, "category")
    if set(item) != {
        "id", "alias", "title_zh", "dimensions", "composable",
        "is_composite",
    }:
        raise ValueError("local source category fields are invalid")
    dimensions = _array(item.get("dimensions"), "category.dimensions")
    if not dimensions or any(not isinstance(value, str) for value in dimensions):
        raise ValueError("local source category dimensions are invalid")
    if not all(isinstance(item.get(key), bool) for key in ("composable", "is_composite")):
        raise ValueError("local source category flags are invalid")
    return dict(item)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _string_map(value: Any, field: str) -> dict[str, str]:
    item = _object(value, field)
    if any(not isinstance(key, str) or not isinstance(raw, str) for key, raw in item.items()):
        raise ValueError(f"{field} must contain strings")
    return dict(item)


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text
