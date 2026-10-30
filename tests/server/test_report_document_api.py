from __future__ import annotations

from flask import Flask
import pytest

from server.modules.single_factor_test import sft_bp


@pytest.fixture(autouse=True)
def verified_manager_keycloak_session(monkeypatch):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        "server.identity.user_session.keycloak_session",
        lambda token: ({"username": "alice", "role": "user", "keycloak_roles": ()}
                       if token == "keycloak-access-token" else None),
    )
    monkeypatch.setattr(
        "server.identity.keycloak_authorization.keycloak_authorized",
        lambda _token, **_kwargs: True,
    )


def _allow_keycloak_resource(monkeypatch):
    monkeypatch.setattr(
        "server.identity.keycloak_authorization.keycloak_authorized",
        lambda _token, **_kwargs: True,
    )


def _manager_token(client):
    client.set_cookie("ft-manager-session", "keycloak-access-token")


def test_report_owner_without_keycloak_resource_mapping_is_denied(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice"}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.get("/api/reports/report:job:1")
    assert response.status_code == 403


def test_report_attachment_api_checks_owner(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice", "keycloak_resource_id": "r1", "attachments": {"tearsheet.html": "abc.html"}}
        def get_attachment(self, ref, name): return b"<html/>"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    _allow_keycloak_resource(monkeypatch)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.get("/api/reports/report:job:1/attachments/tearsheet.html")
    assert response.status_code == 200
    assert response.data == b"<html/>"


def test_report_document_api_uses_keycloak_not_local_permission_database(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "bob", "keycloak_resource_id": "r1"}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    _allow_keycloak_resource(monkeypatch)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.get("/api/reports/report:job:1")
    assert response.status_code == 200


def test_report_conflicts_are_owner_resolvable(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice", "keycloak_resource_id": "r1"}
        def conflicts(self, ref): return ["2-a", "2-b"]
        def resolve_conflicts(self, ref, *, keep_rev): return ["2-a"]

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    _allow_keycloak_resource(monkeypatch)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    assert client.get("/api/reports/report:job:1/conflicts").get_json()["conflicts"] == ["2-a", "2-b"]
    response = client.post("/api/reports/report:job:1/conflicts/resolve", json={"keep_rev": "2-a"})
    assert response.status_code == 200
    assert response.get_json()["conflicts"] == ["2-a"]


def test_versioned_object_api_reads_factor_document(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path, body=None, content_type="application/json"):
            import json
            return 200, json.dumps({"_id": path, "kind": "factor_version", "owner": "alice", "keycloak_resource_id": "r1", "payload": {}}).encode()

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    _allow_keycloak_resource(monkeypatch)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
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
    monkeypatch.setattr(
        "server.identity.keycloak_authorization.ensure_keycloak_resource",
        lambda **_kwargs: "created-resource",
    )
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.post("/api/objects", json={
        "kind": "factor_version", "ref": "factor:v2:abc", "payload": {"x": 1},
    })
    assert response.status_code == 200
    assert b'"owner": "alice"' in written["factor:v2:abc"]
    assert b'"keycloak_resource_id": "created-resource"' in written["factor:v2:abc"]


def test_report_attachment_list_is_scoped(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref):
            return {"_id": ref, "owner": "alice", "keycloak_resource_id": "r1", "_attachments": {
                "tearsheet.html": {"content_type": "text/html", "length": 10},
            }}

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    _allow_keycloak_resource(monkeypatch)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.get("/api/reports/report:job:1/attachments")
    assert response.status_code == 200
    assert response.get_json()["attachments"][0]["name"] == "tearsheet.html"


def test_job_test_report_alias_route(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def get_report(self, ref): return {"_id": ref, "owner": "alice", "keycloak_resource_id": "r1", "_attachments": {}}
        def get_attachment(self, ref, name): return b"x"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    assert client.get("/api/job-test-reports/report:job:1/attachments").status_code == 200


def test_research_report_api_uses_publication_namespace(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"kind": "research_report", "publication_id": "p1",
                                    "owner_ref": "alice", "keycloak_resource_id": "r1", "visibility": "private"}).encode()

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    assert client.get("/api/research-reports/p1").get_json()["document"]["kind"] == "research_report"


def test_research_report_attachments_are_listed_and_streamed(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"kind": "research_report", "publication_id": "p1",
                                    "owner_ref": "alice", "keycloak_resource_id": "r1", "visibility": "private",
                                    "attachments": {"chapters/a.json": {
                                        "name": "abc.json", "content_type": "application/json",
                                        "size_bytes": 1}}}).encode()
        def get_attachment(self, ref, name): return b"x"

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    listing = client.get("/api/research-reports/p1/attachments").get_json()
    assert listing["attachments"][0]["name"] == "abc.json"
    assert client.get("/api/research-reports/p1/attachments/abc.json").data == b"x"


def test_research_report_agent_endpoints(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"_id": "research-report:p1", "kind": "research_report",
                                    "publication_id": "p1", "owner_ref": "alice", "keycloak_resource_id": "r1",
                                    "title": "T", "visibility": "private",
                                    "attachments": {"projection.json": {"name": "p.json"},
                                                    "index.json": {"name": "i.json"}}}).encode()
        def get_attachment(self, ref, name):
            import json
            if name == "p.json":
                return json.dumps({"chapters": []}).encode()
            if name == "i.json":
                return json.dumps({"chapters": []}).encode()
            return json.dumps({"components": []}).encode()

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "t"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    assert client.get("/api/research-reports/p1/agent").get_json()["success"] is True
    assert client.get("/api/research-reports/p1/agent.md").mimetype == "text/markdown"


def test_research_report_move_chapter_uses_base_rev(monkeypatch):
    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path, body=None, content_type="application/json"):
            import json
            if method == "GET" and not path.endswith(".json"):
                return 200, json.dumps({"_id": "research-report:p1", "_rev": "1-a",
                                        "kind": "research_report", "owner_ref": "alice", "keycloak_resource_id": "r1",
                                        "attachments": {"index.json": {"name": "idx.json"}}}).encode()
            if method == "GET": return 200, b'{"chapters":[{"component_id":"a"},{"component_id":"b"}]}'
            if "/idx" in path or path.endswith(".json"): return 201, b'{"rev":"2-b"}'
            return 201, b'{"rev":"2-b"}'
        def get_attachment(self, ref, name):
            return b'{"chapters":[{"component_id":"a"},{"component_id":"b"}]}'

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "t"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.post("/api/research-reports/p1/operations", json={
        "base_rev": "1-a", "op": "move_chapter", "chapter_id": "b", "after_chapter_id": "a",
    })
    assert response.status_code == 200, response.get_data(as_text=True)


def test_research_report_chapter_api(monkeypatch):
    from server.jobs.storage.research_report_agent import chapter_attachment_path

    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"_id": "research-report:p1", "kind": "research_report",
                                    "owner_ref": "alice", "keycloak_resource_id": "r1",
                                    "attachments": {chapter_attachment_path("x"): {"name": "c.json"}}}).encode()
        def get_attachment(self, ref, name):
            return b'{"title": "Chapter", "components": []}'

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "t"; app.register_blueprint(sft_bp)
    client = app.test_client()
    _manager_token(client)
    response = client.get(f"/api/research-reports/p1/chapters/{'x'}")
    # The fixture uses chapters/x.json; real code derives a hash, so accept 404 here.
    assert response.status_code == 200
