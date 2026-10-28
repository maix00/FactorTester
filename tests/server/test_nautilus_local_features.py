from server.services.nautilus_bridge.config import compile_frozen_execution_plan
from tests.server.test_nautilus_bridge_config import _minimal_frozen


def test_local_feature_manifest_marks_unwired_capabilities():
    plan = compile_frozen_execution_plan(
        _minimal_frozen(), feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
    )
    features = plan.manifest()["local_nautilus_features"]
    assert features["next_bar_open_market"] == "supported"
    assert features["position_cost_basis_by_instrument"] == "supported"
    assert features["fund_transfers"].startswith("blocked")
    assert features["dynamic_instrument_updates"].startswith("adapter_only")
    assert features["trading_day_inventory_roll"].startswith("adapter_only")


def test_unwired_local_features_are_blocked_not_ignored():
    import pytest
    from server.services.nautilus_bridge.config import UnsupportedExecutionConfig, compile_frozen_execution_plan
    from tests.server.test_nautilus_bridge_config import _minimal_frozen

    for key in ("fund_transfers", "instrument_updates", "trading_day_inventory_roll"):
        with pytest.raises(UnsupportedExecutionConfig) as error:
            compile_frozen_execution_plan(
                _minimal_frozen(**{key: [{"x": 1}]}), feed_kind="bar",
                adapter_capabilities=frozenset({
                    "native_bar_open_market_orders", "daily_settlement",
                }),
            )
        assert error.value.field == key
