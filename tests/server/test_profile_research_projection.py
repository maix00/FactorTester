from __future__ import annotations

import time

from flask import Flask
import orjson
import pytest

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
)
from server.services.research_graph import (
    profile_research_projection as projection,
)
from tools.data.sqlite.db import connect_sqlite


def _checkpoint() -> dict:
    return {
        "schema_version": 1,
        "projection_hash": "a" * 64,
        "contract_hash": "b" * 64,
        "trial_plan_hash": "c" * 64,
        "methodology_hash": "d" * 64,
        "claims": [{
            "claim_id": "claim-1",
            "claim_type": "bounded_predictive_relationship",
            "evidence_state": "unknown",
            "source_code": "must-not-leak",
        }],
        "obligations": [{
            "obligation_id": "obligation-1",
            "status": "open",
            "materiality": "decision_blocking",
            "epistemic_question": "Does the factor survive costs?",
            "markdown": "# must not leak",
        }],
        "closure": None,
    }


def _evidence(index: int) -> dict:
    return {
        "evidence_refs": [f"artifact:evidence-{index}"],
        "trial_plan_hash": "c" * 64,
        "job_attempt_request": {"job_id": f"job-{index}"},
        "run_id": f"run-{index}",
        "stdout": "private stdout",
        "source_code": "private factor source",
        "markdown": "# full report",
        "research_cycle": {
            "events": [{
                "event_type": "adjudication_proposed",
                "proposal": {
                    "obligation_delta": [{
                        "obligation_id": "obligation-1",
                        "from_state": "open",
                        "to_state": "serviced",
                        "criterion_ref": "trial:cost",
                    }],
                    "claim_evidence_delta": [{
                        "claim_id": "claim-1",
                        "from_state": "unknown",
                        "to_state": "inconclusive",
                    }],
                },
            }],
        },
        "research_cycle_checkpoint": _checkpoint(),
    }


def _seed(path, *, branch_count: int = 3, trace_count: int = 5) -> None:
    now = 1_000.0
    with connect_sqlite(path) as conn:
        create_instance_branch_schema(conn)
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, mode, shadow_run_id, created_at
            ) VALUES (
                'instance-a', 'alice', 'factor-research', 6, 'CNFutures',
                'workspace-a', 'live', '', ?
            )
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, mode, shadow_run_id, created_at
            ) VALUES (
                'instance-bob', 'bob', 'factor-research', 6, 'CNFutures',
                'workspace-a', 'live', '', ?
            )
            """,
            (now,),
        )
        conn.executemany(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, trial_stage_projection_json,
                evidence_refs_json, omitted_evidence_count,
                latest_trace_id, created_at, updated_at
            ) VALUES (?, 'instance-a', ?, 'statistical_robustness', 'running',
                      '{}', ?, ?, ?, ?, 3, ?, ?, ?)
            """,
            [
                (
                    f"branch-{index:04d}",
                    f"research {index}",
                    f"resolution-{index}",
                    "c" * 64,
                    orjson.dumps({
                        "current_stage": "selection",
                        "plan_version": 1,
                    }).decode(),
                    orjson.dumps([f"artifact:current-{index}"]).decode(),
                    f"trace-{min(index, trace_count - 1):06d}",
                    now + index,
                    now + index,
                )
                for index in range(branch_count)
            ],
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, trial_stage_projection_json,
                evidence_refs_json, omitted_evidence_count,
                latest_trace_id, created_at, updated_at
            ) VALUES (
                'branch-bob', 'instance-bob', 'bob private', 'hypothesis',
                'running', '{}', '', '', '{}', '[]', 0, '', ?, ?
            )
            """,
            (now, now),
        )
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                ?, 'instance-a', 'branch-0000', ?,
                'factor_semantics', 'statistical_robustness',
                ?, '{"input_tokens":999}', 'research-agent', ?
            )
            """,
            [
                (
                    f"trace-{index:06d}",
                    f"edge-{index}",
                    (
                        "{}"
                        if trace_count > 1_000
                        else orjson.dumps(_evidence(index)).decode()
                    ),
                    now + index,
                )
                for index in range(trace_count)
            ],
        )


def _service(path, monkeypatch) -> projection.ProfileResearchProjection:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    return projection.ProfileResearchProjection()


