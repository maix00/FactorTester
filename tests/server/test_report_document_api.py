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
