from __future__ import annotations

import settings as Settings
from tools.data.account_manage import load_factor_param_config, save_factor_param_config


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

