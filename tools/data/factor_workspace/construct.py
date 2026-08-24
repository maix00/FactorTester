"""Workspace construction and stub rendering."""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path
from typing import Any

from tools.data.factor_workspace import storage as factor_workspace_storage
from tools.decorators.factor_workspace import extract_factor_workspace_exports, has_factor_workspace_decorator

from .sdk import AUTHOR_SDK_MODULES


def _workspace_root(username: str) -> str:
    return factor_workspace_storage.factor_source_root(username)


def _workspace_public_dir(root: str) -> str:
    return os.path.join(root, "public_factors")


def _workspace_custom_dir(root: str) -> str:
    return os.path.join(root, "custom_factors")


def _workspace_tools_dir(root: str) -> str:
    return os.path.join(root, "tools")


def _workspace_policies_dir(root: str) -> str:
    return os.path.join(root, "policies")


def _source_tools_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "tools")


def _ensure_workspace_layout(root: str) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    Path(_workspace_public_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_custom_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_tools_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_policies_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, ".factor_workspace")).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, ".vscode")).mkdir(parents=True, exist_ok=True)
    _write_text_if_changed(
        os.path.join(root, ".gitignore"),
        "\n".join([
            ".factor_workspace/",
            "",
        ]),
    )


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


def _is_authoring_marker(decorator: ast.expr) -> bool:
    name = _decorator_to_source(decorator)
    return name == "factor_workspace"


