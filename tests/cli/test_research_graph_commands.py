from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.client import FactorTesterClient
from tools.cli.commands import agent_flow as agent_flow_commands
from tools.cli.commands import research_graph as commands
from tools.cli.commands import (
    research_graph_continuation_report as continuation_report,
)


class FakeClient:
    def __init__(self) -> None:
        self.published = None
        self.validation = None
        self.proposal = None
        self.review = None
        self.authorization = None
        self.rollback = None
        self.advance = None
        self.advance_call_count = 0
        self.advance_response = None
        self.continuation_preview = None
        self.continuation = None
        self.continuation_response = None
        self.profile_research_branch = None
        self.agent_budget_call = None
        self.agent_invocation_call = None
        self.instance_call = None
        self.trial_plan_revision = None
        self.activation_preflight = None
        self.activation_preflight_response = None
        self.proposal_detail = None
        self.reviewed_activation = None

    def publish_research_graph(self, graph):
        self.published = graph
        return graph

    def revise_trial_plan(
        self,
        instance_id,
        branch_id,
        **kwargs,
    ):
        self.trial_plan_revision = (instance_id, branch_id, kwargs)
        return {
            "operation": "revise_unused_trial_plan",
            "trial_plan_hash": "b" * 64,
        }

    def list_research_graph_versions(self, graph_id):
        return [{"graph_id": graph_id, "version": 2, "lifecycle": "draft"}]

    def get_active_research_graph(self, graph_id):
        return {
            "graph_id": graph_id,
            "version": 2,
            "lifecycle": "draft",
            "is_active": True,
            "active_pointer": {"version": 2},
        }

    def get_research_graph_activation_preflight(self, graph_id, version):
        self.activation_preflight = (graph_id, version)
        return self.activation_preflight_response or {
            "graph_id": graph_id,
            "active_version": 8,
            "target_version": version,
            "rollback_version": 8,
            "ready_for_human_authorization": False,
            "completed_gates": ["independent_review", "grill_audit"],
            "missing_gates": ["deterministic_validation"],
            "already_active": False,
            "proposal_id": "proposal-1",
            "next_command": (
                "factortester research-graph validate factor-research 9 "
                "--proposal-id proposal-1 "
                "--routine-instance-id <shadow-instance-id> "
                "--routine-branch-id <shadow-branch-id> "
                "--baseline-run-id <baseline-run-id>"
            ),
        }

    def get_research_graph_proposal(self, proposal_id):
        self.proposal_detail = proposal_id
        return {
            "proposal": {
                "proposal_id": proposal_id,
                "action": "activate_graph",
                "evidence_refs": ["test:proposal"],
            },
            "target_graph": {
                "graph_id": "factor-research",
                "version": 10,
                "content_hash": "a" * 64,
                "parent_version": 9,
                "change_manifest": {
                    "changes": [{"change_id": "change.capability-resume"}],
                },
            },
            "gate_readiness": {
                "independent_review": False,
                "deterministic_validation": False,
                "grill_audit": False,
                "human_authorization": False,
            },
            "review_contract": {
                "requires_independent_principal_and_lineage": True,
                "command": (
                    "factortester research-graph review proposal-1 "
                    "--disposition <approved|rejected|disagreed> "
                    "--agent-execution-id "
                    "<settled-independent-reviewer-invocation-id>"
                ),
            },
        }

    def activate_reviewed_research_graph(
        self,
        graph_id,
        version,
        *,
        approval_ref,
    ):
        self.reviewed_activation = (graph_id, version, approval_ref)
        return {
            "graph_id": graph_id,
            "from_version": 8,
            "to_version": version,
            "rollback_version": 8,
            "already_active": False,
            "promoted_continuation_count": 1,
        }

    def validate_research_graph(
        self, graph_id, version, evidence, *, proposal_id,
    ):
        self.validation = (graph_id, version, evidence, proposal_id)
        return {"validation_id": "validation-1", "evidence": evidence}

    def audit_research_graph(
        self, graph_id, version, *, proposal_id, disposition,
        grill_evidence, grill_ref,
    ):
        return {
            "audit_id": "audit-1",
            "proposal_id": proposal_id,
            "disposition": disposition,
            "grill_evidence": grill_evidence,
            "grill_ref": grill_ref,
        }

    def activate_research_graph(
        self,
        graph_id,
        version,
        *,
        human_authorization_id,
    ):
        return {
            "graph_id": graph_id,
            "version": version,
            "lifecycle": "draft",
            "is_active": True,
            "active_pointer": {"version": version},
            "human_authorization_id": human_authorization_id,
        }

    def propose_research_graph(self, graph_id, version, **kwargs):
        self.proposal = (graph_id, version, kwargs)
        return {"proposal_id": "proposal-1", **kwargs}

    def review_research_graph_proposal(self, proposal_id, **kwargs):
        self.review = (proposal_id, kwargs)
        return {"review_id": "review-1", **kwargs}

    def rollback_research_graph(self, graph_id, **kwargs):
        self.rollback = (graph_id, kwargs)
        return {
            "graph_id": graph_id,
            "from_version": 4,
            "to_version": kwargs["target_version"],
        }

    def authorize_research_graph_activation(self, **kwargs):
        self.authorization = kwargs
        return {"authorization_id": "gate-rollback-1", **kwargs}

    def create_research_graph_instance(self, **kwargs):
        self.instance_call = kwargs
        return {
            "instance_id": "instance-1",
            **kwargs,
            "branches": [{"branch_id": "branch-1", "status": "running"}],
        }

    def advance_research_graph_node(
        self,
        instance_id,
        branch_id,
        *,
        edge_id,
        evidence,
    ):
        self.advance_call_count += 1
        self.advance = (instance_id, branch_id, edge_id, evidence)
        return self.advance_response or {
            "instance_id": instance_id,
            "branch_id": branch_id,
            "current_node": "validation",
        }

    def preview_research_graph_continuation(
        self,
        instance_id,
        branch_id,
        *,
        target_graph_version,
        job_id,
        execution_mode="live",
        shadow_run_id="",
        shadow_proposal_id="",
    ):
        self.continuation_preview = (
            instance_id,
            branch_id,
            target_graph_version,
            job_id,
            execution_mode,
            shadow_run_id,
            shadow_proposal_id,
        )
        return {
            "action": "continue_graph_branch",
            "target_hash": "c" * 64,
            "descriptor": {
                "target_graph_version": target_graph_version,
                "target_node": "capability_gap",
                "requirement_preflight": {
                    "assessment_required_ids": [
                        "other.unclassified_material_question",
                    ],
                },
                "capability_detour": {
                    "episode_id": "episode-1",
                    "resume_node": "hypothesis_preregistration",
                },
            },
        }

    def continue_research_graph_branch(
        self,
        instance_id,
        branch_id,
        *,
        target_graph_version,
        job_id,
        expected_target_hash,
        execution_mode="live",
        shadow_run_id="",
        shadow_proposal_id="",
    ):
        self.continuation = (
            instance_id,
            branch_id,
            target_graph_version,
            job_id,
            expected_target_hash,
            execution_mode,
            shadow_run_id,
            shadow_proposal_id,
        )
        return self.continuation_response or {
            "instance_id": "instance-v6",
            "work_package_id": "instance-v5",
            "graph_version": target_graph_version,
            "branches": [{"branch_id": "branch-v6"}],
        }

    def get_profile_research_branch(self, work_package_ref, branch_id):
        return self.profile_research_branch or {
            "work_package_ref": work_package_ref,
            "branch_id": branch_id,
        }

    def load_agent_budget_period(self, agent_id):
        self.agent_budget_call = ("load", agent_id, {})
        return {
            "period_id": "period-1",
            "agent_id": agent_id,
            "token_limit": 2000,
        }

    def get_active_research_runtime_budget_profile(self):
        return {
            "profile_ref": "agent-packet-runtime:test",
            "ceiling_bytes": 7000,
        }

    def configure_research_runtime_budget_profile(self, **kwargs):
        self.runtime_budget_profile = kwargs
        return {
            "profile_ref": "agent-packet-runtime:configured",
            **kwargs,
        }

    def configure_agent_budget_period(self, agent_id, *, token_limit):
        self.agent_budget_call = (
            "configure",
            agent_id,
            {"token_limit": token_limit},
        )
        return {
            "period_id": "period-1",
            "agent_id": agent_id,
            "token_limit": token_limit,
        }

    def reset_agent_budget_period(self, agent_id, *, token_limit=None):
        self.agent_budget_call = (
            "reset",
            agent_id,
            {"token_limit": token_limit},
        )
        return {
            "period_id": "period-2",
            "agent_id": agent_id,
            "token_limit": token_limit,
        }

    def reserve_agent_invocation(self, **kwargs):
        self.agent_invocation_call = ("reserve", kwargs)
        return {
            "invocation_id": "invocation-1",
            "status": "reserved",
            **kwargs,
        }

    def settle_agent_invocation(self, invocation_id, **kwargs):
        self.agent_invocation_call = (
            "settle",
            {"invocation_id": invocation_id, **kwargs},
        )
        return {
            "invocation_id": invocation_id,
            "status": "settled",
            **kwargs,
        }

    def release_agent_invocation(self, invocation_id):
        self.agent_invocation_call = (
            "release",
            {"invocation_id": invocation_id},
        )
        return {
            "invocation_id": invocation_id,
            "status": "released",
        }

    def get_current_graph_requirement(
        self, instance_id, branch_id, requirement_id,
    ):
        return {
            "graph_ref": "factor-research@v9",
            "node_id": "data_contract",
            "requirement": {
                "requirement_id": requirement_id,
                "title_zh": "产品数据源",
            },
        }


