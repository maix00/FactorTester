from __future__ import annotations

from pathlib import Path

from tools.cli.release.profile_lifecycle import ProfileLifecycle
from tools.cli.release.strategy_workspace import CanonicalStrategyRepoStore
from tools.cli.release.strategy_worktree import (
    apply_strategy_worktree_binding,
    plan_strategy_worktree_binding,
)
from tools.cli.release.strategy_worktree_audit import (
    rollback_strategy_worktree_binding,
    verify_strategy_worktree_binding,
)
from tools.cli.release.user_layout import default_user_strategy_library


def test_strategy_worktree_verify_and_rollback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "support"
    profile = ProfileLifecycle(root)
    profile.create(
        profile_id="demo",
        display_name="Demo",
        server_url="http://127.0.0.1:8141",
        principal_ref="alice",
    )
    canonical = default_user_strategy_library("alice")
    settings = CanonicalStrategyRepoStore(root).register(canonical, owner_ref="alice")
    assert settings["owner_ref"] == "alice"
    plan = plan_strategy_worktree_binding(root, "demo")
    receipt = apply_strategy_worktree_binding(root, plan)
    assert verify_strategy_worktree_binding(root, "demo")["valid"]
    result = rollback_strategy_worktree_binding(root, "demo")
    assert result["status"] == "rolled_back"
    assert not Path(receipt["worktree_path"]).exists()
