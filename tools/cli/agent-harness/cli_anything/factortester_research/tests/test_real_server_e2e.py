from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from http.cookiejar import LWPCookieJar
from pathlib import Path
from typing import Any, Iterator
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import orjson
from werkzeug.serving import make_server

import settings as Settings
from server import create_app
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
) -> Iterator[tuple[str, str, str, str]]:
    database = tmp_path / "server" / "factortester.sqlite"
    database.parent.mkdir(parents=True)
    provider_secret = secrets.token_hex(32)
    launcher_secret = secrets.token_hex(32)
    human_secret = secrets.token_hex(32)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    monkeypatch.setattr(Settings, "CACHE_DIR", database.parent)
    monkeypatch.setenv("FLASK_SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setenv(
        "RESEARCH_PROVIDER_USAGE_SECRET",
        provider_secret,
    )
    monkeypatch.setenv(
        "RESEARCH_AGENT_LAUNCHER_SECRET",
        launcher_secret,
    )
    monkeypatch.setenv(
        "RESEARCH_HUMAN_ACTIVATION_SECRET",
        human_secret,
    )
    app = create_app()
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://127.0.0.1:{httpd.server_port}",
            provider_secret,
            launcher_secret,
            human_secret,
        )
    finally:
        httpd.shutdown()
        thread.join(timeout=10)
        httpd.server_close()


