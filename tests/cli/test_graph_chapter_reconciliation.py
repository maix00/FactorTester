from __future__ import annotations

import json

import pytest

from tools.cli.commands import research_graph_chapter_reconciliation as recovery
from tools.cli.commands.research_graph_local_report import (
    resolve_local_graph_report,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.workspace import initialize_work_package


def _scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究", "status": "pending",
        "scope": {}, "factor_family_versions": [], "agent_id": "agent",
        "created_at": 1, "updated_at": 1, "workspace_ref": "workspace:1",
        "run_ref": "", "graph_instance_ref": "work-package:instance",
        "graph_branch_ref": "graph-branch:instance:branch",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=workspace, work_package_id="wp", branch_id="branch",
        workspace_id="1", title="研究",
        branch_ref="graph-branch:instance:branch",
    )
    return resolve_local_graph_report(
        client_root=client_root, profile_id="maxa", agent_id="agent",
        instance_id="instance", branch_id="branch",
    )


def test_failed_post_transition_sync_is_durable_and_reconciled(
    monkeypatch, tmp_path,
):
    scope = _scope(tmp_path)
    synchronize = recovery.synchronize_report_container
    monkeypatch.setattr(
        recovery, "synchronize_report_container",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    container = {
        "kind": "chapter",
        "anchor_node": "data_contract",
        "current_node": "data_contract",
        "latest_trace_id": "trace-1",
    }

    with pytest.raises(
        recovery.ChapterReconciliationRequired,
        match="server transition completed",
    ):
        recovery.synchronize_transition_container(
            scope, container=container,
        )

    marker = recovery.load_pending(scope)
    assert marker is not None
    assert marker["report_container"] == container
    assert marker["reason"] == "disk full"
    marker_path = (
        scope.client_root / "graph-report-reconciliation" / "maxa"
        / "instance--branch.json"
    )
    assert json.loads(marker_path.read_text()) == marker

    monkeypatch.setattr(recovery, "synchronize_report_container", synchronize)
    result = recovery.reconcile_current_container(
        scope, container=container,
    )
    assert result["existing_count"] == 1
    assert recovery.load_pending(scope) is None
