"""Workspace architecture collection for factor sources."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

from tools.decorators.factor_workspace import (
    collect_factor_workspace_import_dependencies,
    extract_factor_workspace_exports,
    has_factor_workspace_decorator,
)


@dataclass(frozen=True)
class WorkspaceSourceSpec:
    source_path: str
    relative_path: str
    module_name: str
    is_package_init: bool
    factor_workspace_import_names: tuple[str, ...]
    workspace_decorated_names: tuple[str, ...]
    workspace_exports: tuple[str, ...] | None
    dependency_names: tuple[str, ...]


def _source_tools_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "tools")


def _source_root_candidates() -> list[tuple[str, str]]:
    repo_root = Path(__file__).resolve().parents[3]
    return [
        (str(repo_root / "Settings.py"), "Settings.py"),
        (str(repo_root / "tools"), "tools"),
    ]


def _module_name_from_relative_path(relative_path: str) -> str:
    path = relative_path[:-3] if relative_path.endswith(".py") else relative_path
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    path = path.replace(os.sep, ".").replace("/", ".")
    return path


def _is_workspace_relevant_path(relative_path: str) -> bool:
    if relative_path == "Settings.py":
        return True
    if relative_path in {"tools/__init__.py", "tools/data/__init__.py"}:
        return True
    if relative_path.startswith("tools/factors/tests/"):
        return False
    if relative_path.startswith("tools/backtest/"):
        return False
    if relative_path.startswith("tools/data/sqlite/"):
        return False
    if relative_path.startswith("tools/data/cache/"):
        return False
    if relative_path.startswith("tools/data/account_manage/"):
        return False
    if relative_path.startswith("tools/data/factor_workspace/"):
        return False
    if relative_path.startswith("tools/data/tech_docs/"):
        return False
    allowed_prefixes = (
        "tools/decorators/",
        "tools/factors/",
        "tools/parameters/",
        "tools/products/",
        "tools/data/types/",
        "tools/data/views/",
        "tools/data/providers/",
    )
    return any(relative_path.startswith(prefix) for prefix in allowed_prefixes)


def _collect_source_spec(source_path: str, relative_path: str) -> WorkspaceSourceSpec | None:
    try:
        source_code = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source_code)
    except Exception:
        return None
    workspace_import_names: set[str] = set()
    decorated_names = []
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "FACTOR_WORKSPACE":
            for child in node.body:
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        workspace_import_names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
                elif isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        workspace_import_names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and has_factor_workspace_decorator(node):
            decorated_names.append(node.name)
    exports = extract_factor_workspace_exports(tree)
    dependencies = collect_factor_workspace_import_dependencies(tree, exports)
    return WorkspaceSourceSpec(
        source_path=source_path,
        relative_path=relative_path,
        module_name=_module_name_from_relative_path(relative_path),
        is_package_init=relative_path.endswith("__init__.py"),
        factor_workspace_import_names=tuple(sorted(workspace_import_names)),
        workspace_decorated_names=tuple(sorted(decorated_names)),
        workspace_exports=tuple(sorted(exports)) if exports is not None else None,
        dependency_names=tuple(sorted(dependencies)),
    )


def collect_workspace_architecture(source_root: str | None = None) -> list[WorkspaceSourceSpec]:
    """Collect the source files and decorator-driven export graph for workspace generation."""
    specs: list[WorkspaceSourceSpec] = []
    for source_path, relative_root in _source_root_candidates():
        path = Path(source_path)
        if not path.exists():
            continue
        if path.is_file():
            if not _is_workspace_relevant_path(relative_root):
                continue
            spec = _collect_source_spec(str(path), relative_root)
            if spec is not None:
                specs.append(spec)
            continue
        for current_root, dirs, filenames in os.walk(path):
            dirs[:] = [d for d in sorted(dirs) if not d.startswith("__pycache__") and not d.startswith(".")]
            rel_dir = os.path.relpath(current_root, path)
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                source_file = os.path.join(current_root, filename)
                relative_path = os.path.join(relative_root, filename) if rel_dir == "." else os.path.join(relative_root, rel_dir, filename)
                if not _is_workspace_relevant_path(relative_path):
                    continue
                spec = _collect_source_spec(source_file, relative_path)
                if spec is not None:
                    specs.append(spec)
    specs.sort(key=lambda item: item.relative_path)
    return specs
