"""Read-only bounded factor summary for Planning Agent startup."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


_MAX_FAMILY_REFS = 32
_MAX_FAMILY_REF_BYTES = 1024


def load_workspace_factor_summary(
    *,
    workspace_id: str,
    owner: str,
) -> dict[str, Any] | None:
    """Read one compact summary without schema work or source disclosure."""
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT configuration_id, revision, payload_json
                FROM research_configurations
                WHERE workspace_id=? AND owner=? AND role='workspace'
                  AND deleted_at IS NULL
                """,
                (str(workspace_id), str(owner)),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: research_configurations" not in str(exc):
            raise
        return None
    if row is None:
        return None
    payload = orjson.loads(row["payload_json"])
    shared = payload.get("shared") if isinstance(payload, dict) else {}
    factors = shared.get("factors") if isinstance(shared, dict) else []
    family_refs = _bounded_family_refs_from_factors(factors)
    payload_hash = hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    return {
        "configuration_id": str(row["configuration_id"]),
        "revision": int(row["revision"]),
        "fingerprint": payload_hash,
        "family_count": len(family_refs),
        "factor_count": len(factors) if isinstance(factors, list) else 0,
        "family_refs": family_refs,
        "omitted_family_count": max(
            _factor_family_count(factors) - len(family_refs), 0,
        ),
    }


def _factor_family_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item.get("factor_family_ref") or item.get("family_ref")
            or item.get("factor_family_alias") or "")
        for item in value if isinstance(item, dict)
        and str(item.get("factor_family_ref") or item.get("family_ref")
            or item.get("factor_family_alias") or "")
    ))


def _factor_family_count(value: Any) -> int:
    return len(_factor_family_refs(value))


def _bounded_family_refs_from_factors(value: Any) -> list[str]:
    result: list[str] = []
    for alias in _factor_family_refs(value):
        candidate = [*result, alias]
        if (
            len(candidate) > _MAX_FAMILY_REFS
            or len(orjson.dumps(candidate)) > _MAX_FAMILY_REF_BYTES
        ):
            break
        result = candidate
    return result
