from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cli_anything.factortester_research.core.capabilities import (
    evaluate_capability_predicate,
    load_builtin_capability_registry,
    resolve_graph_capabilities,
)
from cli_anything.factortester_research.core.plan import build_factor_research_plan, validation_checklist
from cli_anything.factortester_research.core.replay import replay_graph_trace
from cli_anything.factortester_research.core.external_factor import (
    validate_dataset_manifest,
    validate_factor_manifest,
    validate_handoff_manifest,
    vibe_pipeline_plan,
)
from cli_anything.factortester_research.core.evidence import (
    persist_command_evidence,
    validate_evidence_envelope,
)
from cli_anything.factortester_research.core.graph import (
    build_draft_graph,
    build_observed_graph,
    graph_content_hash,
    validate_graph,
)
from cli_anything.factortester_research.core.service import ManagedWorktree, select_worktree
from cli_anything.factortester_research.core.session import (
    ResearchSession,
    record_gap,
    record_skill_usage,
    resolve_gap,
)
from cli_anything.factortester_research.core.slices import default_factor_validation_plan


HARNESS_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_observed_graph_distinguishes_advisory_plan_from_enforced_gap_state() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS"],
        configuration_file="configuration.json",
    )
    graph = build_observed_graph(plan)

    assert graph["lifecycle"] == "observed"
    nodes = {item["node_id"]: item for item in graph["nodes"]}
    assert nodes["inspect_factor_expr_dsl"]["enforcement"] == "advisory"
    assert nodes["code_improvement_required"]["enforcement"] == "deterministic"
    assert {
        (item["from_node"], item["to_node"], item["edge_type"])
        for item in graph["edges"]
    } >= {
        ("inspect_factor_expr_dsl", "prepare_factor_workspace", "recommended"),
        ("research_ready", "code_improvement_required", "failure"),
        ("code_improvement_required", "research_ready", "recovery"),
    }


def test_observed_graph_content_hash_is_stable() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS"],
        configuration_file="configuration.json",
    )
    first = build_observed_graph(plan)
    second = build_observed_graph(plan)

    assert graph_content_hash(first) == graph_content_hash(second)
    assert len(graph_content_hash(first)) == 64


def test_graph_validation_rejects_a_dangling_edge() -> None:
    graph = build_observed_graph(build_factor_research_plan(
        factor_families=["SgCCS"],
        configuration_file="configuration.json",
    ))
    graph["edges"][0]["to_node"] = "missing-node"

    with pytest.raises(ValueError, match="unknown node"):
        validate_graph(graph)


def test_capability_resolution_reports_available_bindings_and_gaps() -> None:
    graph = build_observed_graph(build_factor_research_plan(
        factor_families=["SgCCS"],
        configuration_file="configuration.json",
    ))
    registry = {
        "schema_version": 1,
        "catalog_id": "factor-research-capabilities",
        "capabilities": [{
            "capability_id": "factor-expr.operator-registry.inspect",
            "industry_semantics": (
                "Verify operator availability and causal semantics before "
                "factor evaluation."
            ),
            "when_to_use": ["before evaluating a factor expression"],
            "preconditions": [],
            "prohibitions": [],
            "implementations": [{
                "implementation_id": "factortester.custom-factors.operators",
                "provider": "factortester",
                "kind": "cli",
                "approval_status": "approved",
                "execution_mode": "real_backend",
                "product_scopes": ["china_futures"],
            }],
        }],
    }

    result = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        include_all=True,
    )

    assert result["bindings"][0]["capability_id"] == (
        "factor-expr.operator-registry.inspect"
    )
    assert result["bindings"][0]["implementation_id"] == (
        "factortester.custom-factors.operators"
    )
    assert "factor-workspace.prepare" in {
        item["capability_id"] for item in result["gaps"]
    }