def test_shadow_start_forwards_explicit_proposal_id(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    resolution_file = tmp_path / "resolution.json"
    resolution_file.write_text(
        json.dumps({
            "node_id": "hypothesis",
            "bindings": [],
            "gaps": [],
            "triggered_conditional_bindings": [],
            "undetermined_conditions": [],
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, [
        "research-graph", "start", "factor-research",
        "--product-group", "equities",
        "--workspace-id", "workspace-1",
        "--shadow-graph-version", "9",
        "--shadow-run-id", "run-shadow",
        "--shadow-proposal-id", "proposal-v9",
        "--capability-resolution-file", str(resolution_file),
    ])

    assert result.exit_code == 0, result.output
    assert fake.instance_call["shadow_proposal_id"] == "proposal-v9"


def test_research_graph_cli_publishes_and_reads_versions(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(json.dumps({
        "graph_id": "factor-research",
        "version": 2,
        "lifecycle": "draft",
    }))
    runner = CliRunner()

    published = runner.invoke(
        cli, ["research-graph", "publish", str(graph_file)],
    )
    listed = runner.invoke(
        cli, ["research-graph", "versions", "factor-research"],
    )
    active = runner.invoke(
        cli, ["research-graph", "active", "factor-research"],
    )

    assert published.exit_code == 0
    assert fake.published["version"] == 2
    assert '"lifecycle": "draft"' in listed.output
    assert '"is_active": true' in active.output
    assert '"version": 2' in active.output


def test_research_graph_activation_status_is_compact_and_server_derived(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph",
        "activation-status",
        "factor-research",
        "9",
    ])

    assert result.exit_code == 0, result.output
    assert fake.activation_preflight == ("factor-research", 9)
    payload = json.loads(result.output)
    assert payload == {
        "active_version": 8,
        "already_active": False,
        "completed_gates": ["independent_review", "grill_audit"],
        "graph_id": "factor-research",
        "missing_gates": ["deterministic_validation"],
        "next_command": (
            "factortester research-graph validate factor-research 9 "
            "--proposal-id proposal-1 "
            "--routine-instance-id <shadow-instance-id> "
            "--routine-branch-id <shadow-branch-id> "
            "--baseline-run-id <baseline-run-id>"
        ),
        "proposal_id": "proposal-1",
        "ready_for_human_authorization": False,
        "rollback_version": 8,
        "target_version": 9,
    }
    assert "content_hash" not in result.output


def test_research_graph_proposal_returns_exact_reviewer_packet(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph",
        "proposal",
        "proposal-1",
    ])

    assert result.exit_code == 0, result.output
    assert fake.proposal_detail == "proposal-1"
    payload = json.loads(result.output)
    assert payload["target_graph"]["version"] == 10
    assert payload["target_graph"]["parent_version"] == 9
    assert payload["proposal"]["evidence_refs"] == ["test:proposal"]
    assert payload["review_contract"][
        "requires_independent_principal_and_lineage"
    ] is True
    assert "settled-independent-reviewer-invocation-id" in (
        payload["review_contract"]["command"]
    )


def test_research_graph_activate_yes_uses_server_orchestration(
    monkeypatch,
) -> None:
    fake = FakeClient()
    fake.activation_preflight_response = {
        "graph_id": "factor-research",
        "active_version": 8,
        "target_version": 9,
        "rollback_version": 8,
        "ready_for_human_authorization": True,
        "completed_gates": [
            "independent_review",
            "deterministic_validation",
            "grill_audit",
        ],
        "missing_gates": [],
        "already_active": False,
    }
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph",
        "activate",
        "factor-research",
        "9",
        "--yes",
    ])

    assert result.exit_code == 0, result.output
    assert fake.reviewed_activation[:2] == ("factor-research", 9)
    assert fake.reviewed_activation[2].startswith(
        "auth-conversation-event:cli-"
    )
    payload = json.loads(result.output)
    assert payload["from_version"] == 8
    assert payload["to_version"] == 9
    assert "nodes" not in payload


