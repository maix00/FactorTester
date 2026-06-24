import pytest

from server.modules.single_factor_test.group import (
    _event_group_detail,
    _event_group_ranking_detail,
    _event_group_snapshot,
)


def _execution() -> dict:
    return {
        "run_id": "run-1",
        "group_owner": [
            {
                "product_path_selection_id": "submission-1",
                "group_id": "group-1",
                "group_name": "第一组",
                "group_index": 0,
            },
            {
                "product_path_selection_id": "submission-1",
                "group_id": "group-2",
                "group_name": "第二组",
                "group_index": 1,
            },
        ],
        "serialized_execution": {
            "metrics": {"第一组": {"Total Return": 10.0}},
        },
        "engine_result": {
            "engine": "native",
            "portfolios": {
                "group-1": {
                    "equity_curve": {
                        "2024-01-01T00:00:00": 100.0,
                        "2024-01-02T00:00:00": 102.0,
                    },
                    "position_curve": {
                        "2024-01-01T00:00:00": {"A": 0.0},
                        "2024-01-02T00:00:00": {"A": 2.0},
                    },
                    "notional_curve": {
                        "2024-01-01T00:00:00": {"A": 0.0},
                        "2024-01-02T00:00:00": {"A": 200.0},
                    },
                    "margin_curve": {
                        "2024-01-01T00:00:00": {"A": 0.0},
                        "2024-01-02T00:00:00": {"A": 20.0},
                    },
                },
                "group-2": {
                    "equity_curve": {
                        "2024-01-01T00:00:00": 100.0,
                        "2024-01-02T00:00:00": 99.0,
                    },
                    "position_curve": {
                        "2024-01-01T00:00:00": {"B": 0.0},
                        "2024-01-02T00:00:00": {"B": 1.0},
                    },
                    "notional_curve": {
                        "2024-01-01T00:00:00": {"B": 0.0},
                        "2024-01-02T00:00:00": {"B": 50.0},
                    },
                    "margin_curve": {
                        "2024-01-01T00:00:00": {"B": 0.0},
                        "2024-01-02T00:00:00": {"B": 5.0},
                    },
                },
            },
            "target_trace": {
                "group-1": {
                    "2024-01-01T00:00:00": {"A": 1.0},
                    "2024-01-02T00:00:00": {"A": 0.5},
                },
                "group-2": {"2024-01-01T00:00:00": {"B": 1.0}},
            },
        },
    }


def test_event_snapshot_exposes_position_and_target_tabs() -> None:
    execution = _execution()

    result = _event_group_snapshot(
        execution, "submission-1", 1_704_153_600_000
    )

    assert result["success"] is True
    assert result["event_type"] == "FILL"
    assert len(result["event_cursors"]) == 5
    assert [matrix["key"] for matrix in result["matrices"]] == [
        "positions_contracts", "positions_products",
        "targets_contracts", "targets_products",
    ]
    assert result["matrices"][0]["rows"][0]["name"] == "总资产"
    assert result["matrices"][0]["rows"][1]["name"] == "现金"
    assert result["matrices"][0]["columns"][0]["events"] == [{"type": "FILL", "label": "成交后"}]
    assert result["matrices"][0]["cells"][2][0]["quantity"] == 2.0
    assert result["matrices"][0]["cells"][2][0]["status"] == "entering"
    assert result["matrices"][0]["cells"][2][0]["change_direction"] == "increase"
    assert result["matrices"][0]["cells"][2][0]["amount"] == 200.0
    assert result["matrices"][0]["cells"][2][0]["margin_amount"] == 20.0
    assert result["matrices"][0]["cells"][2][0]["delta_margin_amount"] == 20.0
    assert result["matrices"][2]["cells"][0][0]["selected"] is True
    assert result["default_matrix_key"] == "positions_contracts"

    fill = _event_group_snapshot(
        execution,
        "submission-1",
        1_704_153_600_000,
        result["event_cursors"][-2],
    )
    assert fill["event_type"] == "FILL"

    target = _event_group_snapshot(
        execution,
        "submission-1",
        1_704_153_600_000,
        result["event_cursors"][-3],
    )
    assert target["event_type"] == "TARGET"
    assert target["matrices"][0]["columns"][0]["events"] == [{"type": "TARGET", "label": "目标更新"}]
    assert target["matrices"][0]["cells"][2][0]["quantity"] == 0.0
    assert target["matrices"][2]["cells"][0][0]["selected"] is True


def test_event_detail_uses_ledger_positions_and_equity() -> None:
    detail = _event_group_detail(_execution(), "submission-1", 0)

    assert detail["summary"]["Total Return"] == 10.0
    assert detail["entry_frequency"][0]["product"]["name"] == "A"
    assert detail["return_series"][-1]["return"] == pytest.approx(0.02)


def test_event_ranking_aligns_framework_equity_curves() -> None:
    detail = _event_group_ranking_detail(_execution(), "submission-1")

    assert detail["comparable_period_count"] == 2
    assert detail["top_bottom"]["mean_spread"] == pytest.approx(0.015)
    assert detail["top_bottom"]["positive_ratio"] == 0.5
