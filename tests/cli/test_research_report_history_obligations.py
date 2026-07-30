from __future__ import annotations

from tools.cli.commands import research_report_history_reconciliation as history
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
                    "question_summary": "数据是否覆盖预注册试验范围？",
                }],
            }],
            "next_cursor": None,
        }

    def get_research_graph_node_info(self, *_args):
        raise AssertionError("timeline should provide report history")


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
    table = next(
        item for item in snapshot["components"]
        if item["parent_id"] == special["component_id"]
        and item["kind"] == "table"
    )
    parent = by_id[special["parent_id"]]

    assert parent["title"] == "因子语义"
    assert special["kind"] == "special"
    assert special["title"] == "数据契约 → 因子语义"
    assert table["content"]["rows"][0][1] == "数据是否覆盖预注册试验范围？"
    assert "factortester://obligation/" in table["content"]["rows"][0][0]
    assert table["content"]["rows"][0][4] == "新增 `data.coverage`"
    assert applied["obligation_change_operation_count"] == 2

    repeated = history._reconcile(**options, apply_changes=True)
    assert repeated["obligation_change_operation_count"] == 0
    assert repeated["git"]["committed"] is False
