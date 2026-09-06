"""Resolve hash-bound factor source objects from Manager SQLite."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

from tools.data.sqlite.factor_source_store import normalize_factor_source_code
from tools.data.sqlite.db import connect_sqlite
from tools.cli.factor_subject_refs import split_owner_qualified_factor_family


class FactorSourceStore:
    """Read and commit one hash-bound factor source in Manager SQLite."""

    def __init__(self, *, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    @staticmethod
    def identity(object_id: str) -> tuple[str, str, str, str]:
        owner, factor_id = split_owner_qualified_factor_family(
            str(object_id or ""),
        )
        if owner is None or not factor_id:
            raise ValueError("factor source object must include its owner")
        source_kind = "public" if owner == "public" else "custom"
        owner_username = "" if source_kind == "public" else owner
        return owner, factor_id, source_kind, owner_username

    def source(self, object_id: str, *, expected_sha256: str = "") -> str:
        _owner, factor_id, source_kind, owner_username = self.identity(object_id)
        with connect_sqlite(self.database) as connection:
            _ensure_schema(connection)
            row = connection.execute(
                """
                SELECT source_code FROM factor_family_sources
                WHERE source_kind=? AND owner_username=? AND factor_id=?
                """,
                (source_kind, owner_username, factor_id),
            ).fetchone()
        if row is None and not expected_sha256:
            raise FileNotFoundError("factor source object is unavailable")
        source = normalize_factor_source_code(str(row["source_code"] or "")) if row else ""
        if expected_sha256 and hashlib.sha256(source.encode()).hexdigest() != expected_sha256:
            from tools.data.sqlite.factor_source_versions import _ensure_schema as ensure_versions
            with connect_sqlite(self.database) as connection:
                ensure_versions(connection)
                version = connection.execute(
                    "SELECT source_code FROM factor_family_formula_versions "
                    "WHERE source_kind=? AND owner_username=? AND factor_id=? AND source_sha256=?",
                    (source_kind, owner_username, factor_id, expected_sha256),
                ).fetchone()
            if version is None:
                raise FileNotFoundError("factor source version is unavailable")
            source = str(version["source_code"])
        if not source.strip():
            raise FileNotFoundError("factor source object is empty")
        return source

    def metadata(self, object_id: str, *, expected_sha256: str = "") -> dict[str, object]:
        owner, factor_id, source_kind, owner_username = self.identity(object_id)
        source = self.source(object_id, expected_sha256=expected_sha256)
        raw = source.encode("utf-8")
        return {
            "object_id": f"{owner}:{factor_id}",
            "source_kind": source_kind,
            "source_owner": owner,
            "factor_id": factor_id,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_bytes": len(raw),
            "owner_username": owner_username,
        }

    def store_from_file(
        self,
        object_id: str,
        source_path: str | Path,
        *,
        principal: str,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        owner, factor_id, source_kind, owner_username = self.identity(object_id)
        if source_kind == "custom" and owner != str(principal or "").strip():
            raise PermissionError("factor source owner does not match transfer")
        source_path = Path(source_path).expanduser().resolve()
        if source_path.is_symlink() or not source_path.is_file():
            raise FileNotFoundError("factor source upload staging is unavailable")
        raw = source_path.read_bytes()
        expected_size = int(expected_size)
        expected_sha256 = str(expected_sha256 or "").strip().lower()
        if len(raw) != expected_size:
            raise ValueError("factor source upload size is invalid")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("factor source upload hash is invalid")
        try:
            source = normalize_factor_source_code(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("factor source upload is not UTF-8") from exc
        normalized = source.encode("utf-8")
        if len(normalized) != expected_size or hashlib.sha256(normalized).hexdigest() != expected_sha256:
            raise ValueError("factor source normalization changed its identity")
        with connect_sqlite(self.database) as connection:
            _ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO factor_family_sources(
                    source_kind, owner_username, factor_id, factor_name,
                    source_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_kind, owner_username, factor_id)
                DO UPDATE SET source_code=excluded.source_code,
                              factor_name=excluded.factor_name,
                              updated_at=excluded.updated_at
                """,
                (
                    source_kind,
                    owner_username,
                    factor_id,
                    factor_id,
                    source,
                    time.time(),
                ),
            )
        source_path.unlink(missing_ok=True)


class FactorSourceOriginAdapter:
    def __init__(self, *, database: str | Path, cache_root: str | Path) -> None:
        self.store = FactorSourceStore(database=database)
        self.cache_root = Path(cache_root).expanduser().resolve()

    def __call__(self, transfer) -> Path:
        _owner, factor_id, _source_kind, _owner_username = self.store.identity(
            str(transfer.object_id or ""),
        )
        source = self.store.source(str(transfer.object_id or ""), expected_sha256=str(transfer.expected_sha256 or "").lower())
        raw = source.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(transfer.expected_sha256 or "").lower():
            raise RuntimeError("factor source hash changed after authorization")
        if len(raw) != int(transfer.expected_size):
            raise RuntimeError("factor source size changed after authorization")
        path = self.cache_root / "factor-sources" / f"{digest}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size != len(raw):
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_bytes(raw)
            os.replace(temporary, path)
            path.chmod(0o600)
        return path


class FactorSourceDestinationAdapter:
    """Commit a verified 7997 factor-source upload into local SQLite."""

    def __init__(self, *, database: str | Path) -> None:
        self.store = FactorSourceStore(database=database)

    def __call__(self, context, staged_path: Path) -> Path:
        transfer = context.transfer
        if str(transfer.object_kind) != "factor_source":
            return staged_path
        self.store.store_from_file(
            str(transfer.object_id or ""),
            staged_path,
            principal=str(transfer.principal or ""),
            expected_size=int(transfer.expected_size),
            expected_sha256=str(transfer.expected_sha256 or ""),
        )
        return staged_path


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_family_sources (
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


__all__ = [
    "FactorSourceDestinationAdapter",
    "FactorSourceOriginAdapter",
    "FactorSourceStore",
]
