"""SQLite store for factor source code."""

from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

SOURCE_TABLE = "factor_family_sources"
METADATA_TABLE = "factor_family_source_metadata"


class FactorSourceMetadataUnavailable(RuntimeError):
    """The source row predates the explicit metadata schema migration."""

_IMPORT_MODULE_BY_SYMBOL: dict[str, str] = {
    "DataColumn": "tools.data.types",
    "DataCurrency": "tools.data.types",
    "DataFreq": "tools.data.types",
    "DataIndex": "tools.data.types",
    "DataMoneyMinorUnits": "tools.data.types",
    "DataTime": "tools.data.types",
    "TimePrecision": "tools.data.types",
    "UniqueNameObject": "tools.data.types",
    "CurrencyConversionContext": "tools.data.types.currency",
    "default_fx_rate_provider": "tools.data.types.currency",
    "normalize_currency": "tools.data.types.currency",
    "normalize_optional_currency": "tools.data.types.currency",
    "resolve_product_currency": "tools.data.types.currency",
    "require_product_currency_vector": "tools.data.types.currency",
    "ProductDataView": "tools.data.views",
    "DataProvider": "tools.data.providers",
    "DataProviderSync": "tools.data.providers",
    "_DataProviderMeta": "tools.data.providers",
    "_DataMultipleProviderMeta": "tools.data.providers",
    "DataProviderProductTS": "tools.data.providers",
    "PathResolver": "tools.data.providers.DistributedComponents",
    "LocalPathResolver": "tools.data.providers.DistributedComponents",
    "Factor": "tools.factors",
    "FactorFamily": "tools.factors",
    "Parameter": "tools.parameters",
    "TypeParam": "tools.parameters",
    "FinRangeParam": "tools.parameters",
    "TimeDeltaParam": "tools.parameters",
    "FactorParam": "tools.parameters",
    "ValueSpace": "tools.parameters",
    "DataColumnParam": "tools.parameters",
    "DataTimeParam": "tools.parameters",
    "WindowParam": "tools.parameters",
}


def _split_import_line(line: str) -> list[str]:
    try:
        node = ast.parse(line).body[0]
    except Exception:
        return [line]
    if not isinstance(node, ast.ImportFrom) or node.module is None:
        return [line]
    grouped: dict[tuple[str, int], list[ast.alias]] = {}
    original_aliases = list(node.names)
    changed = False
    for alias in original_aliases:
        imported_name = alias.name
        target_module = _IMPORT_MODULE_BY_SYMBOL.get(imported_name, node.module)
        if target_module != node.module:
            changed = True
        key = (target_module, node.level)
        grouped.setdefault(key, []).append(alias)
    if not changed:
        return [line]
    rendered: list[str] = []
    for (module, level), aliases in grouped.items():
        rendered.append(
            ast.unparse(
                ast.ImportFrom(module=module, names=aliases, level=level)
            )
        )
    return rendered


def normalize_factor_source_code(source_code: str) -> str:
    trailing_newline = source_code.endswith("\n")
    lines: list[str] = []
    for raw_line in source_code.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("from ") and " import " in stripped:
            indent = raw_line[: len(raw_line) - len(stripped)]
            rewritten = _split_import_line(stripped)
            lines.extend(indent + item for item in rewritten)
        else:
            lines.append(raw_line)
    normalized = "\n".join(lines)
    if trailing_newline and normalized:
        normalized += "\n"
    return normalized


