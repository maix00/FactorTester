"""Materialize and reuse explicit market-data capability snapshots."""

from __future__ import annotations

from functools import lru_cache
import json
import threading
import time
from typing import Any

import settings as Settings
from server.modules.shared.price_services import cached_products
from tools.data.availability import build_availability_profile
from tools.data.availability.model import (
    PROFILE_SCHEMA_VERSION,
    canonical_hash,
    profile_document,
)
from tools.data.availability.registry import (
    availability_connector,
)
from tools.data.field_history import summarize_historical_field_coverage
from tools.data.source_catalog import (
    data_source_declaration,
    data_source_declarations,
)
from tools.data.types import DataFreq
from tools.data.sqlite.db import connect_sqlite


_PROFILE_PREFIX = "data-availability-profile:"
_profile_locks_guard = threading.Lock()
_profile_locks: dict[str, threading.Lock] = {}


def availability_for_scope(
    *,
    product_names: list[str],
    source_names: list[str],
    frequency_names: list[str] | None = None,
    probe: bool = False,
    expanded: bool = False,
    required_fields: list[str] | None = None,
    include_field_catalog: bool = False,
    include_historical_fields: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return a request-scoped availability observation, scanning on first use.

    The request and profile schema are the cache identity. The profile reports
    the source's observed coverage; it does not pin the source's data bytes.
    Concurrent clients requesting the same scope share one materialization;
    later calls only read SQLite. Refresh remains an internal authority
    operation, not an Agent query option.
    """
    request = _request_document(
        product_names=product_names,
        source_names=source_names,
        frequency_names=frequency_names or [],
        probe=probe,
        expanded=expanded,
        required_fields=required_fields or [],
        include_field_catalog=include_field_catalog,
        include_historical_fields=include_historical_fields,
    )
    request_hash = _profile_request_cache_identity(request)
    if not refresh:
        cached = _load_by_request_hash(request_hash)
        if cached is not None:
            return cached
    lock = _profile_lock(request_hash)
    with lock:
        if not refresh:
            cached = _load_by_request_hash(request_hash)
            if cached is not None:
                return cached
        profile = _inspect_scope(
            product_names=product_names,
            source_names=source_names,
            frequency_names=frequency_names,
            probe=probe,
            expanded=expanded,
            required_fields=required_fields,
            include_field_catalog=include_field_catalog,
            include_historical_fields=include_historical_fields,
        )
        _store_profile(request_hash=request_hash, request=request, profile=profile)
        return profile


def load_availability_profile(profile_ref: str) -> dict[str, Any]:
    """Load a stored availability observation without probing its data source."""
    normalized = str(profile_ref or "")
    if not normalized.startswith(_PROFILE_PREFIX):
        raise ValueError("invalid data availability profile reference")
    profile_hash = normalized.removeprefix(_PROFILE_PREFIX)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_profile_schema(conn)
        row = conn.execute(
            "SELECT profile_json FROM data_availability_profiles "
            "WHERE profile_hash=?",
            (profile_hash,),
        ).fetchone()
    if row is None:
        raise KeyError("data availability profile not found")
    return json.loads(row["profile_json"])


def data_capability_catalog() -> dict[str, Any]:
    """Return declared sources and already-materialized coverage observations."""
    _ensure_sources_registered()
    sources = []
    for declaration in data_source_declarations():
        members = declaration.members
        sources.append({
            "source": declaration.key,
            "label": declaration.label,
            "provider_kind": declaration.provider_kind,
            "modes": [mode.as_dict() for mode in declaration.modes()],
            "frequencies": sorted({
                member.frequency for member in members if member.frequency
            }),
            "fields": sorted({
                value for member in members for value in member.data_columns.values()
            }),
            "time_fields": sorted({
                value for member in members for value in member.time_columns.values()
            }),
            "inspection_runtime": "server",
        })
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_profile_schema(conn)
        rows = conn.execute(
            "SELECT profile_hash, request_json, profile_json, created_at "
            "FROM data_availability_profiles ORDER BY created_at DESC"
        ).fetchall()
    snapshots = []
    for row in rows:
        profile = json.loads(row["profile_json"])
        snapshots.append({
            "profile_ref": _PROFILE_PREFIX + str(row["profile_hash"]),
            "request": json.loads(row["request_json"]),
            "as_of": profile.get("as_of"),
            "entry_count": len(profile.get("entries") or []),
            "historical_fields": profile.get("historical_fields") or [],
        })
    return {
        "schema_version": 1,
        "sources": sorted(sources, key=lambda item: item["source"]),
        "snapshots": snapshots,
    }


def profile_reference(profile: dict[str, Any]) -> str:
    return _PROFILE_PREFIX + str(profile["profile_hash"])


def request_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    value = {
        "products": list(profile.get("product_scope") or []),
        "sources": list(profile.get("source_scope") or []),
        "frequencies": list(profile.get("frequency_scope") or []),
        "probe": bool(profile.get("probe", False)),
        "expanded": bool(profile.get("expanded", False)),
    }
    if "required_fields" in profile:
        value["fields"] = list(profile.get("required_fields") or [])
    if "include_field_catalog" in profile:
        value["include_field_catalog"] = bool(profile["include_field_catalog"])
    if "include_historical_fields" in profile:
        value["include_historical_fields"] = bool(profile["include_historical_fields"])
    return value


def _inspect_scope(
    *,
    product_names: list[str],
    source_names: list[str],
    frequency_names: list[str] | None,
    probe: bool,
    expanded: bool,
    required_fields: list[str] | None,
    include_field_catalog: bool,
    include_historical_fields: bool,
) -> dict[str, Any]:
    _ensure_sources_registered()
    products = _resolve_products(product_names)
    frequencies = _normalise_frequencies(frequency_names or [])
    sources, connectors = _resolve_sources(source_names, frequencies)
    from datetime import datetime, timezone

    as_of = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    if sources:
        entries.extend(build_availability_profile(
            products=products,
            sources=sources,
            as_of=as_of,
            required_fields=required_fields,
            include_field_catalog=include_field_catalog,
        )["entries"])
    for connector in connectors:
        entries.extend(connector.inspect(
            products,
            probe=probe,
            expanded=expanded,
        ))
    history = (
        summarize_historical_field_coverage(product_names)
        if include_historical_fields
        else None
    )
    return profile_document(
        product_scope=list(product_names),
        source_scope=list(source_names),
        frequency_scope=frequencies,
        probe=probe,
        expanded=expanded,
        required_fields=list(required_fields or []),
        include_field_catalog=include_field_catalog,
        include_historical_fields=include_historical_fields,
        historical_fields=history,
        inspection_runtime="server",
        entries=entries,
        as_of=as_of,
    )


def _request_document(**values: Any) -> dict[str, Any]:
    return {
        "products": list(values["product_names"]),
        "sources": list(values["source_names"]),
        "frequencies": _normalise_frequencies(values["frequency_names"]),
        "probe": bool(values["probe"]),
        "expanded": bool(values["expanded"]),
        "fields": list(values["required_fields"]),
        "include_field_catalog": bool(values["include_field_catalog"]),
        "include_historical_fields": bool(values["include_historical_fields"]),
        "inspection_runtime": "server",
    }


def _profile_request_cache_identity(request: dict[str, Any]) -> str:
    return canonical_hash({
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "request": request,
    })


def _profile_lock(request_hash: str) -> threading.Lock:
    with _profile_locks_guard:
        return _profile_locks.setdefault(request_hash, threading.Lock())


def _ensure_profile_schema(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_availability_profiles (
            profile_hash TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL UNIQUE,
            request_json TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)


def _load_by_request_hash(request_hash: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_profile_schema(conn)
        row = conn.execute(
            "SELECT profile_json FROM data_availability_profiles "
            "WHERE request_hash=?",
            (request_hash,),
        ).fetchone()
    return json.loads(row["profile_json"]) if row is not None else None


def _store_profile(
    *, request_hash: str, request: dict[str, Any], profile: dict[str, Any],
) -> None:
    profile_hash = str(profile["profile_hash"])
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_profile_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO data_availability_profiles "
            "(profile_hash, request_hash, request_json, profile_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                profile_hash,
                request_hash,
                json.dumps(request, ensure_ascii=False, sort_keys=True),
                json.dumps(profile, ensure_ascii=False, sort_keys=True),
                time.time(),
            ),
        )


def _frequency_name(value: Any) -> str:
    try:
        return DataFreq(value).name
    except Exception:
        return str(value)


@lru_cache(maxsize=1)
def _ensure_sources_registered() -> None:
    from sources.registry import load_all_sources

    load_all_sources()


def _resolve_products(names: list[str]) -> list[Any]:
    registered = {
        str(getattr(product, "name", getattr(product, "alias", product))): product
        for product in cached_products()
        if product is not None
    }
    missing = [name for name in names if name not in registered]
    if missing:
        raise LookupError(f"未找到产品: {', '.join(missing)}")
    return [registered[name] for name in names]


def _resolve_sources(
    names: list[str],
    frequencies: list[str],
) -> tuple[list[Any], list[Any]]:
    registered_members = {
        member.key: member.execution_provider
        for declaration in data_source_declarations()
        for member in declaration.members
        if member.execution_provider is not None
    }
    resolved: list[Any] = []
    connectors: list[Any] = []
    missing: list[str] = []
    for name in names:
        declaration = data_source_declaration(name)
        provider = registered_members.get(name)
        providers = (
            declaration.execution_providers()
            if declaration is not None
            else ((provider,) if provider is not None else ())
        )
        resolved.extend(_filter_by_frequency(providers, frequencies))
        connector_key = (
            declaration.connector_key
            if declaration is not None
            else name
        )
        connector = availability_connector(connector_key) if connector_key else None
        if connector is not None:
            connectors.append(connector)
        if declaration is None and provider is None and connector is None:
            missing.append(name)
    if missing:
        raise LookupError(f"未找到数据源: {', '.join(missing)}")
    unique = {str(getattr(source, "key", source)): source for source in resolved}
    return list(unique.values()), connectors


def _normalise_frequencies(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        try:
            normalized = DataFreq(value).name
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无效数据频率: {value}") from exc
        if normalized not in result:
            result.append(normalized)
    return result


def _filter_by_frequency(
    sources: tuple[Any, ...],
    frequencies: list[str],
) -> tuple[Any, ...]:
    if not frequencies:
        return sources
    requested = set(frequencies)
    return tuple(
        source for source in sources
        if DataFreq(getattr(source, "freq", None)).name in requested
    )
