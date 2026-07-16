from __future__ import annotations

import settings as Settings
from flask import Flask
import pytest

from server.modules.single_factor_test import sft_bp


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "research-jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_user_can_create_and_reopen_a_durable_research_workspace(client) -> None:
    created = client.post(
        "/api/workspaces",
        json={
            "kind": "single_factor",
            "title": "MmMADevRat research",
            "factor_family_alias": "MmMADevRat",
            "draft": {"time_range": {"start": "2025-01-02", "end": "2025-02-14"}},
        },
    )

    assert created.status_code == 201
    workspace = created.get_json()["workspace"]
    assert workspace["owner"] == "alice"
    assert workspace["revision"] == 1
    assert workspace["draft"]["time_range"]["end"] == "2025-02-14"

    reopened = client.get(f"/api/workspaces/{workspace['workspace_id']}")

    assert reopened.status_code == 200
    assert reopened.get_json()["workspace"] == workspace
