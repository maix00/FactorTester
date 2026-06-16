from __future__ import annotations

import json
import importlib.util
import subprocess
from pathlib import Path

import pytest

from server.services import factor_workspace


def _load_storage_module():
    storage_path = Path(__file__).resolve().parents[2] / "server" / "modules" / "custom_factors" / "storage.py"
    spec = importlib.util.spec_from_file_location("test_factor_workspace_storage", storage_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factor_workspace_build_refreshes_and_prunes_stale_files(monkeypatch, tmp_path):
    workspace_root = tmp_path / "factor-root"
    custom_dir = workspace_root / "custom_factors"
    public_dir = workspace_root / "public_factors"
    custom_dir.mkdir(parents=True)
    public_dir.mkdir(parents=True)

    stale_custom = custom_dir / "OldFactor.py"
    stale_public = public_dir / "OldPublic.py"
    stale_root = workspace_root / "stale.txt"
    stale_custom.write_text("class OldFactor(FactorFamily):\n    pass\n", encoding="utf-8")
    stale_public.write_text("class OldPublic(FactorFamily):\n    pass\n", encoding="utf-8")
    stale_root.write_text("old\n", encoding="utf-8")

    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_workspace, "_storage", lambda: factor_storage)
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(
        factor_workspace,
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
    monkeypatch.setattr(factor_workspace, "scan_tool_files", lambda tools_dir, include_symbols=False: [
        {"path": "base/User.py", "name": "base / User.py", "desc": "", "symbols": []}
    ])
    monkeypatch.setattr(factor_workspace, "_ensure_git_workspace", lambda root, username: {
        "git_enabled": True,
        "git_repo_root": str(workspace_root),
        "git_current_branch": "main",
        "git_auto_sync_branch": "main",
        "git_force_sync_branch": "release",
        "git_branches": ["main", "release"],
    })

    result = factor_workspace.build_factor_workspace("default$alice@1")

    assert result["custom_factor_count"] == 1
    assert result["public_factor_count"] == 1
    assert not stale_custom.exists()
    assert not stale_public.exists()
    assert not stale_root.exists()
    assert (custom_dir / "FreshFactor.py").read_text(encoding="utf-8") == "class FreshFactor(FactorFamily):\n    pass\n"
    assert (public_dir / "PublicFactor.py").read_text(encoding="utf-8") == "class PublicFactor(FactorFamily):\n    pass\n"
    assert (workspace_root / ".factor_workspace" / "manifest.json").exists()
    assert (workspace_root / "tools_index.json").exists()
    assert (workspace_root / "Settings.pyi").exists()
    factor_family_stub = (workspace_root / "tools" / "factors" / "FactorFamily.pyi").read_text(encoding="utf-8")
    parameters_stub = (workspace_root / "tools" / "factors" / "Parameters.pyi").read_text(encoding="utf-8")
    factor_expr_wrapper_stub = (workspace_root / "tools" / "factors" / "FactorExpr.pyi").read_text(encoding="utf-8")
    expr_pkg_stub = (workspace_root / "tools" / "factors" / "expr" / "__init__.pyi").read_text(encoding="utf-8")
    tools_stub = (workspace_root / "tools" / "__init__.pyi").read_text(encoding="utf-8")
    parameters_pkg_stub = (workspace_root / "tools" / "parameters" / "__init__.pyi").read_text(encoding="utf-8")
    factors_pkg_stub = (workspace_root / "tools" / "factors" / "__init__.pyi").read_text(encoding="utf-8")
    assert "class FactorFamily" in factor_family_stub
    assert "def get_factor" in factor_family_stub
    assert not (workspace_root / "tools" / "factors" / "FactorFamily.py").exists()
    assert "ReturnFreqParam" in parameters_stub
    assert "FactorFreqParam" in parameters_stub
    assert "StartCalcPointParam" in parameters_stub
    assert "# 因子系统专用参数模块" in parameters_stub
    assert "WindowParam" in parameters_pkg_stub
    assert "FactorTester" not in factors_pkg_stub
    assert "EvaluateContext" not in factors_pkg_stub
    assert "visual_groups" not in factors_pkg_stub
    assert "CLOSE" in factor_expr_wrapper_stub
    assert "SMALL_VAL" in factor_expr_wrapper_stub
    assert "CLOSE" in expr_pkg_stub
    assert "SMALL_VAL" in expr_pkg_stub
    assert "ProductDataView" in tools_stub
    assert (workspace_root / "tools" / "factors" / "Parameters.py").exists() is False
    assert (workspace_root / "tools" / "__init__.pyi").exists()
    assert (workspace_root / "tools" / "factors" / "__init__.pyi").exists()
    assert (workspace_root / "tools" / "factors" / "FactorTester.pyi").exists() is False
    assert (workspace_root / "tools" / "data" / "types" / "DataIndex.pyi").exists() is False
    assert not (workspace_root / "tools" / "backtest").exists()
    assert result["git"]["git_enabled"] is True
    assert result["git"]["git_auto_sync_branch"] == "main"
    assert result["git"]["git_force_sync_branch"] == "release"
    settings = json.loads((workspace_root / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.analysis.extraPaths"] == ["${workspaceFolder}"]
    assert settings["python.analysis.autoSearchPaths"] is True


def test_factor_workspace_push_blocks_public_changes_for_non_admin(monkeypatch, tmp_path):
    workspace_root = tmp_path / "factor-root"
    public_dir = workspace_root / "public_factors"
    public_dir.mkdir(parents=True)
    (public_dir / "PublicFactor.py").write_text("class PublicFactor(FactorFamily):\n    pass\n", encoding="utf-8")

    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_workspace, "_storage", lambda: factor_storage)
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(factor_storage, "load_public_factor_source", lambda factor_id: "class PublicFactor(FactorFamily):\n    pass\n# db version\n")

    with pytest.raises(PermissionError):
        factor_workspace.push_factor_workspace("default$alice@1", allow_public_write=False)


def test_factor_workspace_sync_can_checkout_force_branch(monkeypatch, tmp_path):
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(workspace_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (workspace_root / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "checkout", "-b", "release"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(workspace_root), "checkout", "main"], check=True, capture_output=True, text=True)

    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_workspace, "_storage", lambda: factor_storage)
    monkeypatch.setattr(factor_storage, "factor_source_root", lambda username: str(workspace_root))
    monkeypatch.setattr(
        factor_workspace,
        "list_factor_sources",
        lambda source_kind: [],
    )
    monkeypatch.setattr(factor_workspace, "scan_tool_files", lambda tools_dir, include_symbols=False: [])

    from server.services.sqlite.factor_source_workspace_settings import save_factor_source_workspace_settings
    save_factor_source_workspace_settings(
        "default$alice@1",
        git_enabled=True,
        git_repo_root=str(workspace_root),
        auto_sync_branch="main",
        force_sync_branch="release",
    )

    result = factor_workspace.sync_factor_workspace("default$alice@1", branch_mode="force")

    current_branch = subprocess.check_output(["git", "-C", str(workspace_root), "branch", "--show-current"], text=True).strip()
    assert current_branch == "release"
    assert result["git_selected_branch"] == "release"
