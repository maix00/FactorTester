"""Registry of source modules that participate in visit tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisitSource:
    key: str
    label: str


_VISIT_SOURCES: dict[str, VisitSource] = {}


def register_visit_source(key: str, label: str) -> VisitSource:
    source = VisitSource(key=key, label=label)
    _VISIT_SOURCES[key] = source
    return source


def iter_visit_sources() -> tuple[VisitSource, ...]:
    return tuple(_VISIT_SOURCES[key] for key in sorted(_VISIT_SOURCES))

