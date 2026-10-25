from __future__ import annotations

from flask import Flask

from server.modules.single_factor_test import sft_bp


def test_report_document_api_checks_owner(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice"}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/reports/report:job:1")
    assert response.status_code == 200
    assert response.get_json()["document"]["owner"] == "alice"


def test_report_attachment_api_checks_owner(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice", "attachments": {"tearsheet.html": "abc.html"}}
        def get_attachment(self, ref, name): return b"<html/>"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/reports/report:job:1/attachments/tearsheet.html")
    assert response.status_code == 200
    assert response.data == b"<html/>"


def test_report_document_api_uses_managed_permission(monkeypatch, tmp_path):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "bob"}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    db = tmp_path / "permissions.db"
    monkeypatch.setenv("FACTORTESTER_PERMISSIONS_DB", str(db))
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    from server.permissions.entries import PermissionEntry, PermissionStore
    PermissionStore(db).add(PermissionEntry(
        subject="user:alice", resource_type="report",
        resource_ref="report:job:1", action="read", created_by="admin",
    ))
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/reports/report:job:1")
    assert response.status_code == 200


def test_report_conflicts_are_owner_resolvable(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice"}
        def conflicts(self, ref): return ["2-a", "2-b"]
        def resolve_conflicts(self, ref, *, keep_rev): return ["2-a"]

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    assert client.get("/api/reports/report:job:1/conflicts").get_json()["conflicts"] == ["2-a", "2-b"]
    response = client.post("/api/reports/report:job:1/conflicts/resolve", json={"keep_rev": "2-a"})
    assert response.status_code == 200
    assert response.get_json()["conflicts"] == ["2-a"]