def test_builtin_registry_distinguishes_backend_guidance_and_product_gaps() -> None:
    registry = load_builtin_capability_registry()
    capabilities = {
        item["capability_id"]: item for item in registry["capabilities"]
    }

    factor_ic = capabilities["factor-validation.cross-sectional-ic"]
    implementations = {
        item["implementation_id"]: item
        for item in factor_ic["implementations"]
    }
    assert implementations["factortester.analysis.ic"]["execution_mode"] == (
        "real_backend"
    )
    assert implementations["vibe.factor-research"]["execution_mode"] == (
        "guidance_only"
    )
    assert implementations["vibe.factor-research"]["approval_status"] == (
        "quarantined"
    )

    futures_accounting = capabilities["market-accounting.replay"]
    assert futures_accounting["prohibitions"]
    assert any(
        item["implementation_id"] == "vibe.china-futures-engine"
        and item["approval_status"] == "quarantined"
        for item in futures_accounting["implementations"]
    )


def test_draft_graph_exposes_adaptive_research_and_capability_gap_branches() -> None:
    graph = build_draft_graph()
    edges = {item["edge_id"]: item for item in graph["edges"]}
    nodes = {item["node_id"]: item for item in graph["nodes"]}

    assert graph["lifecycle"] == "draft"
    assert graph["version"] == 3
    assert graph["parent_version"] == 2
    assert nodes["cheap_factor_diagnostics"]["required_capabilities"] == [
        "factor-validation.cross-sectional-ic",
        "factor-validation.quantile-monotonicity",
    ]
    assert edges["cheap_diagnostics__backtest"]["guard"] == {
        "diagnostics_viable": True,
        "selection_role": "in_sample",
    }
    assert edges["backtest__statistical_robustness"]["guard"] == {
        "terminal_job_evidence_retained": True,
        "net_return_series_available": True,
    }
    assert edges["statistical_robustness__result_audit"]["guard"] == {
        "uncertainty_review_passed": True,
    }
    assert "cheap_diagnostics__statistical_robustness" not in edges
    assert "statistical_robustness__backtest" not in edges
    assert "backtest__result_audit" not in edges
    assert edges["cheap_diagnostics__result_audit"]["guard"] == {
        "diagnostics_reject": True,
    }
    assert edges["statistical_robustness__result_audit_reject"]["guard"] == {
        "robustness_reject": True,
    }
    assert edges["statistical_robustness__factor_improvement"]["guard"] == {
        "robustness_revise": True,
        "new_falsifiable_hypothesis_proposed": True,
        "selection_holdout_not_reused": True,
        "remaining_revision_budget_positive": True,
    }
    assert "result_audit__statistical_robustness" not in edges
    assert edges["factor_improvement__hypothesis"]["guard"] == {
        "new_hypothesis_version_recorded": True,
        "trial_ledger_incremented": True,
        "holdout_status_recorded": True,
        "factor_change_retained": True,
    }
    assert edges["any_node__capability_gap"]["from_node"] == "*"
    assert nodes["capability_gap"]["required_capabilities"] == [
        "capability-gap.classify"
    ]
    conditional = {
        item["capability_id"]
        for item in nodes["factor_semantics"]["conditional_capabilities"]
    }
    assert conditional == {
        "market-microstructure.intraday-diagnose",
        "factor-combination.multi-factor",
    }
    validation_required = set(
        nodes["validation_design"]["required_capabilities"]
    )
    validation_conditional = {
        item["capability_id"]: item["predicate"]
        for item in nodes["validation_design"]["conditional_capabilities"]
    }
    robustness_required = set(
        nodes["statistical_robustness"]["required_capabilities"]
    )
    robustness_conditional = {
        item["capability_id"]: item["predicate"]
        for item in nodes["statistical_robustness"]["conditional_capabilities"]
    }
    assert "multiple-testing.false-discovery-control" not in validation_required
    assert validation_conditional[
        "multiple-testing.false-discovery-control"
    ] == {"field": "research.trial_count", "greater_than": 1}
    assert robustness_required == {"performance.bootstrap-sharpe"}
    assert robustness_conditional["performance.deflated-sharpe"] == {
        "field": "research.trial_count",
        "greater_than": 1,
    }
    assert robustness_conditional[
        "performance.backtest-overfit-probability"
    ] == {
        "all": [
            {"field": "research.trial_count", "greater_than": 1},
            {
                "field": "selection.complete_candidate_return_matrix",
                "equals": True,
            },
        ],
    }
    assert "provisional local memory" in nodes["research_decision"]["purpose"]
    assert nodes["factor_semantics"]["exit_evidence"] == [
        "hypothesis hash and factor source or AST hash",
        "financial mechanism to implementation alignment",
        "numerical examples and semantic invariant checks",
    ]
    assert nodes["research_decision"]["exit_evidence"] == [
        "provisional local memory reference containing hypothesis, code, data, "
        "RunSpec, trial ledger, result, failure cause, and decision",
    ]


