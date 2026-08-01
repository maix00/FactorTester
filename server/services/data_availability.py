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
from tools.data.availability.model import canonical_hash, profile_document
from tools.data.availability.registry import (
    availability_connector,
    availability_connector_keys,
)
from tools.data.field_history import summarize_historical_field_coverage
from tools.data.providers import DataProviderProductTS
from tools.data.providers.DataProviderProductTSBundle import (
    DataProviderProductTSBundle,
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
    inspection_runtime: str = "server",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return one immutable profile, scanning only on the first request.

    The canonical request is the cache identity. Concurrent clients requesting
    the same scope share one materialization; later calls only read SQLite.
    Refresh is intentionally an internal authority operation, not an Agent
    query option.
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
        inspection_runtime=inspection_runtime,
    )
    request_hash = canonical_hash(request)
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
            inspection_runtime=inspection_runtime,
        )
        _store_profile(request_hash=request_hash, request=request, profile=profile)
        return profile


def load_availability_profile(profile_ref: str) -> dict[str, Any]:
    """Load a frozen profile without touching any registered data source."""
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
    """Return declared sources and already-materialized coverage snapshots."""
    _ensure_sources_registered()
    sources = []
    for source in DataProviderProductTS.all():
        sources.append({
            "source": str(getattr(source, "key", source)),
            "label": str(getattr(source, "label", getattr(source, "key", source))),
            "frequency": _frequency_name(getattr(source, "freq", None)),
            "fields": sorted({
                str(value) for value in getattr(source, "data_cols_mapping", {}).values()
            }),
            "time_fields": sorted({
                str(value) for value in getattr(source, "time_cols_mapping", {}).values()
            }),
            "inspection_runtime": "server",
        })
    registered = {item["source"] for item in sources}
    for key in availability_connector_keys():
        if key not in registered:
            sources.append({
                "source": key,
                "label": key,
                "frequency": None,
                "fields": [],
                "time_fields": [],
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
    inspection_runtime: str,
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
        inspection_runtime=inspection_runtime,
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
        "inspection_runtime": str(values["inspection_runtime"]),
    }


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
    registered = {
        str(getattr(source, "key", source)): source
        for source in DataProviderProductTS.all()
    }
    resolved: list[Any] = []
    connectors: list[Any] = []
    missing: list[str] = []
    for name in names:
        provider = registered.get(name)
        connector = availability_connector(name)
        if isinstance(provider, DataProviderProductTSBundle):
            resolved.extend(_filter_by_frequency(provider.members, frequencies))
        elif provider is not None:
            resolved.extend(_filter_by_frequency((provider,), frequencies))
        if connector is not None:
            connectors.append(connector)
        if provider is None and connector is None:
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
