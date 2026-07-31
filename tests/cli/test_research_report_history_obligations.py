from __future__ import annotations

from types import SimpleNamespace

from tools.cli.commands import research_report_history_reconciliation as history
from tools.cli.commands.research_graph_obligations import (
    _load_logical_obligation_history,
)
from tools.cli.commands.research_report_history_obligations import (
    obligation_change_operations,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)

from tests.cli.test_research_graph_detour_report import _scope


class _ObligationHistoryClient:
    def list_profile_research_branch_timeline(
        self, _work_package, _branch, *, limit, after,
    ):
        assert limit == 50
        return {
            "items": [] if after else [{
                "step_ref": "trace:obligation-step",
                "from_node": "data_contract",
                "to_node": "factor_semantics",
                "created_at": 2,
                "source_report_container": {
                    "kind": "chapter",
                    "anchor_node": "data_contract",
                },
                "report_container": {
                    "kind": "chapter",
                    "anchor_node": "factor_semantics",
                },
                "capability_detour": {
                    "state_before": None,
                    "delta": None,
                    "state_after": None,
                },
                "evidence_refs": [],
                "obligation_changes": [{
                    "obligation_id": "coverage",
                    "from_state": "open",
                    "to_state": "bounded",
                    "from_requirement_refs": [],
                    "to_requirement_refs": ["data.coverage"],
                }],
                "obligation_presentations": [{
                    "obligation_ref": "obligation:coverage",
                    "title_zh": "数据覆盖",
                    "question_summary": "数据是否覆盖预注册试验范围？",
                }],
                "requirement_presentations": [{
                    "requirement_id": "data.coverage",
                    "title_zh": "数据覆盖",
                }],
            }],
            "next_cursor": None,
        }

    def get_research_graph_node_info(self, *_args):
        raise AssertionError("timeline should provide report history")


class _ExactBranchHistoryClient:
    def list_profile_research_timeline(
        self, research_ref, *, limit, after,
    ):
        assert research_ref == "graph-branch:instance:historical"
        assert limit == 50
        assert after == ""
        return {"items": [], "next_cursor": None}

    def list_profile_research_branch_timeline(self, *_args, **_kwargs):
        raise AssertionError("must not resolve history through current branch")


class _LogicalBranchHistoryClient:
    def list_profile_research_branch_timeline(
        self, work_package_ref, branch_id, *, limit, after,
    ):
        assert work_package_ref == "work-package:logical"
        assert branch_id == "current"
        assert limit == 50
        assert after == ""
        return {"items": [], "next_cursor": None}

    def list_profile_research_timeline(self, *_args, **_kwargs):
        raise AssertionError("migration must include inherited history")


def test_obligation_ledger_migration_uses_logical_branch_history() -> None:
    items = _load_logical_obligation_history(
        _LogicalBranchHistoryClient(),
        scope=SimpleNamespace(record={"record_id": "logical"}),
        branch_id="current",
    )
    assert items == []


def test_history_loader_can_read_one_exact_historical_incarnation() -> None:
    from tools.cli.commands.research_report_history_timeline import (
        load_history,
        obligation_history_contexts,
    )

    items = load_history(
        _ExactBranchHistoryClient(),
        work_package_ref="work-package:logical",
        branch_id="historical",
        research_ref="graph-branch:instance:historical",
    )
    assert items == []
    assert obligation_history_contexts(items) == []


def test_obligation_history_does_not_depend_on_report_container_replay() -> None:
    from tools.cli.commands.research_report_history_timeline import (
        obligation_history_contexts,
    )

    contexts = obligation_history_contexts([{
        "step_ref": "trace:continuation",
        "from_node": "capability_gap",
        "to_node": "capability_gap",
        "created_at": 1,
        "obligation_changes": [],
        "obligation_presentations": [],
        "source_report_container": {
            "kind": "special",
            "resume_node_required": True,
        },
        "report_container": {
            "kind": "special",
            "resume_node_required": True,
        },
    }])

    assert contexts == [{
        "step_ref": "trace:continuation",
        "side": "target",
        "from_node": "capability_gap",
        "to_node": "capability_gap",
        "created_at": 1,
        "obligation_changes": [],
        "obligation_presentations": [],
        "requirement_presentations": [],
    }]


