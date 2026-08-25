from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager

import orjson
from click.testing import CliRunner
from flask import Flask, session
from werkzeug.serving import make_server

from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test import (
    profile_research_routes,
    research_result_report_routes,
)
from server.services import research_graphs
from server.services.research_report_presentations import (
    run_spec_presentation,
)
from server.services.research_step.result_reporting.projection import (
    build_result_report_projection,
)
from tests.release.report_tree_fixtures import (
    carrier as _carrier,
    profile as _profile,
    publish_research_checkpoint,
)
from tests.server.test_current_report_checkpoint import _seed
from tools.cli.app import cli
from tools.cli.client import FactorTesterClient
from tools.cli.commands import research_result_report as result_commands
from tools.cli.http import ClientConfig, HttpSession, save_config
from tools.cli.release.research_reporting.audit_objects import (
    stage_run_spec_preview,
)
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.authoring.tree_render import (
    render_tree_markdown,
)
from tools.factors.formula_identity import freeze_factor_identity


@contextmanager
def _server(app):
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_result_route_cli_local_publish_and_server_append(
    tmp_path, monkeypatch,
):
    database = tmp_path / "result-report.db"
    _seed(database, monkeypatch)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE research_graph_branches "
            "SET current_node='trial_execution'"
        )

    factor = freeze_factor_identity(
        owner_ref="alice",
        family_alias="SgCPS",
        factor_alias="SgCPS|N:20d",
        family_formula_fingerprint="c" * 64,
        self_formula_fingerprint="d" * 64,
        params={"N": "20d"},
    )
    run_spec = {
        "run_spec_version": 3,
        "configuration_revision": 7,
        "analyses": ["ic"],
        "configuration": {
            "shared": {"factors": [factor]},
            "analyses": {"ic": {
                "product_path_selection": {"label": "日盘", "paths": []},
                "local_settings": {"factor": "SgCPS|20"},
            }},
        },
    }
    run_spec_hash = hashlib.sha256(orjson.dumps(
        run_spec, option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    projection = build_result_report_projection(
        action={
            "action_id": "action:in-sample-ic",
            "output_evidence_refs": ["evidence:" + "a" * 64],
        },
        plan_hash="b" * 64,
        rows=[{
            "index": 1,
            "run_id": "run-1",
            "job_id": "job-1",
            "kind": "ic",
            "status": "succeeded",
            "trial_role": "candidate",
            "run_spec_hash": run_spec_hash,
            "run_spec_alias_zh": "截面 IC · 日盘 · SgCPS",
            "result_summary": {"ic_stats": {
                "columns": ["index", "SgCPS"],
                "rows": [{"index": "mean", "SgCPS": 0.031}],
            }},
        }],
        receipt=None,
    )
    projection["node_id"] = "trial_execution"

    carrier = _carrier()
    carrier["graph_ref"] = "factor-research@v9"
    carrier["branch_ref"] = "graph-branch:instance-1:branch-1"
    carrier["current_node"] = "trial_execution"
    carrier["latest_transition"]["from_node"] = "trial_execution"
    carrier["latest_transition"]["to_node"] = "trial_execution"

    app = Flask(__name__)
    app.secret_key = "result-report-e2e"

    @app.before_request
    def _authenticate():
        session["username"] = "owner-1"

    app.register_blueprint(sft_bp)
    monkeypatch.setattr(
        research_result_report_routes,
        "load_result_report_projection",
        lambda **kwargs: projection,
    )
    monkeypatch.setattr(
        profile_research_routes._projection,
        "get_work_package_branch",
        lambda **kwargs: {"report_checkpoint": carrier},
    )
    monkeypatch.setattr(
        research_graphs,
        "load_research_cycle_object",
        lambda **kwargs: {
            "schema_version": 1,
            "object_kind": "run",
            "run_id": "run-1",
            "run_spec_hash": run_spec_hash,
            "run_spec_version": 3,
            "run_spec_json": json.dumps(
                run_spec, ensure_ascii=False, indent=2, sort_keys=True,
            ),
            "alias_zh": "截面 IC · 日盘 · SgCPS",
            "summary_zh": "服务器接受后的冻结配置",
        },
    )
    monkeypatch.setattr(
        research_graphs,
        "build_graph_branch_next",
        lambda **_kwargs: {
            "node": {"node_id": "trial_execution"},
            "report_container": {
                "kind": "chapter",
                "anchor_node": "trial_execution",
            },
        },
    )

    root = tmp_path / "client-support"
    store = _profile(root)
    local = store.load("maxa")
    local["agents"][0]["scope"] = {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
    }
    local["research_records"][0]["graph_branch_ref"] = carrier["branch_ref"]
    store.save(local)
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )
    package = root / "profile-root" / "research" / "sgccs-review"
    proposed_path = stage_run_spec_preview(
        package_root=package,
        branch_id="branch-1",
        presentation=run_spec_presentation(
            run_spec,
            run_spec_hash=run_spec_hash,
        ),
    )
    release_profile = tmp_path / "client-profile.json"
    release_profile.write_text(json.dumps({
        "release": {"install_root": str(root)},
    }), encoding="utf-8")

    with _server(app) as base_url:
        cli_config = tmp_path / "client-connection.json"
        save_config(ClientConfig(base_url), path=cli_config)
        result = CliRunner().invoke(cli, [
            "research-graph",
            "result-report",
            "instance-1",
            "branch-1",
            "--action-id",
            "action:in-sample-ic",
            "--work-package-id",
            "sgccs-review",
            "--profile-id",
            "maxa",
            "--agent-id",
            "research-maxa",
            "--release-profile",
            str(release_profile),
        ], env={
            "FACTORTESTER_HOME": str(tmp_path / "cli-home"),
            "FACTORTESTER_CONFIG": str(cli_config),
        })
        frozen = FactorTesterClient(
            HttpSession(base_url, cookies=tmp_path / "cookies.lwp"),
        ).get_research_cycle_object(
            "instance-1", "branch-1", "run", "run-1",
        )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert len(output["receipt"]["coverage"]) == 2
    assert "configuration_revision" in proposed_path.read_text()
    assert "configuration_revision" in frozen["run_spec_json"]

    report_tree = load_snapshot(package_root=package, branch_id="branch-1")
    assert {link["kind"] for link in report_tree["bindings"]} >= {
        "run_spec", "run", "job", "evidence", "trial_plan",
    }
    assert any(
        link["kind"] == "run" and "冻结" in link["label"]
        for link in report_tree["bindings"]
    )
    rendered = render_tree_markdown(report_tree).decode()
    assert "试验结果 · 样本内 IC 检验" in rendered
    assert "IC 均值 · SgCPS" in rendered
    assert not (package / "branches" / "branch-1" / "REPORT.md").exists()
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_report_item_checkpoints"
        ).fetchone()[0] == 1


