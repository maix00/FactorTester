from __future__ import annotations

from copy import deepcopy

from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph import activation_validation
from server.services.research_graph import shadow_validation


def test_shadow_activation_evidence_audits_the_whole_resolver_catalog(
    monkeypatch,
) -> None:
    graph = deepcopy(build_successor_graph())
    graph["requirement_resolver_bindings"][-1][
        "invocation_contract"
    ]["operation_id"] = "factortester-research.graph.requirement-detail"
    runs = {
        "graph-run": {"run_spec_hash": "a" * 64},
        "baseline-run": {"run_spec_hash": "a" * 64},
    }
    monkeypatch.setattr(
        shadow_validation,
        "_load_comparison_scope",
        lambda **_: (
            graph,
            "owner",
            {},
            "graph-run",
            runs,
        ),
    )
    monkeypatch.setattr(
        shadow_validation,
        "replay_shadow_trace",
        lambda **_: {"passed": True},
    )
    monkeypatch.setattr(
        shadow_validation,
        "_compare_run_outcomes",
        lambda **_: {"equivalent": True, "isolated": True},
    )
    monkeypatch.setattr(
        shadow_validation,
        "build_graph_branch_context",
        lambda **_: {"open_gaps": []},
    )
    monkeypatch.setattr(
        shadow_validation,
        "derive_token_metrics",
        lambda **_: {},
    )
    monkeypatch.setattr(
        shadow_validation,
        "token_failures",
        lambda _: [],
    )

    evidence = shadow_validation.derive_activation_evidence(
        graph_id="factor-research",
        version=9,
        routine_instance_id="instance",
        routine_branch_id="branch",
        baseline_run_id="baseline-run",
    )

    assert evidence["requirement_resolvers_complete"] is False
    assert evidence["requirement_resolver_summary"]["requirement_count"] == 60
    assert "static_contract_lookup" in evidence[
        "requirement_resolver_summary"
    ]["failure_codes"]
    assert "requirement_resolvers_complete" in (
        activation_validation._VALIDATION_GATES
    )