def test_numeric_capability_predicates_fail_closed() -> None:
    predicate = {"field": "research.trial_count", "greater_than": 1}

    assert evaluate_capability_predicate(
        predicate,
        {"research": {"trial_count": 2}},
    ) is True
    assert evaluate_capability_predicate(
        predicate,
        {"research": {"trial_count": 1}},
    ) is False
    assert evaluate_capability_predicate(predicate, {}) is None
    with pytest.raises(ValueError, match="numeric"):
        evaluate_capability_predicate(
            predicate,
            {"research": {"trial_count": "many"}},
        )


def test_trial_family_capabilities_are_triggered_only_when_applicable() -> None:
    graph = build_draft_graph()
    registry = load_builtin_capability_registry()
    single = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="statistical_robustness",
        facts={
            "research": {"trial_count": 1},
            "selection": {"complete_candidate_return_matrix": False},
        },
    )
    family = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="statistical_robustness",
        facts={
            "research": {"trial_count": 4},
            "selection": {"complete_candidate_return_matrix": True},
        },
    )

    assert single["triggered_conditional_gaps"] == []
    assert {
        item["capability_id"]
        for item in family["triggered_conditional_gaps"]
    } == {
        "performance.deflated-sharpe",
        "performance.backtest-overfit-probability",
    }


def test_external_skill_execution_requires_an_explicit_grant() -> None:
    graph = build_draft_graph()
    graph["nodes"] = [{
        "node_id": "commodity_hypothesis",
        "kind": "research",
        "purpose": "generate a commodity hypothesis",
        "enforcement": "audited",
        "required_capabilities": ["hypothesis.commodity-structure"],
        "entry_evidence": [],
        "exit_evidence": [],
    }]
    graph["edges"] = []
    registry = load_builtin_capability_registry()

    blocked = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        node_id="commodity_hypothesis",
    )
    granted = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        approved_implementation_ids={"vibe.commodity-analysis"},
        node_id="commodity_hypothesis",
    )

    assert blocked["gaps"][0]["capability_id"] == (
        "hypothesis.commodity-structure"
    )
    assert blocked["gaps"][0]["reason"] == "execution_approval_required"
    assert blocked["gaps"][0]["candidate_implementation_ids"] == [
        "vibe.commodity-analysis"
    ]
    assert blocked["gaps"][0]["required_by"] == "commodity_hypothesis"
    assert blocked["gaps"][0]["capability_description"]
    assert len(blocked["gaps"][0]["descriptor_hash"]) == 64
    assert granted["bindings"][0]["implementation_id"] == (
        "vibe.commodity-analysis"
    )


def test_capability_resolution_keeps_conditional_skills_out_of_mandatory_gaps() -> None:
    graph = build_draft_graph()
    not_triggered = resolve_graph_capabilities(
        graph,
        load_builtin_capability_registry(),
        product_group="china_futures",
        facts={
            "hypothesis": {"origin": "native", "features": ["momentum"]},
            "research": {"needs_prior_art_dedup": False},
        },
    )
    triggered = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        product_group="china_futures",
        facts={
            "hypothesis": {
                "origin": "native",
                "features": ["inventory", "term_structure"],
            },
            "research": {"needs_prior_art_dedup": False},
        },
    )

    assert not_triggered["triggered_conditional_bindings"] == []
    assert not_triggered["triggered_conditional_gaps"] == []
    triggered_ids = {
        item["capability_id"]
        for item in triggered["triggered_conditional_gaps"]
    }
    assert triggered_ids == {"hypothesis.commodity-structure"}


