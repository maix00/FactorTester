"""Workspace construction and stub rendering."""

from __future__ import annotations

import ast
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from tools.data.factor_workspace import storage as factor_workspace_storage
from tools.data.tech_docs import scan_tool_files
from tools.decorators.factor_workspace import (
    collect_factor_workspace_import_dependencies,
    extract_factor_workspace_exports,
    has_factor_workspace_decorator,
)

from .pre import WorkspaceSourceSpec, collect_workspace_architecture


def _workspace_root(username: str) -> str:
    return factor_workspace_storage.factor_source_root(username)


def _workspace_public_dir(root: str) -> str:
    return os.path.join(root, "public_factors")


def _workspace_custom_dir(root: str) -> str:
    return os.path.join(root, "custom_factors")


def _workspace_tools_dir(root: str) -> str:
    return os.path.join(root, "tools")


def _source_tools_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "tools")


def _ensure_workspace_layout(root: str) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    Path(_workspace_public_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_custom_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_tools_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, ".factor_workspace")).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, ".vscode")).mkdir(parents=True, exist_ok=True)


def _write_text_if_changed(path: str, content: str) -> bool:
    existing = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            existing = file.read()
    if existing == content:
        return False
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return True


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return _write_text_if_changed(path, content + "\n")


def _annotation_to_source(node: ast.AST | None) -> str:
    if node is None:
        return "Any"
    try:
        return ast.unparse(node)
    except Exception:
        return "Any"


def _format_arguments(args: ast.arguments) -> str:
    parts: list[str] = []
    posonly = list(args.posonlyargs)
    normal = list(args.args)
    defaults = [None] * (len(posonly) + len(normal) - len(args.defaults)) + list(args.defaults)
    for index, arg in enumerate(posonly + normal):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {_annotation_to_source(arg.annotation)}"
        default = defaults[index] if index < len(defaults) else None
        if default is not None:
            piece += " = ..."
        parts.append(piece)
        if posonly and index + 1 == len(posonly):
            parts.append("/")
    if args.vararg is not None:
        piece = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            piece += f": {_annotation_to_source(args.vararg.annotation)}"
        parts.append(piece)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {_annotation_to_source(arg.annotation)}"
        if default is not None:
            piece += " = ..."
        parts.append(piece)
    if args.kwarg is not None:
        piece = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            piece += f": {_annotation_to_source(args.kwarg.annotation)}"
        parts.append(piece)
    return ", ".join(parts)


def _decorator_to_source(decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        try:
            return ast.unparse(decorator)
        except Exception:
            return None
    return None


def _comment_block_before(lines: list[str], lineno: int) -> list[str]:
    block: list[str] = []
    idx = lineno - 2
    saw_comment = False
    blank_run = 0
    while idx >= 0:
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            block.append(lines[idx].rstrip())
            saw_comment = True
            blank_run = 0
        elif stripped == "":
            if saw_comment:
                blank_run += 1
                if blank_run > 1:
                    break
                block.append("")
            elif block:
                block.append("")
        else:
            break
        idx -= 1
    while block and block[-1] == "":
        block.pop()
    block.reverse()
    return block


def _append_comment_block(lines: list[str], comment_block: list[str]) -> None:
    if not comment_block:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(comment_block)


def _render_assignment_stub(node: ast.Assign) -> str | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    target = node.targets[0].id
    if target.startswith("_"):
        return None
    inferred = "Any"
    if isinstance(node.value, ast.Call):
        func_name = ""
        if isinstance(node.value.func, ast.Name):
            func_name = node.value.func.id
        elif isinstance(node.value.func, ast.Attribute):
            func_name = node.value.func.attr
        if func_name.endswith("_param") or func_name.startswith("get_"):
            inferred = "Parameter"
    return f"{target}: {inferred} = ..."


def _collect_instance_attrs(class_node: ast.ClassDef) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr not in attrs
                    ):
                        attrs[target.attr] = "Any"
            elif isinstance(child, ast.AnnAssign):
                target = child.target
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr not in attrs
                ):
                    attrs[target.attr] = _annotation_to_source(child.annotation)
    return attrs


