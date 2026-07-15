from __future__ import annotations

import sqlite3

import settings as Settings
from tools.data.account_manage import (
    list_factor_research_runs,
    save_factor_research_run,
)
from tools.data.sqlite.account_manager import ensure_account_manager_sqlite_store


def test_factor_research_result_store_saves_metrics_and_bootstraps(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    ensure_account_manager_sqlite_store()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'account_factor_research_%'"
            ).fetchall()
        }
    assert tables == {"account_factor_research_runs", "account_factor_research_metrics"}

    saved = save_factor_research_run(
        "alice",
        ff_alias="MmVolWgtRet",
        factor_alias="MmVolWgtRet|P:CA|V:V|N:10d|RF:1d|$F:1d",
        factor_source="public",
        product_group="trend5_path",
        start_date="2024-01-02",
        end_date="2025-12-31",
        test_type="backtest",
        config={"fee_mode": "exact", "margin_mode": "off"},
        metrics={
            "a1_return": 0.58,
            "ls_return": 0.4369,
            "max_drawdown": -0.3732,
            "monotonic_score": 0.8,
            "tags": ["strict", "costed"],
        },
        report_path="/research/mmvolwgtret.md",
        artifact_path="/research/mmvolwgtret.json",
        note="regime candidate",
    )

    runs = list_factor_research_runs("alice", start_date="2025-01-01", end_date="2025-03-31")
    assert [run["run_id"] for run in runs] == [saved["run_id"]]
    run = runs[0]
    assert run["ff_alias"] == "MmVolWgtRet"
    assert run["product_group"] == "trend5_path"
    assert run["config"] == {"fee_mode": "exact", "margin_mode": "off"}
    assert run["metrics"]["ls_return"] == 0.4369
    assert run["metrics"]["tags"] == ["strict", "costed"]


def test_factor_research_result_query_filters_and_sorts(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    common = {
        "username": "alice",
        "ff_alias": "MmTrend",
        "test_type": "backtest",
        "product_group": "core8",
        "factor_source": "public",
        "config": {"fee_mode": "exact"},
    }
    save_factor_research_run(
        **common,
        factor_alias="MmTrend|N:10d|$F:1d",
        start_date="2024-04-01",
        end_date="2024-06-30",
        metrics={"ls_return": 0.28, "max_drawdown": -0.05, "ic_mean": 0.17},
    )
    save_factor_research_run(
        **common,
        factor_alias="MmTrend|N:20d|$F:1d",
        start_date="2025-01-01",
        end_date="2025-03-31",
        metrics={"ls_return": -0.04, "max_drawdown": -0.07, "ic_mean": 0.05},
    )
    save_factor_research_run(
        **common,
        factor_alias="MmTrend|N:60d|$F:1d",
        start_date="2025-10-01",
        end_date="2025-12-31",
        metrics={"ls_return": 0.13, "max_drawdown": -0.09, "ic_mean": 0.04},
    )

    runs = list_factor_research_runs(
        "alice",
        ff_alias="MmTrend",
        product_group="core8",
        start_date="2024-01-01",
        end_date="2025-12-31",
        min_metrics={"ls_return": 0.0},
        max_metrics={"max_drawdown": -0.04},
        order_by_metric="ls_return",
    )
    assert [run["factor_alias"] for run in runs] == [
        "MmTrend|N:10d|$F:1d",
        "MmTrend|N:60d|$F:1d",
    ]

    contained = list_factor_research_runs(
        "alice",
        start_date="2024-05-01",
        end_date="2024-05-31",
        overlap=False,
    )
    assert contained == []


def test_factor_research_result_upsert_replaces_metrics(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    first = save_factor_research_run(
        "alice",
        ff_alias="MmRet",
        factor_alias="MmRet|N:10d",
        product_group="core8",
        start_date="2024-01-02",
        end_date="2024-12-31",
        test_type="ic",
        config={"return_basis": "next_open_to_open_adjusted"},
        metrics={"ic_mean": 0.1, "ic_t_stat": 2.0},
    )
    second = save_factor_research_run(
        "alice",
        ff_alias="MmRet",
        factor_alias="MmRet|N:10d",
        product_group="core8",
        start_date="2024-01-02",
        end_date="2024-12-31",
        test_type="ic",
        config={"return_basis": "next_open_to_open_adjusted"},
        metrics={"ic_mean": 0.2},
    )

    assert first["run_id"] == second["run_id"]
    runs = list_factor_research_runs("alice", ff_alias="MmRet", test_type="ic")
    assert len(runs) == 1
    assert runs[0]["metrics"] == {"ic_mean": 0.2}
