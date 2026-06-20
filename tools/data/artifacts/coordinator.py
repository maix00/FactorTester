"""Cross-platform inspection, locking, building, and status persistence."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from scripts.data_dir import CACHE_DB_PATH
from tools.data.sqlite.db import connect_sqlite

from .model import ArtifactCoverage, DerivedArtifactSpec
from .registry import ArtifactRegistry, artifact_registry


ARTIFACT_STATE_TABLE = "derived_artifact_state"
ARTIFACT_COVERAGE_TABLE = "derived_artifact_coverage"


def _atomic_replace(source: Path, destination: Path, *, timeout: float = 3.0) -> None:
    """Publish a file, tolerating short-lived Windows reader handles."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _fingerprint(paths: tuple[Path, ...], *, schema_version: str) -> str:
    values = [("schema_version", schema_version)]
    for path in paths:
        try:
            stat = path.stat()
            values.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            values.append((str(path), None, None))
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))


def ensure_artifact_schema(db_path: str | Path) -> None:
    with connect_sqlite(db_path) as conn:
        conn.execute(
            f'''CREATE TABLE IF NOT EXISTS "{ARTIFACT_STATE_TABLE}" (
                artifact_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                variant TEXT NOT NULL,
                output_path TEXT NOT NULL,
                status TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                output_mtime_ns INTEGER,
                output_size_bytes INTEGER,
                updated_at REAL NOT NULL,
                error TEXT
            )'''
        )
        conn.execute(
            f'''CREATE TABLE IF NOT EXISTS "{ARTIFACT_COVERAGE_TABLE}" (
                artifact_key TEXT NOT NULL,
                product_name TEXT NOT NULL,
                variant TEXT NOT NULL,
                start_value TEXT,
                end_value TEXT,
                row_count INTEGER,
                entity_count INTEGER,
                PRIMARY KEY (artifact_key, product_name, variant)
            )'''
        )


