from __future__ import annotations

from copy import deepcopy
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
from server.services import research_graphs, research_runs
from server.services.research_evidence_catalog import (
    create_evidence,
    put_source_capture,
    put_source_fragment,
)
from server.services.agent_flow.verified_usage import (
    VerifiedProviderUsage,
    clear_usage_receipt_verifiers,
    register_usage_receipt_verifier,
)
from server.services.research_graph.branch.report_coverage import (
    expected_report_bindings,
)
from server.services.research_graph.packet_budget import graph_packet_budget
from server.services.research_graph.protocol import graph_content_hash
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.local_profile_contracts import new_local_profile
from tools.cli.release.research_reporting.workspace import (
    initialize_work_package,
)
from tools.cli.release.research_reporting.report_items import report_fragment_hash


class _E2EUsageVerifier:
    """Test Provider adapter exercising the public receipt path."""

    def verify(self, receipt: str, *, reservation: dict) -> VerifiedProviderUsage:
        payload = json.loads(receipt)
        expected = {
            key: reservation[key]
            for key in (
                "invocation_id",
                "agent_id",
                "task_ref",
                "runtime_id",
                "model_id",
                "lineage_hash",
                "input_hash",
            )
        }
        if payload.get("reservation") != expected:
            raise ValueError("E2E usage receipt does not match reservation")
        return VerifiedProviderUsage(
            provider_id="e2e-provider",
            provider_request_id=str(payload["provider_request_id"]),
            input_tokens=int(payload["input_tokens"]),
            output_tokens=int(payload["output_tokens"]),
            cache_read_tokens=int(payload["cache_read_tokens"]),
            provider_attestation=str(payload["provider_attestation"]),
            launcher_attestation="verified-by:e2e-provider@1",
        )


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
    clear_usage_receipt_verifiers()
    register_usage_receipt_verifier(
        "e2e-provider",
        _E2EUsageVerifier(),
    )
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
        clear_usage_receipt_verifiers()