def test_audit_backfill_accepts_authoritative_command_wrapper(
    tmp_path, monkeypatch,
):
    checkpoint = {
        "schema_version": 1,
        "current_action_id": "action:in-sample-ic",
    }
    checkpoint_path = tmp_path / "audited.json"
    checkpoint_path.write_text(json.dumps({
        "operation": "audit",
        "checkpoint": checkpoint,
    }), encoding="utf-8")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({
        "proposal": {"proposal_id": "proposal-1"},
        "decision": {"decision_id": "decision-1"},
    }), encoding="utf-8")

    class Client:
        observed = None

        def backfill_result_audit(self, *args, **kwargs):
            self.observed = kwargs
            return {"receipt_id": "receipt-1"}

    client = Client()
    monkeypatch.setattr(
        result_commands, "client_from_config", lambda: client,
    )
    result = CliRunner().invoke(cli, [
        "research-graph",
        "result-audit-backfill",
        "instance-1",
        "branch-1",
        "--audited-checkpoint-file",
        str(checkpoint_path),
        "--audit-payload-file",
        str(payload_path),
    ])

    assert result.exit_code == 0, result.output
    assert client.observed["audited_checkpoint"] == checkpoint

    checkpoint_path.write_text(
        json.dumps(checkpoint), encoding="utf-8",
    )
    replay = CliRunner().invoke(cli, [
        "research-graph",
        "result-audit-backfill",
        "instance-1",
        "branch-1",
        "--audited-checkpoint-file",
        str(checkpoint_path),
        "--audit-payload-file",
        str(payload_path),
    ])
    assert replay.exit_code == 0, replay.output
    assert client.observed["audited_checkpoint"] == checkpoint
