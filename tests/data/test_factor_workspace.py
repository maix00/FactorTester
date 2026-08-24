from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from server.services import factor_workspace
from tools.data.factor_workspace import construct as factor_workspace_construct
from tools.data.factor_workspace import git as factor_workspace_git
from tools.data.factor_workspace import storage as factor_workspace_storage
from tools.data.factor_workspace import sync as factor_workspace_sync
from tools.data.factor_workspace.repository import FactorWorkspaceRepository
from tools.data.factor_workspace.sdk import author_sdk_paths


def test_factor_workspace_build_refreshes_and_prunes_stale_files(monkeypatch, tmp_path):
    workspace_root = tmp_path / "factor-root"
    custom_dir = workspace_root / "custom_factors"
    public_dir = workspace_root / "public_factors"
    custom_dir.mkdir(parents=True)
    public_dir.mkdir(parents=True)
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$alice@1"}),
        encoding="utf-8",
    )

    stale_custom = custom_dir / "OldFactor.py"
    stale_public = public_dir / "OldPublic.py"
    stale_root = workspace_root / "stale.txt"
    stale_custom.write_text("class OldFactor(FactorFamily):\n    pass\n", encoding="utf-8")
    stale_public.write_text("class OldPublic(FactorFamily):\n    pass\n", encoding="utf-8")
    stale_root.write_text("old\n", encoding="utf-8")
    report = workspace_root / "research" / "branches" / "branch-1" / "REPORT.md"
    note = workspace_root / "research" / "notes" / "agent-note.md"
    report.parent.mkdir(parents=True)
    note.parent.mkdir(parents=True)
    report.write_text("derived report\n", encoding="utf-8")
    note.write_text("provisional note\n", encoding="utf-8")

    factor_storage = factor_workspace_storage
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(
        factor_workspace_sync,
        "list_factor_sources",
        lambda source_kind: [
            {
                "owner_username": "default$alice@1",
                "factor_id": "FreshFactor",
                "source_code": "class FreshFactor(FactorFamily):\n    pass\n",
            }
        ]
        if source_kind == "custom"
        else [
            {
                "owner_username": "",
                "factor_id": "PublicFactor",
                "source_code": "class PublicFactor(FactorFamily):\n    pass\n",
            }
        ],
    )
    git_state = {
        "git_enabled": True,
        "git_repo_root": str(workspace_root),
        "git_current_branch": "upload",
        "git_auto_sync_branch": "upload",
        "git_force_sync_branch": "download",
        "git_branches": ["main", "upload", "download"],
    }
    monkeypatch.setattr(FactorWorkspaceRepository, "ensure", lambda self: git_state)
    monkeypatch.setattr(FactorWorkspaceRepository, "checkout", lambda self, mode: "upload")
    monkeypatch.setattr(FactorWorkspaceRepository, "commit", lambda self, message: None)
    monkeypatch.setattr(FactorWorkspaceRepository, "state", lambda self: git_state)

    result = factor_workspace.build_factor_workspace("default$alice@1")

    assert result["custom_factor_count"] == 1
    assert result["public_factor_count"] == 1
    assert not stale_custom.exists()
    assert not stale_public.exists()
    assert not stale_root.exists()
    assert report.read_text(encoding="utf-8") == "derived report\n"
    assert note.read_text(encoding="utf-8") == "provisional note\n"
    assert (custom_dir / "FreshFactor.py").read_text(encoding="utf-8") == "class FreshFactor(FactorFamily):\n    pass\n"
    assert (public_dir / "PublicFactor.py").read_text(encoding="utf-8") == "class PublicFactor(FactorFamily):\n    pass\n"
    assert (workspace_root / ".factor_workspace" / "manifest.json").exists()
    assert ".factor_workspace/" in (workspace_root / ".gitignore").read_text(encoding="utf-8")
    parameters_pkg_stub = (workspace_root / "tools" / "parameters" / "__init__.pyi").read_text(encoding="utf-8")
    factors_pkg_stub = (workspace_root / "tools" / "factors" / "__init__.pyi").read_text(encoding="utf-8")
    expr_pkg_stub = (workspace_root / "tools" / "factors" / "expr" / "__init__.pyi").read_text(encoding="utf-8")
    assert "WindowParam" in parameters_pkg_stub
    assert "FactorTester" not in factors_pkg_stub
    assert "EvaluateContext" not in factors_pkg_stub
    assert "visual_groups" not in factors_pkg_stub
    assert "WindowParam" in parameters_pkg_stub
    assert "FactorExpr" in factors_pkg_stub
    assert "EvaluateContext" not in expr_pkg_stub
    assert "as_intermediate" not in expr_pkg_stub
    assert (workspace_root / "tools" / "__init__.pyi").exists()
    assert (workspace_root / "tools" / "factors" / "__init__.pyi").exists()
    assert (workspace_root / "tools" / "testers" / "backtest" / "modules" / "strategy_book.pyi").exists()
    assert (workspace_root / "tools" / "testers" / "backtest" / "modules" / "volume_capacity.pyi").exists()
    assert not (workspace_root / "tools" / "factors" / "FactorTester.pyi").exists()
    assert not (workspace_root / "tools" / "factors" / "tests").exists()
    assert result["git"]["git_enabled"] is True
    assert result["git"]["git_auto_sync_branch"] == "upload"
    assert result["git"]["git_force_sync_branch"] == "download"
    settings = json.loads((workspace_root / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.analysis.extraPaths"] == ["${workspaceFolder}"]
    assert settings["python.analysis.autoSearchPaths"] is True
    assert settings["python.analysis.diagnosticSeverityOverrides"]["reportMissingModuleSource"] == "none"
    pyright_config = json.loads((workspace_root / "pyrightconfig.json").read_text(encoding="utf-8"))
    assert pyright_config["include"] == ["custom_factors", "public_factors", "policies", "tools", "pandas"]
    assert pyright_config["pythonVersion"] == "3.10"
    assert pyright_config["reportMissingModuleSource"] == "none"
    assert "venv" not in pyright_config
    assert "venvPath" not in pyright_config
    assert "python.defaultInterpreterPath" not in settings
    assert (workspace_root / "pandas" / "__init__.pyi").exists()
    assert (workspace_root / "FACTOR_WORKSPACE.md").exists()
    assert (workspace_root / "policies" / "README.md").exists()
    assert (workspace_root / "policies" / "strategy_book_policy_example.py").exists()
    assert "StrategyBook" in (workspace_root / "policies" / "README.md").read_text(encoding="utf-8")
    extensions = json.loads((workspace_root / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    assert extensions["recommendations"] == ["ms-python.vscode-pylance"]
    assert not (workspace_root / "tools" / "factors" / "FactorExpr.py").exists()
    assert not (workspace_root / "tools" / "parameters" / "WindowParam.py").exists()
    assert not (workspace_root / "tools" / "factors" / "FactorFamily.py").exists()
    manifest = json.loads((workspace_root / ".factor_workspace" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_selected_branch"] == "upload"


def test_factor_workspace_build_refuses_root_owned_by_another_profile(monkeypatch, tmp_path):
    workspace_root = tmp_path / "shared-factor-root"
    custom_dir = workspace_root / "custom_factors"
    custom_dir.mkdir(parents=True)
    protected_source = custom_dir / "OwnerFactor.py"
    protected_source.write_text("owner source\n", encoding="utf-8")
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$owner@1"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        factor_workspace_storage,
        "factor_source_root",
        lambda username: str(workspace_root),
    )

    with pytest.raises(PermissionError, match="default\\$owner@1"):
        factor_workspace.build_factor_workspace("default$other@1")

    assert protected_source.read_text(encoding="utf-8") == "owner source\n"


def test_factor_workspace_sync_refuses_root_owned_by_another_profile(
    monkeypatch,
    tmp_path,
):
    workspace_root = tmp_path / "shared-factor-root"
    custom_dir = workspace_root / "custom_factors"
    custom_dir.mkdir(parents=True)
    protected_source = custom_dir / "OwnerFactor.py"
    protected_source.write_text("owner source\n", encoding="utf-8")
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$owner@1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        factor_workspace_storage,
        "factor_source_root",
        lambda username: str(workspace_root),
    )

    with pytest.raises(PermissionError, match="default\\$owner@1"):
        factor_workspace.sync_factor_workspace(
            "default$other@1",
            branch_mode="force",
        )

    assert protected_source.read_text(encoding="utf-8") == "owner source\n"


def test_factor_workspace_push_refuses_root_owned_by_another_profile(
    monkeypatch,
    tmp_path,
):
    workspace_root = tmp_path / "shared-factor-root"
    custom_dir = workspace_root / "custom_factors"
    custom_dir.mkdir(parents=True)
    protected_source = custom_dir / "OwnerFactor.py"
    protected_source.write_text("owner source\n", encoding="utf-8")
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$owner@1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        factor_workspace_storage,
        "factor_source_root",
        lambda username: str(workspace_root),
    )

    with pytest.raises(PermissionError, match="default\\$owner@1"):
        factor_workspace.push_factor_workspace("default$other@1")

    assert protected_source.read_text(encoding="utf-8") == "owner source\n"


def test_factor_workspace_build_refuses_nonempty_unmanaged_root(monkeypatch, tmp_path):
    workspace_root = tmp_path / "unmanaged-root"
    workspace_root.mkdir()
    protected_file = workspace_root / "research-notes.md"
    protected_file.write_text("keep me\n", encoding="utf-8")

    monkeypatch.setattr(
        factor_workspace_storage,
        "factor_source_root",
        lambda username: str(workspace_root),
    )

    with pytest.raises(PermissionError, match="没有有效的 Factor Workspace 所有权标记"):
        factor_workspace.build_factor_workspace("default$alice@1")

    assert protected_file.read_text(encoding="utf-8") == "keep me\n"


def test_factor_workspace_sync_rejects_profile_worktree_root(monkeypatch, tmp_path):
    profile_root = tmp_path / "users" / "alice" / "profiles" / "maxa" / "factor-worktree"
    profile_root.mkdir(parents=True)
    monkeypatch.setattr(
        factor_workspace_storage,
        "factor_source_root",
        lambda username: str(profile_root),
    )

    with pytest.raises(PermissionError, match="Profile factor-worktree"):
        factor_workspace.sync_factor_workspace("alice", branch_mode="force")


def test_generated_workspace_commit_suppresses_recursive_autosync(monkeypatch):
    observed: list[str | None] = []
    monkeypatch.delenv("FACTOR_WORKSPACE_SKIP_AUTOSYNC", raising=False)
    monkeypatch.setattr(
        FactorWorkspaceRepository,
        "commit",
        lambda self, message: observed.append(
            __import__("os").environ.get("FACTOR_WORKSPACE_SKIP_AUTOSYNC")
        ),
    )

    repository = FactorWorkspaceRepository("default$alice@1")
    repository.commit_generated("chore: generated")

    assert observed == ["1"]
    assert __import__("os").environ.get("FACTOR_WORKSPACE_SKIP_AUTOSYNC") is None


def test_factor_source_change_commits_current_upload_workspace(monkeypatch):
    observed: list[tuple[str, str]] = []
    git_state = {
        "git_enabled": True,
        "git_current_branch": "upload",
    }
    monkeypatch.setattr(
        factor_workspace,
        "sync_database_to_workspace",
        lambda username, branch_mode, clear_existing: {
            "username": username,
            "git": git_state,
            "git_selected_branch": branch_mode,
        },
    )
    monkeypatch.setattr(
        FactorWorkspaceRepository,
        "commit_generated",
        lambda self, message: observed.append((self.username, message)) or "abc1234",
    )
    monkeypatch.setattr(
        FactorWorkspaceRepository,
        "state",
        lambda self: {**git_state, "git_current_branch": "upload"},
    )

    result = factor_workspace.commit_factor_source_change(
        "default$alice@1", "factor: create Momentum",
    )

    assert observed == [("default$alice@1", "factor: create Momentum")]
    assert result["git_commit_sha"] == "abc1234"
    assert result["git_selected_branch"] == "upload"


def test_factor_workspace_push_blocks_public_changes_for_non_admin(monkeypatch, tmp_path):
    workspace_root = tmp_path / "factor-root"
    public_dir = workspace_root / "public_factors"
    public_dir.mkdir(parents=True)
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$alice@1"}),
        encoding="utf-8",
    )
    (public_dir / "PublicFactor.py").write_text("class PublicFactor(FactorFamily):\n    pass\n", encoding="utf-8")

    factor_storage = factor_workspace_storage
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(factor_storage, "load_public_factor_source", lambda factor_id: "class PublicFactor(FactorFamily):\n    pass\n# db version\n")

    with pytest.raises(PermissionError):
        factor_workspace.push_factor_workspace("default$alice@1", allow_public_write=False, branch_mode="force")


def test_factor_workspace_push_reports_source_free_public_change(
    monkeypatch, tmp_path,
):
    workspace_root = tmp_path / "factor-root"
    public_dir = workspace_root / "public_factors"
    public_dir.mkdir(parents=True)
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "root"}), encoding="utf-8",
    )
    source = "class PublicFactor(FactorFamily):\n    pass\n"
    (public_dir / "PublicFactor.py").write_text(source, encoding="utf-8")
    stored = {"value": "old\n"}

    monkeypatch.setattr(
        factor_workspace_storage, "factor_source_root",
        lambda _username: str(workspace_root),
    )
    monkeypatch.setattr(
        factor_workspace_storage, "load_public_factor_source",
        lambda _factor_id: stored["value"],
    )
    monkeypatch.setattr(
        factor_workspace_storage, "save_public_factor_source",
        lambda _factor_id, value: stored.update(value=value),
    )
    monkeypatch.setattr(FactorWorkspaceRepository, "ensure", lambda _self: {})
    monkeypatch.setattr(
        FactorWorkspaceRepository, "current_branch", lambda _self: "upload",
    )
    monkeypatch.setattr(
        FactorWorkspaceRepository, "checkout", lambda _self, _mode: "upload",
    )
    monkeypatch.setattr(
        factor_workspace_sync, "get_factor_workspace_autosync_branch",
        lambda _username: "upload",
    )

    result = factor_workspace.push_factor_workspace(
        "root", allow_public_write=True, branch_mode="auto",
    )

    change = result["public_factor_changes"][0]
    assert change == {
        "factor_id": "PublicFactor",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "source_bytes": len(source.encode()),
    }
    assert "source_code" not in change


