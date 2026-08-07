"""Transactional access to the client-local catalog."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from .schema import connect_catalog, ensure_catalog_schema


class LocalCatalogStore:
    """Own catalog metadata and bindings without resolving server products."""

    def __init__(self, client_root: str | Path) -> None:
        self.client_root = Path(client_root).expanduser().resolve()
        self.database_path = self.client_root / "catalog" / "catalog.sqlite"

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = connect_catalog(self.database_path)
        try:
            ensure_catalog_schema(connection)
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> dict[str, Any]:
        with self.connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            counts = self._counts(connection)
        return {"schema_version": version, "database": str(self.database_path), **counts}

    def upsert_source(self, value: dict[str, Any]) -> None:
        now = time.time()
        if any(not str(value.get(key) or "").strip() for key in ("source_id", "source_kind")):
            raise ValueError("catalog source_id and source_kind are required")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO catalog_sources (
                    source_id, source_kind, owner_ref, class_path,
                    source_revision, content_hash, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    owner_ref = excluded.owner_ref,
                    class_path = excluded.class_path,
                    source_revision = excluded.source_revision,
                    content_hash = excluded.content_hash,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    value["source_id"], value["source_kind"],
                    str(value.get("owner_ref") or ""), str(value.get("class_path") or ""),
                    str(value.get("source_revision") or ""),
                    str(value.get("content_hash") or ""),
                    str(value.get("state") or "active"), now, now,
                ),
            )

    def upsert_product(self, value: dict[str, Any]) -> None:
        now = time.time()
        product_ref = str(value.get("product_ref") or "").strip()
        source_id = str(value.get("source_id") or "").strip()
        class_path = str(value.get("class_path") or "").strip()
        alias = str(value.get("alias") or "").strip()
        if not all((product_ref, source_id, class_path, alias)):
            raise ValueError("product_ref, source_id, class_path and alias are required")
        if "/_products/" in class_path or any(part == "Category" for part in class_path.split("/")):
            raise ValueError("product class_path must not contain category or _products segments")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("product metadata must be an object")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO products (
                    product_ref, source_id, class_path, alias, display_name,
                    product_kind, catalog_revision, metadata_json, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_ref) DO UPDATE SET
                    source_id = excluded.source_id,
                    class_path = excluded.class_path,
                    alias = excluded.alias,
                    display_name = excluded.display_name,
                    product_kind = excluded.product_kind,
                    catalog_revision = excluded.catalog_revision,
                    metadata_json = excluded.metadata_json,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    product_ref, source_id, class_path, alias,
                    str(value.get("display_name") or alias),
                    str(value.get("product_kind") or "product"),
                    str(value.get("catalog_revision") or ""),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    str(value.get("state") or "active"), now, now,
                ),
            )

    def upsert_group(self, value: dict[str, Any]) -> None:
        now = time.time()
        group_ref = str(value.get("group_ref") or "").strip()
        owner_ref = str(value.get("owner_ref") or "").strip()
        name = str(value.get("name") or "").strip()
        if not all((group_ref, owner_ref, name)):
            raise ValueError("group_ref, owner_ref and name are required")
        definition = value.get("definition") or {}
        if not isinstance(definition, dict):
            raise ValueError("group definition must be an object")
        encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True)
        definition_hash = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO product_groups (
                    group_ref, owner_ref, name, definition_json, definition_hash,
                    catalog_revision, membership_hash, valid_from, valid_to,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_ref) DO UPDATE SET
                    owner_ref = excluded.owner_ref,
                    name = excluded.name,
                    definition_json = excluded.definition_json,
                    definition_hash = excluded.definition_hash,
                    catalog_revision = excluded.catalog_revision,
                    membership_hash = excluded.membership_hash,
                    valid_from = excluded.valid_from,
                    valid_to = excluded.valid_to,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    group_ref, owner_ref, name, encoded, definition_hash,
                    str(value.get("catalog_revision") or ""),
                    str(value.get("membership_hash") or ""),
                    str(value.get("valid_from") or ""), str(value.get("valid_to") or ""),
                    str(value.get("state") or "active"), now, now,
                ),
            )

    def replace_group_products(self, group_ref: str, products: list[dict[str, Any]]) -> None:
        """Replace one group's product membership as one local transaction."""
        group_ref = str(group_ref or "").strip()
        if not group_ref:
            raise ValueError("group_ref is required")
        with self.connection() as connection:
            connection.execute("DELETE FROM product_group_products WHERE group_ref = ?", (group_ref,))
            for product in products:
                product_ref = str(product.get("product_ref") or "").strip()
                if not product_ref:
                    raise ValueError("product_ref is required")
                connection.execute(
                    """
                    INSERT INTO product_group_products (
                        group_ref, product_ref, valid_from, valid_to, state,
                        source_revision, relation_revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group_ref, product_ref, str(product.get("valid_from") or ""),
                        str(product.get("valid_to") or ""), str(product.get("state") or "active"),
                        str(product.get("source_revision") or ""),
                        int(product.get("relation_revision") or 1),
                    ),
                )

    def upsert_factor(self, value: dict[str, Any]) -> None:
        now = time.time()
        factor_ref = str(value.get("factor_ref") or "").strip()
        family_name = str(value.get("family_name") or "").strip()
        factor_name = str(value.get("factor_name") or "").strip()
        if not all((factor_ref, family_name, factor_name)):
            raise ValueError("factor_ref, family_name and factor_name are required")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factors (
                    factor_ref, owner_ref, family_name, factor_name,
                    logical_kind, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_ref) DO UPDATE SET
                    owner_ref = excluded.owner_ref,
                    family_name = excluded.family_name,
                    factor_name = excluded.factor_name,
                    logical_kind = excluded.logical_kind,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    factor_ref, str(value.get("owner_ref") or ""), family_name,
                    factor_name, str(value.get("logical_kind") or "factor"),
                    str(value.get("state") or "active"), now, now,
                ),
            )

    def upsert_factor_revision(self, value: dict[str, Any]) -> None:
        now = time.time()
        revision_ref = str(value.get("factor_revision_ref") or "").strip()
        factor_ref = str(value.get("factor_ref") or "").strip()
        required = ("repository_ref", "git_commit", "git_blob", "relative_path", "source_hash")
        if not revision_ref or not factor_ref or not all(
            str(value.get(key) or "").strip() for key in required
        ):
            raise ValueError("factor revision identity and Git fields are required")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factor_revisions (
                    factor_revision_ref, factor_ref, repository_ref, git_commit,
                    git_blob, relative_path, source_hash, dirty, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_revision_ref) DO UPDATE SET
                    factor_ref = excluded.factor_ref, repository_ref = excluded.repository_ref,
                    git_commit = excluded.git_commit, git_blob = excluded.git_blob,
                    relative_path = excluded.relative_path, source_hash = excluded.source_hash,
                    dirty = excluded.dirty
                """,
                (
                    revision_ref, factor_ref, str(value["repository_ref"]),
                    str(value["git_commit"]), str(value["git_blob"]),
                    str(value["relative_path"]), str(value["source_hash"]),
                    int(bool(value.get("dirty", False))), now,
                ),
            )

    def upsert_factor_set(self, value: dict[str, Any]) -> None:
        now = time.time()
        set_ref = str(value.get("set_ref") or "").strip()
        owner_ref = str(value.get("owner_ref") or "").strip()
        set_id = str(value.get("set_id") or "").strip()
        required = ("manifest_path", "git_commit", "git_blob", "member_hash")
        if not set_ref or not owner_ref or not set_id or not all(
            str(value.get(key) or "").strip() for key in required
        ):
            raise ValueError("factor-set identity and Git fields are required")
        members = value.get("members") or []
        if not isinstance(members, list) or any(not str(member).strip() for member in members):
            raise ValueError("factor-set members must be a non-empty list")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factor_sets (
                    set_ref, owner_ref, set_id, title_zh, description_zh,
                    manifest_path, git_commit, git_blob, member_hash,
                    member_count, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(set_ref) DO UPDATE SET
                    owner_ref = excluded.owner_ref, set_id = excluded.set_id,
                    title_zh = excluded.title_zh, description_zh = excluded.description_zh,
                    manifest_path = excluded.manifest_path, git_commit = excluded.git_commit,
                    git_blob = excluded.git_blob, member_hash = excluded.member_hash,
                    member_count = excluded.member_count, state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    set_ref, owner_ref, set_id, str(value.get("title_zh") or set_id),
                    str(value.get("description_zh") or ""), str(value["manifest_path"]),
                    str(value["git_commit"]), str(value["git_blob"]),
                    str(value["member_hash"]), len(members), str(value.get("state") or "active"),
                    now, now,
                ),
            )
            connection.execute("DELETE FROM factor_set_members WHERE set_ref = ?", (set_ref,))
            connection.executemany(
                "INSERT INTO factor_set_members (set_ref, ordinal, factor_ref) VALUES (?, ?, ?)",
                [(set_ref, ordinal, str(member)) for ordinal, member in enumerate(members)],
            )

    def list_groups(self, owner_ref: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if owner_ref:
                rows = connection.execute(
                    "SELECT * FROM product_groups WHERE owner_ref = ? "
                    "ORDER BY name, group_ref", (owner_ref,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM product_groups ORDER BY owner_ref, name, group_ref"
                ).fetchall()
        return [dict(row) for row in rows]

    def list_group_subjects(self, group_ref: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM product_group_subject_bindings "
                "WHERE group_ref = ? ORDER BY subject_kind, subject_ref, valid_from",
                (group_ref,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_group_products(self, group_ref: str) -> list[dict[str, Any]]:
        """Return the product memberships for one local product group."""
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM product_group_products "
                "WHERE group_ref = ? ORDER BY product_ref, valid_from",
                (group_ref,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_factors(self, owner_ref: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM factors"
        args: tuple[Any, ...] = ()
        if owner_ref:
            query += " WHERE owner_ref = ?"
            args = (owner_ref,)
        query += " ORDER BY owner_ref, family_name, factor_name, factor_ref"
        with self.connection() as connection:
            rows = connection.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def list_factor_sets(self, owner_ref: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM factor_sets"
        args: tuple[Any, ...] = ()
        if owner_ref:
            query += " WHERE owner_ref = ?"
            args = (owner_ref,)
        query += " ORDER BY owner_ref, set_id, git_commit, git_blob"
        with self.connection() as connection:
            rows = connection.execute(query, args).fetchall()
            result = []
            for row in rows:
                value = dict(row)
                members = connection.execute(
                    "SELECT factor_ref FROM factor_set_members "
                    "WHERE set_ref = ? ORDER BY ordinal", (row["set_ref"],)
                ).fetchall()
                value["members"] = [item[0] for item in members]
                result.append(value)
        return result

    def replace_group_subjects(self, group_ref: str, subjects: list[dict[str, Any]]) -> None:
        """Replace one group's factor and factor-set bindings atomically."""
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM product_group_subject_bindings WHERE group_ref = ?",
                (group_ref,),
            )
            for subject in subjects:
                kind = str(subject.get("subject_kind") or "")
                ref = str(subject.get("subject_ref") or "").strip()
                if kind not in {"factor", "factor_set"} or not ref:
                    raise ValueError("subject_kind and subject_ref are required")
                connection.execute(
                    """
                    INSERT INTO product_group_subject_bindings (
                        group_ref, subject_kind, subject_ref, valid_from, valid_to,
                        state, source_revision, sync_state, relation_revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group_ref, kind, ref, str(subject.get("valid_from") or ""),
                        str(subject.get("valid_to") or ""), str(subject.get("state") or "active"),
                        str(subject.get("source_revision") or ""),
                        str(subject.get("sync_state") or "local"),
                        int(subject.get("relation_revision") or 1),
                    ),
                )

    @staticmethod
    def _counts(connection: sqlite3.Connection) -> dict[str, int]:
        tables = (
            "catalog_sources", "products", "product_groups", "product_group_products",
            "factors", "factor_revisions", "factor_sets", "factor_set_members",
            "product_group_subject_bindings",
        )
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