def test_history_replay_preserves_legacy_special_bindings() -> None:
    contexts = [{
        "step_ref": "trace:obligation-step",
        "side": "target",
        "from_node": "data_contract",
        "to_node": "factor_semantics",
        "obligation_changes": [{
            "obligation_id": "coverage",
            "from_state": "open",
            "to_state": "bounded",
            "from_requirement_refs": [],
            "to_requirement_refs": ["data.coverage"],
        }],
        "obligation_presentations": [{
            "obligation_ref": "obligation:coverage",
            "title_zh": "数据覆盖",
            "question_summary": "数据覆盖问题",
        }],
        "requirement_presentations": [{
            "requirement_id": "data.coverage",
            "title_zh": "数据覆盖",
        }],
    }]
    components = {}
    first, _ = obligation_change_operations(
        contexts,
        parent_by_step={"trace:obligation-step": "chapter-factor"},
        components=components,
    )
    special = next(item for item in first if item["kind"] == "special")
    components[special["component_id"]]["bindings"] = [{
        "binding_id": "legacy-obligation-binding",
        "kind": "obligation",
        "target_ref": "obligation:coverage",
        "label": "coverage",
        "data": {},
    }]

    repeated, _ = obligation_change_operations(
        contexts,
        parent_by_step={"trace:obligation-step": "chapter-factor"},
        components=components,
    )

    assert repeated == []


def test_reconciliation_rebuilds_obligation_changes_as_special_section(
    tmp_path,
    monkeypatch,
) -> None:
    scope, _ = _scope(tmp_path)
    scope.store.upsert_research_record("maxa", {
        **scope.store.load("maxa")["research_records"][0],
        "graph_instance_ref": "work-package:wp",
    })
    monkeypatch.setattr(
        history, "load_profile_root", lambda _path: scope.client_root,
    )
    options = {
        "profile_id": "maxa",
        "work_package_id": "wp",
        "branch_id": "branch",
        "release_profile": None,
        "component_map_file": None,
        "client": _ObligationHistoryClient(),
    }

    plan = history._reconcile(**options, apply_changes=False)
    assert plan["obligation_change_episode_count"] == 1
    assert plan["obligation_change_count"] == 1

    applied = history._reconcile(**options, apply_changes=True)
    snapshot = load_snapshot(
        package_root=scope.package_root,
        branch_id="branch",
    )
    by_id = {item["component_id"]: item for item in snapshot["components"]}
    special = next(
        item for item in snapshot["components"]
        if item["display_kind"] == "obligation_changes"
    )
    tables = [
        item for item in snapshot["components"]
        if item["parent_id"] == special["component_id"]
        and item["kind"] == "table"
    ]
    table = next(item for item in tables if item["title"] == "义务变化")
    current = next(
        item for item in tables if item["title"] == "当前义务清单"
    )
    coverage = next(
        item for item in tables if item["title"] == "义务要求覆盖"
    )
    parent = by_id[special["parent_id"]]

    assert parent["title"] == "因子语义"
    assert special["kind"] == "special"
    assert special["title"] == "数据契约 → 因子语义"
    assert table["content"]["rows"][0][1] == "数据是否覆盖预注册试验范围？"
    assert "factortester://obligation/" in table["content"]["rows"][0][0]
    assert "factortester://entry_requirement/" in (
        table["content"]["rows"][0][4]
    )
    assert table["content"]["columns"] == [
        "研究义务", "问题", "原状态", "新状态",
        "新增覆盖小类", "移除覆盖小类", "证据", "证据使用理由",
    ]
    assert current["display_kind"] == "current_obligations"
    assert coverage["display_kind"] == "obligation_requirement_coverage"
    assert coverage["content"]["columns"] == [
        "义务小类", "小类说明", "当前覆盖义务", "覆盖义务状态",
        "证据", "节点要求", "Edge 义务", "最低证据资格", "满足状态",
    ]
    assert "factortester://entry_requirement/" in (
        coverage["content"]["rows"][0][0]
    )
    assert "factortester://obligation/" in (
        coverage["content"]["rows"][0][2]
    )
    assert applied["obligation_change_operation_count"] == 4

    repeated = history._reconcile(**options, apply_changes=True)
    assert repeated["obligation_change_operation_count"] == 0
    assert repeated["git"]["committed"] is False