def test_factor_workspace_sync_can_checkout_force_branch(monkeypatch, tmp_path):
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(workspace_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (workspace_root / "README.md").write_text("hello\n", encoding="utf-8")
    manifest_dir = workspace_root / ".factor_workspace"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"username": "default$alice@1"}),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(workspace_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "checkout", "-b", "download"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "checkout", "main"], check=True, capture_output=True, text=True)

    factor_storage = factor_workspace_storage
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(
        factor_workspace_sync,
        "list_factor_sources",
        lambda source_kind: [],
    )

    from tools.data.sqlite.factor_source_workspace_settings import save_factor_source_workspace_settings
    save_factor_source_workspace_settings(
        "default$alice@1",
        git_enabled=True,
        git_repo_root=str(workspace_root),
    )

    result = factor_workspace.sync_factor_workspace("default$alice@1", branch_mode="force")

    current_branch = subprocess.check_output(["git", "-C", str(workspace_root), "branch", "--show-current"], text=True).strip()
    assert current_branch == "download"
    assert result["git_selected_branch"] == "download"


def test_factor_workspace_exports_only_singletons():
    source_paths = [
        Path("tools/factors/Parameters.py"),
        Path("tools/factors/expr/__init__.py"),
    ]
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        singleton_names: set[str] = set()
        class_names: set[str] = set()
        function_names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_names.add(node.name)
            elif isinstance(node, ast.FunctionDef):
                function_names.add(node.name)
            elif isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "__factor_workspace__" for target in node.targets):
                    value = node.value
                    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                        for item in value.elts:
                            assert isinstance(item, ast.Constant)
                            assert isinstance(item.value, str)
                            singleton_names.add(item.value)
        assert singleton_names
        assert singleton_names.isdisjoint(class_names)
        assert singleton_names.isdisjoint(function_names)


