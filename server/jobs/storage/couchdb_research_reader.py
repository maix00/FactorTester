"""Read-through Research Report authority backed by CouchDB."""

from __future__ import annotations

import json
import time
from typing import Any

from server.jobs.storage.couchdb_research_reports import (
    get_research_report, projection,
)


class CouchDBResearchReader:
    def __init__(self, store, *, cache_seconds: float = 5.0) -> None:
        self.store = store
        self.cache_seconds = cache_seconds
        self._records: dict[str, tuple[float, dict]] = {}
        self._projections: dict[str, tuple[float, dict]] = {}

    def record(self, publication_id: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._records.get(publication_id)
        if cached and now - cached[0] < self.cache_seconds:
            return dict(cached[1])
        document = get_research_report(self.store, publication_id)
        value = dict(document.get("publication") or {})
        if not value:
            raise ValueError("CouchDB research report has no publication record")
        self._records[publication_id] = (now, value)
        return dict(value)

    def projection(self, publication_id: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._projections.get(publication_id)
        if cached and now - cached[0] < self.cache_seconds:
            return dict(cached[1])
        document = get_research_report(self.store, publication_id)
        value = projection(self.store, document)
        self._projections[publication_id] = (now, value)
        return dict(value)
