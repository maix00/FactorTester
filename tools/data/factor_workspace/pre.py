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
    has_workspace_marker: bool
    factor_workspace_import_names: tuple[str, ...]
    workspace_decorated_names: tuple[str, ...]
    workspace_exports: tuple[str, ...] | None
    defined_names: tuple[str, ...]
    dependency_names: tuple[str, ...]


def _source_tools_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "tools")


def _source_root_candidates(source_root: str | None = None) -> list[tuple[str, str]]:
    if source_root is not None:
        root = Path(source_root).resolve()
        return [
            (str(root / "Settings.py"), "Settings.py"),
            (str(root / "tools"), "tools"),
        ]
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


def _collect_defined_names(tree: ast.Module, *, is_package_init: bool) -> tuple[str, ...]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id != "__all__":
                    names.add(target.id)
                elif isinstance(target, ast.Tuple):
                    for item in target.elts:
                        if isinstance(item, ast.Name) and not item.id.startswith("_"):
                            names.add(item.id)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id != "__all__":
                names.add(target.id)
        elif is_package_init and isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        elif is_package_init and isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    return tuple(sorted(names))


def _has_workspace_marker(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__factor_workspace__" for target in node.targets):
                return True
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "FACTOR_WORKSPACE":
            for child in node.body:
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    return True
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and has_factor_workspace_decorator(node):
            return True
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and has_factor_workspace_decorator(child):
                    return True
    return False


def _is_workspace_blocked_path(relative_path: str) -> bool:
    blocked_prefixes = (
        "tools/factors/tests/",
        "tools/backtest/",
        "tools/data/sqlite/",
        "tools/data/cache/",
        "tools/data/account_manage/",
        "tools/data/factor_workspace/",
        "tools/data/tech_docs/",
    )
    blocked_files = {
        "tools/factors/FactorTester.py",
        "tools/factors/backtest_progress.py",
        "tools/factors/eval_progress.py",
    }
    return relative_path in blocked_files or any(relative_path.startswith(prefix) for prefix in blocked_prefixes)


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
        has_workspace_marker=_has_workspace_marker(tree),
        factor_workspace_import_names=tuple(sorted(workspace_import_names)),
        workspace_decorated_names=tuple(sorted(decorated_names)),
        workspace_exports=tuple(sorted(exports)) if exports is not None else None,
        defined_names=_collect_defined_names(tree, is_package_init=relative_path.endswith("__init__.py")),
        dependency_names=tuple(sorted(dependencies)),
    )


def collect_workspace_architecture(source_root: str | None = None) -> list[WorkspaceSourceSpec]:
    """Collect the decorator-driven export graph for workspace generation."""
    specs: list[WorkspaceSourceSpec] = []
    for source_path, relative_root in _source_root_candidates(source_root):
        path = Path(source_path)
        if not path.exists():
            continue
        if path.is_file():
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
                spec = _collect_source_spec(source_file, relative_path)
                if spec is not None:
                    specs.append(spec)
    specs_by_path = {spec.relative_path: spec for spec in specs}
    specs_by_name: dict[str, list[WorkspaceSourceSpec]] = {}
    for spec in specs:
        for name in spec.defined_names:
            specs_by_name.setdefault(name, []).append(spec)

    selected_paths: set[str] = {spec.relative_path for spec in specs if spec.has_workspace_marker}

    def _ancestor_inits(relative_path: str) -> list[str]:
        ancestors: list[str] = []
        if relative_path == "Settings.py":
            return ancestors
        current = Path(relative_path)
        while current.parent != current and current.parent != Path("."):
            init_path = str(current.parent / "__init__.py")
            if init_path in specs_by_path:
                ancestors.append(init_path)
            current = current.parent
        return ancestors

    changed = True
    while changed:
        changed = False
        for rel_path in list(selected_paths):
            spec = specs_by_path.get(rel_path)
            if spec is None:
                continue
            for ancestor_path in _ancestor_inits(rel_path):
                if ancestor_path not in selected_paths:
                    selected_paths.add(ancestor_path)
                    changed = True
            for name in spec.dependency_names:
                for candidate in specs_by_name.get(name, []):
                    if candidate.relative_path not in selected_paths:
                        selected_paths.add(candidate.relative_path)
                        changed = True

    specs = [
        specs_by_path[relative_path]
        for relative_path in sorted(selected_paths)
        if not _is_workspace_blocked_path(relative_path)
    ]
    specs.sort(key=lambda item: item.relative_path)
    return specs
