from __future__ import annotations

import importlib.util
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
    stale_custom.write_text("class OldFactor(FactorFamily):\n    pass\n", encoding="utf-8")
    stale_public.write_text("class OldPublic(FactorFamily):\n    pass\n", encoding="utf-8")

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

    result = factor_workspace.build_factor_workspace("default$alice@1")

    assert result["custom_factor_count"] == 1
    assert result["public_factor_count"] == 1
    assert not stale_custom.exists()
    assert not stale_public.exists()
    assert (custom_dir / "FreshFactor.py").read_text(encoding="utf-8") == "class FreshFactor(FactorFamily):\n    pass\n"
    assert (public_dir / "PublicFactor.py").read_text(encoding="utf-8") == "class PublicFactor(FactorFamily):\n    pass\n"
    assert (workspace_root / ".factor_workspace" / "manifest.json").exists()
    assert (workspace_root / "tools_index.json").exists()


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
