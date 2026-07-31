from __future__ import annotations

import json

from server.services.research_graph.branch.capability_detour import (
    project_trace_rows,
)
from tools.cli.commands import research_report_history_reconciliation as history
from tools.cli.commands.research_report_history_apply import (
    _bound_anchor_chapters,
)
from tools.cli.commands.research_report_history_map import load_history_map
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.commands.research_report_history_timeline import (
    history_contexts,
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
            "evidence_refs": (
                ["report:legacy-upgrade-report"]
                if row["trace_id"] == "t1" else []
            ),
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

    def get_research_graph_node_info(self, _instance, _branch):
        return {"graph": "factor-research@v10"}

    def list_research_graph_versions(self, _graph_id):
        return [{
            "version": 10,
            "requirement_catalog": {"requirements": [{
                "requirement_id": (
                    "hypothesis_validity.mechanism_chain"
                ),
                "title_zh": "机制作用链",
            }]},
        }]


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


def test_history_includes_each_transition_source_container() -> None:
    rows = [
        _row(
            "legacy-open",
            "hypothesis_preregistration",
            "capability_resolution",
            1,
        ),
        _row(
            "legacy-exit",
            "capability_resolution",
            "data_contract",
            2,
        ),
        _row("ordinary-next", "data_contract", "factor_semantics", 3),
    ]
    placements = project_trace_rows(rows)["items"]
    items = [{
        "step_ref": f"trace:{row['trace_id']}",
        "from_node": row["from_node"],
        "to_node": row["to_node"],
        "created_at": row["created_at"],
        "evidence_refs": [],
        "obligation_changes": [],
        "obligation_presentations": [],
        **placements[row["trace_id"]],
    } for row in rows]

    contexts = history_contexts(items)

    assert any(
        item["side"] == "source"
        and item["container"]["kind"] == "chapter"
        and item["container"]["anchor_node"] == "data_contract"
        for item in contexts
    )


def test_history_map_accepts_reviewed_pre_binding_requirement(
    tmp_path,
) -> None:
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({
        "schema_version": 3,
        "episode_components": {},
        "component_parents": {},
        "component_special_kinds": {},
        "component_requirements": {
            "historical-mechanism": {
                "requirement_id": "hypothesis_validity.mechanism_chain",
                "subject_ref": "obligation:price-momentum-core-hypothesis",
                "content_kind": "list",
            },
        },
    }), encoding="utf-8")

    result = load_history_map(mapping, episode_ids=set())

    assert result["component_requirements"] == {
        "historical-mechanism": {
            "requirement_id": "hypothesis_validity.mechanism_chain",
            "subject_ref": "obligation:price-momentum-core-hypothesis",
            "content_kind": "list",
        },
    }


def test_history_map_accepts_reviewed_report_component_alias(
    tmp_path,
) -> None:
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({
        "schema_version": 4,
        "episode_components": {},
        "component_parents": {},
        "component_special_kinds": {
            "historical-upgrade": "graph_continuation",
        },
        "component_requirements": {},
        "report_components": {
            "legacy-upgrade-report": "historical-upgrade",
        },
    }), encoding="utf-8")

    result = load_history_map(mapping, episode_ids=set())

    assert result["report_components"] == {
        "legacy-upgrade-report": "historical-upgrade",
    }


def test_detour_only_history_preserves_inherited_anchor_chapter() -> None:
    snapshot = {
        "components": [{
            "component_id": "chapter-hypothesis",
            "kind": "chapter",
            "parent_id": None,
        }, {
            "component_id": "chapter-capability",
            "kind": "chapter",
            "parent_id": None,
        }],
        "bindings": [{
            "component_id": "chapter-hypothesis",
            "kind": "graph_reference",
            "target_ref": "node:hypothesis_preregistration",
            "data": {"role": "report_chapter"},
        }, {
            "component_id": "chapter-capability",
            "kind": "graph_reference",
            "target_ref": "node:capability_gap",
            "data": {"role": "report_chapter"},
        }],
    }

    assert _bound_anchor_chapters(
        snapshot,
        anchor_nodes={"hypothesis_preregistration"},
    ) == {"chapter-hypothesis"}


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
    _component(scope, "section-t3", chapter["component_id"], "trace:t3")
    _component(scope, "section-t5", chapter["component_id"], "trace:t5")
    add_component(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
        component_id="historical-mechanism",
        kind="entry",
        title="历史机制正文",
        parent_id=chapter["component_id"],
        body="保留历史机制正文",
        content=None,
        display_kind="",
        bindings=[],
    )
    add_component(
        package_root=scope.package_root,
        branch_id=scope.branch_id,
        component_id="historical-upgrade",
        kind="section",
        title="研究图升级",
        parent_id=chapter["component_id"],
        body="保留历史图升级说明",
        content=None,
        display_kind="",
        bindings=[],
    )
    commit_work_package(scope.package_root, message="Historical report fixture")
    scope.store.upsert_research_record("maxa", {
        **scope.store.load("maxa")["research_records"][0],
        "graph_instance_ref": "work-package:wp",
    })
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({
        "schema_version": 4,
        "episode_components": {"capability-detour:t2": legacy},
        "component_parents": {
            "section-t1": chapter["component_id"],
            legacy: chapter["component_id"],
        },
        "component_special_kinds": {
            "historical-upgrade": "graph_continuation",
        },
        "component_requirements": {
            "historical-mechanism": {
                "requirement_id": (
                    "hypothesis_validity.mechanism_chain"
                ),
                "subject_ref": (
                    "obligation:price-momentum-core-hypothesis"
                ),
                "content_kind": "list",
            },
        },
        "report_components": {
            "legacy-upgrade-report": "historical-upgrade",
        },
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
    assert plan["historical_requirement_count"] == 1
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
    assert by_id["section-t1"]["parent_id"] == chapter["component_id"]
    assert by_id["historical-upgrade"]["parent_id"] == data["component_id"]
    assert by_id["historical-upgrade"]["kind"] == "special"
    assert by_id["historical-upgrade"]["display_kind"] == (
        "graph_continuation"
    )
    assert by_id["section-t2"]["parent_id"] == legacy
    assert by_id["section-t3"]["parent_id"] == legacy
    assert by_id["section-t5"]["parent_id"] == factor["component_id"]
    requirement_wrapper = by_id[
        by_id["historical-mechanism"]["parent_id"]
    ]
    assert requirement_wrapper["kind"] == "special"
    assert requirement_wrapper["display_kind"] == (
        "obligation_requirement"
    )
    assert requirement_wrapper["title"] == "机制作用链"
    assert [
        item["component_id"]
        for item in snapshot["components"]
        if item["parent_id"] == legacy
    ] == ["section-t2", "section-t3"]
    assert applied["ignored_system_parent_hints"] == [legacy]
    assert applied["created_container_count"] == 3
    repeated = history._reconcile(
        profile_id="maxa", work_package_id="wp", branch_id="branch",
        release_profile=None, component_map_file=mapping,
        apply_changes=True, client=_Client(),
    )
    assert repeated["created_container_count"] == 0
    assert repeated["moved_item_count"] == 0
    assert repeated["git"]["committed"] is False
