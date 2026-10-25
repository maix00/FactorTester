import json
from server.jobs.storage.couchdb_library_reader import CouchDBLibraryReader


class Store:
    def _request(self, method, path, body=None):
        assert path == "_find"
        return 200, json.dumps({"docs": [
            {"kind": "product_group", "owner_ref": "alice", "payload": {"id": "g1", "name": "G"}},
        ]}).encode()


def test_product_group_reader_returns_payloads():
    assert CouchDBLibraryReader(Store()).product_groups("alice")[0]["id"] == "g1"
