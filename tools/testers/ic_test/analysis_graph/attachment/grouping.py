"""Normalize one authoring selection into registered map/combine target groups."""

from __future__ import annotations

from collections.abc import Iterable

from tools.testers.analysis_graph import AnalysisMapping


def normalize_target_refs(values: Iterable[str]) -> tuple[tuple[str, ...], int]:
    supplied = tuple(str(value or "").strip() for value in values)
    normalized = tuple(sorted(set(supplied)))
    return normalized, len(supplied) - len(normalized)


def target_groups(
    mapping: AnalysisMapping,
    target_refs: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    if not target_refs:
        return ((),)
    if mapping is AnalysisMapping.MAP_EACH:
        return tuple((target,) for target in target_refs)
    return (target_refs,)


__all__ = ["normalize_target_refs", "target_groups"]
