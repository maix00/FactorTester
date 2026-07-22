from __future__ import annotations

import json

from click.testing import CliRunner

from cli_anything.factortester_research.factortester_research_cli import cli
from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from cli_anything.factortester_research.core.draft_graph import (
    build_draft_graph,
)
from server.services.research_graph.branch.topology_preflight import (
    assess_topology_continuation,
)


def test_successor_graph_is_deterministic_and_contract_complete() -> None:
    first = build_successor_graph()
    second = build_successor_graph()

    assert first == second
    assert first["schema_version"] == 2
    assert first["version"] == 9
    assert len(first["content_hash"]) == 64
    assert len(first["requirement_catalog"]["categories"]) == 7
    assert len(first["requirement_catalog"]["requirements"]) == 50
    source_refs = {
        item["source_ref"] for item in first["industry_basis_catalog"]
    }
    assert {
        "S-NIST-DOE", "S-W3C-PROV", "S-ASA-PVALUE",
        "S-BAILEY-BACKTEST-OVERFITTING", "S-MARKET-RULES-PIT",
    } <= source_refs
    assert all(
        set(item["industry_basis_refs"]) <= source_refs
        for item in first["requirement_catalog"]["requirements"]
    )


def test_successor_graph_removes_fixed_method_states() -> None:
    graph = build_successor_graph()
    node_ids = {item["node_id"] for item in graph["nodes"]}

    assert "trial_execution" in node_ids
    assert "cheap_factor_diagnostics" not in node_ids
    assert "statistical_robustness" not in node_ids
    assert "authoritative_backtest" not in node_ids
    assert "job_evidence_ready" not in node_ids


def test_successor_graph_reports_every_node_edge_and_system_gate() -> None:
    graph = build_successor_graph()
    report_ids = {
        item["report_requirement_id"]
        for item in graph["report_requirements"]
    }

    for node in graph["nodes"]:
        assert set(node["entry_report_refs"]) <= report_ids
        assert set(node["node_report_refs"]) <= report_ids
    for edge in graph["edges"]:
        assert set(edge["report_requirement_refs"]) <= report_ids
    assert {
        "report.system.continuation_reentry",
        "report.system.node_reentry",
        "report.system.evidence_admission",
    } <= report_ids


def test_successor_graph_keeps_only_semantic_obligation_categories() -> None:
    graph = build_successor_graph()
    category_ids = {
        item["category_id"]
        for item in graph["requirement_catalog"]["categories"]
    }

    assert "capability" not in category_ids
    assert "evidence_integrity" not in category_ids
    assert "research_decision" not in category_ids
    assert "report_coverage" not in category_ids
    assert "factor_semantics" in category_ids
    assert "trading_strategy" in category_ids
    assert "market_rules_accounting" in category_ids
    assert "hypothesis_validity" not in category_ids
    assert "market_execution_accounting" not in category_ids


def test_successor_allows_early_reentry_but_rejects_deleted_method_history() -> None:
    source = build_draft_graph()
    target = build_successor_graph()
    early = assess_topology_continuation(
        source_graph=source,
        target_graph=target,
        current_node="factor_semantics",
        footprint={
            "node_ids": [
                "hypothesis_preregistration",
                "capability_resolution",
                "data_contract",
                "factor_semantics",
            ],
            "edge_ids": [
                "hypothesis__capability_resolution",
                "capability_resolution__data_contract",
                "data_contract__factor_semantics",
            ],
        },
    )
    method_history = assess_topology_continuation(
        source_graph=source,
        target_graph=target,
        current_node="cheap_factor_diagnostics",
        footprint={
            "node_ids": [
                "validation_design",
                "cheap_factor_diagnostics",
            ],
            "edge_ids": ["validation_design__cheap_diagnostics"],
        },
    )

    assert early["eligible"] is True, early
    assert method_history["eligible"] is False
    assert method_history["missing_nodes"] == ["cheap_factor_diagnostics"]


def test_successor_requirement_cli_returns_one_bounded_local_packet() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "graph",
            "requirements",
            "--node",
            "validation_design",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["anchor_ref"] == "validation_design"
    assert len(payload["requirements"]) == 8
    assert len(result.output.encode()) < 6000
    assert payload["requirements"][0]["industry_basis_refs"]
    assert payload["requirements"][0]["industry_principle_zh"]


def test_successor_source_cli_lazy_loads_one_auditable_reference() -> None:
    result = CliRunner().invoke(
        cli,
        ["graph", "source", "S-NIST-DOE", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source_ref"] == "S-NIST-DOE"
    assert payload["locators"] == [
        "https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm"
    ]
    assert len(result.output.encode()) < 1200


def test_successor_requirement_cli_rejects_ambiguous_anchor() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "graph",
            "requirements",
            "--node",
            "data_contract",
            "--edge",
            "data_contract__factor_semantics",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "exactly one" in result.output
