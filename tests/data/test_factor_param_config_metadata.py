from __future__ import annotations

import settings as Settings
from tools.data.account_manage import (
    delete_factor_family_configs,
    load_factor_param_config,
    save_factor_param_config,
)


def test_factor_param_config_preserves_research_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    saved = save_factor_param_config(
        "alice",
        "MmRet",
        [{"N": "10d", "$F": "1d"}],
        "research-core8",
        metadata={
            "note": "sample-in good, oos weak",
            "research_report": "/tmp/report.md",
            "product_group_paths": ["Product/Futures/CNFutures/日夜盘/日盘/_products/AP.CZC"],
        },
    )

    assert saved["metadata"]["note"] == "sample-in good, oos weak"
    loaded = load_factor_param_config("alice", "MmRet", "research-core8")
    assert loaded is not None
    assert loaded["metadata"] == saved["metadata"]


def test_delete_factor_family_configs_cascades_rows_across_scopes(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    save_factor_param_config("alice", "MmRet", [{"N": "10d"}], "default")
    save_factor_param_config("alice", "MmRet", [{"N": "20d"}, {"N": "30d"}], "night")
    save_factor_param_config("alice", "MmOther", [{"N": "5d"}], "default")
    save_factor_param_config("bob", "MmRet", [{"N": "60d"}], "default")

    deleted = delete_factor_family_configs("MmRet", username="alice")

    assert deleted == {"config_count": 2, "factor_count": 3}
    assert load_factor_param_config("alice", "MmRet", "default") is None
    assert load_factor_param_config("alice", "MmRet", "night") is None
    assert load_factor_param_config("alice", "MmOther", "default") is not None
    assert load_factor_param_config("bob", "MmRet", "default") is not None
