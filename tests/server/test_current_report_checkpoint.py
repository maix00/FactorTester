from __future__ import annotations

import sqlite3

import pytest

from server.services.research_graph.branch.schema import (
    create_instance_branch_schema, ensure_instance_branch_schema,
)
from server.services.research_graph.current_report_checkpoint import (
    append_current_report_checkpoint,
    load_current_report_submission,
)
from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
    report_item_hash,
)


def _seed(path, monkeypatch) -> None:
    monkeypatch.setattr("settings.CACHE_DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        create_instance_branch_schema(conn)
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, created_at
            ) VALUES ('instance-1', 'owner-1', 'graph-1', 9, 'MaxA', 'ws', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash, created_at, updated_at
            ) VALUES (
                'branch-1', 'instance-1', 'main', 'research', 'active',
                '{}', 'resolution', 1, 1
            )
            """
        )


def _submission(count: int = 11) -> dict:
    content = [
        {"text": "中文叙事"},
        {"latex": r"\operatorname{SgCPSVol}_{t}=\sigma(r_{t-19:t})"},
        {"items": ["定义", "滞后", "稳健性"]},
        {
            "columns": ["窗口", "IC"],
            "rows": [["20", "0.031"], ["60", "0.018"]],
        },
    ]
    items = []
    for index in range(count):
        kind = ("sentence", "figure", "list", "table")[index % 4]
        item = {
            "report_requirement_id": f"maxa-{index + 1}",
            "subject_ref": "factor:SgCPSVol",
            "content_kind": kind,
        }
        item["item_hash"] = report_item_hash(
            **item,
            content=content[index % 4],
        )
        items.append(item)
    return {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(items),
        "items": items,
    }


def test_maxa_items_append_idempotently_without_advancing(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.db"
    _seed(path, monkeypatch)
    kwargs = {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "owner": "owner-1",
        "node_id": "research",
        "report_submission": _submission(),
        "report_artifact_ref": "artifact:research/instance-1/branches/branch-1/authoring/HEAD.json",
    }
    first = append_current_report_checkpoint(**kwargs)
    second = append_current_report_checkpoint(**kwargs)

    assert first == second
    assert len(first["coverage"]) == 11
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_report_item_checkpoints"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT current_node FROM research_graph_branches"
        ).fetchone()[0] == "research"
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_trace"
        ).fetchone()[0] == 0


def test_batches_append_history_and_failure_does_not_advance(
    tmp_path, monkeypatch,
):
    path = tmp_path / "checkpoint.db"
    _seed(path, monkeypatch)
    common = {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "owner": "owner-1",
        "node_id": "research",
        "report_artifact_ref": "artifact:research/instance-1/branches/branch-1/authoring/HEAD.json",
    }
    append_current_report_checkpoint(
        **common, report_submission=_submission(5),
    )
    append_current_report_checkpoint(
        **common, report_submission=_submission(11),
    )
    invalid = _submission(1)
    invalid["items"][0]["item_hash"] = "0" * 64
    with pytest.raises(ValueError, match="fragment_hash mismatch"):
        append_current_report_checkpoint(
            **common, report_submission=invalid,
        )

    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_report_item_checkpoints"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT current_node FROM research_graph_branches"
        ).fetchone()[0] == "research"


def test_current_visit_submission_merges_receipts_and_excludes_history(
    tmp_path, monkeypatch,
):
    path = tmp_path / "checkpoint.db"
    _seed(path, monkeypatch)
    common = {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "owner": "owner-1",
        "node_id": "research",
        "report_artifact_ref": (
            "artifact:research/instance-1/branches/branch-1/authoring/HEAD.json"
        ),
    }
    append_current_report_checkpoint(
        **common, report_submission=_submission(5),
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE research_report_item_checkpoints SET created_at=1"
        )
    append_current_report_checkpoint(
        **common, report_submission=_submission(6),
    )
    cutoff = 2
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        current = load_current_report_submission(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            node_id="research",
            owner="owner-1",
            since=cutoff,
        )
        excluded = load_current_report_submission(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            node_id="research",
            owner="another-owner",
            since=0,
        )

    assert current is not None
    assert len(current["items"]) == 6
    assert current["fragment_hash"] == _submission(6)["fragment_hash"]
    assert excluded is None


def test_authoritative_action_result_submission_is_accepted(
    tmp_path, monkeypatch,
):
    from server.services.research_step.result_reporting.projection import (
        build_result_report_projection,
    )

    path = tmp_path / "result-report.db"
    _seed(path, monkeypatch)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE research_graph_branches "
            "SET current_node='trial_execution'"
        )
    projection = build_result_report_projection(
        action={
            "action_id": "action:ic",
            "obligation_refs": [],
            "output_evidence_refs": ["evidence:" + "a" * 64],
        },
        plan_hash="b" * 64,
        rows=[{
            "index": 1, "run_id": "run-1", "job_id": "job-1",
            "kind": "ic", "status": "succeeded", "trial_role": "candidate",
            "run_spec_hash": "c" * 64, "run_spec_alias_zh": "截面 IC · 日盘",
            "result_summary": {"mean_ic": 0.031},
        }],
        receipt=None,
    )

    receipt = append_current_report_checkpoint(
        instance_id="instance-1", branch_id="branch-1", owner="owner-1",
        node_id="trial_execution",
        report_submission=projection["report_submission"],
        report_artifact_ref="artifact:research/instance-1/branches/branch-1/authoring/HEAD.json",
    )

    assert len(receipt["coverage"]) == 2
    assert {
        item["report_requirement_id"] for item in receipt["coverage"]
    } == {"report.node.trial_execution.action"}


def test_legacy_journal_receipt_column_is_migrated_once(tmp_path, monkeypatch):
    path = tmp_path / "legacy-receipt.db"
    _seed(path, monkeypatch)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("ALTER TABLE research_report_item_checkpoints RENAME TO old_receipts")
        conn.execute(
            """
            CREATE TABLE research_report_item_checkpoints (
                checkpoint_hash TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
                branch_id TEXT NOT NULL, node_id TEXT NOT NULL,
                fragment_hash TEXT NOT NULL, report_items_json TEXT NOT NULL,
                journal_artifact_ref TEXT NOT NULL, actor TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO research_report_item_checkpoints VALUES "
            "('hash', 'instance-1', 'branch-1', 'research', 'fragment', '[]', "
            "'journal-artifact:sha256:legacy', 'owner-1', 1)"
        )
        conn.execute("DROP TABLE old_receipts")
        ensure_instance_branch_schema(conn)
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(research_report_item_checkpoints)"
            )
        }
        value = conn.execute(
            "SELECT report_artifact_ref FROM research_report_item_checkpoints"
        ).fetchone()[0]
    assert columns >= {"report_artifact_ref"}
    assert "journal_artifact_ref" not in columns
    assert value == "journal-artifact:sha256:legacy"
