from server.modules.single_factor_test.planning import _strategy_execution_block


def test_threshold_family_is_frozen_into_trade_research_plan():
    data = {
        "strategy_specs": [{
            "strategy_kind": "threshold",
            "parameters": {"entry": 0.5, "exit": 0.5},
            "data": {
                "factor": "momentum",
                "products": ["AL.SHF"],
            },
        }],
    }
    shared = {"factors": [{"alias": "momentum", "ref": "factor:v2:abc"}]}
    block = _strategy_execution_block(data, shared)
    assert block == {
        "kind": "threshold",
        "family_id": "threshold",
        "parameters": {
            "entry_threshold": 0.5,
            "exit_threshold": 0.5,
            "side_mode": "long_short",
        },
        "factor_roles": {
            "factor": {"alias": "momentum", "ref": "factor:v2:abc"},
        },
        "products": ["AL.SHF"],
    }


def test_group_family_is_frozen_into_trade_research_plan():
    data = {
        "strategy_specs": [{
            "strategy_kind": "cross_sectional_group",
            "parameters": {"split_count": 5, "group_index": 1},
            "data": {"factor": "momentum", "products": ["AL.SHF"]},
        }],
    }
    shared = {"factors": [{"alias": "momentum", "ref": "factor:v2:abc"}]}
    block = _strategy_execution_block(data, shared)
    assert block["kind"] == "cross_sectional_group"
    assert block["parameters"] == {"split_count": 5, "group_index": 1}
