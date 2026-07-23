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
    assert len(first["requirement_catalog"]["categories"]) == 8
    assert len(first["requirement_catalog"]["requirements"]) == 60
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
    operations = {
        item["capability_id"]
        for item in [
            *first["research_cycle_operations"],
            *first["maintenance_operations"],
        ]
    }
    assert {
        "research-obligation.discover",
        "research-trial.synthesize",
        "research-evidence.adjudicate",
        "research-exhaustion.assess",
        "research-methodology.impact",
    } == operations
    assert operations <= set(first["capability_descriptors"])
    catalog_requirements = {
        item["requirement_id"]
        for item in first["requirement_catalog"]["requirements"]
    }
    entry_requirements = {
        requirement_id
        for node in first["nodes"]
        for requirement_id in node["entry_requirement_refs"]
    }
    assert entry_requirements == catalog_requirements


def test_successor_graph_removes_fixed_method_states() -> None:
    graph = build_successor_graph()
    nodes = {
        item["node_id"]: item
        for item in graph["nodes"]
    }
    node_ids = set(nodes)

    assert "trial_execution" in node_ids
    assert nodes["trial_execution"]["kind"] == "execution"
    assert nodes["capability_gap"]["kind"] == "capability_gap"
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
    node_reports = [
        item for item in graph["report_requirements"]
        if item["report_requirement_id"].startswith("report.node.")
    ]
    assert all("requirement_ref" not in item for item in node_reports)
    assert all(item.get("coordination_ref") for item in node_reports)
    requirement_reports = [
        item for item in graph["report_requirements"]
        if item["report_requirement_id"].startswith("report.requirement.")
    ]
    assert all(item.get("requirement_ref") for item in requirement_reports)
    methods = graph["report_method_descriptors"]
    assert "figure" in methods["explain_formula"]["allowed_content"]
    formula_reports = {
        item["requirement_ref"]: item["method_ref"]
        for item in requirement_reports
        if item["requirement_ref"].startswith("factor_semantics.")
    }
    assert formula_reports["factor_semantics.expression_identity"] == (
        "explain_formula"
    )
    factor_node = next(
        item for item in graph["report_requirements"]
        if item["report_requirement_id"] == "report.node.factor_semantics.action"
    )
    assert factor_node["method_ref"] == "explain_formula"


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
    assert "hypothesis_validity" in category_ids
    assert "trial_design_validity" in category_ids
    assert "strategy_design" in category_ids
    assert "market_execution_accounting" in category_ids
    assert "trial_design" not in category_ids
    assert "trading_strategy" not in category_ids
    assert "market_rules_accounting" not in category_ids


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


def test_topology_preflight_rejects_a_visited_node_kind_change() -> None:
    source = build_draft_graph()
    target = build_successor_graph()
    target_node = next(
        item for item in target["nodes"]
        if item["node_id"] == "factor_semantics"
    )
    target_node["kind"] = "research"

    result = assess_topology_continuation(
        source_graph=source,
        target_graph=target,
        current_node="factor_semantics",
        footprint={
            "node_ids": ["factor_semantics"],
            "edge_ids": [],
        },
    )

    assert result["eligible"] is False
    assert result["redefined_nodes"] == ["factor_semantics"]


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
    assert len(payload["requirements"]) == 12
    assert len(result.output.encode()) < 6000
    assert {item["category_id"] for item in payload["category_contexts"]} == {
        "trial_design_validity",
    }
    assert all(item["industry_basis_refs"] for item in payload["category_contexts"])
    assert all(item["industry_principle_zh"] for item in payload["category_contexts"])


def test_trial_execution_packet_covers_strategy_and_market_rules() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "graph",
            "requirements",
            "--node",
            "trial_execution",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    requirement_ids = {
        item["requirement_id"]
        for item in payload["requirements"]
    }
    assert {
        "strategy_design.signal_schedule",
        "strategy_design.strategy_conditioning",
        "strategy_design.position_and_rebalance",
        "strategy_design.session_policy",
        "market_execution_accounting.session_calendar",
        "market_execution_accounting.contract_lifecycle",
        "market_execution_accounting.order_and_fill",
        "market_execution_accounting.cost_margin_and_settlement",
        "market_execution_accounting.backtest_live_consistency",
    } <= requirement_ids
    assert len(result.output.encode()) < 6000


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
