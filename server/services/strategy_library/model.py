"""Validation and source inspection for persistent Strategy entries."""

from __future__ import annotations

import ast
import hashlib
import re
from typing import Any

from tools.testers.backtest.engines.native.strategy import STRATEGY_CALLBACKS


MAX_SOURCE_BYTES = 1024 * 1024
VISIBILITIES = frozenset({"private", "shared", "public"})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STRATEGY_BASES = frozenset({
    "Strategy", "BarStrategy", "EventStrategy", "OrderAwareStrategy",
})


def normalize_text(value: object, *, field: str, limit: int) -> str:
    result = " ".join(str(value or "").split())
    if len(result) > limit:
        raise ValueError(f"{field} is too long")
    return result


def normalize_entrypoint(value: object) -> str:
    entrypoint = str(value or "Strategy").strip()
    if not _IDENTIFIER.fullmatch(entrypoint):
        raise ValueError("strategy entrypoint must be a Python identifier")
    return entrypoint


def inspect_source(source_code: object, entrypoint: object = "Strategy") -> dict[str, Any]:
    """Parse source once and return a bounded, UI-safe hook projection."""
    source = str(source_code or "")
    if not source.strip():
        raise ValueError("strategy source code is required")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("strategy source code exceeds 1 MiB")
    name = normalize_entrypoint(entrypoint)
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        location = f" at line {exc.lineno}" if exc.lineno else ""
        raise ValueError(f"strategy source has invalid Python syntax{location}: {exc.msg}") from exc
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    selected = next((node for node in classes if node.name == name), None)
    if selected is None:
        available = ", ".join(node.name for node in classes) or "none"
        raise ValueError(f"strategy entrypoint class not found: {name} (available: {available})")
    class_map = {node.name: node for node in classes}
    if not _inherits_strategy(name, class_map, set()):
        raise ValueError(f"strategy entrypoint is not a native Strategy: {name}")

    lines = source.splitlines()
    hooks: list[dict[str, Any]] = []
    for node in selected.body:
        function = node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hook_name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
            hook_name = str(node.targets[0].id) if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) else ""
        else:
            continue
        if not hook_name or hook_name.startswith("_"):
            continue
        if hook_name not in STRATEGY_CALLBACKS:
            continue
        start = int(getattr(function, "lineno", 0) or 0)
        end = int(getattr(function, "end_lineno", start) or start)
        snippet = "\n".join(lines[start - 1:end]) if start else ""
        hooks.append({
            "name": hook_name,
            "lineno": start,
            "end_lineno": end,
            "source": snippet,
        })
    return {
        "entrypoint": name,
        "hooks": hooks,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "source_bytes": len(source.encode("utf-8")),
    }


def normalize_visibility(value: object) -> str:
    visibility = str(value or "private").strip().lower()
    if visibility not in VISIBILITIES:
        raise ValueError("strategy visibility must be private, shared, or public")
    return visibility


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
