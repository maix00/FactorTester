"""Schema and connection helpers for the client-local catalog database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.data.sqlite.db import connect_sqlite


SCHEMA_VERSION = 1


def connect_catalog(path: str | Path) -> sqlite3.Connection:
    """Open a local catalog database with short, WAL-backed transactions."""
    database = Path(path).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(database, foreign_keys=True, timeout=5.0)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def ensure_catalog_schema(connection: sqlite3.Connection) -> None:
    """Create the versioned catalog schema without touching existing rows."""
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"local catalog schema {current} is newer than supported "
            f"schema {SCHEMA_VERSION}"
        )
    if current == 0:
        _create_schema(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_sources (
            source_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            owner_ref TEXT NOT NULL DEFAULT '',
            class_path TEXT NOT NULL DEFAULT '',
            source_revision TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'unavailable')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            product_ref TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES catalog_sources(source_id),
            class_path TEXT NOT NULL,
            alias TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            product_kind TEXT NOT NULL DEFAULT 'product',
            catalog_revision TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'unavailable')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (source_id, class_path, alias)
        );
        CREATE INDEX IF NOT EXISTS idx_products_lookup
            ON products(source_id, class_path, alias);

        CREATE TABLE IF NOT EXISTS product_groups (
            group_ref TEXT PRIMARY KEY,
            owner_ref TEXT NOT NULL,
            name TEXT NOT NULL,
            definition_json TEXT NOT NULL DEFAULT '{}',
            definition_hash TEXT NOT NULL,
            catalog_revision TEXT NOT NULL DEFAULT '',
            membership_hash TEXT NOT NULL DEFAULT '',
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'superseded')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (owner_ref, name)
        );
        CREATE INDEX IF NOT EXISTS idx_product_groups_owner
            ON product_groups(owner_ref, state, updated_at DESC);

        CREATE TABLE IF NOT EXISTS product_group_products (
            group_ref TEXT NOT NULL REFERENCES product_groups(group_ref)
                ON DELETE CASCADE,
            product_ref TEXT NOT NULL REFERENCES products(product_ref),
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'superseded')),
            source_revision TEXT NOT NULL DEFAULT '',
            relation_revision INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (group_ref, product_ref, valid_from)
        );
        CREATE INDEX IF NOT EXISTS idx_group_products_effective
            ON product_group_products(group_ref, state, valid_from, valid_to);

        CREATE TABLE IF NOT EXISTS factors (
            factor_ref TEXT PRIMARY KEY,
            owner_ref TEXT NOT NULL DEFAULT '',
            family_name TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            logical_kind TEXT NOT NULL DEFAULT 'factor',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'superseded')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS factor_revisions (
            factor_revision_ref TEXT PRIMARY KEY,
            factor_ref TEXT NOT NULL REFERENCES factors(factor_ref)
                ON DELETE CASCADE,
            repository_ref TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            git_blob TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            dirty INTEGER NOT NULL DEFAULT 0 CHECK (dirty IN (0, 1)),
            created_at REAL NOT NULL,
            UNIQUE (factor_ref, git_commit, git_blob)
        );
        CREATE INDEX IF NOT EXISTS idx_factor_revisions_factor
            ON factor_revisions(factor_ref, created_at DESC);

        CREATE TABLE IF NOT EXISTS factor_sets (
            set_ref TEXT PRIMARY KEY,
            owner_ref TEXT NOT NULL,
            set_id TEXT NOT NULL,
            title_zh TEXT NOT NULL,
            description_zh TEXT NOT NULL DEFAULT '',
            manifest_path TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            git_blob TEXT NOT NULL,
            member_hash TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'superseded')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (owner_ref, set_id, git_commit, git_blob)
        );

        CREATE TABLE IF NOT EXISTS factor_set_members (
            set_ref TEXT NOT NULL REFERENCES factor_sets(set_ref)
                ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            factor_ref TEXT NOT NULL,
            PRIMARY KEY (set_ref, ordinal),
            UNIQUE (set_ref, factor_ref)
        );

        CREATE TABLE IF NOT EXISTS product_group_subject_bindings (
            group_ref TEXT NOT NULL REFERENCES product_groups(group_ref)
                ON DELETE CASCADE,
            subject_kind TEXT NOT NULL
                CHECK (subject_kind IN ('factor', 'factor_set')),
            subject_ref TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'disabled', 'superseded')),
            source_revision TEXT NOT NULL DEFAULT '',
            sync_state TEXT NOT NULL DEFAULT 'local'
                CHECK (sync_state IN ('local', 'pending', 'synced', 'conflict')),
            relation_revision INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (group_ref, subject_kind, subject_ref, valid_from)
        );
        CREATE INDEX IF NOT EXISTS idx_group_subjects_effective
            ON product_group_subject_bindings(group_ref, subject_kind, state);
        """
    )
