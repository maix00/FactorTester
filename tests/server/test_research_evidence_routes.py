from __future__ import annotations

from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test import research_evidence_routes as _legacy_routes  # noqa: F401


def _client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_fragment_bound_evidence_http_workflow(monkeypatch, tmp_path) -> None:
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(path))
    client = _client()

    retired = client.post("/api/research-evidence", json={})
    assert retired.status_code == 410

    source_response = client.post(
        "/api/research-evidence/sources",
        json={
            "source_kind": "terminal",
            "identity": {"execution_id": "exec-1"},
            "content_hash": "a" * 64,
            "audit": {"argv": ["python", "-V"], "returncode": 0},
        },
    )
    assert source_response.status_code == 201
    source = source_response.get_json()["source"]

    fragment_response = client.post(
        f"/api/research-evidence/sources/{source['source_ref']}/fragments",
        json={
            "selector": {
                "stream": "stdout",
                "line_range": {"start": 1, "end": 1},
            },
            "fragment_hash": "b" * 64,
            "title_zh": "版本输出",
            "summary_zh": "命令输出中的解释器版本",
            "preview": {"text": "Python 3.14"},
        },
    )
    assert fragment_response.status_code == 201
    fragment = fragment_response.get_json()["fragment"]

    evidence_response = client.post(
        "/api/research-evidence/compositions",
        json={
            "evidence_kind": "data_availability",
            "fragment_refs": [fragment["fragment_ref"]],
            "title_zh": "运行环境版本",
            "description_zh": "确认真实命令所使用的解释器版本",
            "claim_summary": "当前环境使用指定解释器版本",
            "applicability": {
                "source_refs": ["environment:gtht"],
                "contract_hash": "c" * 64,
                "methodology_hash": "d" * 64,
            },
            "identity_refs": {
                "contract_hash": "c" * 64,
                "methodology_hash": "d" * 64,
            },
            "limitations": ["只覆盖当前环境"],
            "conflicts": [],
        },
    )
    assert evidence_response.status_code == 201
    evidence_ref = evidence_response.get_json()["evidence"]["evidence_ref"]

    detail = client.get(f"/api/research-evidence/{evidence_ref}")
    assert detail.status_code == 200
    assert detail.get_json()["evidence"]["fragments"][0][
        "fragment_ref"
    ] == fragment["fragment_ref"]

    search = client.get(
        "/api/research-evidence/search",
        query_string={"source_kind": "terminal", "text": "运行环境"},
    )
    assert search.status_code == 200
    assert search.get_json()["result"]["items"][0][
        "evidence_ref"
    ] == evidence_ref

    proposal = client.post(
        "/api/research-evidence/tags/proposals",
        json={
            "title_zh": "运行环境",
            "description_zh": "用于检索解释器与运行环境证据",
            "created_by_profile_ref": "profile:maxa",
        },
    )
    assert proposal.status_code == 201
    token = proposal.get_json()["proposal"]["proposal_token"]
    created = client.post(
        "/api/research-evidence/tags",
        json={"proposal_token": token},
    )
    assert created.status_code == 201

    excluded = client.post(
        f"/api/research-evidence/{evidence_ref}/status",
        json={
            "action": "exclude",
            "reason_zh": "该版本输出不再适用于当前运行环境",
            "operation_id": "exclude-old-environment",
        },
    )
    assert excluded.status_code == 200
    assert excluded.get_json()["lifecycle"]["status"] == "excluded"
    assert client.get("/api/research-evidence/search").get_json()[
        "result"
    ]["items"] == []
    audit = client.get(
        "/api/research-evidence/search",
        query_string={"include_excluded": "1"},
    )
    assert audit.get_json()["result"]["items"][0][
        "lifecycle_status"
    ] == "excluded"
    linked_detail = client.get(f"/api/research-evidence/{evidence_ref}")
    assert linked_detail.status_code == 200
    assert linked_detail.get_json()["evidence"]["lifecycle"][
        "status"
    ] == "excluded"
