from __future__ import annotations

import json

from server.services.research_graph.branch.capability_detour import (
    project_trace_rows,
)
from tools.cli.commands import research_report_history_reconciliation as history
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.git import commit_work_package

from tests.cli.test_research_graph_detour_report import _scope


class _Client:
    def __init__(self) -> None:
        rows = [
            _row("t1", "hypothesis_preregistration", "data_contract", 1),
            _row("t2", "data_contract", "capability_gap", 2),
            _row("t3", "capability_gap", "capability_resolution", 3),
            _row("t4", "capability_resolution", "data_contract", 4),
            _row("t5", "data_contract", "factor_semantics", 5),
        ]
        placements = project_trace_rows(rows)["items"]
        self.items = list(reversed([{
            "step_ref": f"trace:{row['trace_id']}",
            "from_node": row["from_node"], "to_node": row["to_node"],
            "created_at": row["created_at"],
            "evidence_refs": [],
            **placements[row["trace_id"]],
        } for row in rows]))

    def list_profile_research_branch_timeline(
        self, _work_package, _branch, *, limit, after,
    ):
        assert limit == 50
        return {
            "items": [] if after else self.items,
            "next_cursor": None,
        }


def _row(trace, source, target, created):
    return {
        "trace_id": trace, "edge_id": f"edge-{trace}",
        "from_node": source, "to_node": target,
        "created_at": created, "evidence_json": "{}",
    }


def _component(scope, component_id, parent_id, trace_ref):
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id=component_id, kind="section", title=component_id,
        parent_id=parent_id, body="既有内容", content=None, display_kind="",
        bindings=[{
            "binding_id": f"binding-{component_id}", "kind": "checkpoint",
            "target_ref": trace_ref, "label": "检查点",
            "data": {"link_id": "checkpoint"},
        }],
    )


def test_history_reconciliation_creates_chapters_reuses_special_and_moves_items(
    tmp_path,
    monkeypatch,
) -> None:
    scope, _ = _scope(tmp_path)
    chapter = synchronize_report_container(
        scope, container={
            "kind": "chapter", "anchor_node": "hypothesis_preregistration",
            "current_node": "hypothesis_preregistration",
            "latest_trace_id": "",
        },
    )
    legacy = "profile-screen-alias-capability-resolution"
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id=legacy, kind="special", title="能力缺口",
        parent_id=chapter["component_id"], body="人工记录", content={"old": 1},
        display_kind="capability_resolution", bindings=[],
    )
    _component(scope, "section-t1", chapter["component_id"], "trace:t1")
    _component(scope, "section-t2", chapter["component_id"], "trace:t2")
    _component(scope, "section-t5", chapter["component_id"], "trace:t5")
    commit_work_package(scope.package_root, message="Historical report fixture")
    scope.store.upsert_research_record("maxa", {
        **scope.store.load("maxa")["research_records"][0],
        "graph_instance_ref": "work-package:wp",
    })
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({
        "schema_version": 1,
        "episode_components": {"capability-detour:t2": legacy},
    }), encoding="utf-8")
    monkeypatch.setattr(
        history, "load_profile_root", lambda _path: scope.client_root,
    )

    plan = history._reconcile(
        profile_id="maxa", work_package_id="wp", branch_id="branch",
        release_profile=None, component_map_file=mapping,
        apply_changes=False, client=_Client(),
    )
    assert plan["chapter_nodes"] == [
        "hypothesis_preregistration", "data_contract", "factor_semantics",
    ]
    applied = history._reconcile(
        profile_id="maxa", work_package_id="wp", branch_id="branch",
        release_profile=None, component_map_file=mapping,
        apply_changes=True, client=_Client(),
    )
    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
    by_id = {item["component_id"]: item for item in snapshot["components"]}
    data = next(
        item for item in snapshot["components"]
        if item["title"] == "数据契约"
    )
    factor = next(
        item for item in snapshot["components"]
        if item["title"] == "因子语义"
    )
    assert by_id[legacy]["parent_id"] == data["component_id"]
    assert by_id[legacy]["body"] == "人工记录"
    assert by_id["section-t1"]["parent_id"] == data["component_id"]
    assert by_id["section-t2"]["parent_id"] == legacy
    assert by_id["section-t5"]["parent_id"] == factor["component_id"]
    assert applied["created_container_count"] == 2
    repeated = history._reconcile(
        profile_id="maxa", work_package_id="wp", branch_id="branch",
        release_profile=None, component_map_file=mapping,
        apply_changes=True, client=_Client(),
    )
    assert repeated["created_container_count"] == 0
    assert repeated["moved_item_count"] == 0
    assert repeated["git"]["committed"] is False
