from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.client import FactorTesterClient
from tools.cli.commands import agent_flow as agent_flow_commands
from tools.cli.commands import research_graph as commands
from tools.cli.http import HttpClientError


class FakeClient:
    def __init__(self) -> None:
        self.published = None
        self.validation = None
        self.proposal = None
        self.review = None
        self.authorization = None
        self.rollback = None
        self.agent_budget_call = None
        self.agent_invocation_call = None

    def publish_research_graph(self, graph):
        self.published = graph
        return graph

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

    def evaluate_backend_assurance(self, **kwargs):
        return {
            "receipt_id": "assurance-1",
            "disposition": "trusted",
            "requires_verifier": False,
            **kwargs,
        }

    def verify_backend_assurance(self, receipt_id, **kwargs):
        return {
            "receipt_id": receipt_id,
            "disposition": "verifier_required",
            **kwargs,
        }

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

    def load_agent_budget_period(self, agent_id):
        self.agent_budget_call = ("load", agent_id, {})
        return {
            "period_id": "period-1",
            "agent_id": agent_id,
            "token_limit": 2000,
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
    assert '"is_active": true' in active.output
    assert '"version": 2' in active.output


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
        "proposal-1",
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
        "--conversation-ref", "auth-conversation:test-cli",
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
    assert (
        fake.proposal[2]["conversation_ref"]
        == "auth-conversation:test-cli"
    )
    assert fake.review[1]["scope_drift"] is False


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
        "--authority-scope", "local_research",
        "--agent-principal-hash", "a" * 64,
        "--lineage-hash", "b" * 64,
        "--launcher-attestation", "c" * 64,
    ])

    assert created.exit_code == 0
    assert reserved.exit_code == 0
    assert agent.exit_code == 0
    assert '"reservation_id": "reservation-1"' in reserved.output


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

    released = runner.invoke(cli, [
        "agent-flow", "invocation", "release", "invocation-1",
    ])
    assert released.exit_code == 0
    assert json.loads(released.output)["status"] == "released"


def test_legacy_graph_agent_and_token_commands_are_deprecated() -> None:
    help_result = CliRunner().invoke(cli, ["research-graph", "--help"])

    assert help_result.exit_code == 0
    for command_name in (
        "agent-start",
        "budget-create",
        "token-reserve",
        "token-commit",
        "token-release",
    ):
        command_line = next(
            line for line in help_result.output.splitlines()
            if command_name in line
        )
        assert "deprecated" in command_line.lower()


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


def test_research_graph_backend_assurance_commands_are_deprecated(
    monkeypatch,
) -> None:
    class GoneSession:
        def post(self, path, payload):
            raise HttpClientError(
                410,
                f"http://test{path}",
                '{"error":"retired"}',
            )

    monkeypatch.setattr(
        commands,
        "client_from_config",
        lambda: FactorTesterClient(GoneSession()),
    )
    runner = CliRunner()

    graph_help = runner.invoke(cli, ["research-graph", "--help"])
    assure_help = runner.invoke(
        cli,
        ["research-graph", "backend-assure", "--help"],
    )
    verify_help = runner.invoke(
        cli,
        ["research-graph", "backend-verify", "--help"],
    )
    assured = runner.invoke(cli, [
        "research-graph", "backend-assure", "job-1",
        "--instance-id", "instance-1",
        "--branch-id", "branch-1",
        "--node-id", "authoritative-backtest",
    ])
    verified = runner.invoke(cli, [
        "research-graph", "backend-verify", "assurance-1",
        "--verifier-execution-id", "verifier-1",
        "--disposition", "confirmed_reliable",
        "--evidence-ref", "artifact:verification-1",
    ])

    assert graph_help.exit_code == 0
    for command_name in ("backend-assure", "backend-verify"):
        assert command_name in graph_help.output
    assert graph_help.output.count("(DEPRECATED)") >= 7
    for result in (assure_help, verify_help, assured, verified):
        assert "job show/detail" in result.output
        assert "evidence.terminal_assurance" in result.output
        assert "Maintenance Case" in result.output
    assert assured.exit_code == 1
    assert verified.exit_code == 1
