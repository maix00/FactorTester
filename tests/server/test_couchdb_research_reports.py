import json
from server.jobs.storage.couchdb_research_reports import document_id, get_research_report


class Fake:
    def _request(self, method, path):
        return 200, json.dumps({"kind": "research_report", "publication_id": "p1"}).encode()


def test_research_report_namespace_is_distinct():
    assert document_id("p1") == "research-report:p1"
    assert get_research_report(Fake(), "p1")["publication_id"] == "p1"


def test_projection_loads_content_addressed_attachment():
    import json
    from server.jobs.storage.couchdb_research_reports import projection

    class Store:
        def get_attachment(self, doc_id, name):
            return json.dumps({"schema_version": 2, "report_id": "r"}).encode()

    assert projection(Store(), {"_id": "research-report:p1",
                                "attachments": {"projection.json": {"name": "x.json"}}})["schema_version"] == 2


def test_research_report_conflicts_are_owner_scoped(monkeypatch):
    from flask import Flask
    from server.modules.single_factor_test import sft_bp

    class Store:
        def __init__(self, *args, **kwargs): pass
        def _request(self, method, path):
            import json
            return 200, json.dumps({"_id": "research-report:p1", "kind": "research_report",
                                    "publication_id": "p1", "owner_ref": "alice"}).encode()
        def conflicts(self, ref): return ["2-a"]
        def resolve_conflicts(self, ref, *, keep_rev): return []

    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    monkeypatch.setattr("server.jobs.storage.couchdb_reports.CouchDBObjectStore", Store)
    app = Flask(__name__); app.secret_key = "t"; app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "alice"
    assert client.get("/api/research-reports/p1/conflicts").get_json()["conflicts"] == ["2-a"]
    assert client.post("/api/research-reports/p1/conflicts/resolve", json={"keep_rev": "2-a"}).status_code == 200
