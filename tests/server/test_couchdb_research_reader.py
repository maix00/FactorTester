from server.jobs.storage.couchdb_research_reader import CouchDBResearchReader
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary


class Store:
    def _request(self, method, path):
        import json
        return 200, json.dumps({
            "_id": "research-report:p1", "kind": "research_report", "publication_id": "p1",
            "publication": {"publication_id": "p1", "owner_ref": "alice"},
            "attachments": {"projection.json": {"name": "x.json"}},
        }).encode()
    def get_attachment(self, ref, name):
        return b'{"schema_version": 2}'


def test_library_prefers_couchdb_reader(tmp_path):
    library = PublicResearchLibrary(tmp_path, couchdb_reader=CouchDBResearchReader(Store()))
    assert library._record("p1")["owner_ref"] == "alice"
    assert library._projection("p1")["schema_version"] == 2