def test_research_graph_cli_requires_explicit_gate_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()

    result = runner.invoke(cli, [
        "research-graph",
        "validate",
        "factor-research",
        "2",
        "--proposal-id",
        "proposal-1",
        "--routine-instance-id",
        "instance-shadow-1",
        "--routine-branch-id",
        "branch-shadow-1",
        "--baseline-run-id",
        "run-baseline-1",
    ])

    assert result.exit_code == 0
    assert fake.validation == (
        "factor-research",
        2,
        {
            "shadow_comparison_refs": {
                "routine_instance_id": "instance-shadow-1",
                "routine_branch_id": "branch-shadow-1",
                "baseline_run_id": "run-baseline-1",
            },
        },
        "proposal-1",
    )


def test_research_graph_cli_forwards_opaque_packet_calibration_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    receipt = tmp_path / "packet-calibration.receipt"
    receipt.write_text("opaque-provider-receipt", encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research-graph", "validate", "factor-research", "9",
        "--proposal-id", "proposal-9",
        "--routine-instance-id", "instance-9",
        "--routine-branch-id", "branch-9",
        "--baseline-run-id", "baseline-9",
        "--packet-calibration-provider-id", "provider-a",
        "--packet-tokenizer-id", "tokenizer-a",
        "--packet-tokenizer-revision", "revision-a",
        "--packet-calibration-receipt-file", str(receipt),
    ])

    assert result.exit_code == 0, result.output
    evidence = fake.validation[2]
    assert evidence["packet_calibration_receipt"] == {
        "provider_id": "provider-a",
        "tokenizer_id": "tokenizer-a",
        "tokenizer_revision": "revision-a",
        "receipt": "opaque-provider-receipt",
    }


