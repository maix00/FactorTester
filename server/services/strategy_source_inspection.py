"""Shared AST-only inspection for Strategy source submissions."""

from __future__ import annotations

import ast
import hashlib
import re
from typing import Any

from tools.testers.backtest.engines.native.strategy import STRATEGY_CALLBACKS


MAX_SOURCE_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STRATEGY_BASES = frozenset({
    "Strategy", "BarStrategy", "EventStrategy", "OrderAwareStrategy",
})


def normalize_entrypoint(value: object) -> str:
    entrypoint = str(value or "Strategy").strip()
    if not _IDENTIFIER.fullmatch(entrypoint):
        raise ValueError("strategy entrypoint must be a Python identifier")
    return entrypoint


def inspect_source(
    source_code: object,
    entrypoint: object | None = "Strategy",
) -> dict[str, Any]:
    """Parse source once and return bounded hook and callback metadata.

    ``entrypoint=None`` selects the only native Strategy subclass.  A named
    entrypoint preserves the library/configuration behaviour where the caller
    explicitly chooses a class.  No user code is imported or executed here.
    """
    source = _normalize_source(source_code)
    tree = _parse(source)
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    candidates = [
        name for name in classes if _inherits_strategy(name, classes, set())
    ]
    requested = None if entrypoint is None or str(entrypoint).strip() == "" else (
        normalize_entrypoint(entrypoint)
    )
    if requested is None:
        if len(candidates) == 1:
            name = candidates[0]
        elif not candidates:
            raise ValueError("strategy source does not define a Strategy subclass")
        else:
            raise ValueError("strategy source has multiple entrypoints; choose one")
    else:
        name = requested
        selected = classes.get(name)
        if selected is None:
            available = ", ".join(classes) or "none"
            raise ValueError(
                f"strategy entrypoint class not found: {name} (available: {available})"
            )
        if not _inherits_strategy(name, classes, set()):
            raise ValueError(f"strategy entrypoint is not a native Strategy: {name}")

    selected = classes[name]
    return {
        "entrypoint": name,
        "callbacks": sorted(_strategy_methods(name, classes, set())),
        "hooks": _hooks(selected, source),
        "effective_hooks": _effective_hooks(name, classes, source, set()),
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "source_bytes": len(source.encode("utf-8")),
    }


def _normalize_source(value: object) -> str:
    source = str(value or "")
    if not source.strip():
        raise ValueError("strategy source code is required")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("strategy source code exceeds 1 MiB")
    return source


def _parse(source: str) -> ast.Module:
    try:
        return ast.parse(source, mode="exec")
    except SyntaxError as exc:
        location = f" at line {exc.lineno}" if exc.lineno else ""
        raise ValueError(
            f"strategy source has invalid Python syntax{location}: {exc.msg}"
        ) from exc


def _hooks(
    node: ast.ClassDef,
    source: str,
    *,
    declared_on: str | None = None,
) -> list[dict[str, Any]]:
    lines = source.splitlines()
    hooks: list[dict[str, Any]] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hook_name = item.name
        elif isinstance(item, ast.Assign) and isinstance(item.value, ast.Lambda):
            hook_name = (
                str(item.targets[0].id)
                if len(item.targets) == 1 and isinstance(item.targets[0], ast.Name)
                else ""
            )
        else:
            continue
        if not hook_name or hook_name.startswith("_"):
            continue
        if hook_name not in STRATEGY_CALLBACKS:
            continue
        start = int(getattr(item, "lineno", 0) or 0)
        end = int(getattr(item, "end_lineno", start) or start)
        hook = {
            "name": hook_name,
            "lineno": start,
            "end_lineno": end,
            "source": "\n".join(lines[start - 1:end]) if start else "",
        }
        if declared_on:
            hook["declared_on"] = declared_on
        hooks.append(hook)
    return hooks


def _effective_hooks(
    name: str,
    classes: dict[str, ast.ClassDef],
    source: str,
    visiting: set[str],
) -> list[dict[str, Any]]:
    """Return source-backed hooks using Python's first-definition precedence."""
    if name in visiting or name not in classes:
        return []
    visiting = {*visiting, name}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hook in _hooks(classes[name], source, declared_on=name):
        seen.add(hook["name"])
        result.append(hook)
    for base in classes[name].bases:
        for hook in _effective_hooks(_base_name(base), classes, source, visiting):
            if hook["name"] not in seen:
                seen.add(hook["name"])
                result.append(hook)
    return result


def _base_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _inherits_strategy(
    name: str,
    classes: dict[str, ast.ClassDef],
    visiting: set[str],
) -> bool:
    if name in visiting:
        return False
    node = classes.get(name)
    if node is None:
        return False
    visiting = {*visiting, name}
    for base in node.bases:
        base_name = _base_name(base)
        if base_name in _STRATEGY_BASES:
            return True
        if _inherits_strategy(base_name, classes, visiting):
            return True
    return False


def _strategy_methods(
    name: str,
    classes: dict[str, ast.ClassDef],
    visiting: set[str],
) -> set[str]:
    if name in visiting or name not in classes:
        return set()
    visiting = {*visiting, name}
    node = classes[name]
    methods = {
        item.name for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name in STRATEGY_CALLBACKS
    }
    for base in node.bases:
        methods.update(_strategy_methods(_base_name(base), classes, visiting))
    return methods