def test_same_local_resolution_uses_content_addressed_cache() -> None:
    kwargs = {
        "product_group": "china_futures",
        "node_id": "factor_semantics",
        "facts": {
            "signal": {"frequency": "DAY1"},
            "hypothesis": {"features": ["momentum"]},
            "factor": {"is_multi": False},
        },
    }
    first = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        **kwargs,
    )
    second = resolve_graph_capabilities(
        build_draft_graph(),
        load_builtin_capability_registry(),
        **kwargs,
    )

    assert first["cache"]["hit"] is False
    assert second["cache"] == {
        "key": first["cache"]["key"],
        "hit": True,
        "scope": "process",
    }


def test_external_provider_change_invalidates_cache_and_fails_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("# Approved skill\n", encoding="utf-8")
    approved_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    graph = {
        "entry_node": "research",
        "nodes": [{
            "node_id": "research",
            "required_capabilities": ["research.external"],
        }],
        "edges": [],
    }
    registry = {
        "schema_version": 1,
        "catalog_id": "provider-fingerprint-test",
        "capabilities": [{
            "capability_id": "research.external",
            "industry_semantics": "Use an approved external research method.",
            "when_to_use": ["when the capability is required"],
            "preconditions": [],
            "prohibitions": [],
            "implementations": [{
                "implementation_id": "external.skill",
                "provider": "external",
                "kind": "skill",
                "approval_status": "approved",
                "execution_mode": "guidance_only",
                "product_scopes": ["all"],
                "source_path": str(source),
                "approved_source_sha256": approved_hash,
            }],
        }],
    }

    approved = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
    )
    source.write_text("# Provider changed the skill\n", encoding="utf-8")
    changed = resolve_graph_capabilities(
        graph,
        registry,
        product_group="equities",
    )

    assert approved["bindings"][0]["source_fingerprint"] == approved_hash
    assert approved["cache"]["hit"] is False
    assert changed["cache"]["hit"] is False
    assert changed["cache"]["key"] != approved["cache"]["key"]
    assert changed["bindings"] == []
    assert changed["gaps"][0]["reason"] == "provider_fingerprint_mismatch"
    assert changed["gaps"][0]["expected_sha256"] == approved_hash


def test_model_identity_does_not_change_deterministic_resolution() -> None:
    graph = build_draft_graph()
    registry = load_builtin_capability_registry()
    first = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        facts={"runtime": {"model_id": "model-a"}},
    )
    second = resolve_graph_capabilities(
        graph,
        registry,
        product_group="china_futures",
        facts={"runtime": {"model_id": "model-b"}},
    )

    assert first["semantic_cache_key"] == second["semantic_cache_key"]
    assert first["bindings"] == second["bindings"]
    assert first["gaps"] == second["gaps"]


def test_historical_preflight_replay_is_non_mutating_and_stops_at_real_gap() -> None:
    trace = json.loads(
        (FIXTURES / "historical_preflight_2026_07_16.json").read_text()
    )
    before = json.dumps(trace, sort_keys=True)

    report = replay_graph_trace(build_draft_graph(), trace)

    assert json.dumps(trace, sort_keys=True) == before
    assert report["external_mutations"] == 0
    assert report["status"] == "expected_block"
    assert report["branches"]["primary"]["current_node"] == "capability_gap"
    assert report["branches"]["primary"]["status"] == "paused"
    assert report["source"]["stale_historical_evidence"] is True
    assert report["coverage"]["edge_ids"] == [
        "hypothesis__capability_resolution",
        "capability_resolution__data_contract",
        "any_node__capability_gap",
    ]


