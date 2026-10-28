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


def test_all_frozen_public_factor_families_are_preserved():
    from server.modules.single_factor_test.planning import _strategy_execution_blocks
    ref='factor:v2:'+'a'*43
    specs=[dict(strategy_id=f'Group-{i}',strategy_kind='factor_template',template_kind='cross_sectional_group',
                parameters={'split_count':2,'group_index':i},factor_bindings={'signal':ref}) for i in (1,2)]
    result=_strategy_execution_blocks({'strategy_specs':specs},{'factors':[{'ref':ref,'alias':'mean'}]})
    assert [x['strategy_id'] for x in result]==['Group-1','Group-2']
    assert [x['parameters']['group_index'] for x in result]==[1,2]
    assert all(x['factor_roles']=={'signal':{'ref':ref,'alias':'mean'}} for x in result)
