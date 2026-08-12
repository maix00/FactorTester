"""Load public factor families from the authoritative SQLite registry."""

from __future__ import annotations

from types import ModuleType
from typing import Any

from tools.data.sqlite.factor_source_store import load_factor_source


def load_public_factor_module(factor_id: str) -> ModuleType:
    source = load_factor_source("public", "", factor_id)
    if not source:
        raise AssertionError(
            f"public factor {factor_id!r} is missing from factor_family_sources"
        )
    namespace: dict[str, Any] = {
        "__name__": f"factor_family_sources_public_{factor_id}",
        "__file__": f"factor_family_sources:public/{factor_id}",
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    module = ModuleType(namespace["__name__"])
    module.__file__ = namespace["__file__"]
    module.__dict__.update(namespace)
    return module


def load_public_factor_class(factor_id: str) -> type:
    from tools.factors.FactorFamily import FactorFamily

    module = load_public_factor_module(factor_id)
    for value in module.__dict__.values():
        if (
            isinstance(value, type)
            and issubclass(value, FactorFamily)
            and value is not FactorFamily
        ):
            return value
    raise AssertionError(
        f"public factor {factor_id!r} has no FactorFamily class"
    )
