"""Tools source scanner for docs and CLI output."""

from __future__ import annotations

import ast
import os
from typing import Any

from tools.decorators.tech_docs import extract_tech_docs_exports, has_tech_docs_decorator

VISIBILITY_ALL = "all"
VISIBILITY_PUBLIC = "public"

_SCAN_CACHE: dict[tuple[str, bool, bool, str], tuple[tuple[tuple[str, int], ...], list[dict[str, Any]]]] = {}
_DETAIL_CACHE: dict[tuple[str, str], tuple[int, dict[str, Any] | None]] = {}


def extract_header_description(source: str) -> str:
    lines = source.split("\n")
    desc_lines = []
    in_header = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ====") and not in_header:
            in_header = True
            continue
        if stripped.startswith("# ====") and in_header:
            break
        if in_header:
            if stripped.startswith("# "):
                desc_lines.append(stripped[2:])
            elif stripped == "#":
                desc_lines.append("")
            else:
                break
    return "\n".join(desc_lines).strip()


def _load_tree(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _public_export_names(tree: ast.Module | None) -> set[str] | None:
    if tree is None:
        return None
    return extract_tech_docs_exports(tree)


def _is_public_function(node: ast.FunctionDef, exported_names: set[str] | None) -> bool:
    if has_tech_docs_decorator(node):
        return True
    if exported_names is not None:
        return node.name in exported_names
    return False


def _is_public_class(node: ast.ClassDef, exported_names: set[str] | None) -> bool:
    if has_tech_docs_decorator(node):
        return True
    if exported_names is not None:
        return node.name in exported_names
    return False


def _method_visible_for_public(method: ast.FunctionDef, class_visible: bool) -> bool:
    return class_visible and not method.name.startswith("_")


def extract_tool_symbols(source: str, visibility: str = VISIBILITY_ALL) -> list[dict[str, str]]:
    tree = _load_tree(source)
    if tree is None:
        return []
    exported_names = _public_export_names(tree) if visibility == VISIBILITY_PUBLIC else None
    symbols: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_visible = visibility != VISIBILITY_PUBLIC or _is_public_class(node, exported_names)
            if not class_visible:
                continue
            symbols.append({"kind": "class", "name": node.name})
            for child in node.body:
                if not isinstance(child, ast.FunctionDef):
                    continue
                if visibility == VISIBILITY_PUBLIC:
                    if _method_visible_for_public(child, class_visible):
                        symbols.append({"kind": "method", "name": f"{node.name}.{child.name}"})
                elif not child.name.startswith("_"):
                    symbols.append({"kind": "method", "name": f"{node.name}.{child.name}"})
        elif isinstance(node, ast.FunctionDef):
            if visibility == VISIBILITY_PUBLIC:
                if _is_public_function(node, exported_names):
                    symbols.append({"kind": "function", "name": node.name})
            elif not node.name.startswith("_"):
                symbols.append({"kind": "function", "name": node.name})
    return symbols


def parse_tool_file(
    filepath: str,
    tools_dir: str,
    include_code: bool = False,
    include_symbols: bool = False,
    visibility: str = VISIBILITY_ALL,
) -> dict[str, Any] | None:
    with open(filepath, "r", encoding="utf-8") as file:
        source = file.read()
    rel_path = os.path.relpath(filepath, tools_dir)
    tree = _load_tree(source)
    symbols = extract_tool_symbols(source, visibility=visibility) if include_symbols or visibility == VISIBILITY_PUBLIC else []
    if visibility == VISIBILITY_PUBLIC and not symbols:
        return None
    item: dict[str, Any] = {
        "path": rel_path,
        "name": rel_path.replace("/", " / ").replace("\\", " / "),
        "desc": extract_header_description(source),
    }
    if include_code:
        item["code"] = source
    if include_symbols:
        item["symbols"] = symbols
    if tree is not None:
        item["tree"] = tree
    return item


def _scan_state(tools_dir: str) -> tuple[tuple[str, int], ...]:
    items: list[tuple[str, int]] = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith("__pycache__") and not d.startswith(".")]
        for filename in sorted(filenames):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            path = os.path.join(root, filename)
            rel_path = os.path.relpath(path, tools_dir)
            try:
                mtime_ns = os.stat(path).st_mtime_ns
            except OSError:
                mtime_ns = -1
            items.append((rel_path, mtime_ns))
    return tuple(items)


