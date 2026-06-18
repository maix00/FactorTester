"""Workspace visibility rules for factor editor code.

Only objects marked with `@factor_workspace` should be emitted into the user
workspace. `__factor_workspace__` is reserved for singleton values that cannot
carry a decorator directly, such as shared parameter instances or constant
objects that must still be visible to factor authors. Modules may also set
`FACTOR_WORKSPACE = True` and place header imports under `if FACTOR_WORKSPACE:`
to explicitly mark imports that must be preserved in the workspace view.

"""

from __future__ import annotations

from typing import TypeVar

from ..shared.ast import (
    collect_import_dependencies,
    extract_export_names,
    has_import_guard,
    has_decorator,
)

T = TypeVar("T")


def factor_workspace(obj: T) -> T:
    """Mark a class/function as workspace-exported without changing runtime behavior."""
    return obj


def extract_factor_workspace_exports(tree):
    """Return singleton names explicitly declared for workspace exposure."""
    return extract_export_names(tree, "__factor_workspace__")


def collect_factor_workspace_import_dependencies(tree, exported_names):
    return collect_import_dependencies(
        tree,
        exported_names,
        sentinel_name="__factor_workspace__",
        decorator_names={"factor_workspace"},
    )


def has_factor_workspace_decorator(node):
    return has_decorator(node, "factor_workspace")


def has_factor_workspace_import_guard(node):
    return has_import_guard(node, "FACTOR_WORKSPACE")


__all__ = [
    "collect_factor_workspace_import_dependencies",
    "extract_factor_workspace_exports",
    "factor_workspace",
    "has_factor_workspace_import_guard",
    "has_factor_workspace_decorator",
]