def _provider_usage_receipt(
    *,
    base_url: str,
    cli_home: Path,
    provider_secret: str,
    reservation_id: str,
    input_tokens: int,
    output_tokens: int,
) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "provider": "e2e-provider-gateway",
        "provider_request_id": uuid.uuid4().hex,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    payload["usage_attestation"] = hmac.new(
        provider_secret.encode(),
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    cookie_jar = LWPCookieJar(str(cli_home / "cookies.lwp"))
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    request = Request(
        f"{base_url}/api/research-provider-usage-receipts",
        data=json.dumps(payload).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with opener.open(request, timeout=30) as response:
        value = json.loads(response.read().decode())
    assert value["success"] is True
    return value["provider_receipt"]


def _commit_usage(
    *,
    factortester: list[str],
    env: dict[str, str],
    base_url: str,
    cli_home: Path,
    provider_secret: str,
    scope_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    reservation = _run_json(
        factortester,
        [
            "research-graph",
            "token-reserve",
            scope_id,
            "--work-kind",
            "researcher",
            "--max-input-tokens",
            str(input_tokens),
            "--max-output-tokens",
            str(output_tokens),
        ],
        env=env,
    )
    receipt = _provider_usage_receipt(
        base_url=base_url,
        cli_home=cli_home,
        provider_secret=provider_secret,
        reservation_id=reservation["reservation_id"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    committed = _run_json(
        factortester,
        [
            "research-graph",
            "token-commit",
            reservation["reservation_id"],
            "--provider-receipt-id",
            receipt["provider_receipt_id"],
        ],
        env=env,
    )
    assert committed["status"] == "committed"
    return reservation["reservation_id"]


def _agent_execution(
    *,
    factortester: list[str],
    env: dict[str, str],
    role: str,
    owner: str,
    launcher_secret: str,
) -> dict:
    scope_id = f"e2e:{role}:{uuid.uuid4().hex}"
    _run_json(
        factortester,
        [
            "research-graph",
            "budget-create",
            scope_id,
            "--token-limit",
            "1000",
        ],
        env=env,
    )
    reservation = _run_json(
        factortester,
        [
            "research-graph",
            "token-reserve",
            scope_id,
            "--work-kind",
            role,
            "--max-input-tokens",
            "400",
            "--max-output-tokens",
            "200",
        ],
        env=env,
    )
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    attested_payload = {
        "owner_user_id": owner,
        "actor_role": role,
        "model_id": "e2e-model",
        "codex_version": "e2e",
        "reservation_id": reservation["reservation_id"],
        "agent_principal_hash": principal_hash,
        "lineage_hash": lineage_hash,
    }
    launcher_attestation = hmac.new(
        launcher_secret.encode(),
        orjson.dumps(attested_payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    return _run_json(
        factortester,
        [
            "research-graph",
            "agent-start",
            "--role",
            role,
            "--model-id",
            "e2e-model",
            "--codex-version",
            "e2e",
            "--reservation-id",
            reservation["reservation_id"],
            "--agent-principal-hash",
            principal_hash,
            "--lineage-hash",
            lineage_hash,
            "--launcher-attestation",
            launcher_attestation,
        ],
        env=env,
    )


def _capability_receipt(
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
    approvals = {}
    for capability_id in node.get("required_capabilities") or []:
        descriptor = descriptors[capability_id]
        approval = _run_json(
            factortester,
            [
                "research-graph",
                "approve-capability",
                capability_id,
                "--descriptor-hash",
                descriptor["descriptor_hash"],
                "--product-group",
                product_group,
                "--evidence-ref",
                f"e2e:approval:{node_id}:{capability_id}",
            ],
            env=env,
        )
        approvals[capability_id] = approval["approval_id"]
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
    suffix = f"{graph_version}-{node_id}-{'shadow' if shadow_mode else 'live'}"
    resolution_file = tmp_path / f"resolution-{suffix}.json"
    approvals_file = tmp_path / f"approvals-{suffix}.json"
    resolution_file.write_text(json.dumps(resolution), encoding="utf-8")
    approvals_file.write_text(json.dumps(approvals), encoding="utf-8")
    args = [
        "research-graph",
        "attest",
        graph["graph_id"],
        str(graph_version),
        "--node",
        node_id,
        "--product-group",
        product_group,
        "--resolution-file",
        str(resolution_file),
        "--approval-refs-file",
        str(approvals_file),
        "--product-profile-hash",
        "d" * 64,
        "--resolver-version",
        "e2e-resolver-v1",
    ]
    if shadow_mode:
        args.append("--shadow-mode")
    return _run_json(factortester, args, env=env)


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
    with _real_server(tmp_path, monkeypatch) as (
        base_url,
        provider_secret,
        launcher_secret,
        human_secret,
    ):
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

        proposer = _agent_execution(
            factortester=factortester,
            env=env,
            role="proposer",
            owner=owner,
            launcher_secret=launcher_secret,
        )
        reviewer = _agent_execution(
            factortester=factortester,
            env=env,
            role="reviewer",
            owner=owner,
            launcher_secret=launcher_secret,
        )
        assert proposer["execution_id"] != reviewer["execution_id"]
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
                proposer["execution_id"],
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
                reviewer["execution_id"],
            ],
            env=env,
        )
        assert review["reviewer_execution_id"] == reviewer["execution_id"]

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
        shadow_receipt = _capability_receipt(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=graph["version"],
            node_id=entry_node,
            product_group="equities",
            shadow_mode=True,
        )
        shadow_receipt_file = tmp_path / "shadow-receipt.json"
        shadow_receipt_file.write_text(
            json.dumps(shadow_receipt),
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
                "--token-budget",
                "1000",
                "--shadow-graph-version",
                str(graph["version"]),
                "--shadow-run-id",
                graph_run["run_id"],
                "--capability-receipt-file",
                str(shadow_receipt_file),
            ],
            env=env,
        )
        shadow_branch_id = shadow_instance["branches"][0]["branch_id"]
        _commit_usage(
            factortester=factortester,
            env=env,
            base_url=base_url,
            cli_home=cli_home,
            provider_secret=provider_secret,
            scope_id=f"instance:{shadow_instance['instance_id']}",
            input_tokens=70,
            output_tokens=10,
        )
        baseline_scope = f"research-run:{baseline_run['run_id']}"
        _run_json(
            factortester,
            [
                "research-graph",
                "budget-create",
                baseline_scope,
                "--token-limit",
                "1000",
            ],
            env=env,
        )
        _commit_usage(
            factortester=factortester,
            env=env,
            base_url=base_url,
            cli_home=cli_home,
            provider_secret=provider_secret,
            scope_id=baseline_scope,
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
                "--replay-passed",
                "--shadow-passed",
                "--capability-resolution-complete",
                "--unaffected-jobs-preserved",
                "--token-efficiency-passed",
                "--routine-instance-id",
                shadow_instance["instance_id"],
                "--routine-branch-id",
                shadow_branch_id,
                "--baseline-run-id",
                baseline_run["run_id"],
            ],
            env=env,
        )
        metrics = validation["evidence"]["token_metrics"]
        assert metrics["shadow_graph_total_tokens"] == 80
        assert metrics["shadow_baseline_total_tokens"] == 100
        assert metrics["routine_context_bytes"] <= 6000
        assert metrics["token_authority"] == (
            "trusted_provider_usage_receipts"
        )

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
            ],
            env=env,
        )
        change_diff = json.loads(change_file.read_text(encoding="utf-8"))
        diff_hash = hashlib.sha256(orjson.dumps(
            change_diff,
            option=orjson.OPT_SORT_KEYS,
        )).hexdigest()
        nonce = uuid.uuid4().hex
        expires_at = time.time() + 300
        human_payload = {
            "owner_user_id": owner,
            "graph_id": graph["graph_id"],
            "graph_version": graph["version"],
            "graph_hash": graph["content_hash"],
            "proposal_id": proposal["proposal_id"],
            "diff_hash": diff_hash,
            "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
            "authorized_by": "e2e-human-auditor",
            "expires_at": expires_at,
        }
        human_attestation = hmac.new(
            human_secret.encode(),
            orjson.dumps(human_payload, option=orjson.OPT_SORT_KEYS),
            hashlib.sha256,
        ).hexdigest()
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
                diff_hash,
                "--nonce",
                nonce,
                "--authorized-by",
                "e2e-human-auditor",
                "--expires-at",
                str(expires_at),
                "--human-attestation",
                human_attestation,
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
        assert active["lifecycle"] == "active"

        live_entry_receipt = _capability_receipt(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=active["version"],
            node_id=entry_node,
            product_group="equities",
            shadow_mode=False,
        )
        live_entry_file = tmp_path / "live-entry-receipt.json"
        live_entry_file.write_text(
            json.dumps(live_entry_receipt),
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
                "--token-budget",
                "1000",
                "--capability-receipt-file",
                str(live_entry_file),
            ],
            env=env,
        )
        live_branch = live_instance["branches"][0]
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
        next_packet = _run_json(
            factortester,
            [
                "research-graph",
                "next",
                live_instance["instance_id"],
                live_branch["branch_id"],
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
        target_receipt = _capability_receipt(
            factortester=factortester,
            env=env,
            tmp_path=tmp_path,
            graph=graph,
            graph_version=active["version"],
            node_id=edge["to_node"],
            product_group="equities",
            shadow_mode=False,
        )
        target_receipt_file = tmp_path / "target-receipt.json"
        target_receipt_file.write_text(
            json.dumps(target_receipt),
            encoding="utf-8",
        )
        evidence = {
            **(edge.get("guard") or {}),
            "evidence_refs": ["e2e:transition"],
        }
        evidence_file = tmp_path / "transition-evidence.json"
        evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
        advanced = _run_json(
            factortester,
            [
                "research-graph",
                "advance",
                live_instance["instance_id"],
                live_branch["branch_id"],
                "--edge-id",
                edge["edge_id"],
                "--evidence-file",
                str(evidence_file),
                "--target-capability-receipt-file",
                str(target_receipt_file),
            ],
            env=env,
        )
        assert advanced["current_node"] == edge["to_node"]

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
