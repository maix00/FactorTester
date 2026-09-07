from types import SimpleNamespace

from server.modules.shared.run_spec_resolution.factors import RunFactorResolver
from server.modules.single_factor_test.process_runners import _typed_ic_execution_payload
from tools.factors.formula_identity import freeze_factor_identity


def frozen(alias, family, params):
    return freeze_factor_identity(
        owner_ref="principal:alice",
        family_alias=family,
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params=params,
    )


def test_shared_resolver_passes_complete_multilevel_graph(monkeypatch):
    leaf = frozen("Leaf", "Leaf", {})
    child = {
        **frozen("Child|P:[Leaf]", "Child", {"P": leaf["ref"]}),
        "factor_dependencies": [leaf],
    }
    parent = {
        **frozen("Parent|P:[Child|P:[Leaf]]", "Parent", {"P": child["ref"]}),
        "factor_dependencies": [child],
    }
    captured = {}

    def resolve(record, **kwargs):
        captured["record"] = record
        captured["index"] = kwargs["frozen_by_ref"]
        return SimpleNamespace(alias=record["alias"])

    monkeypatch.setattr(
        "server.modules.shared.factor_param_resolver.resolve_factor_param_value",
        resolve,
    )
    result = RunFactorResolver(
        owner="alice", frozen_factors=[parent],
    ).resolve(factor_ref=parent["ref"])

    assert result.alias == parent["alias"]
    assert set(captured["index"]) == {parent["ref"], child["ref"], leaf["ref"]}
    assert captured["record"]["factor_dependencies"][0]["ref"] == child["ref"]


def test_typed_ic_projection_preserves_full_records_and_selects_root():
    child = frozen("Child", "Child", {})
    parent = {
        **frozen("Parent|P:[Child]", "Parent", {"P": child["ref"]}),
        "factor_dependencies": [child],
    }
    payload = {
        "factors": [parent, child],
        "run_spec": {
            "configuration": {"shared": {
                "factors": [parent, child],
                "product_selections": {"scope": {"paths": ["/products/a"]}},
            }},
            "typed_ic": {
                "authoring_core_tests": [{
                    "request_ref": "request",
                    "product_scope_refs": ["scope"],
                    "factor_refs": [parent["ref"]],
                    "entry_delay_bars": [0],
                    "methods": ["rank"],
                }],
                "resolved_horizons_by_request": {
                    "request": {parent["ref"]: [{"physical_frequency": "1d"}]},
                },
            },
        },
    }

    projected = _typed_ic_execution_payload(payload)

    assert projected["factor_ref"] == parent["ref"]
    assert projected["factors"] == [parent, child]
    assert projected["factors"][0]["factor_dependencies"] == [child]
