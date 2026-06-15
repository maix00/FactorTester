"""Visit 访问追踪注册 — 兼容层，委托给 DataHub。"""

from __future__ import annotations

from tools.data.data_source.DataHub import DataHub, VisitSource  # noqa: F401


def _hub() -> DataHub:
    return DataHub.get_instance()


def register_visit_source(key: str, label: str) -> VisitSource:
    return _hub().register_visit_source(key, label)


def iter_visit_sources() -> tuple[VisitSource, ...]:
    return tuple(_hub().iter_visit_sources())

