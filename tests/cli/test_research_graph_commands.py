from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_graph as commands


class FakeClient:
    def __init__(self) -> None:
        self.published = None
        self.validation = None
        self.proposal = None
        self.review = None

    def publish_research_graph(self, graph):
        self.published = graph
        return graph

    def list_research_graph_versions(self, graph_id):
        return [{"graph_id": graph_id, "version": 2, "lifecycle": "draft"}]

    def get_active_research_graph(self, graph_id):
        return {"graph_id": graph_id, "version": 3, "lifecycle": "active"}

    def validate_research_graph(self, graph_id, version, evidence):
        self.validation = (graph_id, version, evidence)
        return {"validation_id": "validation-1", "evidence": evidence}

    def audit_research_graph(
        self, graph_id, version, *, disposition, grill_evidence,
    ):
        return {
            "audit_id": "audit-1",
            "disposition": disposition,
            "grill_evidence": grill_evidence,
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
            "version": version + 1,
            "lifecycle": "active",
            "human_authorization_id": human_authorization_id,
        }

    def propose_research_graph(self, graph_id, version, **kwargs):
        self.proposal = (graph_id, version, kwargs)
        return {"proposal_id": "proposal-1", **kwargs}

    def review_research_graph_proposal(self, proposal_id, **kwargs):
        self.review = (proposal_id, kwargs)
        return {"review_id": "review-1", **kwargs}

    def rollback_research_graph(self, graph_id, **kwargs):
        return {"graph_id": graph_id, "from_version": 5, "to_version": kwargs["target_version"]}

    def create_research_graph_instance(self, **kwargs):
        return {
            "instance_id": "instance-1",
            **kwargs,
            "branches": [{"branch_id": "branch-1", "status": "running"}],
        }

    def create_research_agent_execution(self, **kwargs):
        return {"execution_id": "execution-1", **kwargs}

    def approve_research_capability(self, **kwargs):
        return {"approval_id": "approval-1", **kwargs}

    def attest_research_capabilities(self, payload):
        return {
            "receipt_id": "receipt-1",
            "resolver_attestation": "a" * 64,
            **payload,
        }

    def create_research_token_budget(self, **kwargs):
        return {"used_tokens": 0, "reserved_tokens": 0, **kwargs}

    def reserve_research_tokens(self, scope_id, **kwargs):
        return {
            "reservation_id": "reservation-1",
            "scope_id": scope_id,
            "status": "granted",
            **kwargs,
        }

    def commit_research_tokens(self, reservation_id, **kwargs):
        return {"reservation_id": reservation_id, "status": "committed"}

    def release_research_tokens(self, reservation_id):
        return {"reservation_id": reservation_id, "status": "released"}

    def get_research_graph_branch_context(self, instance_id, branch_id):
        return {
            "graph": "factor-research@v3",
            "branch": {"instance_id": instance_id, "branch_id": branch_id},
            "node": {"node_id": "hypothesis"},
        }

    def get_research_graph_branch_next(self, instance_id, branch_id):
        return {
            "graph": "factor-research@v3",
            "branch": {"instance_id": instance_id, "branch_id": branch_id},
            "node": {"node_id": "hypothesis"},
            "candidate_edges": [],
            "requires_agent_judgment": False,
        }


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
    assert '"lifecycle": "active"' in active.output


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
        "--replay-passed",
        "--shadow-passed",
        "--capability-resolution-complete",
        "--unaffected-jobs-preserved",
        "--token-efficiency-passed",
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
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_measurement_refs": {
                "routine_instance_id": "instance-shadow-1",
                "routine_branch_id": "branch-shadow-1",
                "baseline_run_id": "run-baseline-1",
            },
        },
    )


def test_research_graph_start_consumes_capability_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(json.dumps({
        "receipt": {
            "receipt_id": "receipt-1",
            "resolver_attestation": "a" * 64,
        }
    }))

    result = CliRunner().invoke(cli, [
        "research-graph",
        "start",
        "factor-research",
        "--product-group",
        "china_futures",
        "--workspace-id",
        "workspace-1",
        "--capability-receipt-file",
        str(receipt_file),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["graph_id"] == "factor-research"
    assert payload["product_group"] == "china_futures"
    assert payload["capability_receipt"]["receipt_id"] == "receipt-1"


def test_research_graph_next_and_bounded_review_commands(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()
    diff_file = tmp_path / "diff.json"
    diff_file.write_text(json.dumps({"reason": "semantic edge change"}))

    next_result = runner.invoke(cli, [
        "research-graph", "next", "instance-1", "branch-1",
    ])
    proposed = runner.invoke(cli, [
        "research-graph", "propose", "factor-research", "2",
        "--risk-level", "L4",
        "--change-diff-file", str(diff_file),
        "--evidence-ref", "artifact:counterexample",
        "--token-estimate", "400",
        "--agent-execution-id", "proposer-execution",
    ])
    reviewed = runner.invoke(cli, [
        "research-graph", "review", "proposal-1",
        "--disposition", "approved",
        "--evidence-ref", "artifact:review",
        "--agent-execution-id", "reviewer-execution",
    ])

    assert next_result.exit_code == 0
    assert '"node_id": "hypothesis"' in next_result.output
    assert '"candidate_edges": []' in next_result.output
    assert proposed.exit_code == 0
    assert reviewed.exit_code == 0
    assert fake.proposal[2]["token_estimate"] == 400
    assert fake.proposal[2]["agent_execution_id"] == "proposer-execution"
    assert fake.review[1]["scope_drift"] is False


def test_research_graph_capability_attestation_cli(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()
    resolution_file = tmp_path / "resolution.json"
    resolution_file.write_text(json.dumps({"resolution": {
        "node_id": "hypothesis",
        "catalog_hash": "c" * 64,
        "provider_conformance_hash": "e" * 64,
        "bindings": [],
        "gaps": [],
    }}))
    approvals_file = tmp_path / "approvals.json"
    approvals_file.write_text("{}")

    result = runner.invoke(cli, [
        "research-graph", "attest", "factor-research", "3",
        "--node", "hypothesis",
        "--product-group", "china_futures",
        "--resolution-file", str(resolution_file),
        "--approval-refs-file", str(approvals_file),
        "--product-profile-hash", "d" * 64,
        "--resolver-version", "resolver-v1",
    ])

    assert result.exit_code == 0
    assert '"receipt_id": "receipt-1"' in result.output


def test_research_graph_token_budget_cli_denies_work_before_agent_launch(
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    runner = CliRunner()

    created = runner.invoke(cli, [
        "research-graph", "budget-create", "proposal:factor-research:2",
        "--token-limit", "2000",
    ])
    reserved = runner.invoke(cli, [
        "research-graph", "token-reserve", "proposal:factor-research:2",
        "--work-kind", "reviewer",
        "--max-input-tokens", "500",
        "--max-output-tokens", "200",
    ])
    agent = runner.invoke(cli, [
        "research-graph", "agent-start",
        "--role", "reviewer",
        "--reservation-id", "reservation-1",
        "--agent-principal-hash", "a" * 64,
        "--lineage-hash", "b" * 64,
        "--launcher-attestation", "c" * 64,
    ])

    assert created.exit_code == 0
    assert reserved.exit_code == 0
    assert agent.exit_code == 0
    assert '"reservation_id": "reservation-1"' in reserved.output