def test_replay_rejects_an_unsatisfied_guard_without_running_work() -> None:
    report = replay_graph_trace(build_draft_graph(), {
        "schema_version": 1,
        "source": {"expected_outcome": "complete"},
        "events": [{
            "type": "transition",
            "branch_id": "primary",
            "edge_id": "hypothesis__capability_resolution",
            "evidence": {"hypothesis_frozen": False},
        }],
    })

    assert report["status"] == "failed"
    assert report["external_mutations"] == 0
    assert "hypothesis_frozen" in report["errors"][0]


def test_plan_uses_one_workspace_run_job_contract() -> None:
    plan = build_factor_research_plan(
        factor_families=["SgCCS", "MmRet"],
        factors=["SgCCS=SgCCS|P:CA|N:10d", "MmRet=MmRet|P:CA|N:5d"],
        configuration_file="run spec.json",
        analyses=["ic", "factor_type_analysis", "backtest"],
    )
    commands = "\n".join(item["command"] for item in plan)
    phases = [item["phase"] for item in plan]
    assert phases.index("understand_factor_source") < phases.index("submit_run")
    assert "workspace create --factor-family SgCCS --factor-family MmRet" in commands
    assert "--factor 'SgCCS=SgCCS|P:CA|N:10d'" in commands
    assert "workspace update --file 'run spec.json'" in commands
    assert "run submit --analysis ic --analysis factor_type_analysis --analysis backtest" in commands
    assert "job watch <job_id>" in commands
    assert "single_factor_test" not in commands
    assert "ic_test grid" not in commands
    assert "backtest compare" not in commands


def test_plan_treats_factor_families_as_values() -> None:
    plan = build_factor_research_plan(
        factor_families=["MyCustomFamily", "AnotherFamily"],
        configuration_file="configuration.json",
    )
    commands = "\n".join(item["command"] for item in plan)
    assert "--factor-family MyCustomFamily" in commands
    assert "--factor-family AnotherFamily" in commands
    assert "SgCCS" not in commands


def test_validation_checklist_encodes_durable_and_quant_contracts() -> None:
    text = "\n".join(validation_checklist())
    for required in (
        "RunSpec", "ranking universe", "product mask", "多重检验", "未来函数",
        "费用", "ResearchSlice/ValidationPlan", "traceback", "TTL", "retry_of",
        "page_uuid",
    ):
        assert required in text


def test_gap_state_machine_blocks_and_resumes_research() -> None:
    session = ResearchSession(status="research_ready")
    gap = record_gap(session, "missing IC decay", "backend did not return decay")
    assert gap["id"] == "gap-1"
    assert session.status == "code_improvement_required"
    resolve_gap(session, "gap-1", note="implemented")
    assert session.status == "research_ready"


def test_local_skill_usage_ledger_records_identity_and_reuse_without_server() -> None:
    session = ResearchSession()
    common = {
        "capability_description": "Challenge a graph change.",
        "descriptor_hash": "a" * 64,
        "skill_name": "grill-me",
        "skill_description": "Challenge a plan through structured questions.",
        "provider": "local",
        "version": "1",
        "source_fingerprint": "b" * 64,
        "approval_ref": "audit:skill-execution:17",
        "matching_rationale": "The capability requires adversarial review.",
    }
    loaded = record_skill_usage(
        session,
        **common,
        load_mode="loaded",
        skill_document_tokens=120,
    )
    reused = record_skill_usage(
        session,
        **common,
        load_mode="reused",
        cache_read_tokens=80,
    )

    assert loaded["record_hash"]
    assert reused["previous_record_hash"] == loaded["record_hash"]
    assert reused["skill_document_tokens"] == 0
    assert session.to_dict()["skill_usage"][1]["skill_name"] == "grill-me"


def test_local_evidence_envelope_keeps_output_behind_hashed_refs(
    tmp_path: Path,
) -> None:
    session_path = tmp_path / "research.json"
    envelope = persist_command_evidence(
        session_path=str(session_path),
        envelope_id="command-1",
        argv=["factortester", "job", "show", "job-1"],
        returncode=0,
        stdout='{"status":"complete"}\n',
        stderr="",
        hypotheses_tested=3,
        stop_condition=None,
        decision="continue",
    )

    assert validate_evidence_envelope(envelope)["decision"] == "continue"
    assert envelope["command"]["stdout_ref"].startswith("local-artifact:")
    assert '{"status"' not in json.dumps(envelope)
    assert len(envelope["envelope_hash"]) == 64


