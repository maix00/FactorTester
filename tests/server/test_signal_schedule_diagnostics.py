from __future__ import annotations

import pandas as pd
from types import SimpleNamespace
from unittest.mock import sentinel

from server.modules.single_factor_test.signal_schedule_diagnostics import (
    policy_for_factor,
    summarize_signal_schedule,
)
from server.modules.single_factor_test.evaluation import FactorEvaluation


def test_factor_evaluation_run_spec_keeps_flattened_execution_window(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.modules.single_factor_test.evaluation.selection_from_request",
        lambda data, page_uuid: sentinel.selection,
    )

    evaluation = FactorEvaluation.from_run_spec({
        "_owner": "owner",
        "run_id": "run-1",
        "factor_family_alias": "Family",
        "factor_alias": "Factor|$F:1m",
        "start_date": "2024-01-02",
        "end_date": "2025-05-30",
        "start_time": "09:00",
        "end_time": "15:00",
        "time_precision": "exact",
        "timezone": "Asia/Shanghai",
    })

    start, end = evaluation._run_window_datetimes()

    assert evaluation.selection is sentinel.selection
    assert start is not None and start.ts == pd.Timestamp(
        "2024-01-02 09:00", tz="Asia/Shanghai",
    )
    assert end is not None and end.ts == pd.Timestamp(
        "2025-05-30 15:00", tz="Asia/Shanghai",
    )


def test_factor_evaluation_rejects_missing_or_reversed_run_window(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.modules.single_factor_test.evaluation.selection_from_request",
        lambda data, page_uuid: sentinel.selection,
    )
    base = {
        "_owner": "owner",
        "run_id": "run-1",
        "factor_family_alias": "Family",
        "factor_alias": "Factor|$F:1m",
    }

    missing = FactorEvaluation.from_run_spec(base)
    reversed_window = FactorEvaluation.from_run_spec({
        **base,
        "start_date": "2025-06-01",
        "end_date": "2025-05-30",
    })

    import pytest

    with pytest.raises(ValueError, match="运行时间范围缺失"):
        missing._run_window_datetimes()
    with pytest.raises(ValueError, match="start_date 必须早于或等于 end_date"):
        reversed_window._run_window_datetimes()


def test_schedule_summary_is_compact_and_does_not_claim_incremental_equivalence() -> None:
    raw = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0],
        index=pd.to_datetime([
            "2026-01-05 14:57:00",
            "2026-01-05 15:00:00",
            "2026-01-05 21:00:00",
            "2026-01-05 21:03:00",
            "2026-01-05 21:06:00",
        ]),
    )
    scheduled = raw.iloc[[1, 3, 4]]

    summary = summarize_signal_schedule(
        raw,
        scheduled,
        policy={
            "signal_frequency": "3m",
            "basepoint": "last",
            "daily_basepoint": None,
            "end_session_skip": False,
            "end_session_gap": "3h",
        },
    )

    assert summary["policy"]["end_session_skip"] is False
    assert summary["raw_observation_count"] == 5
    assert summary["scheduled_observation_count"] == 3
    assert len(summary["scheduled_timestamp_hash"]) == 64
    assert len(summary["scheduled_value_hash"]) == 64
    assert summary["boundary_basis"] == "elapsed_gap_only"
    assert summary["trading_day_mapping_status"] == "not_bound"
    assert summary["incremental_equivalence_status"] == "not_evaluated"
    assert summary["session_gap_samples"] == [{
        "previous_timestamp": "2026-01-05T15:00:00",
        "next_timestamp": "2026-01-05T21:00:00",
        "gap_seconds": 21600.0,
    }]
    assert "timestamps" not in summary
    assert "values" not in summary


def test_schedule_value_changes_do_not_change_timestamp_identity() -> None:
    index = pd.to_datetime(["2026-01-05 09:03", "2026-01-05 09:06"])
    raw = pd.Series([1.0, 2.0], index=index)
    before = summarize_signal_schedule(raw, raw, policy={})
    after = summarize_signal_schedule(raw, raw * 2, policy={})

    assert before["scheduled_timestamp_hash"] == after["scheduled_timestamp_hash"]
    assert before["scheduled_value_hash"] != after["scheduled_value_hash"]


def test_policy_comes_from_bound_family_without_changing_skip_semantics() -> None:
    factor = SimpleNamespace(
        signal_freq="3m",
        family=SimpleNamespace(
            basepoint="last",
            daily_basepoint=None,
            end_session_skip=False,
            end_session_gap=pd.Timedelta("3h"),
        ),
    )

    assert policy_for_factor(factor) == {
        "signal_frequency": "3m",
        "basepoint": "last",
        "daily_basepoint": None,
        "end_session_skip": False,
        "end_session_gap": "0 days 03:00:00",
    }


def test_factor_evaluation_projects_raw_and_scheduled_views_without_database_reads() -> None:
    index = pd.to_datetime([
        "2026-01-05 14:57",
        "2026-01-05 15:00",
        "2026-01-05 21:00",
        "2026-01-05 21:03",
    ])
    raw = pd.DataFrame({"CU": [1.0, 2.0, 3.0, 4.0]}, index=index)
    scheduled = raw.iloc[[1, 3]]
    factor = SimpleNamespace(
        signal_freq="3m",
        family=SimpleNamespace(
            basepoint="last",
            daily_basepoint=None,
            end_session_skip=False,
            end_session_gap=pd.Timedelta("3h"),
        ),
    )
    tester = SimpleNamespace(start_date=None, end_date=None)

    summary = FactorEvaluation._signal_schedule_payload(
        raw,
        scheduled,
        "CU",
        factor,
        tester,
        None,
        None,
    )

    assert summary is not None
    assert summary["raw_observation_count"] == 4
    assert summary["scheduled_observation_count"] == 2
    assert summary["policy"]["end_session_skip"] is False
    assert summary["incremental_equivalence_status"] == "not_evaluated"
