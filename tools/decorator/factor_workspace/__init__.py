from __future__ import annotations

from typing import TypeVar

from ..shared.ast import (
    collect_import_dependencies,
    extract_export_names,
    has_decorator,
)

T = TypeVar("T")


def factor_workspace(obj: T) -> T:
    """Mark a class/function as workspace-exported without changing runtime behavior."""
    return obj


def extract_factor_workspace_exports(tree):
    return extract_export_names(tree, "__factor_workspace__")


def collect_factor_workspace_import_dependencies(tree, exported_names):
    return collect_import_dependencies(
        tree,
        exported_names,
        sentinel_name="__factor_workspace__",
        decorator_name="factor_workspace",
    )


def has_factor_workspace_decorator(node):
    return has_decorator(node, "factor_workspace")


__all__ = [
    "collect_factor_workspace_import_dependencies",
    "extract_factor_workspace_exports",
    "factor_workspace",
    "has_factor_workspace_decorator",
]
