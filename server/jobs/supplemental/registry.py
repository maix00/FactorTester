"""Adapter registry for test-domain supplemental computations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Prepare = Callable[[Any, Any, dict[str, Any]], dict[str, Any]]
Execute = Callable[[dict[str, Any], Any, Any], None]


@dataclass(frozen=True)
class SupplementalAdapter:
    kind: str
    parent_kinds: frozenset[str]
    prepare: Prepare
    execute: Execute


_ADAPTERS: dict[str, SupplementalAdapter] = {}


def register(value: SupplementalAdapter) -> SupplementalAdapter:
    key = str(value.kind).strip()
    if not key:
        raise ValueError("supplemental adapter kind is required")
    if key in _ADAPTERS:
        raise ValueError(f"supplemental adapter already registered: {key}")
    _ADAPTERS[key] = value
    return value


def adapter(kind: str) -> SupplementalAdapter:
    _load_builtin_adapters()
    try:
        return _ADAPTERS[str(kind)]
    except KeyError as exc:
        raise ValueError(f"unsupported supplemental kind: {kind}") from exc


def _load_builtin_adapters() -> None:
    if _ADAPTERS:
        return
    from server.modules.single_factor_test.supplemental import (  # noqa: F401
        backtest_strategy_analysis,
        custom_python_analysis,
        report_output_generation,
    )
