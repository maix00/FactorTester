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


def test_versioned_object_api_reads_factor_document(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path, body=None, content_type="application/json"):
            import json
            return 200, json.dumps({"_id": path, "kind": "factor_version", "owner": "alice", "payload": {}}).encode()

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/objects/factor:v2:abc")
    assert response.status_code == 200
    assert response.get_json()["document"]["kind"] == "factor_version"


def test_versioned_object_write_sets_owner(monkeypatch):
    written = {}

    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path, body=None, content_type="application/json"):
            written[path] = body; return 201, b"{}"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.post("/api/objects", json={
        "kind": "factor_version", "ref": "factor:v2:abc", "payload": {"x": 1},
    })
    assert response.status_code == 200
    assert b'"owner": "alice"' in written["factor:v2:abc"]


def test_report_attachment_list_is_scoped(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref):
            return {"_id": ref, "owner": "alice", "_attachments": {
                "tearsheet.html": {"content_type": "text/html", "length": 10},
            }}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    response = client.get("/api/reports/report:job:1/attachments")
    assert response.status_code == 200
    assert response.get_json()["attachments"][0]["name"] == "tearsheet.html"


def test_job_test_report_alias_route(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice", "_attachments": {}}
        def get_attachment(self, ref, name): return b"x"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    assert client.get("/api/job-test-reports/report:job:1/attachments").status_code == 200


def test_research_report_api_uses_publication_namespace(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"kind": "research_report", "publication_id": "p1",
                                    "owner_ref": "alice", "visibility": "private"}).encode()

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    assert client.get("/api/research-reports/p1").get_json()["document"]["kind"] == "research_report"