def _is_factor_workspace_flag(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "FACTOR_WORKSPACE"


def _collect_factor_workspace_header_imports(tree: ast.Module) -> list[ast.stmt]:
    imports: list[ast.stmt] = []
    for node in tree.body:
        if not isinstance(node, ast.If) or not _is_factor_workspace_flag(node.test):
            continue
        for child in node.body:
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                imports.append(child)
    return imports


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


def _render_stub_module(source: str, filename: str, *, explicit_author_api: bool = False) -> str:
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

    if workspace_exports is not None:
        needed_names.update(workspace_exports)
    header_import_nodes = _collect_factor_workspace_header_imports(tree)
    header_import_node_ids = {id(node) for node in header_import_nodes}

    def _import_alias_name(alias: ast.alias) -> str:
        return alias.asname or alias.name.rsplit(".", 1)[-1]

    def _render_import_from(node: ast.ImportFrom) -> str | None:
        aliases = []
        for alias in node.names:
            if alias.name == "factor_workspace":
                continue
            local_name = _import_alias_name(alias)
            imported_name = alias.name.rsplit(".", 1)[-1]
            if local_name in needed_names or imported_name in needed_names:
                aliases.append(alias)
        if not aliases:
            return None
        new_node = ast.ImportFrom(module=node.module, names=aliases, level=node.level)
        return ast.unparse(new_node)

    for node in tree.body:
        if id(node) in header_import_node_ids:
            continue
        comment_block = _comment_block_before(source_lines, getattr(node, "lineno", 1))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "__future__":
                continue
            if isinstance(node, ast.Import):
                aliases = [
                    alias
                    for alias in node.names
                    if _import_alias_name(alias) in needed_names
                ]
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
            if explicit_author_api and not has_factor_workspace_decorator(node) and (workspace_exports is None or node.name not in workspace_exports):
                continue
            if workspace_exports is not None and node.name not in workspace_exports and not has_factor_workspace_decorator(node):
                continue
            decorators = [_decorator_to_source(dec) for dec in node.decorator_list if not _is_authoring_marker(dec)]
            decorators = [item for item in decorators if item]
            _append_comment_block(lines, comment_block)
            for decorator in decorators:
                lines.append(f"@{decorator}")
            signature = _format_arguments(node.args)
            return_annotation = "None" if node.name == "__init__" else (_annotation_to_source(node.returns) if node.returns is not None else "Any")
            lines.append(f"def {node.name}({signature}) -> {return_annotation}: ...")
        elif isinstance(node, ast.ClassDef):
            if explicit_author_api and not has_factor_workspace_decorator(node) and (workspace_exports is None or node.name not in workspace_exports):
                continue
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
                if _is_authoring_marker(decorator):
                    continue
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
                    decorators = [_decorator_to_source(dec) for dec in child.decorator_list if not _is_authoring_marker(dec)]
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
            if _is_factor_workspace_flag(node.test):
                for child in node.body:
                    rendered_import = None
                    if isinstance(child, ast.ImportFrom):
                        aliases = [
                            alias for alias in child.names
                            if alias.name != "factor_workspace"
                        ]
                        if aliases:
                            rendered_import = ast.unparse(
                                ast.ImportFrom(module=child.module, names=aliases, level=child.level)
                            )
                    elif isinstance(child, ast.Import):
                        aliases = [
                            alias for alias in child.names
                            if _import_alias_name(alias) != "factor_workspace"
                        ]
                        if aliases:
                            rendered_import = ast.unparse(ast.Import(names=aliases))
                    if rendered_import:
                        child_comment_block = _comment_block_before(source_lines, getattr(child, "lineno", 1))
                        _append_comment_block(lines, child_comment_block)
                        lines.append(rendered_import)
                continue
            continue

    lines.append("")
    return "\n".join(lines)


def _clear_workspace_generated(root: str) -> list[str]:
    removed: list[str] = []
    if not os.path.isdir(root):
        return removed
    preserve = {".git", ".gitignore", "research"}
    for name in sorted(os.listdir(root)):
        if name in preserve:
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
            if os.path.exists(path):
                # 有些目录可能因为并发写入或文件句柄占用而暂时删不净，
                # 这里做一次兜底清理，避免把建工作区整条链路卡死。
                for current_root, dirs, filenames in os.walk(path, topdown=False):
                    for filename in filenames:
                        file_path = os.path.join(current_root, filename)
                        try:
                            os.remove(file_path)
                        except FileNotFoundError:
                            pass
                    for dirname in dirs:
                        dir_path = os.path.join(current_root, dirname)
                        try:
                            os.rmdir(dir_path)
                        except OSError:
                            pass
                try:
                    os.rmdir(path)
                except OSError:
                    pass
            removed.append(path)
        elif os.path.exists(path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
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


def _sync_tools_sdk(root: str) -> bool:
    workspace_root = _workspace_tools_dir(root)
    touched = False
    expected_files: set[str] = set()

    repo_root = Path(__file__).resolve().parents[3]
    for module in AUTHOR_SDK_MODULES:
        expected_files.add(module.destination)
        dest_path = os.path.join(root, module.destination)
        if module.content is not None:
            stub_code = module.content
        else:
            source_path = repo_root / str(module.source)
            source_code = source_path.read_text(encoding="utf-8")
            stub_code = _render_stub_module(source_code, str(module.source), explicit_author_api=True)
            if module.prelude:
                marker = "from typing import Any\n"
                stub_code = stub_code.replace(marker, marker + module.prelude, 1)
            if module.footer:
                stub_code = stub_code.rstrip() + "\n\n" + module.footer
        if _write_text_if_changed(dest_path, stub_code):
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
    touched |= _sync_pyright_config(root)
    touched |= _sync_workspace_guide(root)
    touched |= _sync_policy_workspace(root)
    return touched


def _sync_pyright_config(root: str) -> bool:
    return _write_json(
        os.path.join(root, "pyrightconfig.json"),
        {
            "include": ["custom_factors", "public_factors", "policies", "tools", "pandas"],
            "extraPaths": ["."],
            "pythonVersion": "3.10",
            "reportMissingModuleSource": "none",
        },
    )


def _sync_workspace_guide(root: str) -> bool:
    extensions_changed = _write_json(
        os.path.join(root, ".vscode", "extensions.json"),
        {"recommendations": ["ms-python.vscode-pylance"]},
    )
    guide_changed = _write_text_if_changed(
        os.path.join(root, "FACTOR_WORKSPACE.md"),
        "# Factor Workspace\n\n"
        "Open this directory as the VS Code workspace and install the recommended "
        "Pylance extension. Type checking and completion use the generated `.pyi` files; "
        "no local GTHT conda environment is required.\n\n"
        "Edit files under `custom_factors/`. Factor execution and data access happen on "
        "the FactorTester server after synchronization. Generated SDK files under `tools/` "
        "and `pandas/` should not be edited.\n\n"
        "Use `policies/` for local StrategyBook policy experiments and research notes. "
        "Policy files are versioned with the workspace Git repository, but they are not "
        "executed by the server unless a reviewed runtime adapter explicitly wires them in.\n",
    )
    return extensions_changed or guide_changed


def _sync_policy_workspace(root: str) -> bool:
    policies_dir = _workspace_policies_dir(root)
    Path(policies_dir).mkdir(parents=True, exist_ok=True)
    readme_changed = _write_text_if_changed(
        os.path.join(policies_dir, "README.md"),
        "# StrategyBook Policies\n\n"
        "This directory is for local policy research that travels with the private factor "
        "workspace Git history. Keep these files small, reviewable, and explicit.\n\n"
        "Supported policy surfaces are declared by the backend StrategyBook registry. "
        "Typical examples include order sizing, cash availability, order routing, pending "
        "order conflict handling, and strategy-intent precomputation.\n\n"
        "Current runtime note: these files are authoring artifacts. The server will not "
        "import or execute arbitrary workspace policy code unless a reviewed adapter maps "
        "a named policy to a registered StrategyBook field.\n\n"
        "Research loop:\n\n"
        "1. Define or edit factors in `custom_factors/` and parameter candidates through "
        "the CLI factor-library commands.\n"
        "2. Draft policy ideas in `policies/`.\n"
        "3. Use `factortester custom_factors workspace git status|diff|commit` to keep "
        "the experiment reproducible.\n"
        "4. Run CLI backtests against selected product groups and compare results.\n",
    )
    example_changed = _write_text_if_changed(
        os.path.join(policies_dir, "strategy_book_policy_example.py"),
        '"""Example StrategyBook policy helpers for local research.\n\n'
        "These functions document the shape of policy hooks. They are not imported by the "
        "server automatically; wire them through an explicit backend/CLI adapter before "
        "using them in production backtests.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n\n"
        "def order_sizing_identity(state: Any, ctx: Any, strategy: Any, deltas: dict[Any, float]) -> dict[Any, float]:\n"
        "    \"\"\"Return target deltas unchanged.\n\n"
        "    Use this as the smallest possible starting point when comparing a custom "
        "    sizing idea against the backend default sizing policy.\n"
        "    \"\"\"\n"
        "    return dict(deltas)\n\n\n"
        "def reserve_cash_ratio(state: Any, ledger: Any, cash_available: float, currency: str, *, reserve: float = 0.10) -> float:\n"
        "    \"\"\"Keep a fraction of cash unavailable for new orders.\"\"\"\n"
        "    reserve = min(max(float(reserve), 0.0), 1.0)\n"
        "    return float(cash_available) * (1.0 - reserve)\n",
    )
    return readme_changed or example_changed


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
    changed = payload.pop("python.defaultInterpreterPath", None) is not None
    for key, value in updates.items():
        if payload.get(key) != value:
            payload[key] = value
            changed = True
    if not os.path.exists(settings_path) or changed:
        return _write_json(settings_path, payload)
    return False


def build_factor_workspace(username: str) -> dict[str, Any]:
    from .sync import sync_database_to_workspace
    from .repository import FactorWorkspaceRepository

    result = sync_database_to_workspace(username, branch_mode="auto", clear_existing=True)
    git_info = result.get("git") or {}
    if git_info.get("git_enabled"):
        repository = FactorWorkspaceRepository(username)
        commit_sha = repository.commit_generated("chore: rebuild factor workspace")
        if commit_sha:
            created_branches = repository.materialize_branches()
            result["git_commit_sha"] = commit_sha
            if created_branches:
                result["git_created_branches"] = created_branches
        result["git"] = repository.state()
        result["git_selected_branch"] = result["git"].get("git_current_branch", "")
        manifest_path = os.path.join(repository.root, ".factor_workspace", "manifest.json")
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as file:
                manifest = json.load(file)
        manifest["git"] = result["git"]
        manifest["git_selected_branch"] = result["git_selected_branch"]
        _write_json(manifest_path, manifest)
    return result