def _commit_usage(
    *,
    factortester: list[str],
    env: dict[str, str],
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
    receipt_dir: Path,
    task_ref: str = "",
    lineage_hash: str = "",
    input_hash: str = "",
    verified: bool = False,
    role: str = "researcher",
) -> str:
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_value = (
        lineage_hash or hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    )
    reserve_args = [
        "agent-flow",
        "invocation",
        "reserve",
        agent_id,
        "--role",
        role,
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
        lineage_value,
        "--idempotency-key",
        f"e2e-usage-{uuid.uuid4().hex}",
    ]
    if task_ref:
        reserve_args.extend(["--task-ref", task_ref])
    if input_hash:
        reserve_args.extend(["--input-hash", input_hash])
    invocation = _run_json(
        factortester,
        reserve_args,
        env=env,
    )
    settle_args = [
        "agent-flow",
        "invocation",
        "settle",
        invocation["invocation_id"],
    ]
    if verified:
        receipt_path = receipt_dir / f"{invocation['invocation_id']}.json"
        receipt_path.write_text(
            json.dumps({
                "provider_request_id": f"e2e-{uuid.uuid4().hex}",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": 0,
                "provider_attestation": "signed-e2e-usage",
                "reservation": {
                    "invocation_id": invocation["invocation_id"],
                    "agent_id": agent_id,
                    "task_ref": task_ref,
                    "runtime_id": "e2e-runtime",
                    "model_id": "e2e-model",
                    "lineage_hash": lineage_value,
                    "input_hash": input_hash,
                },
            }),
            encoding="utf-8",
        )
        settle_args.extend([
            "--provider-id",
            "e2e-provider",
            "--provider-receipt-file",
            str(receipt_path),
        ])
    else:
        settle_args.extend([
            "--input-tokens",
            str(input_tokens),
            "--output-tokens",
            str(output_tokens),
            "--provider-request-id",
            f"e2e-provider-request-{uuid.uuid4().hex}",
        ])
    settled = _run_json(
        factortester,
        settle_args,
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


def _bind_local_research_report(
    *,
    env: dict[str, str],
    base_url: str,
    instance_id: str,
    branch_id: str,
) -> tuple[str, str, str]:
    """Give the E2E Graph branch the same local identity as real research."""
    client_root = Path(env["FACTORTESTER_CLIENT_ROOT"])
    profile_id = "e2e-maxa"
    agent_id = "research-e2e"
    work_package_id = f"e2e-{instance_id[:24]}-{branch_id[:24]}"
    workspace_root = client_root / "workspaces" / profile_id
    store = LocalProfileStore(client_root)
    try:
        profile = store.load(profile_id)
    except ValueError:
        profile = new_local_profile(
            profile_id=profile_id,
            display_name="E2E MaxA",
            server_url=base_url,
            workspace_root=workspace_root,
        )
    branch_ref = f"graph-branch:{instance_id}:{branch_id}"
    profile["agents"] = [{
        "agent_id": agent_id,
        "role": "research",
        "scope": {"instance_id": instance_id, "branch_id": branch_id},
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    }]
    initialized = initialize_work_package(
        workspace_root=workspace_root,
        work_package_id=work_package_id,
        branch_id=branch_id,
        workspace_id="e2e-workspace",
        title="Active Graph E2E",
        branch_ref=branch_ref,
    )
    record = {
        "record_id": work_package_id,
        "title": "Active Graph E2E",
        "status": "ready",
        "scope": {"profile_id": profile_id},
        "factor_family_versions": [],
        "agent_id": agent_id,
        "created_at": 1,
        "updated_at": 1,
        "workspace_ref": "workspace:e2e-workspace",
        "run_ref": "",
        "graph_instance_ref": f"work-package:{work_package_id}",
        "graph_branch_ref": branch_ref,
        "checkpoint_ref": "",
        "evidence_refs": [],
        "artifacts": [initialized["descriptor"]],
        "provenance": {"kind": "active_graph_e2e"},
        "timeline_refs": [],
    }
    profile["research_records"] = [
        item for item in profile["research_records"]
        if item["record_id"] != work_package_id
    ] + [record]
    store.save(profile)
    return profile_id, agent_id, work_package_id


def _advance_entry_node(
    *,
    factortester: list[str],
    env: dict[str, str],
    base_url: str,
    tmp_path: Path,
    graph: dict,
    instance: dict,
    branch_id: str,
    file_prefix: str,
) -> dict:
    entry_node = str(graph["entry_node"])
    edge = next(
        item for item in graph["edges"]
        if item["from_node"] == entry_node
    )
    transition_invocation_id = _commit_usage(
        factortester=factortester,
        env=env,
        agent_id=f"instance:{instance['instance_id']}",
        input_tokens=12,
        output_tokens=3,
        receipt_dir=tmp_path,
    )
    target_resolution = _capability_resolution(
        factortester=factortester,
        env=env,
        tmp_path=tmp_path,
        graph=graph,
        graph_version=int(instance["graph_version"]),
        node_id=edge["to_node"],
        product_group="equities",
    )
    target_resolution_file = (
        tmp_path / f"{file_prefix}-target-resolution.json"
    )
    target_resolution_file.write_text(
        json.dumps(target_resolution),
        encoding="utf-8",
    )
    edge_requirement_ids = [
        str(item)
        for item in edge.get("obligation_requirement_refs") or []
    ]
    node_requirement_ids = [
        str(item)
        for item in next(
            node for node in graph["nodes"]
            if node["node_id"] == entry_node
        ).get("entry_requirement_refs") or []
    ]

    def obligation(
        requirement_id: str,
        *,
        prefix: str,
        index: int,
    ) -> dict:
        return {
        "schema_version": 1,
        "obligation_id": f"e2e-{prefix}-{index}",
        "contract_hash": "0" * 64,
        "claim_ids": [],
        "obligation_kind": f"e2e_{prefix}_requirement",
        "title_zh": f"{'节点' if prefix == 'node' else 'Edge'}义务{index + 1}",
        "epistemic_question": f"要求 {requirement_id} 是否满足",
        "scope": {"requirement_id": requirement_id},
        "discharge_criterion": {"method": "real_server_e2e"},
        "status": "open",
        "materiality": "decision_blocking",
        "methodology_hash": "1" * 64,
        "created_event_ref": f"e2e:{file_prefix}:entry",
        "requirement_refs": [requirement_id],
        }

    node_obligations = [
        obligation(requirement_id, prefix="node", index=index)
        for index, requirement_id in enumerate(node_requirement_ids)
    ]
    edge_obligations = [
        obligation(requirement_id, prefix="edge", index=index)
        for index, requirement_id in enumerate(edge_requirement_ids)
    ]
    all_obligations = node_obligations + edge_obligations
    initial_checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "0" * 64,
        "methodology_hash": "1" * 64,
        "trial_plan_hash": "",
        "claims": [],
        "obligations": node_obligations,
        "pending_adjudications": [],
        "pending_closure": None,
        "closure": None,
    })
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": f"e2e-{file_prefix}-edge-coverage",
        "proposer_invocation_id": transition_invocation_id,
        "contract_hash": "0" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "1" * 64,
        "evidence_refs": [f"e2e:{file_prefix}:edge-coverage"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "本次仅验证义务覆盖",
        "obligation_delta": [
            {
                "obligation_id": item["obligation_id"],
                "from_state": "open",
                "to_state": "discharged",
                "criterion_ref": "e2e:real-server",
            }
            for item in node_obligations
        ] + [
            {
                "obligation_id": item["obligation_id"],
                "from_state": "absent",
                "to_state": "discharged",
                "criterion_ref": "e2e:real-server",
                "obligation": {**item, "status": "discharged"},
            }
            for item in edge_obligations
        ],
        "decision_warrant": {
            "finding_refs": [f"e2e:{file_prefix}:edge-coverage"],
            "rule_refs": ["e2e:real-server"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    })
    review_invocation_id = _commit_usage(
        factortester=factortester,
        env=env,
        agent_id=f"instance:{instance['instance_id']}:reviewer",
        input_tokens=8,
        output_tokens=2,
        receipt_dir=tmp_path,
        task_ref=(
            "research-cycle-adjudication:"
            f"{proposal['proposal_hash']}"
        ),
        role="reviewer",
    )
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": f"e2e-{file_prefix}-edge-decision",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": review_invocation_id,
        "methodology_hash": "1" * 64,
    })
    evidence = {
        **(edge.get("guard") or {}),
        "evidence_refs": [f"e2e:{file_prefix}:transition"],
        "agent_invocation_ids": [
            transition_invocation_id,
            review_invocation_id,
        ],
        "entry_requirement_assessments": [
            {
                "requirement_id": requirement_id,
                "applicability": {
                    "status": "applicable",
                    "reason_zh": "此端到端迁移显式登记并验证节点义务。",
                    "fact_refs": [
                        f"e2e:entry-requirement:{requirement_id}"
                    ],
                },
                "coverage": {
                    "decision": "map_existing",
                    "obligation_refs": [
                        f"obligation:e2e-node-{index}"
                    ],
                },
                "resolution": {
                    "route": "bounded_unknown",
                    "reuse_status": "none",
                    "validation_refs": [],
                },
                "entry_effect": {
                    "status": "pass",
                    "limitation_refs": [],
                },
            }
            for index, requirement_id in enumerate(next(
                item for item in graph["nodes"]
                if item["node_id"] == entry_node
            ).get("entry_requirement_refs") or [])
        ],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "",
            "initial_checkpoint": initial_checkpoint,
            "expected_base_hash": initial_checkpoint["projection_hash"],
            "events": [
                {"event_type": "adjudication_proposed", "proposal": proposal},
                {"event_type": "adjudication_decided", "decision": decision},
            ],
        },
    }
    source_node = next(
        item for item in graph["nodes"]
        if item["node_id"] == entry_node
    )
    target_node = next(
        item for item in graph["nodes"]
        if item["node_id"] == edge["to_node"]
    )
    report_items = [
        {
            "report_requirement_id": item["report_requirement_id"],
            "subject_ref": item["subject_ref"],
            "content_kind": item["allowed_content"][0],
            "item_hash": hashlib.sha256(
                (
                    f"e2e:{item['report_requirement_id']}:"
                    f"{item['subject_ref']}"
                ).encode()
            ).hexdigest(),
        }
        for item in expected_report_bindings(
            graph=graph,
            source_node=source_node,
            edge=edge,
            target_node=target_node,
            entry_assessments=evidence[
                "entry_requirement_assessments"
            ],
            transition_evidence=evidence,
        )
    ]
    evidence["report_submission"] = {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(report_items),
        "items": report_items,
    }
    profile_id, agent_id, work_package_id = _bind_local_research_report(
        env=env,
        base_url=base_url,
        instance_id=instance["instance_id"],
        branch_id=branch_id,
    )
    obligation_status = _run_json(
        factortester,
        [
            "research-graph", "obligation", "status",
            instance["instance_id"], branch_id,
            "--profile-id", profile_id,
            "--agent-id", agent_id,
        ],
        env=env,
    )
    entry_change_file = tmp_path / f"{file_prefix}-entry-obligations.json"
    entry_change_file.write_text(json.dumps({
        "expected_projection_hash": obligation_status[
            "current_projection"
        ]["projection_hash"],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "",
            "initial_checkpoint": initial_checkpoint,
            "expected_base_hash": initial_checkpoint["projection_hash"],
            "events": [],
        },
        "obligation_delta": [{
            "obligation_id": item["obligation_id"],
            "from_state": "absent",
            "to_state": "open",
            "obligation": item,
        } for item in node_obligations],
        "evidence_use_delta": [],
        "obligation_presentations": {
            f"obligation:{item['obligation_id']}": item[
                "epistemic_question"
            ]
            for item in node_obligations
        },
        "reason_markdown": "本次 E2E 已逐项建立节点入口义务",
    }), encoding="utf-8")
    _run_json(
        factortester,
        [
            "research-graph", "obligation", "change",
            instance["instance_id"], branch_id,
            "--profile-id", profile_id,
            "--agent-id", agent_id,
            "--change-file", str(entry_change_file),
        ],
        env=env,
    )
    reason_file = tmp_path / f"{file_prefix}-edge-reason.md"
    reason_file.write_text(
        "本节点检查完成，选择该边进入下一研究节点",
        encoding="utf-8",
    )
    _run_json(
        factortester,
        [
            "research-graph", "edge", "choose",
            instance["instance_id"], branch_id, edge["edge_id"],
            "--profile-id", profile_id,
            "--agent-id", agent_id,
            "--reason-file", str(reason_file),
        ],
        env=env,
    )
    obligation_status = _run_json(
        factortester,
        [
            "research-graph", "obligation", "status",
            instance["instance_id"], branch_id,
            "--profile-id", profile_id,
            "--agent-id", agent_id,
        ],
        env=env,
    )
    source_payload = {
        "instance_id": instance["instance_id"],
        "branch_id": branch_id,
        "edge_id": edge["edge_id"],
        "result": "requirements verified",
    }
    source = put_source_capture(
        owner=instance["owner"],
        source_kind="terminal",
        identity={
            "execution_id": f"e2e:{instance['instance_id']}:{branch_id}",
        },
        content_hash=hashlib.sha256(
            json.dumps(source_payload, sort_keys=True).encode()
        ).hexdigest(),
        audit={"argv": ["e2e-requirement-check"], "returncode": 0},
    )
    fragment = put_source_fragment(
        owner=instance["owner"],
        source_ref=source["source_ref"],
        selector={"stream": "stdout", "line_range": {"start": 1, "end": 1}},
        fragment_hash=hashlib.sha256(b"requirements verified").hexdigest(),
        title_zh="E2E义务验证结果",
        summary_zh="真实服务器端到端验收确认所选路径义务已验证",
        preview={"text": "requirements verified"},
    )
    cycle = evidence["research_cycle"]["initial_checkpoint"]
    catalog_evidence = create_evidence(
        owner=instance["owner"],
        evidence_kind="data_availability",
        fragment_refs=[fragment["fragment_ref"]],
        title_zh="E2E义务验证证据",
        description_zh="由真实服务器验收命令片段形成的义务覆盖证据",
        claim_summary="所选研究路径要求已由真实端到端验收确认",
        applicability={
            "source_refs": ["e2e:active-graph"],
            "contract_hash": cycle["contract_hash"],
            "methodology_hash": cycle["methodology_hash"],
        },
        identity_refs={
            "contract_hash": cycle["contract_hash"],
            "methodology_hash": cycle["methodology_hash"],
        },
        limitations=["仅用于真实服务器端到端验收"],
        conflicts=[],
    )
    evidence_use_delta = [{
        "op": "add",
        "use": {
            "evidence_ref": catalog_evidence["evidence_ref"],
            "evidence_title_zh": catalog_evidence["title_zh"],
            "obligation_ref": f"obligation:{item['obligation_id']}",
            "requirement_refs": item["requirement_refs"],
            "rationale_zh": "该命令片段直接验证本义务覆盖的小类",
            "qualification": "eligible",
            "scope_match": {
                "scope_compatibility": "compatible",
                "matched_by": ["contract_hash", "methodology_hash"],
                "conflicts": [],
                "limitations": ["仅用于真实服务器端到端验收"],
                "requested_scope": {
                    "contract_hash": cycle["contract_hash"],
                    "methodology_hash": cycle["methodology_hash"],
                },
            },
        },
    } for item in all_obligations]
    change_file = tmp_path / f"{file_prefix}-obligation-change.json"
    continuation_cycle = dict(evidence["research_cycle"])
    continuation_cycle.pop("initial_checkpoint", None)
    continuation_cycle.pop("expected_base_hash", None)
    change_file.write_text(json.dumps({
        "expected_projection_hash": obligation_status[
            "current_projection"
        ]["projection_hash"],
        "research_cycle": continuation_cycle,
        "obligation_delta": [
            {
                "obligation_id": item["obligation_id"],
                "from_state": "open",
                "to_state": "discharged",
            }
            for item in node_obligations
        ] + [
            {
                "obligation_id": item["obligation_id"],
                "from_state": "absent",
                "to_state": "discharged",
                "obligation": {**item, "status": "discharged"},
            }
            for item in edge_obligations
        ],
        "evidence_use_delta": evidence_use_delta,
        "obligation_presentations": {
            f"obligation:{item['obligation_id']}": item[
                "epistemic_question"
            ]
            for item in all_obligations
        },
        "reason_markdown": "本次 E2E 已完成所选 Edge 的验证义务",
    }), encoding="utf-8")
    _run_json(
        factortester,
        [
            "research-graph", "obligation", "change",
            instance["instance_id"], branch_id,
            "--profile-id", profile_id,
            "--agent-id", agent_id,
            "--change-file", str(change_file),
        ],
        env=env,
    )
    report = _run_json(
        factortester,
        [
            "report", "show",
            "--profile", profile_id,
            "--work-package-id", work_package_id,
            "--branch-id", branch_id,
            "--json",
        ],
        env=env,
    )
    node_chapter_ids = {
        item["component_id"]
        for item in report["bindings"]
        if item["kind"] == "graph_reference"
        and item["target_ref"] == f"node:{entry_node}"
        and (item.get("data") or {}).get("role") == "report_chapter"
    }
    assert len(node_chapter_ids) == 1
    chapter_id = node_chapter_ids.pop()
    for index, item in enumerate(report_items):
        report_requirement_id = item["report_requirement_id"]
        if report_requirement_id.startswith("report.requirement."):
            obligation_requirement_id = report_requirement_id.removeprefix(
                "report.requirement."
            )
            _run_json(
                factortester,
                [
                    "report", "add",
                    "--profile", profile_id,
                    "--work-package-id", work_package_id,
                    "--branch-id", branch_id,
                    "--component-id", f"{file_prefix}-requirement-{index}",
                    "--kind", "special",
                    "--title", f"R{index + 1}",
                    "--parent-id", chapter_id,
                    "--body", "E2E",
                    "--display-kind", "obligation_requirement",
                    "--obligation-requirement-id", obligation_requirement_id,
                    "--report-requirement-id", report_requirement_id,
                    "--report-subject-ref", item["subject_ref"],
                    "--report-content-kind", item["content_kind"],
                    "--json",
                ],
                env=env,
            )
            continue
        section_id = f"{file_prefix}-requirement-section-{index}"
        _run_json(
            factortester,
            [
                "report", "add",
                "--profile", profile_id,
                "--work-package-id", work_package_id,
                "--branch-id", branch_id,
                "--component-id", section_id,
                "--kind", "section",
                "--title", f"R{index + 1}",
                "--parent-id", chapter_id,
                "--json",
            ],
            env=env,
        )
        _run_json(
            factortester,
            [
                "report", "add",
                "--profile", profile_id,
                "--work-package-id", work_package_id,
                "--branch-id", branch_id,
                "--component-id", f"{file_prefix}-requirement-{index}",
                "--kind", "entry",
                "--parent-id", section_id,
                "--body", "E2E",
                "--report-requirement-id",
                report_requirement_id,
                "--report-subject-ref", item["subject_ref"],
                "--report-content-kind", item["content_kind"],
                "--json",
            ],
            env=env,
        )
    evidence_file = tmp_path / f"{file_prefix}-transition-evidence.json"
    evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
    result = _run_json(
        factortester,
        [
            "research-graph",
            "node",
            "advance",
            instance["instance_id"],
            branch_id,
            "--edge-id",
            edge["edge_id"],
            "--evidence-file",
            str(evidence_file),
            "--target-capability-resolution-file",
            str(target_resolution_file),
            "--profile-id",
            profile_id,
            "--agent-id",
            agent_id,
        ],
        env=env,
    )
    assert result["branch"]["current_node"] == edge["to_node"]
    assert (
        result["doctor"]["submission_contract"]["local_validation"][
            "proposal_count"
        ]
        == 1
    )
    return result


