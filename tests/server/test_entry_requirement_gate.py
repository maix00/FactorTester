from __future__ import annotations

from copy import deepcopy

import orjson
import pytest
from flask import Flask

import settings as Settings
from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services import research_graphs
from server.modules.single_factor_test import sft_bp
from server.services.research_graph.branch import (
    data_contract as data_contract_service,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.branch.entry_assessments import (
    validate_entry_requirement_assessments,
)
from server.services.research_graph.branch.entry_requirements import (
    compact_entry_requirements,
    requirement_detail,
)
from server.services.research_graph.protocol import MAX_AGENT_PACKET_BYTES
from tests.server.data_contract_fixtures import (
    checkpoint,
    graph as data_graph,
    initialize,
    profile,
    transition_evidence,
)
from tools.data.sqlite.db import connect_sqlite


REQUIREMENT_ID = "data.source_availability"


def _node(graph: dict, node_id: str = "data_contract") -> dict:
    return next(item for item in graph["nodes"] if item["node_id"] == node_id)


def _checkpoint() -> dict:
    value = deepcopy(checkpoint(obligation_status="open"))
    value["obligations"][0]["requirement_refs"] = [REQUIREMENT_ID]
    return value


def _mapped_assessment() -> dict:
    return {
        "requirement_id": REQUIREMENT_ID,
        "applicability": {
            "status": "applicable",
            "reason_zh": "当前试验需要读取目标期货产品的历史行情。",
            "fact_refs": ["data-request:A.DCE"],
        },
        "coverage": {
            "decision": "map_existing",
            "obligation_refs": ["obligation:obligation-data"],
        },
        "resolution": {
            "route": "existing_evidence",
            "reuse_status": "exact",
            "validation_refs": ["availability-receipt:A.DCE"],
        },
        "entry_effect": {
            "status": "pass",
            "limitation_refs": [],
        },
    }


def test_entry_requirement_aliases_do_not_expose_full_contracts() -> None:
    graph = build_successor_graph()

    rows = compact_entry_requirements(
        graph=graph,
        node=_node(graph),
        checkpoint=_checkpoint(),
    )

    assert rows[0]["requirement_id"] == REQUIREMENT_ID
    assert rows[0]["mapped_obligation_refs"] == [
        "obligation:obligation-data"
    ]
    assert "question_zh" not in rows[0]
    assert "industry_basis_refs" not in rows[0]


def test_one_requirement_contract_is_lazy_loaded_with_auditable_aliases() -> None:
    graph = build_successor_graph()

    detail = requirement_detail(
        graph=graph,
        node=_node(graph),
        checkpoint=_checkpoint(),
        requirement_id=REQUIREMENT_ID,
    )

    assert detail["requirement"]["question_zh"]
    assert detail["requirement"]["gate_policy"] == "plan_before_exit"
    assert detail["mapped_obligations"][0]["obligation_id"] == (
        "obligation-data"
    )


def test_assessments_must_exactly_cover_current_node_requirements() -> None:
    graph = build_successor_graph()

    with pytest.raises(ValueError, match="exactly cover current node"):
        validate_entry_requirement_assessments(
            graph=graph,
            node=_node(graph),
            checkpoint=_checkpoint(),
            target_node="factor_semantics",
            submitted=[_mapped_assessment()],
        )


def test_orthogonal_assessment_can_map_and_reuse_at_the_same_time() -> None:
    graph = build_successor_graph()
    node = deepcopy(_node(graph))
    node["entry_requirement_refs"] = [REQUIREMENT_ID]

    result = validate_entry_requirement_assessments(
        graph=graph,
        node=node,
        checkpoint=_checkpoint(),
        target_node="factor_semantics",
        submitted=[_mapped_assessment()],
    )

    assert result[0]["coverage"]["decision"] == "map_existing"
    assert result[0]["resolution"]["reuse_status"] == "exact"
    assert result[0]["entry_effect"]["status"] == "pass"


def test_capability_gap_is_a_route_not_an_obligation_disposition() -> None:
    graph = build_successor_graph()
    node = deepcopy(_node(graph))
    node["entry_requirement_refs"] = [REQUIREMENT_ID]
    assessment = _mapped_assessment()
    assessment["coverage"]["decision"] = "create_new"
    assessment["resolution"] = {
        "route": "capability_gap",
        "reuse_status": "none",
        "validation_refs": [],
    }
    assessment["entry_effect"] = {
        "status": "blocked",
        "limitation_refs": ["capability:data.availability.resolve"],
    }

    result = validate_entry_requirement_assessments(
        graph=graph,
        node=node,
        checkpoint=_checkpoint(),
        target_node="capability_gap",
        submitted=[assessment],
    )

    assert result[0]["coverage"]["decision"] == "create_new"
    assert result[0]["resolution"]["route"] == "capability_gap"


def test_non_material_decision_requires_a_fact_reference() -> None:
    graph = build_successor_graph()
    node = deepcopy(_node(graph))
    node["entry_requirement_refs"] = [REQUIREMENT_ID]
    assessment = _mapped_assessment()
    assessment["applicability"]["fact_refs"] = []
    assessment["coverage"] = {
        "decision": "no_material_issue",
        "obligation_refs": [],
    }
    assessment["resolution"] = {
        "route": "bounded_unknown",
        "reuse_status": "none",
        "validation_refs": [],
    }

    with pytest.raises(ValueError, match="needs fact refs"):
        validate_entry_requirement_assessments(
            graph=graph,
            node=node,
            checkpoint=_checkpoint(),
            target_node="factor_semantics",
            submitted=[assessment],
        )


def test_successor_next_packet_is_local_and_requirement_read_is_lazy(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "entry-requirements.sqlite"
    initialize(path)
    graph = build_successor_graph()
    with connect_sqlite(path) as conn:
        conn.execute(
            "INSERT INTO research_graph_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                graph["graph_id"],
                graph["version"],
                graph["lifecycle"],
                graph["parent_version"],
                graph["content_hash"],
                orjson.dumps(graph).decode(),
                "pytest",
                2,
            ),
        )
        conn.execute(
            "UPDATE research_graph_instances SET graph_version=9 "
            "WHERE instance_id='instance-1'"
        )
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)

    packet = research_graphs.build_graph_branch_next(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    detail = research_graphs.load_current_graph_requirement(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        requirement_id=REQUIREMENT_ID,
    )

    assert packet["entry_requirements"]
    assert packet["next_bytes"] <= MAX_AGENT_PACKET_BYTES
    assert "requirement_catalog" not in packet
    assert detail["requirement"]["requirement_id"] == REQUIREMENT_ID

    app = Flask(__name__)
    app.secret_key = "entry-requirement-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    href = (
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        f"requirements/{REQUIREMENT_ID}"
    )
    with client.session_transaction() as session:
        session["username"] = "alice"
    assert client.get(href).status_code == 200
    with client.session_transaction() as session:
        session["username"] = "bob"
    assert client.get(href).status_code == 404