def canonical_factor_source_code(source_code: str) -> str:
    """Normalize executable source without interpreting legacy metadata.

    Display metadata is migrated explicitly into SQLite.  Runtime reads and
    writes never parse or rewrite it, so legacy rows cannot be silently
    accepted under the new storage contract.
    """
    return normalize_factor_source_code(source_code or "")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SOURCE_TABLE} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            factor_name TEXT NOT NULL DEFAULT '',
            source_code TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {METADATA_TABLE} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            chinese_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id)
        )
        """
    )


def ensure_factor_source_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def _load_source(source_kind: str, owner_username: str, factor_id: str) -> str | None:
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                """
                SELECT s.source_code, m.factor_id AS metadata_factor_id
                FROM factor_family_sources AS s
                LEFT JOIN factor_family_source_metadata AS m
                  ON m.source_kind = s.source_kind
                 AND m.owner_username = s.owner_username
                 AND m.factor_id = s.factor_id
                WHERE s.source_kind = ? AND s.owner_username = ? AND s.factor_id = ?
                """,
                (source_kind, owner_username or "", factor_id),
            ).fetchone()
            if row is None:
                return None
            if row["metadata_factor_id"] is None:
                raise FactorSourceMetadataUnavailable(
                    f"factor source metadata migration required: {source_kind}/{owner_username}/{factor_id}"
                )
            source_code = str(row["source_code"] or "")
            normalized = canonical_factor_source_code(source_code)
            return normalized or None
    except FactorSourceMetadataUnavailable:
        raise
    except Exception:
        return None


def get_factor_source_record(source_kind: str, owner_username: str, factor_id: str) -> dict[str, Any] | None:
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                """
                SELECT s.source_kind, s.owner_username, s.factor_id, s.factor_name,
                       s.source_code, s.updated_at,
                       m.chinese_name, m.description, m.category
                FROM factor_family_sources
                AS s
                LEFT JOIN factor_family_source_metadata AS m
                  ON m.source_kind = s.source_kind
                 AND m.owner_username = s.owner_username
                 AND m.factor_id = s.factor_id
                WHERE s.source_kind = ? AND s.owner_username = ? AND s.factor_id = ?
                """,
                (source_kind, owner_username or "", factor_id),
            ).fetchone()
            if row is None:
                return None
            metadata = {
                "chinese_name": str(row["chinese_name"] or ""),
                "description": str(row["description"] or ""),
                "category": str(row["category"] or ""),
            }
            if row["chinese_name"] is None:
                raise FactorSourceMetadataUnavailable(
                    f"factor source metadata migration required: {source_kind}/{owner_username}/{factor_id}"
                )
            return {
                "source_kind": row["source_kind"],
                "owner_username": row["owner_username"],
                "factor_id": row["factor_id"],
                "factor_name": row["factor_name"],
                "source_code": canonical_factor_source_code(str(row["source_code"] or "")),
                "updated_at": float(row["updated_at"] or 0.0),
                **metadata,
            }
    except FactorSourceMetadataUnavailable:
        raise
    except Exception:
        return None


def load_factor_source(source_kind: str, owner_username: str, factor_id: str) -> str | None:
    return _load_source(source_kind, owner_username, factor_id)


def upsert_factor_source(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    factor_name: str,
    source_code: str,
    *,
    chinese_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    family_formula_fingerprint: str = "",
) -> str:
    normalized_source_code = canonical_factor_source_code(source_code or "")
    metadata = {
        "chinese_name": str(chinese_name or ""),
        "description": str(description or ""),
        "category": str(category or ""),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO factor_family_sources (
                source_kind, owner_username, factor_id, factor_name, source_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, owner_username, factor_id) DO UPDATE SET
                factor_name = excluded.factor_name,
                source_code = excluded.source_code,
                updated_at = excluded.updated_at
            """,
            (
                source_kind,
                owner_username or "",
                factor_id,
                factor_name or factor_id,
                normalized_source_code,
                time.time(),
            ),
        )
        _upsert_metadata(
            conn, source_kind, owner_username, factor_id, metadata,
        )
    _enqueue_source_metadata(
        source_kind, owner_username, factor_id, factor_name,
        normalized_source_code,
        metadata=metadata,
        family_formula_fingerprint=family_formula_fingerprint,
    )
    return str(Settings.CACHE_DB_PATH)


def delete_factor_source(source_kind: str, owner_username: str, factor_id: str) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            DELETE FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", factor_id),
        )
        conn.execute(
            f"""
            DELETE FROM {METADATA_TABLE}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", factor_id),
        )
    _enqueue_source_metadata(
        source_kind, owner_username, factor_id, "", "", deleted=True,
    )
    return str(Settings.CACHE_DB_PATH)


def rename_factor_source(
    source_kind: str,
    owner_username: str,
    old_factor_id: str,
    new_factor_id: str,
    new_factor_name: str,
) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT source_code, factor_name, updated_at
            FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", old_factor_id),
        ).fetchone()
        if row is None:
            return str(Settings.CACHE_DB_PATH)
        metadata_row = conn.execute(
            f"""
            SELECT chinese_name, description, category
            FROM {METADATA_TABLE}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", old_factor_id),
        ).fetchone()
        conn.execute(
            """
            DELETE FROM factor_family_sources
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            """,
            (source_kind, owner_username or "", old_factor_id),
        )
        conn.execute(
            """
            INSERT INTO factor_family_sources (
                source_kind, owner_username, factor_id, factor_name, source_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, owner_username, factor_id) DO UPDATE SET
                factor_name = excluded.factor_name,
                source_code = excluded.source_code,
                updated_at = excluded.updated_at
            """,
            (
                source_kind,
                owner_username or "",
                new_factor_id,
                new_factor_name or new_factor_id,
                canonical_factor_source_code(str(row["source_code"] or "")),
                time.time(),
            ),
        )
        metadata: dict[str, str] = {}
        if metadata_row is not None:
            metadata = {
                "chinese_name": str(metadata_row["chinese_name"] or ""),
                "description": str(metadata_row["description"] or ""),
                "category": str(metadata_row["category"] or ""),
            }
            _upsert_metadata(
                conn,
                source_kind,
                owner_username,
                new_factor_id,
                metadata,
            )
        conn.execute(
            f"DELETE FROM {METADATA_TABLE} WHERE source_kind = ? AND owner_username = ? AND factor_id = ?",
            (source_kind, owner_username or "", old_factor_id),
        )
        source_code = canonical_factor_source_code(str(row["source_code"] or ""))
    # The outbox uses a second connection to the same SQLite database.  It
    # must run after this write transaction is closed; otherwise SQLite keeps
    # the rename transaction open and the nested outbox write raises
    # ``database is locked``.
    _enqueue_source_metadata(
        source_kind, owner_username, old_factor_id, "", "", deleted=True,
    )
    _enqueue_source_metadata(
        source_kind, owner_username, new_factor_id, new_factor_name,
        source_code, metadata=metadata,
    )
    return str(Settings.CACHE_DB_PATH)


