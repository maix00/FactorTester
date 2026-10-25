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


def test_product_group_writer_upserts_and_deletes():
    from server.jobs.storage.couchdb_library_reader import CouchDBLibraryWriter

    class Store:
        def __init__(self): self.body = None
        def _request(self, method, path, body=None):
            if path == "_find":
                return 200, json.dumps({"docs": [
                    {"_id": "product-group:alice:old", "_rev": "1-a"},
                ]}).encode()
            self.body = json.loads(body)
            return 201, b"[]"

    store = Store()
    CouchDBLibraryWriter(store).replace_product_groups("alice", [{"id": "g1", "name": "G"}])
    ids = [doc["_id"] for doc in store.body["docs"]]
    assert "product-group:alice:g1" in ids
    assert "product-group:alice:old" in ids
