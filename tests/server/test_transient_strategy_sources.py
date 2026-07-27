from __future__ import annotations

from pathlib import Path

import pytest

from server.services import transient_strategy_sources as sources


def test_strategy_scope_is_source_free_and_owner_bound(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    scope = sources.create_scope(
        owner="alice",
        entries=[{
            "path": "strategies/demo/actor.py",
            "source_code": "class Demo:\n    pass\n",
        }],
    )
    assert scope["mode"] == "transient_run_source"
    assert "source_code" not in scope["files"][0]
    assert sources.load_source(scope["scope_id"], "strategies/demo/actor.py", owner="alice")
    assert sources.load_source(scope["scope_id"], "strategies/demo/actor.py", owner="bob") is None
    assert sources.cleanup_scope(scope["scope_id"])


def test_strategy_scope_rejects_factor_or_escape_paths() -> None:
    with pytest.raises(ValueError, match="strategies"):
        sources.validate_entries([{"path": "custom_factors/A.py", "source_code": "x"}])
    with pytest.raises(ValueError, match="strategies"):
        sources.validate_entries([{"path": "strategies/../secret.py", "source_code": "x"}])


def test_strategy_scope_requires_owner_and_reports_corruption(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    with pytest.raises(ValueError, match="owner"):
        sources.create_scope(owner="", entries=[{"path": "strategies/demo.py", "source_code": "x"}])
    scope = sources.create_scope(
        owner="alice",
        entries=[{"path": "strategies/demo/actor.py", "source_code": "print(1)"}],
    )
    assert sources.scope_status(scope["scope_id"]) == "available"
    target = tmp_path / "transient_strategy_sources" / scope["scope_id"] / "strategies/demo/actor.py"
    target.write_text("print(2)", encoding="utf-8")
    assert sources.scope_status(scope["scope_id"]) == "corrupt"
