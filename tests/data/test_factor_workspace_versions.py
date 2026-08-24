from __future__ import annotations

import subprocess

from tools.data.factor_workspace import versions


def _git(root, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(root, message: str) -> str:
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message],
        check=True,
        capture_output=True,
        text=True,
    )
    return _git(root, "rev-parse", "HEAD")


def test_factor_source_versions_only_include_source_changes(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    (root / "custom_factors").mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "upload", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(root, "config", "user.name", "FactorTester")
    _git(root, "config", "user.email", "factor@example.test")

    first_source = "class Momentum:\n    expr = 'close'\n"
    second_source = "class Momentum:\n    expr = 'close - open'\n"
    source_path = root / "custom_factors" / "Momentum.py"
    source_path.write_text(first_source, encoding="utf-8")
    first_commit = _commit(root, "factor: create Momentum")

    (root / "README.md").write_text("unrelated\n", encoding="utf-8")
    _commit(root, "docs: update workspace")

    source_path.write_text(second_source, encoding="utf-8")
    second_commit = _commit(root, "factor: update Momentum")

    monkeypatch.setattr(versions, "factor_source_root", lambda _username: str(root))
    monkeypatch.setattr(versions, "WORKSPACE_ROOTS_DIR", str(tmp_path / "none"))
    result = versions.list_factor_source_versions(
        source_kind="custom",
        owner_username="alice",
        factor_id="Momentum",
        current_source=second_source,
    )

    assert result["available"] is True
    assert [item["commit"] for item in result["versions"]] == [
        second_commit, first_commit,
    ]
    assert result["current"]["commit"] == second_commit
    assert result["current"]["is_current"] is True

    historical = versions.load_factor_source_version(
        source_kind="custom",
        owner_username="alice",
        factor_id="Momentum",
        current_source=second_source,
        commit=first_commit,
    )
    assert historical["source_code"] == first_source
    assert historical["is_current"] is False