def _render_stub_module(source: str, filename: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "\n".join([
            "from __future__ import annotations",
            "from typing import Any",
            "",
            "...",
            "",
        ])

    lines: list[str] = ["from __future__ import annotations", "from typing import Any"]
    source_lines = source.splitlines()
    workspace_exports = None
    needed_names: set[str] = set()

    # Collect decorator-driven exports from the source file itself.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__factor_workspace__" for target in node.targets):
                workspace_exports = extract_factor_workspace_exports(tree)
                break

    needed_names = collect_factor_workspace_import_dependencies(tree, workspace_exports)
    is_package_init = filename == "__init__.py"

    def _import_alias_name(alias: ast.alias) -> str:
        return alias.asname or alias.name.rsplit(".", 1)[-1]

    def _render_import_from(node: ast.ImportFrom) -> str | None:
        aliases = []
        for alias in node.names:
            local_name = _import_alias_name(alias)
            imported_name = alias.name.rsplit(".", 1)[-1]
            if local_name in needed_names or imported_name in needed_names:
                aliases.append(alias)
        if not aliases:
            return None
        new_node = ast.ImportFrom(module=node.module, names=aliases, level=node.level)
        return ast.unparse(new_node)

    for node in tree.body:
        comment_block = _comment_block_before(source_lines, getattr(node, "lineno", 1))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "__future__":
                continue
            if is_package_init:
                _append_comment_block(lines, comment_block)
                lines.append(ast.unparse(node))
                continue
            if isinstance(node, ast.Import):
                aliases = [alias for alias in node.names if _import_alias_name(alias) in needed_names]
                if not aliases:
                    continue
                node = ast.Import(names=aliases)
            if isinstance(node, ast.ImportFrom):
                rendered_import = _render_import_from(node)
                if rendered_import is None:
                    continue
                _append_comment_block(lines, comment_block)
                lines.append(rendered_import)
                continue
            _append_comment_block(lines, comment_block)
            lines.append(ast.unparse(node))
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__factor_workspace__" for target in node.targets):
                continue
            if workspace_exports is not None:
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if not any(name in workspace_exports for name in names):
                    continue
            rendered = _render_assignment_stub(node)
            if rendered:
                _append_comment_block(lines, comment_block)
                lines.append(rendered)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                if workspace_exports is not None and node.target.id not in workspace_exports:
                    continue
                _append_comment_block(lines, comment_block)
                lines.append(f"{node.target.id}: {_annotation_to_source(node.annotation)}")
        elif isinstance(node, ast.FunctionDef):
            if workspace_exports is not None and node.name not in workspace_exports and not has_factor_workspace_decorator(node):
                continue
            decorators = [_decorator_to_source(dec) for dec in node.decorator_list]
            decorators = [item for item in decorators if item]
            _append_comment_block(lines, comment_block)
            for decorator in decorators:
                lines.append(f"@{decorator}")
            signature = _format_arguments(node.args)
            return_annotation = "None" if node.name == "__init__" else (_annotation_to_source(node.returns) if node.returns is not None else "Any")
            lines.append(f"def {node.name}({signature}) -> {return_annotation}: ...")
        elif isinstance(node, ast.ClassDef):
            if workspace_exports is not None and node.name not in workspace_exports and not has_factor_workspace_decorator(node):
                continue
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base))
                except Exception:
                    bases.append("Any")
            base_expr = f"({', '.join(bases)})" if bases else ""
            _append_comment_block(lines, comment_block)
            for decorator in node.decorator_list:
                decorator_source = _decorator_to_source(decorator)
                if decorator_source:
                    lines.append(f"@{decorator_source}")
            lines.append(f"class {node.name}{base_expr}:")
            class_lines: list[str] = []
            for attr_name, attr_type in _collect_instance_attrs(node).items():
                class_lines.append(f"{attr_name}: {attr_type}")
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    class_lines.append(f"{child.target.id}: {_annotation_to_source(child.annotation)}")
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            class_lines.append(f"{target.id}: Any")
                elif isinstance(child, ast.FunctionDef):
                    if not has_factor_workspace_decorator(child):
                        continue
                    decorators = [_decorator_to_source(dec) for dec in child.decorator_list]
                    decorators = [item for item in decorators if item]
                    for decorator in decorators:
                        class_lines.append(f"@{decorator}")
                    signature = _format_arguments(child.args)
                    return_annotation = "None" if child.name == "__init__" else (_annotation_to_source(child.returns) if child.returns is not None else "Any")
                    class_lines.append(f"def {child.name}({signature}) -> {return_annotation}: ...")
            if not class_lines:
                class_lines.append("...")
            lines.extend(f"    {line}" for line in class_lines)
        elif isinstance(node, ast.If):
            continue

    lines.append("")
    return "\n".join(lines)