def test_strategy_intent_cli_round_trips_real_workspace(
    tmp_path: Path, monkeypatch,
) -> None:
    factortester = _installed_cli("factortester")
    harness = _installed_cli("cli-anything-factortester-research")
    env = {
        **os.environ,
        "FACTORTESTER_HOME": str(tmp_path / "cli-home-intent"),
        "CLI_ANYTHING_FORCE_INSTALLED": "1",
    }
    with _real_server(tmp_path, monkeypatch) as base_url:
        alias = f"intent_{uuid.uuid4().hex[:10]}"
        password = secrets.token_urlsafe(18)
        assert _post_json(
            f"{base_url}/register", {"username": alias, "password": password},
        )["success"] is True
        _run(factortester, ["configure", "--base-url", base_url], env=env)
        _run(factortester, ["login", "--username", alias, "--password", password], env=env)
        _run(factortester, [
            "workspace", "create", "--factor-family", "Demo",
            "--factor", "Demo=Rank", "--factor", "Demo=Gate", "--factor", "Demo=Size",
        ], env=env)
        payload_file = tmp_path / "intent-workspace.json"
        payload_file.write_text(json.dumps({
            "schema_version": 1,
            "shared": {"factor_families": [{"alias": "Demo"}], "factors": [
                {"factor_family_alias": "Demo", "alias": item}
                for item in ("Rank", "Gate", "Size")
            ]},
            "analyses": {"backtest": {
                "local_settings": {},
                "groups": [{"id": "A1", "name": "A1", "factorAlias": "Rank"}],
            }},
            "ui": {},
        }), encoding="utf-8")
        _run(factortester, ["workspace", "update", "--file", str(payload_file)], env=env)

        configured = _run_json(harness, [
            "strategy-intent", "configure", "A1",
            "--role", "screen=Gate", "--screen-rule", "gte",
            "--role", "sizing=Size", "--allocation-policy", "factor_sizing", "--json",
        ], env=env)
        shown = _run_json(harness, ["strategy-intent", "show", "--group", "A1", "--json"], env=env)
        margin_configured = _run_json(harness, [
            "margin-budget", "configure", "A1",
            "--target", "0.78", "--max", "0.84", "--tolerance", "0.005", "--json",
        ], env=env)
        margin_shown = _run_json(harness, [
            "margin-budget", "show", "--group", "A1", "--json",
        ], env=env)

        assert configured["revision"] == 3
        assert shown["strategies"][0]["factor_role_bindings"] == {
            "screen": "Gate", "sizing": "Size",
        }
        assert margin_configured["revision"] == 4
        assert margin_shown["strategies"][0]["target_margin_utilization"] == 0.78
        assert margin_shown["strategies"][0]["max_margin_utilization"] == 0.84


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
        "FACTORTESTER_CLIENT_ROOT": str(tmp_path / "client-root"),
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
        cookie_key = hashlib.sha256(base_url.rstrip("/").encode()).hexdigest()[:20]
        assert (cli_home / "cookies" / f"{cookie_key}.lwp").is_file()
        assert _run_json(
            factortester,
            ["research-graph", "versions", "factor-research"],
            env=env,
        ) == []

        graph = _run_json(
            harness,
            ["graph", "successor", "--json"],
            env=env,
        )
        # Seed the complete immutable lineage used by transactional validation.
        baseline_graph = _run_json(
            harness,
            ["graph", "draft", "--json"],
            env=env,
        )
        intermediate_graph = deepcopy(baseline_graph)
        intermediate_graph["version"] = 9
        intermediate_graph["parent_version"] = int(
            baseline_graph["version"]
        )
        intermediate_graph["content_hash"] = graph_content_hash(
            intermediate_graph
        )
        research_graphs.register_graph(
            baseline_graph,
            actor="history-fixture",
        )
        research_graphs.register_graph(
            intermediate_graph,
            actor="history-fixture",
        )
        with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO active_research_graphs (
                    graph_id, version, activated_by, activated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (baseline_graph["graph_id"], baseline_graph["version"],
                 "history-fixture", 1.0),
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
        entry_node = graph["entry_node"]
        runtime_packet_budget = graph_packet_budget(graph)
        active = _run_json(
            factortester,
            [
                "research-graph",
                "activate",
                graph["graph_id"],
                str(graph["version"]),
                "--yes",
            ],
            env=env,
        )
        assert active["graph_id"] == graph["graph_id"]
        assert active["to_version"] == graph["version"]
        assert (
            active["upgrade_validation"][
                "persistent_validation_object_count"
            ]
            == 0
        )

        live_entry_resolution = _capability_resolution(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=active["to_version"],
            node_id=entry_node,
            product_group="equities",
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
        packet_ceiling = runtime_packet_budget["ceiling_bytes"]
        node_info = _run_json(
            factortester,
            [
                "research-graph",
                "node",
                "info",
                live_instance["instance_id"],
                live_branch["branch_id"],
            ],
            env=env,
        )
        assert node_info["next_bytes"] <= packet_ceiling
        assert "candidate_edges" in node_info
        _advance_entry_node(
            factortester=factortester,
            env=env,
            base_url=base_url,
            tmp_path=tmp_path,
            graph=graph,
            instance=live_instance,
            branch_id=live_branch["branch_id"],
            file_prefix="live",
        )

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
