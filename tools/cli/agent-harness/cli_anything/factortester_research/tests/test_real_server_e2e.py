from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.request import Request, urlopen

from werkzeug.serving import make_server

import settings as Settings
from server import create_app
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services import research_runs


def _installed_cli(name: str) -> list[str]:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} not found in PATH; install the release candidate first"
        )
    print(f"[_resolve_cli] Using installed command: {path}")
    return [path]


def _run(
    command: list[str],
    args: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command + args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if check and result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {command + args}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _run_json(
    command: list[str],
    args: list[str],
    *,
    env: dict[str, str],
) -> Any:
    result = _run(command, args, env=env)
    return json.loads(result.stdout)


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode())
    assert isinstance(value, dict)
    return value


@contextmanager
def _real_server(
    tmp_path: Path,
    monkeypatch,
) -> Iterator[str]:
    database = tmp_path / "server" / "factortester.sqlite"
    database.parent.mkdir(parents=True)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    monkeypatch.setattr(Settings, "CACHE_DIR", database.parent)
    monkeypatch.setenv("FLASK_SECRET_KEY", secrets.token_hex(32))
    app = create_app()
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=10)
        httpd.server_close()


def _commit_usage(
    *,
    factortester: list[str],
    env: dict[str, str],
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    invocation = _run_json(
        factortester,
        [
            "agent-flow",
            "invocation",
            "reserve",
            agent_id,
            "--role",
            "researcher",
            "--authority-scope",
            "local_research",
            "--purpose",
            "record real-server E2E token usage",
            "--runtime-id",
            "e2e-runtime",
            "--model-id",
            "e2e-model",
            "--max-input-tokens",
            str(input_tokens),
            "--max-output-tokens",
            str(output_tokens),
            "--agent-principal-hash",
            principal_hash,
            "--lineage-hash",
            lineage_hash,
            "--idempotency-key",
            f"e2e-usage-{uuid.uuid4().hex}",
        ],
        env=env,
    )
    settled = _run_json(
        factortester,
        [
            "agent-flow",
            "invocation",
            "settle",
            invocation["invocation_id"],
            "--input-tokens",
            str(input_tokens),
            "--output-tokens",
            str(output_tokens),
            "--provider-request-id",
            f"e2e-provider-request-{uuid.uuid4().hex}",
        ],
        env=env,
    )
    assert settled["status"] == "settled"
    return invocation["invocation_id"]


def _agent_invocation(
    *,
    factortester: list[str],
    env: dict[str, str],
    role: str,
) -> dict:
    authority_scope = (
        "server_backend_code"
        if role in {"implementation_agent", "backend_verifier"}
        else "local_research"
    )
    agent_id = f"e2e:{role}:{uuid.uuid4().hex}"
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    invocation = _run_json(
        factortester,
        [
            "agent-flow",
            "invocation",
            "reserve",
            agent_id,
            "--role",
            role,
            "--authority-scope",
            authority_scope,
            "--purpose",
            f"real-server E2E {role}",
            "--runtime-id",
            "e2e-runtime",
            "--model-id",
            "e2e-model",
            "--max-input-tokens",
            "400",
            "--max-output-tokens",
            "200",
            "--agent-principal-hash",
            principal_hash,
            "--lineage-hash",
            lineage_hash,
            "--idempotency-key",
            f"e2e-{role}-{uuid.uuid4().hex}",
        ],
        env=env,
    )
    settled = _run_json(
        factortester,
        [
            "agent-flow",
            "invocation",
            "settle",
            invocation["invocation_id"],
            "--input-tokens",
            "10",
            "--output-tokens",
            "5",
            "--provider-request-id",
            f"e2e-provider-request-{uuid.uuid4().hex}",
        ],
        env=env,
    )
    assert settled["status"] == "settled"
    return invocation | settled


def _capability_resolution(
    *,
    factortester: list[str],
    env: dict[str, str],
    tmp_path: Path,
    graph: dict,
    graph_version: int,
    node_id: str,
    product_group: str,
    shadow_mode: bool,
) -> dict:
    node = next(
        item for item in graph["nodes"] if item["node_id"] == node_id
    )
    descriptors = graph["capability_descriptors"]
    bindings = []
    for capability_id in node.get("required_capabilities") or []:
        descriptor = descriptors[capability_id]
        bindings.append({
            "capability_id": capability_id,
            "capability_description": descriptor[
                "capability_description"
            ],
            "descriptor_hash": descriptor["descriptor_hash"],
        })
    resolution = {
        "node_id": node_id,
        "catalog_hash": "c" * 64,
        "provider_conformance_hash": "e" * 64,
        "bindings": bindings,
        "gaps": [],
        "triggered_conditional_bindings": [],
        "triggered_conditional_gaps": [],
        "undetermined_conditions": [],
    }
    return resolution


def test_installed_clis_drive_real_server_active_graph_e2e(
    tmp_path: Path,
    monkeypatch,
) -> None:
    factortester = _installed_cli("factortester")
    harness = _installed_cli("cli-anything-factortester-research")
    cli_home = tmp_path / "cli-home"
    env = {
        **os.environ,
        "FACTORTESTER_HOME": str(cli_home),
        "CLI_ANYTHING_FORCE_INSTALLED": "1",
    }
    with _real_server(tmp_path, monkeypatch) as base_url:
        alias = f"e2e_{uuid.uuid4().hex[:10]}"
        password = secrets.token_urlsafe(18)
        registered = _post_json(
            f"{base_url}/register",
            {"username": alias, "password": password},
        )
        assert registered["success"] is True
        owner = registered["username"]

        _run(
            factortester,
            ["configure", "--base-url", base_url],
            env=env,
        )
        login = _run(
            factortester,
            [
                "login",
                "--username",
                alias,
                "--password",
                password,
                "--keep-login",
            ],
            env=env,
        )
        assert "keep_login=true" in login.stdout
        assert (cli_home / "cookies.lwp").is_file()
        assert _run_json(
            factortester,
            ["research-graph", "versions", "factor-research"],
            env=env,
        ) == []

        graph = _run_json(
            harness,
            ["graph", "draft", "--json"],
            env=env,
        )
        graph_file = tmp_path / "draft-graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        published = _run_json(
            factortester,
            ["research-graph", "publish", str(graph_file)],
            env=env,
        )
        assert published["content_hash"] == graph["content_hash"]

        proposer = _agent_invocation(
            factortester=factortester,
            env=env,
            role="proposer",
        )
        reviewer = _agent_invocation(
            factortester=factortester,
            env=env,
            role="reviewer",
        )
        assert proposer["invocation_id"] != reviewer["invocation_id"]
        assert proposer["owner_user_id"] == reviewer["owner_user_id"] == owner

        change_file = tmp_path / "change.json"
        change_file.write_text(
            json.dumps({
                "old_hash": "observed",
                "new_hash": graph["content_hash"],
                "reason": "real installed CLI E2E activation",
                "rollback_target": 1,
            }),
            encoding="utf-8",
        )
        proposal = _run_json(
            factortester,
            [
                "research-graph",
                "propose",
                graph["graph_id"],
                str(graph["version"]),
                "--risk-level",
                "L4",
                "--change-diff-file",
                str(change_file),
                "--evidence-ref",
                "e2e:proposal",
                "--token-estimate",
                "500",
                "--agent-execution-id",
                proposer["invocation_id"],
                "--conversation-ref",
                "auth-conversation:e2e-active-graph",
            ],
            env=env,
        )
        review = _run_json(
            factortester,
            [
                "research-graph",
                "review",
                proposal["proposal_id"],
                "--disposition",
                "approved",
                "--evidence-ref",
                "e2e:independent-review",
                "--agent-execution-id",
                reviewer["invocation_id"],
            ],
            env=env,
        )
        assert review["reviewer_execution_id"] == reviewer["invocation_id"]

        workspace_id = f"e2e-workspace-{uuid.uuid4().hex}"
        run_spec = {
            "workspace_id": workspace_id,
            "factor": "e2e-factor",
            "window": ["2020-01-01", "2024-12-31"],
        }
        graph_run = research_runs.create_run(
            owner=owner,
            workspace_id=workspace_id,
            configuration_id=f"graph-{uuid.uuid4().hex}",
            configuration_revision=1,
            run_spec=run_spec,
        )
        baseline_run = research_runs.create_run(
            owner=owner,
            workspace_id=workspace_id,
            configuration_id=f"baseline-{uuid.uuid4().hex}",
            configuration_revision=1,
            run_spec=run_spec,
        )
        entry_node = graph["entry_node"]
        shadow_resolution = _capability_resolution(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=graph["version"],
            node_id=entry_node,
            product_group="equities",
            shadow_mode=True,
        )
        shadow_resolution_file = tmp_path / "shadow-resolution.json"
        shadow_resolution_file.write_text(
            json.dumps(shadow_resolution),
            encoding="utf-8",
        )
        shadow_instance = _run_json(
            factortester,
            [
                "research-graph",
                "start",
                graph["graph_id"],
                "--product-group",
                "equities",
                "--workspace-id",
                workspace_id,
                "--shadow-graph-version",
                str(graph["version"]),
                "--shadow-run-id",
                graph_run["run_id"],
                "--capability-resolution-file",
                str(shadow_resolution_file),
            ],
            env=env,
        )
        shadow_branch_id = shadow_instance["branches"][0]["branch_id"]
        resume = _run_json(
            factortester,
            [
                "agent-flow",
                "resume",
                f"instance:{shadow_instance['instance_id']}",
                "--role",
                "research",
                "--instance-id",
                shadow_instance["instance_id"],
                "--branch-id",
                shadow_branch_id,
            ],
            env=env,
        )
        assert resume["packet_bytes"] <= 6000
        assert resume["research"]["branch"]["branch_id"] == (
            shadow_branch_id
        )
        _commit_usage(
            factortester=factortester,
            env=env,
            agent_id=f"instance:{shadow_instance['instance_id']}",
            input_tokens=70,
            output_tokens=10,
        )
        baseline_scope = f"research-run:{baseline_run['run_id']}"
        _run_json(
            factortester,
            [
                "agent-flow",
                "budget",
                "configure",
                baseline_scope,
                "--token-limit",
                "1000",
            ],
            env=env,
        )
        _commit_usage(
            factortester=factortester,
            env=env,
            agent_id=baseline_scope,
            input_tokens=90,
            output_tokens=10,
        )

        validation = _run_json(
            factortester,
            [
                "research-graph",
                "validate",
                graph["graph_id"],
                str(graph["version"]),
                "--proposal-id",
                proposal["proposal_id"],
                "--routine-instance-id",
                shadow_instance["instance_id"],
                "--routine-branch-id",
                shadow_branch_id,
                "--baseline-run-id",
                baseline_run["run_id"],
            ],
            env=env,
        )
        assert validation["evidence"]["evidence_authority"] == "server_derived"
        assert validation["evidence"]["replay_passed"] is True
        assert validation["evidence"]["shadow_passed"] is True
        assert validation["evidence"]["replay_summary"]["passed"] is True
        assert (
            validation["evidence"]["shadow_summary"]["equivalent"]
            is True
        )
        metrics = validation["evidence"]["token_metrics"]
        assert metrics["shadow_graph_total_tokens"] == 80
        assert metrics["shadow_baseline_total_tokens"] == 100
        assert metrics["routine_context_bytes"] <= 6000
        assert metrics["token_authority"] == "normalized_agent_invocations"

        grill_file = tmp_path / "grill.json"
        grill_file.write_text(
            json.dumps([{
                "question": "Are activation gates server-derived?",
                "answer": "Yes; this E2E verified their owned references.",
                "status": "pass",
            }]),
            encoding="utf-8",
        )
        _run_json(
            factortester,
            [
                "research-graph",
                "audit",
                graph["graph_id"],
                str(graph["version"]),
                "--disposition",
                "approved",
                "--grill-evidence-file",
                str(grill_file),
                "--proposal-id",
                proposal["proposal_id"],
                "--grill-ref",
                "grill-with-docs:e2e-active-graph",
            ],
            env=env,
        )
        authorization = _run_json(
            factortester,
            [
                "research-graph",
                "human-authorize",
                graph["graph_id"],
                str(graph["version"]),
                "--proposal-id",
                proposal["proposal_id"],
                "--graph-hash",
                graph["content_hash"],
                "--diff-hash",
                proposal["diff_hash"],
                "--conversation-ref",
                "auth-conversation:e2e-active-graph",
                "--approval-ref",
                "auth-conversation-event:e2e-approval",
            ],
            env=env,
        )
        active = _run_json(
            factortester,
            [
                "research-graph",
                "activate",
                graph["graph_id"],
                str(graph["version"]),
                "--human-authorization-id",
                authorization["authorization_id"],
            ],
            env=env,
        )
        assert active["lifecycle"] == "draft"
        assert active["version"] == graph["version"]
        assert active["active_pointer"]["version"] == graph["version"]

        live_entry_resolution = _capability_resolution(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=active["version"],
            node_id=entry_node,
            product_group="equities",
            shadow_mode=False,
        )
        live_entry_file = tmp_path / "live-entry-resolution.json"
        live_entry_file.write_text(
            json.dumps(live_entry_resolution),
            encoding="utf-8",
        )
        live_instance = _run_json(
            factortester,
            [
                "research-graph",
                "start",
                graph["graph_id"],
                "--product-group",
                "equities",
                "--workspace-id",
                workspace_id,
                "--capability-resolution-file",
                str(live_entry_file),
            ],
            env=env,
        )
        live_branch = live_instance["branches"][0]
        repository = JobRepository()
        assurance_job = repository.create(JobRecord(
            job_id=uuid.uuid4().hex,
            run_id=graph_run["run_id"],
            owner=owner,
            workspace_id=workspace_id,
            kind="backtest",
            status=JobStatus.SUBMITTED,
            source_revision="e2e-backend-revision",
            runner_path="e2e:runner",
            job_spec={
                "run_id": graph_run["run_id"],
                "workspace_id": workspace_id,
                "run_spec": run_spec,
            },
            run_spec_hash=graph_run["run_spec_hash"],
        ))
        repository.transition(
            assurance_job.job_id,
            JobStatus.PLANNING,
        )
        repository.set_execution_plan(
            assurance_job.job_id,
            plan={"runner": "e2e:runner", "steps": ["compute"]},
            notices=[],
            requires_confirmation=False,
        )
        repository.transition(
            assurance_job.job_id,
            JobStatus.RUNNING,
            worker_pid=123,
        )
        repository.transition(
            assurance_job.job_id,
            JobStatus.SUCCEEDED,
            worker_exitcode=0,
            result_summary={"sharpe": 1.2, "observations": 1000},
        )
        job_detail = _run_json(
            factortester,
            [
                "job",
                "status",
                assurance_job.job_id,
            ],
            env=env,
        )
        assurance = job_detail["evidence"]["terminal_assurance"]
        assert assurance["disposition"] == "trusted"
        assert assurance["anomaly_codes"] == []
        context = _run_json(
            factortester,
            [
                "research-graph",
                "context",
                live_instance["instance_id"],
                live_branch["branch_id"],
            ],
            env=env,
        )
        cycle_session = tmp_path / "cycle-session.json"
        next_packet = _run_json(
            harness,
            [
                "--session",
                str(cycle_session),
                "cycle",
                "next",
                live_instance["instance_id"],
                live_branch["branch_id"],
                "--json",
            ],
            env=env,
        )
        assert context["context_bytes"] <= 6000
        assert "candidate_edges" not in context
        assert next_packet["next_bytes"] <= 6000
        assert "candidate_edges" in next_packet
        assert "required_capabilities" not in next_packet

        edge = next(
            item for item in graph["edges"]
            if item["from_node"] == entry_node
        )
        transition_invocation_id = _commit_usage(
            factortester=factortester,
            env=env,
            agent_id=f"instance:{live_instance['instance_id']}",
            input_tokens=12,
            output_tokens=3,
        )
        target_resolution = _capability_resolution(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=active["version"],
            node_id=edge["to_node"],
            product_group="equities",
            shadow_mode=False,
        )
        target_resolution_file = tmp_path / "target-resolution.json"
        target_resolution_file.write_text(
            json.dumps(target_resolution),
            encoding="utf-8",
        )
        evidence = {
            **(edge.get("guard") or {}),
            "evidence_refs": ["e2e:transition"],
            "agent_invocation_ids": [transition_invocation_id],
        }
        evidence_file = tmp_path / "transition-evidence.json"
        evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
        cycle_advanced = _run_json(
            harness,
            [
                "--session",
                str(cycle_session),
                "cycle",
                "advance",
                live_instance["instance_id"],
                live_branch["branch_id"],
                "--edge-id",
                edge["edge_id"],
                "--evidence-file",
                str(evidence_file),
                "--target-capability-resolution-file",
                str(target_resolution_file),
                "--json",
            ],
            env=env,
        )
        advanced = cycle_advanced["backend"]
        assert advanced["current_node"] == edge["to_node"]
        assert cycle_advanced["local_validation"]["proposal_count"] == 0
        assert cycle_session.is_file()

        _run(factortester, ["logout"], env=env)
        after_logout = _run(
            factortester,
            ["research-graph", "versions", graph["graph_id"]],
            env=env,
            check=False,
        )
        assert after_logout.returncode != 0
        assert (
            "401" in after_logout.stderr
            or "factortester login" in after_logout.stderr
        )
