"""Access-visit registry for source modules."""

from __future__ import annotations

from ._store import (
    ensure_visits_store,
    get_latest_access_date,
    get_visit,
    record_visit,
)
from .registry import register_visit_source, iter_visit_sources

__all__ = [
    "ensure_visits_store",
    "get_latest_access_date",
    "get_visit",
    "record_visit",
    "register_visit_source",
    "iter_visit_sources",
]
