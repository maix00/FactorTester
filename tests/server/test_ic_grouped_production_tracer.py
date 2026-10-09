from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest


def test_grouped_ic_run_spec_compiles_typed_groups_with_provenance():
    from tools.testers.ic_test.configuration.grouped import compile_ic_grouped_configuration

    frozen = {
        "configuration_groups": [{
            "config_group_id": "cg-alpha",
            "product_scope_ref": "product-scope:core8",
            "factor_ref": "factor:v2:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "horizon": {"mode": "physical_frequency", "frequency": "MIN5"},
            "entry_delay_bars": 1,
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
            "warmup_mode": "fixed",
            "warmup_window": "10d",
        }],
    }
    compiled = compile_ic_grouped_configuration(frozen, factor_frequencies={"factor:v2:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": "MIN5"})
    assert compiled["groups"][0]["config_group_id"] == "cg-alpha"
    assert compiled["groups"][0]["product_scope_ref"] == "product-scope:core8"
    assert compiled["groups"][0]["core_ref"].startswith("ic-core-request:v1:")
    assert compiled["provenance"]["config_group_id"] == "cg-alpha"
    core_ref = compiled["groups"][0]["core_ref"]
    assert compiled["group_execution_settings"][core_ref] == {
        "warmup_mode": "fixed", "warmup_window": "10d",
    }
    assert len(compiled["compiled_config_hash"]) == 64


def test_compiled_group_hash_is_order_independent():
    from tools.testers.ic_test.configuration.grouped import compile_ic_grouped_configuration

    base = {
        "configuration_groups": [
            {"config_group_id": "b", "product_scope_ref": "p:b", "factor_ref": "factor:v2:n6065XCpFt8yYTj9iGHCdrs7ZSKvjHRedB33HumEd5w", "horizon": "MIN5", "entry_delay_bars": 0, "methods": ["rank"], "return_price_basis": "next"},
            {"config_group_id": "a", "product_scope_ref": "p:a", "factor_ref": "factor:v2:Wroo2lwG5LBiImordFdeS5OTS_IAfxFmLCZUzPgJZe4", "horizon": "MIN5", "entry_delay_bars": 0, "methods": ["rank"], "return_price_basis": "next"},
        ]
    }
    with pytest.raises(ValueError, match="exactly one"):
        compile_ic_grouped_configuration(base, factor_frequencies={"factor:v2:Wroo2lwG5LBiImordFdeS5OTS_IAfxFmLCZUzPgJZe4": "MIN5", "factor:v2:n6065XCpFt8yYTj9iGHCdrs7ZSKvjHRedB33HumEd5w": "MIN5"})


def test_run_ic_invokes_worker_once_with_frozen_grouped_execution_view(monkeypatch):
    from server.modules.single_factor_test import ic, process_runners
    from tools.factors.formula_identity import freeze_factor_identity
    from tools.testers.ic_test.configuration.grouped import compile_ic_grouped_configuration

    factor = freeze_factor_identity(
        owner_ref="public",
        family_alias="MmRet",
        factor_alias="MmRet|P:CA|N:10d|$F:5m",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={},
    )
    factor_ref = factor["ref"]
    grouped = {
        "configuration_groups": [{
            "config_group_id": "cg-alpha",
            "product_scope_ref": "product-scope:core8",
            "factor_ref": factor_ref,
            "horizon": {"sampling": "explicit", "bases": ["signal"], "multipliers": [2]},
            "entry_delay_bars": 1,
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
            "warmup_mode": "none",
        }],
    }
    typed = compile_ic_grouped_configuration(
        grouped, factor_frequencies={factor_ref: "MIN5"},
    )
    payload = {
        "_owner": "alice", "run_id": "run-one",
        "factors": [factor],
        "run_spec": {
            "typed_ic": typed,
            "configuration": {"shared": {"product_selections": {
                "product-scope:core8": {
                    "product_path_selection_id": "product-scope:core8",
                    "paths": ["/canonical/products/core8"],
                },
            }}},
        },
        "execution_plan": {"kind": "ic"},
    }
    calls = []
    monkeypatch.setattr(process_runners, "_factor_runtime_scope", lambda _payload: nullcontext())
    monkeypatch.setattr(
        "server.modules.single_factor_test.planning.verify_execution_plan",
        lambda kind, value: None,
    )
    monkeypatch.setattr(
        ic, "execute_ic_run_spec",
        lambda value, **kwargs: calls.append((value, kwargs)),
    )
    process_runners.run_ic(payload, sink=object(), cancel_event=SimpleNamespace(is_set=lambda: False))

    assert len(calls) == 1
    execution = calls[0][0]
    assert execution["product_path_selection_id"] == "product-scope:core8"
    assert execution["paths"] == ["/canonical/products/core8"]
    assert execution["ic_lags"] == [1]
    assert execution["warmup_mode"] == "none"
    assert execution["forward_return_horizons"] == {
        "sampling": "explicit", "bases": ["MIN10"], "multipliers": [1],
    }
    assert execution["typed_ic_core_ref"].startswith("ic-core-request:v1:")


def test_grouped_ic_planner_uses_only_the_group_owned_frozen_scope(monkeypatch):
    """Unrelated shared selections must not widen an IC core or its cache key."""
    from server.modules.single_factor_test.planning import build_execution_plan
    from tools.testers.ic_test.configuration.grouped import compile_ic_grouped_configuration

    factor_ref = "factor:v2:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    typed = compile_ic_grouped_configuration({"configuration_groups": [{
        "config_group_id": "cg-alpha",
        "product_scope_ref": "product-scope:core8",
        "factor_ref": factor_ref,
        "horizon": {"sampling": "explicit", "bases": ["signal"], "multipliers": [1]},
        "entry_delay_bars": 0,
        "methods": ["rank"],
        "return_price_basis": "next_open_to_open_adjusted",
    }]}, factor_frequencies={factor_ref: "MIN5"})
    monkeypatch.setattr(
        "server.services.factor_revisions.assert_run_spec_factor_revisions_resolvable",
        lambda *args, **kwargs: None,
    )
    plan = build_execution_plan("ic", {
        "_owner": "alice",
        "run_spec": {
            "typed_ic": typed,
            "configuration": {"shared": {"product_selections": {
                "product-scope:core8": {
                    "paths": ["/canonical/products/core8", "/canonical/products/core8"],
                    "products": ["core8"],
                },
                "product-scope:unrelated": {
                    "paths": ["/must/not/run"],
                    "products": ["unrelated"],
                },
            }}},
        },
    })

    assert plan["kind"] == "ic"
    assert plan["resolved"]["selected_paths"] == ["/canonical/products/core8"]
    assert plan["resolved"]["products"] == ["core8"]
    assert [row["config_group_id"] for row in plan["resolved"]["group_provenance"]] == ["cg-alpha"]