@contextmanager
def _artifact_lock(path: Path, *, stale_after: float = 24 * 60 * 60) -> Iterator[bool]:
    """Acquire a lock using only O_EXCL, which is portable to Windows."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    try:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime <= stale_after:
                    yield False
                    return
                lock_path.unlink()
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileNotFoundError, FileExistsError):
                yield False
                return
        acquired = True
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(f"pid={os.getpid()}\n")
        yield True
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


class ArtifactCoordinator:
    def __init__(
        self,
        *,
        registry: ArtifactRegistry = artifact_registry,
        db_path: str | Path = CACHE_DB_PATH,
    ) -> None:
        self.registry = registry
        self.db_path = Path(db_path)
        ensure_artifact_schema(self.db_path)

    def inspect(self, spec: DerivedArtifactSpec) -> dict[str, object]:
        source_fingerprint = _fingerprint(spec.source_paths, schema_version=spec.schema_version)
        output_exists = spec.output_path.is_file()
        status = "missing"
        indexed = False
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                f'SELECT source_fingerprint, status FROM "{ARTIFACT_STATE_TABLE}" WHERE artifact_key=?',
                (spec.key,),
            ).fetchone()
            indexed = conn.execute(
                f'SELECT 1 FROM "{ARTIFACT_COVERAGE_TABLE}" WHERE artifact_key=? LIMIT 1',
                (spec.key,),
            ).fetchone() is not None
        if output_exists:
            output_mtime = spec.output_path.stat().st_mtime_ns
            source_is_newer = any(
                path.is_file() and path.stat().st_mtime_ns > output_mtime
                for path in spec.source_paths
            )
            fingerprint_changed = row is not None and row[0] != source_fingerprint
            unmanaged_is_stale = row is None and not spec.accept_unmanaged_existing
            status = "stale" if source_is_newer or fingerprint_changed or unmanaged_is_stale else "ready"
        return {
            "artifact_key": spec.key,
            "status": status,
            "output_path": str(spec.output_path),
            "source_fingerprint": source_fingerprint,
            "coverage_indexed": indexed,
        }

    def inspect_all(self) -> list[dict[str, object]]:
        return [self.inspect(spec) for spec in self.registry.all()]

    def ensure(self, key: str, *, force: bool = False) -> dict[str, object]:
        return self._ensure(self.registry.get(key), force=force, visiting=set())

    def ensure_all(self, *, force: bool = False, auto_only: bool = False) -> list[dict[str, object]]:
        results = []
        for spec in self.registry.all():
            if auto_only and not spec.auto_build:
                continue
            results.append(self.ensure(spec.key, force=force))
        return results

    def _ensure(
        self,
        spec: DerivedArtifactSpec,
        *,
        force: bool,
        visiting: set[str],
    ) -> dict[str, object]:
        if spec.key in visiting:
            raise ValueError(f"Derived artifact dependency cycle: {spec.key}")
        visiting.add(spec.key)
        try:
            for dependency in spec.dependencies:
                self._ensure(self.registry.get(dependency), force=False, visiting=visiting)
            current = self.inspect(spec)
            if not force and current["status"] == "ready" and current["coverage_indexed"]:
                self._write_state(spec, "ready")
                return current
            if not force and current["status"] == "ready":
                coverage = tuple(spec.coverage(spec.output_path))
                self._write_coverage(spec, coverage)
                self._write_state(spec, "ready")
                return self.inspect(spec)
            return self._build(spec)
        finally:
            visiting.remove(spec.key)

    def _build(self, spec: DerivedArtifactSpec) -> dict[str, object]:
        spec.output_path.parent.mkdir(parents=True, exist_ok=True)
        with _artifact_lock(spec.output_path) as acquired:
            if not acquired:
                return {**self.inspect(spec), "status": "building_elsewhere"}
            staging = spec.output_path.with_name(
                f".{spec.output_path.stem}.{uuid.uuid4().hex}.tmp{spec.output_path.suffix}"
            )
            self._write_state(spec, "building")
            try:
                spec.build(staging)
                if not staging.is_file():
                    raise RuntimeError(f"Builder did not create staging artifact: {staging}")
                _atomic_replace(staging, spec.output_path)
                if spec.on_published is not None:
                    spec.on_published(spec.output_path)
                coverage = tuple(spec.coverage(spec.output_path))
                self._write_coverage(spec, coverage)
                self._write_state(spec, "ready")
            except Exception as exc:
                self._write_state(spec, "failed", error=f"{type(exc).__name__}: {exc}")
                try:
                    staging.unlink()
                except FileNotFoundError:
                    pass
                raise
            return self.inspect(spec)

    def _write_state(self, spec: DerivedArtifactSpec, status: str, error: str | None = None) -> None:
        output_stat = spec.output_path.stat() if spec.output_path.is_file() else None
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                f'''INSERT INTO "{ARTIFACT_STATE_TABLE}" (
                    artifact_key, provider, artifact_name, variant, output_path, status,
                    source_fingerprint, output_mtime_ns, output_size_bytes, updated_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_key) DO UPDATE SET
                    output_path=excluded.output_path, status=excluded.status,
                    source_fingerprint=excluded.source_fingerprint,
                    output_mtime_ns=excluded.output_mtime_ns,
                    output_size_bytes=excluded.output_size_bytes,
                    updated_at=excluded.updated_at, error=excluded.error''',
                (
                    spec.key,
                    spec.provider,
                    spec.name,
                    spec.variant,
                    str(spec.output_path),
                    status,
                    _fingerprint(spec.source_paths, schema_version=spec.schema_version),
                    output_stat.st_mtime_ns if output_stat else None,
                    output_stat.st_size if output_stat else None,
                    time.time(),
                    error,
                ),
            )

    def _write_coverage(self, spec: DerivedArtifactSpec, rows: tuple[ArtifactCoverage, ...]) -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                f'DELETE FROM "{ARTIFACT_COVERAGE_TABLE}" WHERE artifact_key=?',
                (spec.key,),
            )
            conn.executemany(
                f'''INSERT INTO "{ARTIFACT_COVERAGE_TABLE}" (
                    artifact_key, product_name, variant, start_value, end_value, row_count, entity_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                [
                    (spec.key, row.product_name, row.variant, row.start_value, row.end_value, row.row_count, row.entity_count)
                    for row in rows
                ],
            )


def start_background_ensure(
    *,
    coordinator: ArtifactCoordinator | None = None,
    force: bool = False,
) -> threading.Thread:
    coordinator = coordinator or ArtifactCoordinator()

    def _run() -> None:
        try:
            coordinator.ensure_all(force=force, auto_only=True)
        except Exception as exc:
            print(f"[derived-artifacts] background ensure failed: {type(exc).__name__}: {exc}")

    thread = threading.Thread(target=_run, daemon=True, name="derived-artifact-ensure")
    thread.start()
    return thread
