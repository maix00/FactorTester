"""tech_docs decorator family.

Import `tech_docs` from `tools.decorators`; import helper utilities from
this submodule so docs-related code keeps the tech_docs semantic path.
"""

from __future__ import annotations

from typing import TypeVar

from ..shared.ast import (
    collect_import_dependencies,
    extract_export_names,
    has_any_decorator,
)

T = TypeVar("T")

_PUBLIC_DECORATORS = {"tech_docs", "factor_workspace"}


def tech_docs(obj: T) -> T:
    """Mark a class/function as visible in public technical docs."""
    return obj


def extract_tech_docs_exports(tree):
    return extract_export_names(tree, "__tech_docs__")


def collect_tech_docs_import_dependencies(tree, exported_names):
    return collect_import_dependencies(
        tree,
        exported_names,
        sentinel_name="__tech_docs__",
        decorator_names=_PUBLIC_DECORATORS,
    )


def has_tech_docs_decorator(node):
    return has_any_decorator(node, _PUBLIC_DECORATORS)


__all__ = [
    "collect_tech_docs_import_dependencies",
    "extract_tech_docs_exports",
    "has_tech_docs_decorator",
    "tech_docs",
]
