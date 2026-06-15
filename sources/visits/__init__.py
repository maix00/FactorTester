"""Access-visit registry for source modules — 委托给 DataHub。"""

from __future__ import annotations

from tools.data.data_source.DataHub import DataHub, VisitSource

_hub = DataHub.get_instance()


def register_visit_source(key: str, label: str) -> VisitSource:
    return _hub.register_visit_source(key, label)


def iter_visit_sources() -> tuple[VisitSource, ...]:
    return tuple(_hub.iter_visit_sources())


def record_visit(source_key: str, *, source_label: str, access_date=None) -> str:
    return _hub.record_visit(source_key, source_label=source_label, access_date=access_date)


def get_visit(source_key: str) -> dict | None:
    return _hub.get_visit(source_key)


def get_latest_access_date(source_key: str) -> str | None:
    return _hub.get_latest_access_date(source_key)


def ensure_visits_store() -> str:
    _hub.ensure_visits_schema()
    return _hub._get_sqlite_store("openctp").path()


__all__ = [
    "ensure_visits_store",
    "get_latest_access_date",
    "get_visit",
    "record_visit",
    "register_visit_source",
    "iter_visit_sources",
]