def _clear_workspace_generated(root: str) -> list[str]:
    removed: list[str] = []
    if not os.path.isdir(root):
        return removed
    preserve = {".git", ".gitignore"}
    for name in sorted(os.listdir(root)):
        if name in preserve:
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
            removed.append(path)
        elif os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return removed


def _remove_missing_files(directory: str, expected_names: set[str]) -> list[str]:
    removed: list[str] = []
    if not os.path.isdir(directory):
        return removed
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py"):
            continue
        if filename in expected_names:
            continue
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def _sync_tools_index(root: str) -> bool:
    tools_dir = os.path.join(os.getcwd(), "tools")
    tool_files = scan_tool_files(tools_dir, include_symbols=True)
    payload = {
        "workspace_root": root,
        "tools_dir": tools_dir,
        "generated_at": time.time(),
        "files": tool_files,
    }
    return _write_json(os.path.join(root, "tools_index.json"), payload)


def _sync_tools_sdk(root: str) -> bool:
    source_root = _source_tools_dir()
    workspace_root = _workspace_tools_dir(root)
    touched = False
    expected_files: set[str] = set()

    for spec in collect_workspace_architecture():
        if spec.relative_path == "Settings.py":
            continue
        source_path = spec.source_path
        rel_path = spec.relative_path
        workspace_rel_path = rel_path[len("tools/"):] if rel_path.startswith("tools/") else rel_path
        dest_rel_path = workspace_rel_path[:-3] + ".pyi"
        expected_files.add(os.path.join("tools", dest_rel_path))
        dest_path = os.path.join(workspace_root, dest_rel_path)
        with open(source_path, "r", encoding="utf-8") as file:
            source_code = file.read()
        stub_code = _render_stub_module(source_code, rel_path)
        if _write_text_if_changed(dest_path, stub_code):
            touched = True

    settings_source = Path(__file__).resolve().parents[3] / "Settings.py"
    if settings_source.exists():
        settings_dest = os.path.join(root, "Settings.pyi")
        expected_files.add("Settings.pyi")
        with open(settings_source, "r", encoding="utf-8") as file:
            source_code = file.read()
        if _write_text_if_changed(settings_dest, _render_stub_module(source_code, "Settings.py")):
            touched = True

    for current_root, dirs, filenames in os.walk(workspace_root):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith("__pycache__") and not d.startswith(".")]
        rel_dir = os.path.relpath(current_root, workspace_root)
        for filename in sorted(filenames):
            if not (filename.endswith(".pyi") or filename.endswith(".py")):
                continue
            if filename.endswith(".pyi"):
                rel_path = os.path.join("tools", filename) if rel_dir == "." else os.path.join("tools", rel_dir, filename)
            else:
                rel_path = (
                    os.path.join("tools", filename[:-3] + ".pyi")
                    if rel_dir == "."
                    else os.path.join("tools", rel_dir, filename[:-3] + ".pyi")
                )
            if rel_path not in expected_files:
                os.remove(os.path.join(current_root, filename))
                touched = True

    touched |= _sync_vscode_settings(root)
    return touched


def _sync_vscode_settings(root: str) -> bool:
    settings_path = os.path.join(root, ".vscode", "settings.json")
    updates = {
        "python.analysis.extraPaths": ["${workspaceFolder}"],
        "python.analysis.autoSearchPaths": True,
        "python.analysis.diagnosticSeverityOverrides": {
            "reportMissingModuleSource": "none",
        },
    }
    payload: dict[str, Any] = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    changed = False
    for key, value in updates.items():
        if payload.get(key) != value:
            payload[key] = value
            changed = True
    if not os.path.exists(settings_path) or changed:
        return _write_json(settings_path, payload)
    return False


def build_factor_workspace(username: str) -> dict[str, Any]:
    from .sync import sync_database_to_workspace

    result = sync_database_to_workspace(username, branch_mode="force", clear_existing=True)
    git_info = result.get("git") or {}
    if git_info.get("git_enabled"):
        root = result.get("workspace_root") or _workspace_root(username)
        from .git import _git_commit_all

        commit_sha = _git_commit_all(str(root), "chore: rebuild factor workspace")
        if commit_sha:
            result["git_commit_sha"] = commit_sha
    return result
