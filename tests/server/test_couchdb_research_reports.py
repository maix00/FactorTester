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