def test_service_target_selection_requires_unambiguous_worktree() -> None:
    worktrees = [
        ManagedWorktree("feat", "feat", "/repo", 7999, False, False),
        ManagedWorktree("fix/issue-123", "fix/issue-123", "/repo/.workspace/fix/issue-123", 8123, True, True),
    ]
    assert select_worktree(worktrees, target_port=8123).branch == "fix/issue-123"


def test_default_validation_plan_separates_selection_from_oos_annotation() -> None:
    payload = default_factor_validation_plan().to_dict()
    assert payload["in_sample_end"] == "2025-12-31"
    assert payload["oos_start"] == "2026-01-01"
    all_slices = [item for group in payload["slice_sets"] for item in group["slices"]]
    assert any(item["kind"] == "rolling" for item in all_slices)
    assert not any(
        item["purpose"] in {"selection", "validation"} and item["start"].startswith("2026")
        for item in all_slices
    )


def test_packaging_and_docs_record_durable_remote_contract() -> None:
    setup_text = (HARNESS_ROOT / "setup.py").read_text(encoding="utf-8")
    readme = (HARNESS_ROOT / "cli_anything/factortester_research/README.md").read_text(encoding="utf-8")
    skill = (HARNESS_ROOT / "cli_anything/factortester_research/skills/SKILL.md").read_text(encoding="utf-8")
    assert 'python_requires=">=3.10"' in setup_text
    for text in (readme, skill):
        assert "workspace" in text
        assert "RunSpec" in text
        assert "job_id" in text
        assert "page_uuid" in text


def test_vibe_pipeline_includes_daily_minute_and_server_handoff(tmp_path: Path) -> None:
    steps = vibe_pipeline_plan(
        integration_root=str(tmp_path / "integration"),
        data_root=str(tmp_path / "LocalCNFutures"),
        alpha_id="academic_carhart_mom",
    )
    phases = [item["phase"] for item in steps]
    assert phases[:4] == [
        "run_versioned_pipeline", "build_daily_panel", "build_minute_panel",
        "compute_vibe_daily_factor",
    ]
    assert steps[-1]["status"] == "ready_for_server_validation"
    assert "external-factor validate" in steps[-1]["reason"]


def test_external_manifests_require_next_bar_and_experimental_status(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        '{"schema_version":1,"rows":10,"symbols":2,'
        '"frequency":"1min","timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    factor = tmp_path / "factor.json"
    factor.write_text(
        '{"schema_version":1,"alpha_id":"x",'
        '"research_status":"experimental_unvalidated","input":{},'
        '"output":{"finite_observations":8},'
        '"timing":{"earliest_execution":"next_bar"}}',
        encoding="utf-8",
    )
    assert validate_dataset_manifest(str(dataset))["frequency"] == "1min"
    assert validate_factor_manifest(str(factor))["alpha_id"] == "x"


def test_handoff_manifest_keeps_import_boundary_explicit(tmp_path: Path) -> None:
    factor = tmp_path / "factor.parquet"
    factor.write_bytes(b"PAR1")
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({
        "schema_version": 1,
        "status": "ready_for_gtht_import_contract",
        "alpha_id": "x",
        "factor": {"path": str(factor), "sha256": "unused"},
        "universe": {},
        "timing": {
            "execution": "next_bar", "same_close_execution_forbidden": True,
        },
        "research": {"status": "experimental_unvalidated"},
        "gtht": {
            "factor_mode": "precomputed", "import_contract_available": False,
        },
    }), encoding="utf-8")
    result = validate_handoff_manifest(str(handoff))
    assert result["kind"] == "gtht_handoff"
    assert result["import_contract_available"] is False
