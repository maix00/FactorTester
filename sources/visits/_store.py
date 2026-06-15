"""Visit SQLite 存储 — 兼容层，委托给 DataHub。"""

from __future__ import annotations

from tools.data.data_source.DataHub import DataHub


def _hub() -> DataHub:
    return DataHub.get_instance()


def ensure_visits_store() -> str:
    _hub().ensure_visits_schema()
    return _hub()._get_sqlite_store("openctp").path()


def record_visit(source_key: str, *, source_label: str, access_date=None) -> str:
    return _hub().record_visit(source_key, source_label=source_label, access_date=access_date)


def get_visit(source_key: str) -> dict | None:
    return _hub().get_visit(source_key)


def get_latest_access_date(source_key: str) -> str | None:
    return _hub().get_latest_access_date(source_key)
