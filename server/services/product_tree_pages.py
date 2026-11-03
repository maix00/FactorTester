"""Bounded, disposable leaf metadata index for the local Manager catalog.

Only the resolved local scope enters this cache. It neither discovers remote
nodes nor gives a source alias a cross-node identity. SQLite holds derived JSON
and casefolded search text on disk; Python retains only the product references
needed for lazy metadata projection. No quotes, bars or user source are stored.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import atexit
import json
import sqlite3
from threading import RLock
from typing import Any, Callable, Iterable


@dataclass
class _Directory:
    number: int
    objects: tuple[Any, ...]
    ordered: tuple[tuple[Any, str], ...]
    alternates: dict[str, list[Any]]
    complete: bool = False


class ProductTreePages:
    """Single-flight projections, capped disk, scope LRU and bounded object refs.

    Inputs are resolved afresh by the caller, including category membership and
    authorized source IDs. Identity comparison detects replacement/deletion
    without running Product equality or hashing an entire serialized directory.
    Capacity errors fail the request; they never return a truncated catalog.
    """
    def __init__(self, *, max_objects: int = 200_000, max_scopes: int = 8,
                 disk_mib: int = 128):
        self.max_objects = max_objects
        self.max_scopes = max_scopes
        self.disk_mib = disk_mib
        self._lock = RLock()
        self._directories: OrderedDict[tuple, _Directory] = OrderedDict()
        self._db: sqlite3.Connection | None = None
        self._serial = 0

    def clear(self) -> None:
        with self._lock:
            self._directories.clear()
            if self._db is not None:
                self._db.close()
                self._db = None

    def _connection(self) -> sqlite3.Connection:
        if self._db is None:
            # SQLite owns this private temporary file and deletes it at close.
            # It may spill beyond the 2 MiB page cache; this is not :memory:.
            self._db = sqlite3.connect(
                "", check_same_thread=False,
            )
            self._db.execute("PRAGMA page_size=4096")
            self._db.execute(f"PRAGMA max_page_count={self.disk_mib * 256}")
            self._db.execute("PRAGMA cache_size=-2048")
            # This is disposable, process-local data protected by one lock.
            # Avoid an unbounded WAL/rollback journal; failure clears the index.
            self._db.execute("PRAGMA journal_mode=OFF")
            self._db.execute("PRAGMA temp_store=FILE")
            self._db.execute("CREATE TABLE leaves (scope INTEGER, ordinal INTEGER, "
                             "payload TEXT NOT NULL, search TEXT NOT NULL, sources INTEGER NOT NULL, "
                             "PRIMARY KEY(scope, ordinal)) WITHOUT ROWID")
            self._db.execute("CREATE TABLE source_sets (id INTEGER PRIMARY KEY, "
                             "bindings TEXT NOT NULL UNIQUE, search TEXT NOT NULL)")
        return self._db

    def page(self, *, scope: tuple, objects: Iterable[Any],
             object_path: Callable[[Any], str], project: Callable[[Any, str], dict],
             query: str, page: int, limit: int) -> dict:
        with self._lock:
            try:
                return self._page(scope, tuple(objects), object_path, project,
                                  query, page, limit)
            except Exception:
                # A failed cold projection must not become a partial snapshot.
                self.clear()
                raise

    def _page(self, scope, objects, object_path, project, query, page, limit):
        if len(objects) > self.max_objects:
            raise ValueError("产品目录超过派生索引容量，请缩小产品或数据源范围")
        db = self._connection()
        directory = self._directories.get(scope)
        if directory is not None and not (
            directory.objects is objects or
            len(directory.objects) == len(objects) and
            all(old is new for old, new in zip(directory.objects, objects))
        ):
            db.execute("DELETE FROM leaves WHERE scope=?", (directory.number,))
            del self._directories[scope]
            directory = None
        if directory is None:
            while self._directories and (
                len(self._directories) >= self.max_scopes or
                sum(len(item.objects) for item in self._directories.values())
                + len(objects) > self.max_objects
            ):
                _, removed = self._directories.popitem(last=False)
                db.execute("DELETE FROM leaves WHERE scope=?", (removed.number,))
            db.execute("DELETE FROM source_sets WHERE id NOT IN (SELECT sources FROM leaves)")
            # Stable product identity, never name/code/source alias. Several
            # source registrations for the same product produce one leaf.
            unique, alternates = {}, {}
            for product in objects:
                path = object_path(product)
                if path not in unique:
                    unique[path] = product
                elif unique[path] is not product:
                    values = alternates.setdefault(path, [unique[path]])
                    if all(item is not product for item in values):
                        values.append(product)
            ordered = tuple(sorted(
                ((product, path) for path, product in unique.items()),
                key=lambda item: (str(getattr(item[0], "name", item[0])), item[1]),
            ))
            self._serial += 1
            directory = _Directory(self._serial, objects, ordered, alternates)
            self._directories[scope] = directory
        self._directories.move_to_end(scope)
        offset = (page - 1) * limit
        binding_numbers = {}

        def materialize(start, stop):
            existing = {row[0] for row in db.execute(
                "SELECT ordinal FROM leaves WHERE scope=? AND ordinal>=? AND ordinal<?",
                (directory.number, start, stop),
            )}
            for ordinal in range(start, stop):
                if ordinal in existing:
                    continue
                product, path = directory.ordered[ordinal]
                value = project(product, path)
                for alternate in directory.alternates.get(path, ())[1:]:
                    other = project(alternate, path)
                    for field in ("product_path", "product_type", "contract_uid"):
                        if value.get(field) != other.get(field):
                            raise ValueError("同一产品引用具有冲突的身份元数据")
                    for field in ("source_ids", "source_family_ids"):
                        if field in value or field in other:
                            value[field] = sorted(set(value.get(field, ())) |
                                                  set(other.get(field, ())))
                    if "has_data" in value or "has_data" in other:
                        value["has_data"] = bool(value.get("has_data") or other.get("has_data"))
                bindings = {key: value.pop(key) for key in
                            ("source_ids", "source_family_ids") if key in value}
                encoded = json.dumps(bindings, ensure_ascii=False, separators=(",", ":"))
                source_number = binding_numbers.get(encoded)
                if source_number is None:
                    db.execute("INSERT OR IGNORE INTO source_sets(bindings,search) VALUES (?,?)",
                               (encoded, str(bindings.get("source_ids") or "").casefold()))
                    source_number = db.execute("SELECT id FROM source_sets WHERE bindings=?",
                                               (encoded,)).fetchone()[0]
                    if len(binding_numbers) < 256:
                        binding_numbers[encoded] = source_number
                search = " ".join(str(value.get(key) or "") for key in (
                    "title", "product_name", "product_code", "desc", "exchange",
                    "product_path",
                )).casefold()
                db.execute("INSERT INTO leaves VALUES (?,?,?,?,?)", (
                    directory.number, ordinal,
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")), search, source_number,
                ))

        total = len(directory.ordered)
        if query:
            if not directory.complete:
                for start in range(0, total, 256):
                    materialize(start, min(start + 256, total))
                directory.complete = True
            where, parameters = "scope=? AND instr(l.search || ' ' || s.search,?)>0", (directory.number, query)
            total = db.execute(f"SELECT count(*) FROM leaves l JOIN source_sets s ON s.id=l.sources WHERE {where}", parameters).fetchone()[0]
        else:
            materialize(min(offset, total), min(offset + limit, total))
            where, parameters = "scope=?", (directory.number,)
        db.commit()
        if query:
            rows = db.execute(
                f"SELECT l.payload,s.bindings FROM leaves l JOIN source_sets s ON s.id=l.sources WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
        else:
            # Earlier pages need not have been materialized.
            rows = db.execute(
                "SELECT l.payload,s.bindings FROM leaves l JOIN source_sets s ON s.id=l.sources WHERE scope=? AND ordinal>=? AND ordinal<? ORDER BY ordinal",
                (directory.number, offset, offset + limit),
            )
        total_pages = max(1, (total + limit - 1) // limit)
        return {"nodes": [json.loads(row[0]) | json.loads(row[1]) for row in rows], "page": page,
                "limit": limit, "total": total, "total_pages": total_pages,
                "has_more": page < total_pages}


product_tree_pages = ProductTreePages()
atexit.register(product_tree_pages.clear)