def test_schema_v2_transition_requires_and_persists_entry_assessments(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "transition-entry-gate.sqlite"
    initialize(path)
    graph = data_graph()
    graph["schema_version"] = 2
    graph["nodes"][0]["entry_requirement_refs"] = [
        "data-availability.scope"
    ]
    graph["nodes"][1]["entry_requirement_refs"] = []
    graph["nodes"][2]["entry_requirement_refs"] = []
    graph["edges"].append({
        "edge_id": "factor_semantics__data_contract",
        "from_node": "factor_semantics",
        "to_node": "data_contract",
        "guard": {},
        "required_evidence": [],
    })
    graph["requirement_catalog"] = {
        "requirements": [{
            "requirement_id": "data-availability.scope",
            "revision": 1,
            "gate_policy": "plan_before_exit",
        }],
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_versions SET graph_json=?",
            (orjson.dumps(graph).decode(),),
        )
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        lambda **_kwargs: profile(),
    )

    with pytest.raises(ValueError, match="must be an array"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="data_contract__factor_semantics",
            evidence=transition_evidence(),
        )

    evidence = transition_evidence()
    evidence["entry_requirement_assessments"] = [{
        "requirement_id": "data-availability.scope",
        "applicability": {
            "status": "applicable",
            "reason_zh": "目标试验需要 A.DCE 分钟数据。",
            "fact_refs": ["data-request:A.DCE"],
        },
        "coverage": {
            "decision": "map_existing",
            "obligation_refs": ["obligation:obligation-data"],
        },
        "resolution": {
            "route": "cli_evidence",
            "reuse_status": "none",
            "validation_refs": ["availability-query:A.DCE"],
        },
        "entry_effect": {
            "status": "pass_limited",
            "limitation_refs": ["limitation:pit-unverified"],
        },
    }]
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="data_contract__factor_semantics",
        evidence=evidence,
    )

    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    trace = orjson.loads(row["evidence_json"])
    assessment = trace["entry_requirement_assessments"][0]
    assert assessment["coverage"]["decision"] == "map_existing"
    assert assessment["resolution"]["route"] == "cli_evidence"
    assert trace["entry_resolution_delta"]["assessed_requirement_ids"] == [
        "data-availability.scope"
    ]
    assert trace["entry_resolution_delta"]["reused_requirement_ids"] == []
    packet = research_graphs.build_graph_branch_next(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert packet["entry_requirements"] == []
    assert packet["entry_resolution"]["reused_requirement_count"] == 0
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="factor_semantics__data_contract",
        evidence={},
    )
    returned = research_graphs.build_graph_branch_next(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert returned["entry_requirements"] == []
    assert returned["entry_resolution"]["reused_requirement_count"] == 1
    with connect_sqlite(path) as conn:
        latest = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()["evidence_json"])
    assert latest["entry_resolution_delta"]["assessed_requirement_ids"] == []
    assert latest["entry_resolution_delta"]["reused_requirement_ids"] == [
        "data-availability.scope"
    ]
