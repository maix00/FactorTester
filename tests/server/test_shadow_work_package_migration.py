from __future__ import annotations

import sqlite3

import orjson

from server.services.research_graph.shadow_work_package_migration import (
    apply_shadow_work_package_migration,
    plan_shadow_work_package_migration,
)


def test_split_shadow_work_packages_are_rebound_and_deleted(tmp_path):
    path = tmp_path / "graph.sqlite"
    conn = sqlite3.connect(path)
    _schema(conn)
    conn.execute(
        "INSERT INTO research_work_packages VALUES ('alice','source','ws')"
    )
    for instance_id, branch_id, traces, objects in (
        ("keep", "keep-branch", 3, 1),
        ("drop-a", "drop-a-branch", 1, 0),
        ("drop-b", "drop-b-branch", 1, 0),
    ):
        conn.execute(
            """
            INSERT INTO research_work_packages VALUES ('alice', ?, 'ws')
            """,
            (instance_id,),
        )
        conn.execute(
            """
            INSERT INTO research_graph_instances VALUES (
                ?, 'alice', 'factor-research', 10, 'ws', 'shadow',
                'run', ?
            )
            """,
            (instance_id, instance_id),
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches VALUES (?, ?, 'node', 'paused', ?)
            """,
            (branch_id, instance_id, f"trace-{instance_id}-{traces - 1}"),
        )
        for index in range(traces):
            evidence = (
                {"graph_continuation": {
                    "source_instance_id": "source",
                    "source_branch_id": "source-branch",
                    "work_package_id": "source",
                    "shadow_proposal_id": "proposal",
                }}
                if index == 0 else {}
            )
            conn.execute(
                """
                INSERT INTO research_graph_trace VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"trace-{instance_id}-{index}",
                    instance_id,
                        branch_id,
                        orjson.dumps(evidence).decode(),
                        float(index),
                ),
            )
        for index in range(objects):
            conn.execute(
                "INSERT INTO research_graph_objects VALUES (?, ?)",
                (instance_id, f"object-{index}"),
            )
        conn.execute(
            "INSERT INTO research_report_item_checkpoints VALUES (?, ?)",
            (instance_id, branch_id),
        )
    conn.commit()
    conn.close()

    plan = plan_shadow_work_package_migration(
        db_path=path,
        owner="alice",
        source_work_package_id="source",
        retained_instance_id="keep",
        retired_instance_ids=["drop-a", "drop-b"],
    )
    receipt = apply_shadow_work_package_migration(
        db_path=path, plan=plan,
    )

    assert receipt["status"] == "applied"
    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT work_package_id FROM research_graph_instances "
        "WHERE instance_id='keep'"
    ).fetchone()[0] == "source"
    assert conn.execute(
        "SELECT COUNT(*) FROM research_graph_instances"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM research_work_packages"
    ).fetchone()[0] == 1
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE research_work_packages (
            owner TEXT, work_package_id TEXT, workspace_id TEXT
        );
        CREATE TABLE research_graph_instances (
            instance_id TEXT, owner TEXT, graph_id TEXT,
            graph_version INTEGER, workspace_id TEXT, mode TEXT,
            shadow_run_id TEXT, work_package_id TEXT
        );
        CREATE TABLE research_graph_branches (
            branch_id TEXT, instance_id TEXT, current_node TEXT,
            status TEXT, latest_trace_id TEXT
        );
        CREATE TABLE research_graph_trace (
            trace_id TEXT, instance_id TEXT, branch_id TEXT,
            evidence_json TEXT, created_at REAL
        );
        CREATE TABLE research_graph_objects (
            instance_id TEXT, object_id TEXT
        );
        CREATE TABLE research_graph_capability_detours (
            instance_id TEXT
        );
        CREATE TABLE research_report_item_checkpoints (
            instance_id TEXT, branch_id TEXT
        );
        CREATE TABLE trial_plan_action_adjudication_receipts (
            instance_id TEXT
        );
        """
    )