def test_research_graph_start_consumes_node_local_capability_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    resolution_file = tmp_path / "resolution.json"
    resolution_file.write_text(json.dumps({
        "resolution": {
            "node_id": "hypothesis",
            "catalog_hash": "a" * 64,
            "provider_conformance_hash": "b" * 64,
            "bindings": [{
                "capability_id": "research-obligation.discover",
                "capability_description": "Discover bounded obligations.",
                "descriptor_hash": "c" * 64,
                "implementation_id": "local.private-skill",
                "provider": "local-runtime",
                "source_fingerprint": "d" * 64,
                "execution_approval_granted": True,
            }],
            "gaps": [],
            "triggered_conditional_bindings": [],
            "triggered_conditional_gaps": [],
            "undetermined_conditions": [],
        },
    }))

    result = CliRunner().invoke(cli, [
        "research-graph",
        "start",
        "factor-research",
        "--product-group",
        "china_futures",
        "--workspace-id",
        "workspace-1",
        "--capability-resolution-file",
        str(resolution_file),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["graph_id"] == "factor-research"
    assert payload["product_group"] == "china_futures"
    assert payload["capability_resolution"]["node_id"] == "hypothesis"
    assert payload["capability_resolution"]["bindings"] == [{
        "capability_id": "research-obligation.discover",
        "capability_description": "Discover bounded obligations.",
        "descriptor_hash": "c" * 64,
    }]
    assert "implementation_id" not in json.dumps(
        payload["capability_resolution"]
    )


def test_research_graph_bounded_review_commands(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()
    diff_file = tmp_path / "diff.json"
    diff_file.write_text(json.dumps({"reason": "semantic edge change"}))

    proposed = runner.invoke(cli, [
        "research-graph", "propose", "factor-research", "2",
        "--risk-level", "L4",
        "--change-diff-file", str(diff_file),
        "--evidence-ref", "artifact:counterexample",
        "--token-estimate", "400",
        "--agent-execution-id", "proposer-execution",
        "--conversation-ref", "auth-conversation:test-cli",
    ])
    reviewed = runner.invoke(cli, [
        "research-graph", "review", "proposal-1",
        "--disposition", "approved",
        "--evidence-ref", "artifact:review",
        "--agent-execution-id", "reviewer-execution",
    ])

    assert proposed.exit_code == 0
    assert reviewed.exit_code == 0
    assert fake.proposal[2]["token_estimate"] == 400
    assert fake.proposal[2]["agent_execution_id"] == "proposer-execution"
    assert (
        fake.proposal[2]["conversation_ref"]
        == "auth-conversation:test-cli"
    )
    assert fake.review[1]["scope_drift"] is False


def test_legacy_graph_navigation_commands_are_removed() -> None:
    runner = CliRunner()
    for command in ("context", "next", "advance"):
        result = runner.invoke(cli, ["research-graph", command])
        assert result.exit_code != 0
        assert "No such command" in result.output


def test_research_graph_requirement_detail_reads_only_one_contract(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph",
        "requirement-detail",
        "instance-1",
        "branch-1",
        "data.product_source_availability",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["requirement"]["title_zh"] == "产品数据源"
    assert "requirement_catalog" not in payload


def test_research_graph_continuation_is_previewed_then_exactly_applied(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()

    preview = runner.invoke(cli, [
        "research-graph", "continuation-preview",
        "instance-v5", "branch-v5",
        "--target-version", "6",
        "--job-id", "job-1",
    ])
    continued = runner.invoke(cli, [
        "research-graph", "continue",
        "instance-v5", "branch-v5",
        "--target-version", "6",
        "--job-id", "job-1",
        "--expected-target-hash", "c" * 64,
    ])

    assert preview.exit_code == 0
    assert continued.exit_code == 0
    assert fake.continuation_preview == (
        "instance-v5", "branch-v5", 6, "job-1", "live", "", "",
    )
    assert fake.continuation == (
        "instance-v5", "branch-v5", 6, "job-1", "c" * 64, "live", "", "",
    )
    plan = json.loads(preview.output)["agent_plan"]
    assert plan["sequence"][0] == {
        "order": 1,
        "action": "assess_current_node_reentry",
        "node_id": "capability_gap",
        "requirement_ids": ["other.unclassified_material_question"],
        "required": True,
    }
    assert plan["sequence"][1]["resume_node"] == (
        "hypothesis_preregistration"
    )
    assert plan["capability_detour_policy"] == {
        "episode": "retain_existing",
        "nested_detour": "forbidden",
        "new_detour": "only_after_existing_episode_is_closed",
    }
    assert plan["next_packet_command"] == (
        "factortester research-graph node info "
        "<target-instance-id> <target-branch-id>"
    )


def test_research_graph_continue_yes_previews_and_applies_exact_hash(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph", "continue",
        "instance-v9", "branch-v9",
        "--target-version", "10",
        "--yes",
    ])

    assert result.exit_code == 0, result.output
    assert fake.continuation_preview == (
        "instance-v9", "branch-v9", 10, "", "live", "", "",
    )
    assert fake.continuation == (
        "instance-v9", "branch-v9", 10, "", "c" * 64, "live", "", "",
    )
    payload = json.loads(result.output)
    assert payload["agent_plan"]["sequence"][0]["node_id"] == (
        "capability_gap"
    )
    assert payload["agent_plan"]["sequence"][3]["scope"] == (
        "when_each_owning_node_is_entered"
    )


def test_graph_governance_help_exposes_real_gate_order() -> None:
    runner = CliRunner()

    proposed = runner.invoke(cli, [
        "research-graph", "propose", "--help",
    ])
    validated = runner.invoke(cli, [
        "research-graph", "validate", "--help",
    ])

    assert proposed.exit_code == 0
    assert "auth-conversation:" in proposed.output
    assert validated.exit_code == 0
    assert "independent review" in validated.output
    assert "draft shadow instance" in validated.output
    assert "research-graph start --shadow-graph-version" in validated.output


def test_runtime_budget_profile_cli_configures_without_graph_version(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph", "budget-profile-configure",
        "--ceiling-bytes", "7200",
        "--provider-id", "provider-a",
        "--model-id", "model-a",
        "--tokenizer-id", "tokenizer-a",
        "--tokenizer-revision", "revision-1",
    ])

    assert result.exit_code == 0, result.output
    assert fake.runtime_budget_profile == {
        "ceiling_bytes": 7200,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "tokenizer_id": "tokenizer-a",
        "tokenizer_revision": "revision-1",
    }


def test_research_graph_continuation_retargets_local_profile_without_new_record(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    fake.continuation_response = {
        "instance_id": "physical-v7",
        "work_package_id": "sgccs-work-package",
        "graph_version": 7,
        "branches": [{"branch_id": "branch-v7"}],
    }
    calls = []
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    monkeypatch.setattr(
        commands,
        "_client_for_profile",
        lambda _root, _profile_id: fake,
    )
    monkeypatch.setattr(
        commands,
        "load_profile_root",
        lambda _profile: tmp_path / "client-support",
    )
    monkeypatch.setattr(
        commands.LocalProfileStore,
        "retarget_research_incarnation",
        lambda self, profile_id, **kwargs: calls.append(
            (profile_id, kwargs)
        ) or {"research_records": [{"record_id": "sgccs-work-package"}]},
    )
    fake.profile_research_branch = {
        "report_checkpoint": {"checkpoint_ref": "trace:continued"}
    }
    monkeypatch.setattr(
        continuation_report,
        "continuation_narrative",
        lambda carrier: {"carrier": carrier["checkpoint_ref"]},
    )
    monkeypatch.setattr(
        continuation_report,
        "prepare_continuation_report_parent",
        lambda **_kwargs: {"component_id": "top-detour"},
    )
    publish_calls = []
    monkeypatch.setattr(
        continuation_report,
        "publish_research_checkpoint",
        lambda **kwargs: publish_calls.append(kwargs) or {
            "changed": True,
            "checkpoint_ref": "trace:continued",
            "artifact": {"artifact_ref": "artifact:continued"},
        },
    )

    result = CliRunner().invoke(cli, [
        "research-graph", "continue",
        "physical-v6", "branch-v6",
        "--target-version", "7",
        "--expected-target-hash", "c" * 64,
        "--profile-id", "maxa",
        "--agent-id", "research-maxa",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["local_profile_sync"] == {
        "status": "retargeted",
        "work_package_id": "sgccs-work-package",
        "target_instance_id": "physical-v7",
        "target_branch_id": "branch-v7",
    }
    assert payload["local_report_publish"] == {
        "status": "published",
        "changed": True,
        "checkpoint_ref": "trace:continued",
        "artifact_ref": "artifact:continued",
        "report_parent_id": "top-detour",
    }
    assert publish_calls[0]["report_parent_id"] == "top-detour"
    assert calls == [("maxa", {
        "agent_id": "research-maxa",
        "work_package_id": "sgccs-work-package",
        "source_instance_id": "physical-v6",
        "source_branch_id": "branch-v6",
        "target_instance_id": "physical-v7",
        "target_branch_id": "branch-v7",
    })]


def test_shadow_continuation_materializes_isolated_local_report(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    fake.continuation_response = {
        "instance_id": "shadow-v10",
        "work_package_id": "shadow-v10",
        "graph_version": 10,
        "mode": "shadow",
        "branches": [{"branch_id": "shadow-branch-v10"}],
    }
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    monkeypatch.setattr(
        commands,
        "_client_for_profile",
        lambda _root, _profile_id: fake,
    )
    monkeypatch.setattr(
        commands,
        "load_profile_root",
        lambda _profile: tmp_path / "client-support",
    )
    materialized = []
    monkeypatch.setattr(
        commands,
        "materialize_shadow_continuation_record",
        lambda **kwargs: materialized.append(kwargs) or {
            "source_work_package_id": "momentum-work-package",
            "record_id": "shadow-v10",
        },
    )
    monkeypatch.setattr(
        commands,
        "publish_continuation_report",
        lambda **kwargs: {
            "status": "published",
            "source_work_package_id": kwargs["source_work_package_id"],
        },
    )

    result = CliRunner().invoke(cli, [
        "research-graph", "continue",
        "physical-v8", "branch-v8",
        "--target-version", "10",
        "--mode", "shadow",
        "--shadow-run-id", "run-shadow",
        "--shadow-proposal-id", "proposal-v10",
        "--expected-target-hash", "c" * 64,
        "--profile-id", "maxa",
        "--agent-id", "research-maxa",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["local_profile_sync"] == {
        "status": "shadow_materialized",
        "work_package_id": "shadow-v10",
        "target_instance_id": "shadow-v10",
        "target_branch_id": "shadow-branch-v10",
        "source_work_package_id": "momentum-work-package",
    }
    assert payload["local_report_publish"] == {
        "status": "published",
        "source_work_package_id": "momentum-work-package",
    }
    assert materialized == [{
        "client_root": tmp_path / "client-support",
        "profile_id": "maxa",
        "agent_id": "research-maxa",
        "source_instance_id": "physical-v8",
        "source_branch_id": "branch-v8",
        "target_instance_id": "shadow-v10",
        "target_branch_id": "shadow-branch-v10",
        "target_work_package_id": "shadow-v10",
    }]


def test_research_graph_pretrial_continuation_omits_job_id(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()

    preview = runner.invoke(cli, [
        "research-graph", "continuation-preview",
        "instance-v6", "branch-v6",
        "--target-version", "7",
    ])
    continued = runner.invoke(cli, [
        "research-graph", "continue",
        "instance-v6", "branch-v6",
        "--target-version", "7",
        "--expected-target-hash", "c" * 64,
    ])

    assert preview.exit_code == 0
    assert continued.exit_code == 0
    assert fake.continuation_preview == (
        "instance-v6", "branch-v6", 7, "", "live", "", "",
    )
    assert fake.continuation == (
        "instance-v6", "branch-v6", 7, "", "c" * 64, "live", "", "",
    )


def test_research_graph_continuation_forwards_explicit_shadow_mode(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "research-graph", "continuation-preview",
        "instance-v8", "branch-v8",
        "--target-version", "9",
        "--mode", "shadow",
        "--shadow-run-id", "run-shadow",
        "--shadow-proposal-id", "proposal-v9",
    ])

    assert result.exit_code == 0, result.output
    assert fake.continuation_preview == (
        "instance-v8", "branch-v8", 9, "", "shadow",
        "run-shadow", "proposal-v9",
    )


def test_research_graph_rollback_requires_exact_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()
    diff_file = tmp_path / "rollback-diff.json"
    diff_file.write_text(json.dumps({"reason": "rollback pointer"}))
    reason = "shadow regression"

    proposed = runner.invoke(cli, [
        "research-graph", "propose", "factor-research", "2",
        "--risk-level", "L4",
        "--change-diff-file", str(diff_file),
        "--token-estimate", "100",
        "--agent-execution-id", "proposer-execution",
        "--conversation-ref", "auth-conversation:test-rollback",
        "--pointer-action", "rollback_graph_pointer",
        "--pointer-from-version", "4",
        "--pointer-reason", reason,
    ])
    authorized = runner.invoke(cli, [
        "research-graph", "human-authorize", "factor-research", "2",
        "--proposal-id", "proposal-1",
        "--graph-hash", "a" * 64,
        "--diff-hash", "b" * 64,
        "--conversation-ref", "auth-conversation:test-rollback",
        "--approval-ref", "auth-conversation-event:test-rollback",
        "--pointer-action", "rollback_graph_pointer",
        "--pointer-from-version", "4",
        "--pointer-reason", reason,
    ])
    rolled_back = runner.invoke(cli, [
        "research-graph", "rollback", "factor-research",
        "--target-version", "2",
        "--reason", reason,
        "--human-authorization-id", "gate-rollback-1",
    ])

    assert proposed.exit_code == 0
    assert authorized.exit_code == 0
    assert rolled_back.exit_code == 0
    assert fake.proposal[2]["pointer_action"] == "rollback_graph_pointer"
    assert fake.proposal[2]["pointer_from_version"] == 4
    assert fake.proposal[2]["pointer_reason"] == reason
    assert fake.authorization["pointer_action"] == "rollback_graph_pointer"
    assert fake.rollback == (
        "factor-research",
        {
            "target_version": 2,
            "reason": reason,
            "human_authorization_id": "gate-rollback-1",
        },
    )


def test_agent_flow_budget_commands_are_canonical_and_machine_readable(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(
        agent_flow_commands,
        "client_from_config",
        lambda: fake,
    )
    runner = CliRunner()

    help_result = runner.invoke(cli, ["agent-flow", "--help"])
    budget_help = runner.invoke(cli, ["agent-flow", "budget", "--help"])
    configured = runner.invoke(cli, [
        "agent-flow", "budget", "configure", "research-agent-1",
        "--token-limit", "2000",
    ])
    loaded = runner.invoke(cli, [
        "agent-flow", "budget", "load", "research-agent-1",
    ])
    reset = runner.invoke(cli, [
        "agent-flow", "budget", "reset", "research-agent-1",
    ])

    assert help_result.exit_code == 0
    assert "budget" in help_result.output
    assert "invocation" in help_result.output
    assert budget_help.exit_code == 0
    assert "configure" in budget_help.output
    assert "load" in budget_help.output
    assert "reset" in budget_help.output
    assert configured.exit_code == 0
    assert json.loads(configured.output)["token_limit"] == 2000
    assert loaded.exit_code == 0
    assert json.loads(loaded.output)["period_id"] == "period-1"
    assert reset.exit_code == 0
    assert json.loads(reset.output)["period_id"] == "period-2"
    assert fake.agent_budget_call == (
        "reset",
        "research-agent-1",
        {"token_limit": None},
    )


def test_agent_flow_invocation_commands_preserve_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(
        agent_flow_commands,
        "client_from_config",
        lambda: fake,
    )
    runner = CliRunner()
    context_file = tmp_path / "context-cost.json"
    context_file.write_text(json.dumps({
        "base_instructions": 40,
        "conversation": 60,
    }))

    reserved = runner.invoke(cli, [
        "agent-flow", "invocation", "reserve", "research-agent-1",
        "--sponsor-agent-id", "planner-agent-1",
        "--role", "researcher",
        "--authority-scope", "local_research",
        "--task-ref", "work-package-1",
        "--purpose", "test one preregistered hypothesis",
        "--runtime-id", "codex-local-1",
        "--model-id", "gpt-5",
        "--max-input-tokens", "500",
        "--max-output-tokens", "200",
        "--agent-principal-hash", "a" * 64,
        "--lineage-hash", "b" * 64,
        "--input-hash", "c" * 64,
        "--context-cost-file", str(context_file),
        "--idempotency-key", "invoke-work-package-1",
    ])

    assert reserved.exit_code == 0, reserved.output
    reserved_payload = json.loads(reserved.output)
    assert reserved_payload["invocation_id"] == "invocation-1"
    assert fake.agent_invocation_call == (
        "reserve",
        {
            "agent_id": "research-agent-1",
            "sponsor_agent_id": "planner-agent-1",
            "actor_role": "researcher",
            "authority_scope": "local_research",
            "task_ref": "work-package-1",
            "purpose": "test one preregistered hypothesis",
            "runtime_id": "codex-local-1",
            "model_id": "gpt-5",
            "max_input_tokens": 500,
            "max_output_tokens": 200,
            "agent_principal_hash": "a" * 64,
            "lineage_hash": "b" * 64,
            "input_hash": "c" * 64,
            "context_cost": {
                "base_instructions": 40,
                "conversation": 60,
            },
            "idempotency_key": "invoke-work-package-1",
        },
    )

    settled = runner.invoke(cli, [
        "agent-flow", "invocation", "settle", "invocation-1",
        "--input-tokens", "320",
        "--output-tokens", "120",
        "--cache-read-tokens", "30",
        "--provider-request-id", "provider-request-1",
        "--provider-attestation", "provider-attestation-1",
    ])
    assert settled.exit_code == 0, settled.output
    assert json.loads(settled.output)["status"] == "settled"
    assert fake.agent_invocation_call == (
        "settle",
        {
            "invocation_id": "invocation-1",
            "input_tokens": 320,
            "output_tokens": 120,
            "cache_read_tokens": 30,
            "provider_request_id": "provider-request-1",
            "provider_attestation": "provider-attestation-1",
        },
    )

    fallback = runner.invoke(cli, [
        "agent-flow", "invocation", "settle", "invocation-2",
        "--reserved-fallback",
        "--provider-request-id", "provider-request-without-usage",
    ])
    assert fallback.exit_code == 0, fallback.output
    assert fake.agent_invocation_call == (
        "settle",
        {
            "invocation_id": "invocation-2",
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_tokens": 0,
            "provider_request_id": "provider-request-without-usage",
            "provider_attestation": "",
        },
    )

    receipt_file = tmp_path / "provider-receipt.json"
    receipt_file.write_text(
        '{"provider_request_id":"provider-request-verified"}'
    )
    verified = runner.invoke(cli, [
        "agent-flow", "invocation", "settle", "invocation-3",
        "--provider-id", "provider-a",
        "--provider-receipt-file", str(receipt_file),
    ])
    assert verified.exit_code == 0, verified.output
    assert fake.agent_invocation_call == (
        "settle",
        {
            "invocation_id": "invocation-3",
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_tokens": 0,
            "provider_request_id": "",
            "provider_attestation": "",
            "provider_id": "provider-a",
            "provider_receipt": (
                '{"provider_request_id":"provider-request-verified"}'
            ),
        },
    )

    released = runner.invoke(cli, [
        "agent-flow", "invocation", "release", "invocation-1",
    ])
    assert released.exit_code == 0
    assert json.loads(released.output)["status"] == "released"


def test_agent_invocation_settle_rejects_ambiguous_usage_mode(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(
        agent_flow_commands,
        "client_from_config",
        lambda: fake,
    )
    runner = CliRunner()

    mixed = runner.invoke(cli, [
        "agent-flow", "invocation", "settle", "invocation-1",
        "--reserved-fallback",
        "--input-tokens", "10",
        "--output-tokens", "5",
    ])
    missing = runner.invoke(cli, [
        "agent-flow", "invocation", "settle", "invocation-1",
    ])

    assert mixed.exit_code != 0
    assert "不能与" in mixed.output
    assert missing.exit_code != 0
    assert "--reserved-fallback" in missing.output


def test_obsolete_research_graph_commands_are_absent() -> None:
    help_result = CliRunner().invoke(cli, ["research-graph", "--help"])

    assert help_result.exit_code == 0
    for command_name in (
        "agent-start",
        "budget-create",
        "token-reserve",
        "token-commit",
        "token-release",
        "backend-assure",
        "backend-verify",
        "approve-capability",
        "attest",
    ):
        assert command_name not in help_result.output


class _RecordingSession:
    def __init__(self) -> None:
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        return {"success": True, "budget_period": {"period_id": "period-1"}}

    def put(self, path, payload):
        self.calls.append(("PUT", path, payload))
        return {
            "success": True,
            "budget_period": {"token_limit": payload["token_limit"]},
        }

    def post(self, path, payload):
        self.calls.append(("POST", path, payload))
        if path.endswith("/settle"):
            return {"success": True, "invocation": {"status": "settled"}}
        if path.endswith("/release"):
            return {"success": True, "invocation": {"status": "released"}}
        if path == "/api/agent-flow/invocations":
            return {
                "success": True,
                "invocation": {"invocation_id": "invocation-1"},
            }
        return {
            "success": True,
            "budget_period": {"period_id": "period-2"},
        }


def test_agent_flow_client_is_a_thin_http_adapter() -> None:
    session = _RecordingSession()
    client = FactorTesterClient(session)

    client.load_agent_budget_period("agent-1")
    client.configure_agent_budget_period("agent-1", token_limit=2000)
    client.reset_agent_budget_period("agent-1", token_limit=None)
    client.reserve_agent_invocation(
        agent_id="agent-1",
        sponsor_agent_id="",
        actor_role="researcher",
        authority_scope="local_research",
        task_ref="task-1",
        purpose="research",
        runtime_id="codex-1",
        model_id="gpt-5",
        max_input_tokens=500,
        max_output_tokens=200,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
        input_hash="c" * 64,
        context_cost={"conversation": 10},
        idempotency_key="request-1",
    )
    client.settle_agent_invocation(
        "invocation-1",
        input_tokens=300,
        output_tokens=100,
        cache_read_tokens=20,
        provider_request_id="request-provider-1",
        provider_attestation="attestation-1",
    )
    client.release_agent_invocation("invocation-1")

    assert session.calls == [
        ("GET", "/api/agent-flow/agents/agent-1/budget", None),
        (
            "PUT",
            "/api/agent-flow/agents/agent-1/budget",
            {"token_limit": 2000},
        ),
        (
            "POST",
            "/api/agent-flow/agents/agent-1/budget/reset",
            {"token_limit": None},
        ),
        (
            "POST",
            "/api/agent-flow/invocations",
            {
                "agent_id": "agent-1",
                "sponsor_agent_id": "",
                "actor_role": "researcher",
                "authority_scope": "local_research",
                "task_ref": "task-1",
                "purpose": "research",
                "runtime_id": "codex-1",
                "model_id": "gpt-5",
                "max_input_tokens": 500,
                "max_output_tokens": 200,
                "agent_principal_hash": "a" * 64,
                "lineage_hash": "b" * 64,
                "input_hash": "c" * 64,
                "context_cost": {"conversation": 10},
                "idempotency_key": "request-1",
            },
        ),
        (
            "POST",
            "/api/agent-flow/invocations/invocation-1/settle",
            {
                "input_tokens": 300,
                "output_tokens": 100,
                "cache_read_tokens": 20,
                "provider_request_id": "request-provider-1",
                "provider_attestation": "attestation-1",
            },
        ),
        (
            "POST",
            "/api/agent-flow/invocations/invocation-1/release",
            {},
        ),
    ]


def test_trial_plan_revise_forwards_exact_cas_and_body(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    plan = {"schema_version": 5, "trial_plan_id": "plan-1"}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "research-graph", "trial-plan-revise", "instance-1", "branch-1",
        "--expected-latest-trace-id", "trace-1",
        "--expected-checkpoint-hash", "a" * 64,
        "--expected-trial-plan-hash", "c" * 64,
        "--trial-plan-file", str(path),
        "--acting-profile-ref", "profile:maxa",
    ])

    assert result.exit_code == 0, result.output
    assert fake.trial_plan_revision == (
        "instance-1",
        "branch-1",
        {
            "expected_latest_trace_id": "trace-1",
            "expected_checkpoint_hash": "a" * 64,
            "expected_trial_plan_hash": "c" * 64,
            "trial_plan": plan,
            "acting_profile_ref": "profile:maxa",
        },
    )
