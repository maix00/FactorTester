from server.jobs.storage.couchdb_objects import VersionedObject, put_object, get_object


class Fake:
    def __init__(self): self.docs = {}
    def _request(self, method, path, body=None, content_type="application/json"):
        if method == "PUT":
            self.docs[path] = body; return 201, b"{}"
        return 200, self.docs[path]


def test_factor_version_document_round_trip():
    store = Fake()
    obj = VersionedObject(
        ref="factor:v2:" + "a" * 43, kind="factor_version", owner="alice",
        payload={"alias": "Mm|H:HA|L:LA|$F:1m"},
        keycloak_resource_id="kc-resource-1",
    )
    put_object(store, obj)
    assert get_object(store, obj.ref)["payload"]["alias"].startswith("Mm|")