def _enqueue_source_metadata(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    factor_name: str,
    source_code: str,
    *,
    metadata: dict[str, str] | None = None,
    deleted: bool = False,
    family_formula_fingerprint: str = "",
) -> None:
    """Sync a source manifest, never the source code itself."""
    try:
        from tools.data.sqlite.account_manager.domain_sync import enqueue_entity

        principal = str(owner_username or "").strip() or "__public__"
        enqueue_entity(
            principal,
            "factor_source",
            f"{source_kind}:{factor_id}",
            {
                "source_kind": source_kind,
                "owner_username": owner_username or "",
                "factor_id": factor_id,
                "factor_name": factor_name or factor_id,
                "source_sha256": hashlib.sha256(source_code.encode("utf-8")).hexdigest()
                if source_code else "",
                "source_bytes": len(source_code.encode("utf-8")),
                "storage_server_id": str(
                    os.environ.get("FACTORTESTER_SERVER_ID") or ""
                ).strip(),
                "visibility": "public" if source_kind == "public" else "private",
                "chinese_name": str((metadata or {}).get("chinese_name") or ""),
                "description": str((metadata or {}).get("description") or ""),
                "category": str((metadata or {}).get("category") or ""),
                # family formula fingerprint is the immutable semantic identity of
                # the source.  The receiving server records it (and, on demand,
                # hydrates the source body) so version history converges across
                # servers even though the body itself is pulled lazily.
                "family_formula_fingerprint": str(
                    family_formula_fingerprint or ""
                ).strip(),
            },
            deleted=deleted,
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return


def list_factor_sources(source_kind: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT s.source_kind, s.owner_username, s.factor_id, s.factor_name,
                   s.source_code, s.updated_at,
                   m.chinese_name, m.description, m.category
            FROM factor_family_sources AS s
            LEFT JOIN factor_family_source_metadata AS m
              ON m.source_kind = s.source_kind
             AND m.owner_username = s.owner_username
             AND m.factor_id = s.factor_id
            WHERE s.source_kind = ?
            ORDER BY s.owner_username, s.factor_id
            """,
            (source_kind,),
        ).fetchall()
    result = []
    for row in rows:
        metadata = {
            "chinese_name": str(row["chinese_name"] or ""),
            "description": str(row["description"] or ""),
            "category": str(row["category"] or ""),
        }
        if row["chinese_name"] is None:
            raise FactorSourceMetadataUnavailable(
                f"factor source metadata migration required: {source_kind}/{row['owner_username']}/{row['factor_id']}"
            )
        result.append({
            "source_kind": row["source_kind"],
            "owner_username": row["owner_username"],
            "factor_id": row["factor_id"],
            "factor_name": row["factor_name"],
            "source_code": canonical_factor_source_code(str(row["source_code"] or "")),
            "updated_at": row["updated_at"],
            **metadata,
        })
    return result


def _upsert_metadata(
    conn: sqlite3.Connection,
    source_kind: str,
    owner_username: str,
    factor_id: str,
    metadata: dict[str, str],
) -> None:
    conn.execute(
        f"""
        INSERT INTO {METADATA_TABLE} (
            source_kind, owner_username, factor_id,
            chinese_name, description, category, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_kind, owner_username, factor_id) DO UPDATE SET
            chinese_name = excluded.chinese_name,
            description = excluded.description,
            category = excluded.category,
            updated_at = excluded.updated_at
        """,
        (
            source_kind,
            owner_username or "",
            factor_id,
            str(metadata.get("chinese_name") or ""),
            str(metadata.get("description") or ""),
            str(metadata.get("category") or ""),
            time.time(),
        ),
    )


def get_factor_source_metadata(
    source_kind: str,
    owner_username: str,
    factor_id: str,
) -> dict[str, str]:
    """Return explicitly migrated display metadata."""
    record = get_factor_source_record(source_kind, owner_username, factor_id)
    if record is None:
        raise FactorSourceMetadataUnavailable(
            f"factor source metadata unavailable: {source_kind}/{owner_username}/{factor_id}"
        )
    return {
        "chinese_name": str(record.get("chinese_name") or ""),
        "description": str(record.get("description") or ""),
        "category": str(record.get("category") or ""),
    }


def upsert_factor_source_metadata(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    *,
    chinese_name: str = "",
    description: str = "",
    category: str = "",
) -> str:
    """Update display metadata without changing the source revision."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        _upsert_metadata(
            conn,
            source_kind,
            owner_username,
            factor_id,
            {
                "chinese_name": chinese_name,
                "description": description,
                "category": category,
            },
        )
    return str(Settings.CACHE_DB_PATH)
