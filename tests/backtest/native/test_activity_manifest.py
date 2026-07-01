from __future__ import annotations

from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.scheduler import (
    FlowRegistry,
    activity_manifest_from_groups,
    sort_and_validate,
)
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES


def _registry() -> FlowRegistry:
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
        for override in getattr(cls, "overrides", ()):
            registry.register_override(override)
    return registry


def _event_labels(manifest: list[dict]) -> list[str]:
    phase = next(item for item in manifest if item["key"] == "event_replay")
    return [flow["flow_label"] for flow in phase["flows"]]


def test_registered_native_flows_all_have_chinese_descriptions():
    missing = []
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            if not flow.description:
                missing.append(f"{cls.__name__}.{flow.name}")

    assert missing == []


def test_activity_manifest_hides_long_short_flow_when_no_long_short_strategy():
    account = BacktestRunState()
    apply_strategy_configs(account, {
        "A1": {
            "factor_mode": "precomputed",
            "split_count": 5,
            "group_index": 0,
        },
    })

    manifest = activity_manifest_from_groups(sort_and_validate(_registry().resolve()), account)

    assert "合成Long-Short目标" not in _event_labels(manifest)


def test_activity_manifest_hides_live_signal_flows_for_precomputed_factor():
    account = BacktestRunState()
    apply_strategy_configs(account, {
        "A1": {
            "factor_mode": "precomputed",
            "split_count": 5,
            "group_index": 0,
        },
    })

    manifest = activity_manifest_from_groups(sort_and_validate(_registry().resolve()), account)

    pre = next(item for item in manifest if item["key"] == "pre_replay")
    pre_labels = [flow["flow_label"] for flow in pre["flows"]]
    event_labels = _event_labels(manifest)
    assert "登记实时因子事件" not in pre_labels
    assert "登记 Bar 事件" not in pre_labels
    assert "读取实时因子信号" not in event_labels
    assert "读取预计算信号" in event_labels


def test_activity_manifest_shows_long_short_flow_only_for_long_short_strategy():
    account = BacktestRunState()
    apply_strategy_configs(account, {
        "A1": {
            "factor_mode": "precomputed",
            "split_count": 5,
            "group_index": 0,
        },
        "LS A1/A5": {
            "strategy_kind": "long_short",
            "factor_mode": "precomputed",
            "split_count": 5,
            "group_index": 0,
            "long_leg_strategy_ids": [{"strategy_id": "A1"}],
            "short_leg_strategy_ids": [{"strategy_id": "A5"}],
        },
    })

    manifest = activity_manifest_from_groups(sort_and_validate(_registry().resolve()), account)

    assert "合成Long-Short目标" in _event_labels(manifest)


def test_activity_manifest_dedupes_logical_live_signal_flow():
    account = BacktestRunState()
    apply_strategy_configs(account, {
        "A1": {
            "factor_mode": "incremental",
            "split_count": 5,
            "group_index": 0,
        },
    })

    manifest = activity_manifest_from_groups(sort_and_validate(_registry().resolve()), account)

    labels = _event_labels(manifest)
    assert labels.count("读取实时因子信号") == 1
