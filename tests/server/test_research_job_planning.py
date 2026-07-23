from __future__ import annotations

from dataclasses import dataclass

import pytest

from server.modules.single_factor_test.planning import (
    build_execution_plan,
    verify_execution_plan,
)


@dataclass(frozen=True)
class _Named:
    name: str


class _Selection:
    selection_id = "core"
    products = (_Named("AP.CZCE"),)


def test_backtest_planner_freezes_term_structure_and_market_data(monkeypatch) -> None:
    prepared = {
        "start_dt": "2025-01-02",
        "end_dt": "2025-02-14",
        "resolved_settings_by_alias": {
            "A1": {"product_path_selection": _Selection(), "factor": object()},
        },
    }
    monkeypatch.setattr(
        (
            "tools.factors.tester_calc.single_factor_test.group.research_run."
            "prepare_group_run_spec"
        ),
        lambda data: prepared,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.engine.engine_mode_for", lambda config: "auto"
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_frequency_for_strategy",
        lambda config, products: _Named("DAY1"),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_data_source_for_strategy",
        lambda config: (),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._factor_required_columns",
        lambda factor: ("open", "close"),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_available_freqs",
        lambda product: [_Named("DAY1")],
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_frequency",
        lambda product, available, required: required,
    )
    source = _Named("LocalCNFutures")
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_source",
        lambda product, frequency, required: source,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.term_structure._expand_product_contracts",
        lambda product, **kwargs: (
            [_Named("AP501.CZCE")],
            [{"contract_product": "AP501.CZCE", "is_identity": False}],
        ),
    )

    plan = build_execution_plan("backtest", {"_owner": "alice"})

    assert plan["resolved"]["strategies"]["A1"]["contracts"] == ["AP501.CZCE"]
    assert plan["resolved"]["data_requirements"] == [
        {
            "product": "AP.CZCE",
            "frequency": "DAY1",
            "data_source": "LocalCNFutures",
            "factor_columns": ["close", "open"],
            "start": "2025-01-02T00:00:00",
            "end": "2025-02-14T00:00:00",
        },
        {
            "product": "AP501.CZCE",
            "frequency": "DAY1",
            "data_source": "LocalCNFutures",
            "factor_columns": ["close", "open"],
            "start": "2025-01-02T00:00:00",
            "end": "2025-02-14T00:00:00",
        },
    ]
    assert plan["notices"][0]["code"] == "term_structure_lifecycle_authority_missing"

    prepared["end_dt"] = "2025-03-01"
    with pytest.raises(RuntimeError, match="changed after planning"):
        verify_execution_plan("backtest", {
            "_owner": "alice",
            "execution_plan": plan,
        })


def test_backtest_planner_merges_compatible_strategy_factor_columns(monkeypatch) -> None:
    first_factor = object()
    second_factor = object()
    prepared = {
        "start_dt": "2025-01-02",
        "end_dt": "2025-02-14",
        "resolved_settings_by_alias": {
            "A1": {"product_path_selection": _Selection(), "factor": first_factor},
            "B1": {"product_path_selection": _Selection(), "factor": second_factor},
        },
    }
    monkeypatch.setattr(
        (
            "tools.factors.tester_calc.single_factor_test.group.research_run."
            "prepare_group_run_spec"
        ),
        lambda data: prepared,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.engine.engine_mode_for", lambda config: "auto"
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_frequency_for_strategy",
        lambda config, products: _Named("DAY1"),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_data_source_for_strategy",
        lambda config: (),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._factor_required_columns",
        lambda factor: (
            ("open", "close") if factor is first_factor else ("close", "volume")
        ),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_available_freqs",
        lambda product: [_Named("DAY1")],
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_frequency",
        lambda product, available, required: required,
    )
    source = _Named("LocalCNFutures")
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_source",
        lambda product, frequency, required: source,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.term_structure._expand_product_contracts",
        lambda product, **kwargs: ([], []),
    )

    plan = build_execution_plan("backtest", {"_owner": "alice"})

    assert plan["resolved"]["data_requirements"] == [
        {
            "product": "AP.CZCE",
            "frequency": "DAY1",
            "data_source": "LocalCNFutures",
            "factor_columns": ["close", "open", "volume"],
            "start": "2025-01-02T00:00:00",
            "end": "2025-02-14T00:00:00",
        },
    ]


def test_backtest_planner_preserves_distinct_frequency_requirements(monkeypatch) -> None:
    prepared = {
        "start_dt": "2025-01-02",
        "end_dt": "2025-02-14",
        "resolved_settings_by_alias": {
            "daily": {
                "product_path_selection": _Selection(),
                "factor": _Named("daily"),
            },
            "minute": {
                "product_path_selection": _Selection(),
                "factor": _Named("minute"),
            },
        },
    }
    monkeypatch.setattr(
        (
            "tools.factors.tester_calc.single_factor_test.group.research_run."
            "prepare_group_run_spec"
        ),
        lambda data: prepared,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.engine.engine_mode_for", lambda config: "auto"
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_frequency_for_strategy",
        lambda config, products: _Named(
            "DAY1" if config["factor"].name == "daily" else "MIN1"
        ),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._required_data_source_for_strategy",
        lambda config: (),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._factor_required_columns",
        lambda factor: ("close",),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_available_freqs",
        lambda product: [_Named("DAY1"), _Named("MIN1")],
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_frequency",
        lambda product, available, required: required,
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._select_required_product_source",
        lambda product, frequency, required: _Named(f"Local{frequency.name}"),
    )
    monkeypatch.setattr(
        "tools.testers.backtest.modules.term_structure._expand_product_contracts",
        lambda product, **kwargs: ([], []),
    )

    plan = build_execution_plan("backtest", {"_owner": "alice"})

    assert [
        (row["frequency"], row["data_source"])
        for row in plan["resolved"]["data_requirements"]
    ] == [("DAY1", "LocalDAY1"), ("MIN1", "LocalMIN1")]