def test_author_sdk_is_explicit_resolvable_and_excludes_runtime_internals(tmp_path):
    workspace_root = tmp_path / "workspace"
    factor_workspace_construct._ensure_workspace_layout(str(workspace_root))
    factor_workspace_construct._sync_tools_sdk(str(workspace_root))

    generated = {
        path.relative_to(workspace_root).as_posix()
        for path in workspace_root.rglob("*.pyi")
    }
    assert generated == author_sdk_paths()

    forbidden = (
        "EvaluateContext",
        "FactorTester",
        "ProductDataView",
        "DataProvider",
        "@factor_workspace",
        "collect_factor_workspace",
        "FACTOR_WORKSPACE",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in workspace_root.rglob("*.pyi"))
    for name in forbidden:
        assert name not in combined
    assert "def rolling_mean(" in combined
    assert "def shift(" in combined
    assert "def tanh(" in combined
    assert "def where(" in combined

    for stub_path in workspace_root.rglob("*.pyi"):
        tree = ast.parse(stub_path.read_text(encoding="utf-8"), filename=str(stub_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith("tools"):
                continue
            module_path = workspace_root / Path(*node.module.split("."))
            assert module_path.with_suffix(".pyi").exists() or (module_path / "__init__.pyi").exists(), (
                f"{stub_path.relative_to(workspace_root)} imports missing {node.module}"
            )


def test_generated_factor_workspace_passes_real_pyright(tmp_path):
    workspace_root = tmp_path / "workspace"
    factor_workspace_construct._ensure_workspace_layout(str(workspace_root))
    factor_workspace_construct._sync_tools_sdk(str(workspace_root))
    (workspace_root / "custom_factors" / "ClientAlpha.py").write_text(
        "from tools.data.types import DataColumn\n"
        "from tools.factors import FactorFamily, where\n"
        "from tools.factors.FactorExpr import ColumnRef\n\n"
        "class ClientAlpha(FactorFamily):\n"
        "    @staticmethod\n"
        "    def factor_expr():\n"
        "        close = ColumnRef(DataColumn.CLOSE)\n"
        "        bounded = close.tanh()\n"
        "        method_form = bounded.where(close > 0, other=0.0)\n"
        "        return where(close <= 0, 0.0, method_form)\n",
        encoding="utf-8",
    )

    pyright = shutil.which("pyright")
    assert pyright is not None, "real Pyright is required for factor-workspace acceptance"
    completed = subprocess.run(
        [pyright, "--outputjson"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["summary"]["errorCount"] == 0, report
    assert report["generalDiagnostics"] == [], report


def test_workspace_hooks_target_stable_feat_root(monkeypatch, tmp_path):
    workspace_root = tmp_path / "factor-workspace"
    stable_root = tmp_path / "Codes"
    script_path = stable_root / "scripts" / "factor_workspace_autosync.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("raise SystemExit(0)\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(workspace_root)], check=True, capture_output=True, text=True)
    monkeypatch.setattr(factor_workspace_git, "get_feat_root", lambda: str(stable_root))

    installed = factor_workspace_git._install_git_autosync_hooks(str(workspace_root), "alice")

    assert len(installed) == 2
    hook = (workspace_root / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
    assert str(script_path) in hook
    assert ".workspace/fix/" not in hook
