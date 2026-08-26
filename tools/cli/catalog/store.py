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
from tools.cli.identities.factor import require_frozen_factor
from tools.cli.identities.factor_set import require_frozen_factor_set


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

    def materialize_source(
        self,
        source: dict[str, Any],
        products: list[dict[str, Any]],
    ) -> None:
        """Atomically materialize one client-owned source and its products."""
        now = time.time()
        source_id = str(source.get("source_id") or "").strip()
        source_kind = str(source.get("source_kind") or "").strip()
        if not source_id or not source_kind:
            raise ValueError("catalog source_id and source_kind are required")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO catalog_sources (
                    source_id, source_kind, owner_ref, class_path,
                    source_revision, content_hash, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_kind=excluded.source_kind,
                    owner_ref=excluded.owner_ref,
                    class_path=excluded.class_path,
                    source_revision=excluded.source_revision,
                    content_hash=excluded.content_hash,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id, source_kind, str(source.get("owner_ref") or ""),
                    str(source.get("class_path") or ""),
                    str(source.get("source_revision") or ""),
                    str(source.get("content_hash") or ""),
                    str(source.get("state") or "active"), now, now,
                ),
            )
            product_refs = {
                str(product.get("product_ref") or "").strip()
                for product in products
                if str(product.get("product_ref") or "").strip()
            }
            if product_refs:
                placeholders = ", ".join("?" for _ in product_refs)
                connection.execute(
                    f"UPDATE products SET state='unavailable', updated_at=? "
                    f"WHERE source_id=? AND product_ref NOT IN ({placeholders})",
                    (now, source_id, *sorted(product_refs)),
                )
            else:
                connection.execute(
                    "UPDATE products SET state='unavailable', updated_at=? "
                    "WHERE source_id=?",
                    (now, source_id),
                )
            for product in products:
                product_ref = str(product.get("product_ref") or "").strip()
                product_source = str(product.get("source_id") or source_id).strip()
                class_path = str(product.get("class_path") or "").strip()
                alias = str(product.get("alias") or "").strip()
                if not all((product_ref, product_source, class_path, alias)):
                    raise ValueError(
                        "product_ref, source_id, class_path and alias are required"
                    )
                if product_source != source_id:
                    raise ValueError("materialized product source_id does not match source")
                if "/_products/" in class_path or any(
                    part == "Category" for part in class_path.split("/")
                ):
                    raise ValueError(
                        "product class_path must not contain category or _products segments"
                    )
                metadata = product.get("metadata") or {}
                if not isinstance(metadata, dict):
                    raise ValueError("product metadata must be an object")
                connection.execute(
                    """
                    INSERT INTO products (
                        product_ref, source_id, class_path, alias, display_name,
                        product_kind, catalog_revision, metadata_json, state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_ref) DO UPDATE SET
                        source_id=excluded.source_id,
                        class_path=excluded.class_path,
                        alias=excluded.alias,
                        display_name=excluded.display_name,
                        product_kind=excluded.product_kind,
                        catalog_revision=excluded.catalog_revision,
                        metadata_json=excluded.metadata_json,
                        state=excluded.state,
                        updated_at=excluded.updated_at
                    """,
                    (
                        product_ref, product_source, class_path, alias,
                        str(product.get("display_name") or alias),
                        str(product.get("product_kind") or "product"),
                        str(product.get("catalog_revision") or ""),
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        str(product.get("state") or "active"), now, now,
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
        frozen = require_frozen_factor(value)
        factor_ref = frozen["ref"]
        identity = frozen["identity"]
        params = identity["params"]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factors (
                    factor_ref, family_ref, owner_ref, family_alias, factor_alias,
                    family_formula_fingerprint, self_formula_fingerprint,
                    params_json, logical_kind, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_ref) DO UPDATE SET
                    family_ref = excluded.family_ref,
                    owner_ref = excluded.owner_ref,
                    family_alias = excluded.family_alias,
                    factor_alias = excluded.factor_alias,
                    family_formula_fingerprint = excluded.family_formula_fingerprint,
                    self_formula_fingerprint = excluded.self_formula_fingerprint,
                    params_json = excluded.params_json,
                    logical_kind = excluded.logical_kind,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    factor_ref, identity["family_ref"], frozen["owner_ref"],
                    identity["family_alias"], frozen["alias"],
                    identity["family_formula_fingerprint"],
                    identity["self_formula_fingerprint"],
                    json.dumps(params, ensure_ascii=False, sort_keys=True),
                    "factor",
                    str(value.get("state") or "active"), now, now,
                ),
            )

    def upsert_factor_provenance(self, value: dict[str, Any]) -> None:
        now = time.time()
        factor_ref = str(value.get("ref") or "").strip()
        relative_path = str(value.get("relative_path") or "").strip()
        source_hash = str(value.get("source_hash") or "").strip()
        if not factor_ref or not relative_path or not source_hash:
            raise ValueError("factor provenance requires factor_ref, path and source hash")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factor_workspace_provenance (
                    factor_ref, repository_ref, revision, blob_hash,
                    relative_path, source_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    factor_ref, repository_ref, revision, blob_hash, relative_path
                ) DO UPDATE SET source_hash = excluded.source_hash
                """,
                (
                    factor_ref, str(value.get("repository_ref") or ""),
                    str(value.get("revision") or ""),
                    str(value.get("blob_hash") or ""), relative_path,
                    source_hash, now,
                ),
            )

    def upsert_factor_set(self, value: dict[str, Any]) -> None:
        now = time.time()
        frozen = require_frozen_factor_set(value)
        set_ref = frozen["ref"]
        owner_ref = frozen["owner_ref"]
        identity = frozen["identity"]
        set_id = identity["set_id"]
        members = identity["members"]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO factor_sets (
                    set_ref, owner_ref, set_id, title_zh, description_zh,
                    member_fingerprint,
                    member_count, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(set_ref) DO UPDATE SET
                    owner_ref = excluded.owner_ref, set_id = excluded.set_id,
                    title_zh = excluded.title_zh, description_zh = excluded.description_zh,
                    member_fingerprint = excluded.member_fingerprint,
                    member_count = excluded.member_count, state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    set_ref, owner_ref, set_id, frozen["alias"],
                    str(value.get("description") or ""),
                    identity["member_fingerprint"], len(members),
                    str(value.get("state") or "active"),
                    now, now,
                ),
            )
            connection.execute("DELETE FROM factor_set_members WHERE set_ref = ?", (set_ref,))
            connection.executemany(
                "INSERT INTO factor_set_members "
                "(set_ref, ordinal, factor_ref, frozen_identity_json) VALUES (?, ?, ?, ?)",
                [
                    (
                        set_ref, ordinal, member["ref"],
                        json.dumps(member, ensure_ascii=False, sort_keys=True),
                    )
                    for ordinal, member in enumerate(members)
                ],
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

    def list_products(self) -> list[dict[str, Any]]:
        """Return locally registered product identities and source metadata."""
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT products.*, catalog_sources.source_kind "
                "FROM products JOIN catalog_sources USING (source_id) "
                "ORDER BY products.class_path, products.alias, products.product_ref"
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            raw_metadata = value.pop("metadata_json", "")
            try:
                metadata = json.loads(raw_metadata) if raw_metadata else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            value["metadata"] = metadata if isinstance(metadata, dict) else {}
            result.append(value)
        return result

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
        query += " ORDER BY owner_ref, family_alias, factor_alias, factor_ref"
        with self.connection() as connection:
            rows = connection.execute(query, args).fetchall()
        return [self._factor_record(dict(row)) for row in rows]

    def list_factor_sets(self, owner_ref: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM factor_sets"
        args: tuple[Any, ...] = ()
        if owner_ref:
            query += " WHERE owner_ref = ?"
            args = (owner_ref,)
        query += " ORDER BY owner_ref, set_id, member_fingerprint"
        with self.connection() as connection:
            rows = connection.execute(query, args).fetchall()
            result = []
            for row in rows:
                stored = dict(row)
                members = connection.execute(
                    "SELECT frozen_identity_json FROM factor_set_members "
                    "WHERE set_ref = ? ORDER BY ordinal", (row["set_ref"],)
                ).fetchall()
                result.append({
                    "schema_version": 2,
                    "ref": stored["set_ref"],
                    "alias": stored["title_zh"],
                    "owner_ref": stored["owner_ref"],
                    "description": stored["description_zh"],
                    "identity": {
                        "set_id": stored["set_id"],
                        "member_fingerprint": stored["member_fingerprint"],
                        "members": [json.loads(item[0]) for item in members],
                    },
                    "state": stored["state"],
                })
        return result

    @staticmethod
    def _factor_record(value: dict[str, Any]) -> dict[str, Any]:
        try:
            params = json.loads(value.get("params_json") or "{}")
        except json.JSONDecodeError as error:
            raise ValueError("stored factor params are invalid") from error
        return {
            "schema_version": 2,
            "ref": value["factor_ref"],
            "alias": value["factor_alias"],
            "owner_ref": value["owner_ref"],
            "identity": {
                "family_ref": value["family_ref"],
                "family_alias": value["family_alias"],
                "family_formula_fingerprint": value[
                    "family_formula_fingerprint"
                ],
                "self_formula_fingerprint": value[
                    "self_formula_fingerprint"
                ],
                "params": params,
            },
            "state": value["state"],
        }

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
            "factors", "factor_workspace_provenance", "factor_sets",
            "factor_set_members",
            "product_group_subject_bindings",
        )
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