def scan_tool_files(
    tools_dir: str,
    include_code: bool = False,
    include_symbols: bool = False,
    visibility: str = VISIBILITY_ALL,
) -> list[dict[str, Any]]:
    cache_key = (os.path.realpath(tools_dir), include_code, include_symbols, visibility)
    state = _scan_state(tools_dir)
    cached = _SCAN_CACHE.get(cache_key)
    if cached is not None and cached[0] == state:
        return [dict(item) for item in cached[1]]
    files = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith("__pycache__") and not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.endswith(".py") and filename != "__init__.py":
                item = parse_tool_file(
                    os.path.join(root, filename),
                    tools_dir,
                    include_code=include_code,
                    include_symbols=include_symbols,
                    visibility=visibility,
                )
                if item is not None:
                    files.append(item)
    files.sort(key=lambda item: item["path"])
    _SCAN_CACHE[cache_key] = (state, [dict(item) for item in files])
    return files


def _comment_block(lines: list[str], start: int) -> str:
    comment = ""
    i = start - 1
    while i >= 0:
        line = lines[i].strip()
        if line.startswith("#") and not line.startswith("# =="):
            comment = line.lstrip("# ").rstrip() + "\n" + comment
            i -= 1
            continue
        break
    return comment.strip()


def _format_signature(node: ast.FunctionDef) -> str:
    parts = []
    for arg in node.args.args:
        item = arg.arg
        if arg.annotation:
            item += ": " + (ast.unparse(arg.annotation) if hasattr(ast, "unparse") else "...")
        parts.append(item)
    if node.args.vararg:
        parts.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        parts.append("**" + node.args.kwarg.arg)
    return ", ".join(parts)


def build_tool_doc_detail(filepath: str, tools_dir: str, visibility: str = VISIBILITY_ALL) -> dict[str, Any] | None:
    real_path = os.path.realpath(filepath)
    try:
        mtime_ns = os.stat(real_path).st_mtime_ns
    except OSError:
        return None
    cache_key = (real_path, visibility)
    cached = _DETAIL_CACHE.get(cache_key)
    if cached is not None and cached[0] == mtime_ns:
        cached_value = cached[1]
        return dict(cached_value) if cached_value is not None else None
    with open(filepath, "r", encoding="utf-8") as file:
        source = file.read()
    lines = source.split("\n")
    tree = _load_tree(source)
    if tree is None:
        return None
    exported_names = _public_export_names(tree) if visibility == VISIBILITY_PUBLIC else None
    rel_path = os.path.relpath(filepath, tools_dir)
    chunks: list[dict[str, Any]] = []
    imports_code = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports_code.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
    if imports_code and visibility != VISIBILITY_PUBLIC:
        chunks.append({"type": "imports", "title": "导入", "code": "\n".join(imports_code), "doc": "", "sub": []})
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_visible = visibility != VISIBILITY_PUBLIC or _is_public_class(node, exported_names)
            if not class_visible:
                continue
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
                    bases.append(f"{base.value.id}.{base.attr}")
                else:
                    bases.append("...")
            methods = []
            for child in node.body:
                if not isinstance(child, ast.FunctionDef):
                    continue
                if visibility == VISIBILITY_PUBLIC and not _method_visible_for_public(child, True):
                    continue
                if visibility != VISIBILITY_PUBLIC and child.name.startswith("_"):
                    continue
                methods.append(
                    {
                        "type": "method",
                        "title": child.name,
                        "signature": _format_signature(child),
                        "doc": (_comment_block(lines, child.lineno - 1) + "\n" + (ast.get_docstring(child) or "")).strip(),
                        "code": "\n".join(lines[child.lineno - 1:child.end_lineno]),
                    }
                )
            chunks.append(
                {
                    "type": "class",
                    "title": node.name,
                    "bases": bases,
                    "doc": (_comment_block(lines, node.lineno - 1) + "\n" + (ast.get_docstring(node) or "")).strip(),
                    "code": "\n".join(lines[node.lineno - 1:node.end_lineno]),
                    "sub": methods,
                }
            )
        elif isinstance(node, ast.FunctionDef):
            if visibility == VISIBILITY_PUBLIC and not _is_public_function(node, exported_names):
                continue
            if visibility != VISIBILITY_PUBLIC and node.name.startswith("_"):
                continue
            chunks.append(
                {
                    "type": "function",
                    "title": node.name,
                    "signature": _format_signature(node),
                    "doc": (_comment_block(lines, node.lineno - 1) + "\n" + (ast.get_docstring(node) or "")).strip(),
                    "code": "\n".join(lines[node.lineno - 1:node.end_lineno]),
                    "sub": [],
                }
            )
    if visibility == VISIBILITY_PUBLIC and not chunks:
        _DETAIL_CACHE[cache_key] = (mtime_ns, None)
        return None
    result = {
        "path": rel_path,
        "description": extract_header_description(source),
        "chunks": chunks,
        "show_code": visibility != VISIBILITY_PUBLIC,
    }
    _DETAIL_CACHE[cache_key] = (mtime_ns, result)
    return dict(result)