def test_research_projects_one_work_package_with_hypothesis_branches(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "work-package-research.sqlite"
    _seed(path, branch_count=3)
    service = _service(path, monkeypatch)

    listing = service.list_research(
        owner="alice",
        workspace_ref="workspace:workspace-a",
    )

    assert [item["research_ref"] for item in listing["items"]] == [
        "work-package:instance-a",
    ]
    assert listing["items"][0]["branch_count"] == 3
    detail = service.get_research(
        owner="alice",
        research_ref="work-package:instance-a",
    )
    assert detail["work_package_ref"] == "work-package:instance-a"
    assert [item["branch_ref"] for item in detail["branches"]] == [
        "graph-branch:instance-a:branch-0002",
        "graph-branch:instance-a:branch-0001",
        "graph-branch:instance-a:branch-0000",
    ]


def test_work_package_list_keyset_pages_instances_not_branches(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "work-package-pagination.sqlite"
    _seed(path, branch_count=3)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, mode, shadow_run_id, created_at
            ) VALUES (
                'instance-new', 'alice', 'factor-research', 6,
                'CNFutures', 'workspace-a', 'live', '', 2000
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, trial_stage_projection_json,
                evidence_refs_json, omitted_evidence_count,
                latest_trace_id, created_at, updated_at
            ) VALUES (
                'branch-new', 'instance-new', 'new research', 'hypothesis',
                'running', '{}', '', '', '{}', '[]', 0, '', 2000, 2000
            )
            """
        )
    service = _service(path, monkeypatch)

    first = service.list_research(
        owner="alice", workspace_ref="workspace:workspace-a", limit=1
    )
    second = service.list_research(
        owner="alice",
        workspace_ref="workspace:workspace-a",
        limit=1,
        after=first["next_cursor"],
    )

    assert [item["research_ref"] for item in first["items"]] == [
        "work-package:instance-new"
    ]
    assert [item["research_ref"] for item in second["items"]] == [
        "work-package:instance-a"
    ]


def test_list_detail_and_timeline_are_bounded_source_free_and_keyset_paged(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "profile-research.sqlite"
    _seed(path)
    service = _service(path, monkeypatch)

    first = service.list_research(
        owner="alice",
        workspace_ref="workspace:workspace-a",
        limit=2,
    )
    assert [item["research_ref"] for item in first["items"]] == [
        "work-package:instance-a",
    ]
    assert first["items"][0]["branch_count"] == 3
    assert first["next_cursor"] is None

    detail = service.get_research(
        owner="alice",
        research_ref="work-package:instance-a",
    )
    assert len(detail["branches"]) == 3
    branch = service.get_branch(
        owner="alice",
        branch_ref="graph-branch:instance-a:branch-0000",
    )
    assert branch["research_cycle"]["obligations"] == [{
        "obligation_ref": "obligation:obligation-1",
        "status": "open",
        "materiality": "decision_blocking",
        "question_summary": "Does the factor survive costs?",
    }]
    assert branch["timeline_href"].endswith("/timeline")
    carrier = branch["report_checkpoint"]
    assert carrier["checkpoint_ref"] == "trace:trace-000000"
    assert carrier["work_package_ref"] == "work-package:instance-a"
    assert carrier["branch_ref"] == (
        "graph-branch:instance-a:branch-0000"
    )
    assert carrier["decision_contract_hash"] == "b" * 64
    assert carrier["methodology_hash"] == "d" * 64
    assert carrier["trial_plan_hash"] == "c" * 64
    assert carrier["latest_transition"]["step_ref"] == (
        "trace:trace-000000"
    )
    assert carrier["latest_transition"]["job_refs"] == ["job:job-0"]
    serialized_detail = orjson.dumps(branch)
    for forbidden in (
        b"source_code",
        b"private factor source",
        b"private stdout",
        b"# full report",
        b"# must not leak",
    ):
        assert forbidden not in serialized_detail

    timeline = service.list_timeline(
        owner="alice",
        research_ref="graph-branch:instance-a:branch-0000",
        limit=2,
    )
    assert len(timeline["items"]) == 2
    assert timeline["next_cursor"]
    step = timeline["items"][0]
    assert step["obligation_changes"] == [{
        "obligation_id": "obligation-1",
        "from_state": "open",
        "to_state": "serviced",
    }]
    assert step["claim_changes"][0]["to_state"] == "inconclusive"
    assert step["job_stream_hrefs"][0].startswith("/api/jobs/")
    serialized_step = orjson.dumps(step)
    assert b"evidence_json" not in serialized_step
    assert b"telemetry_json" not in serialized_step
    assert b"input_tokens" not in serialized_step
    assert len(orjson.dumps(first)) < 64 * 1024
    assert len(orjson.dumps(timeline)) < 64 * 1024


def test_projection_uses_one_read_and_owner_scope_returns_not_found(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "profile-read-count.sqlite"
    _seed(path)
    statements: list[str] = []
    real_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(projection, "connect_sqlite", traced_connect)
    service = _service(path, monkeypatch)
    service.get_research(
        owner="alice",
        research_ref="work-package:instance-a",
    )
    normalized = [
        " ".join(statement.upper().split())
        for statement in statements
    ]
    assert sum(item.startswith("SELECT ") for item in normalized) == 1
    assert not any(item.startswith((
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "REPLACE ",
    )) for item in normalized)

    statements.clear()
    service.get_branch(
        owner="alice",
        branch_ref="graph-branch:instance-a:branch-0000",
    )
    normalized = [
        " ".join(statement.upper().split())
        for statement in statements
    ]
    assert sum(item.startswith("SELECT ") for item in normalized) == 1
    assert not any(item.startswith((
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "REPLACE ",
    )) for item in normalized)

    with pytest.raises(KeyError, match="not found"):
        service.get_research(
            owner="bob",
            research_ref="work-package:instance-a",
        )


def test_large_scope_query_plans_use_indexes_and_ignore_global_history(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "profile-large.sqlite"
    _seed(path, branch_count=1_000, trace_count=100_000)
    service = _service(path, monkeypatch)

    started = time.perf_counter()
    listed = service.list_research(
        owner="alice",
        workspace_ref="workspace:workspace-a",
        limit=20,
    )
    timeline = service.list_timeline(
        owner="alice",
        research_ref="graph-branch:instance-a:branch-0000",
        limit=50,
    )
    elapsed = time.perf_counter() - started

    assert len(listed["items"]) == 1
    assert listed["items"][0]["branch_count"] == 1_000
    assert len(timeline["items"]) == 50
    assert elapsed < 2.0
    with connect_sqlite(path) as conn:
        list_plan = conn.execute(
            "EXPLAIN QUERY PLAN " + projection.LIST_FIRST_SQL,
            ("alice", "workspace-a", 21),
        ).fetchall()
        timeline_plan = conn.execute(
            "EXPLAIN QUERY PLAN " + projection.TIMELINE_FIRST_SQL,
            ("branch-0000", "alice", "instance-a", 51),
        ).fetchall()
    details = [
        str(row["detail"]).upper()
        for row in [*list_plan, *timeline_plan]
    ]
    assert any(
        "IDX_RESEARCH_GRAPH_INSTANCES_OWNER_WORKSPACE" in item
        for item in details
    )
    assert any(
        "IDX_RESEARCH_GRAPH_TRACE_BRANCH_TIMELINE" in item
        for item in details
    )
    assert not any("SCAN T" in item for item in details)


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    path = tmp_path / "profile-routes.sqlite"
    _seed(path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    app = Flask(__name__)
    app.secret_key = "profile-research-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_authenticated_routes_emit_etag_and_honor_conditional_reads(
    app_client,
) -> None:
    listing = app_client.get(
        "/api/profile-research",
        query_string={
            "workspace_ref": "workspace:workspace-a",
            "limit": 2,
        },
    )
    assert listing.status_code == 200
    assert listing.headers["ETag"]
    payload = listing.get_json()
    assert payload["success"] is True
    research_ref = payload["items"][-1]["research_ref"]
    assert research_ref == "work-package:instance-a"

    unchanged = app_client.get(
        "/api/profile-research",
        query_string={
            "workspace_ref": "workspace:workspace-a",
            "limit": 2,
        },
        headers={"If-None-Match": listing.headers["ETag"]},
    )
    assert unchanged.status_code == 304
    assert unchanged.data == b""

    detail = app_client.get(f"/api/profile-research/{research_ref}")
    timeline = app_client.get(
        "/api/profile-research/"
        "work-package:instance-a/branches/branch-0000/timeline",
        query_string={"limit": 3},
    )
    branch = app_client.get(
        "/api/profile-research/"
        "work-package:instance-a/branches/branch-0000"
    )
    assert detail.status_code == 200
    assert len(detail.get_json()["branches"]) == 3
    assert branch.status_code == 200
    assert branch.get_json()["branch_ref"].endswith(":branch-0000")
    assert timeline.status_code == 200
    assert len(timeline.get_json()["items"]) == 3


def test_routes_fail_closed_for_other_owner_and_invalid_paging(
    app_client,
) -> None:
    with app_client.session_transaction() as session:
        session["username"] = "bob"
    denied = app_client.get(
        "/api/profile-research/graph-branch:instance-a:branch-0000"
    )
    assert denied.status_code == 404

    with app_client.session_transaction() as session:
        session["username"] = "alice"
    too_large = app_client.get(
        "/api/profile-research",
        query_string={
            "workspace_ref": "workspace:workspace-a",
            "limit": 51,
        },
    )
    invalid_cursor = app_client.get(
        "/api/profile-research",
        query_string={
            "workspace_ref": "workspace:workspace-a",
            "after": "not-a-cursor",
        },
    )
    assert too_large.status_code == 400
    assert invalid_cursor.status_code == 400
