from server.manager.http.page_assistance_routes import PageAssistanceStore
from threading import Thread
import time


def test_structured_document_is_validated_and_replaced_atomically() -> None:
    store = PageAssistanceStore()
    store.publish("owner", "profile", {
        "tab_id": "factor-new",
        "assistance": {
            "schema_version": 1, "page_kind": "factor-create", "revision": 3,
            "document_schema": {
                "type": "object", "required": ["source"],
                "properties": {"source": {"type": "string"}},
                "additionalProperties": False,
            },
            "document": {"source": "class A: pass"},
        },
    })
    page = store.current("owner", "profile")
    assert page and page["tab_id"] == "factor-new"

    store.validate("owner", "profile", {"source": "class B: pass"})
    queued = store.enqueue("owner", "profile", {
        "tab_id": "factor-new", "expected_revision": 3,
        "document": {"source": "class B: pass"},
    })
    assert queued["kind"] == "replace_document"
    assert queued["expires_at"] > time.time()
    assert store.applications("owner", "profile", "factor-new", 0) == [queued]
    thread = Thread(target=lambda: store.acknowledge("owner", "profile", {
        "sequence": queued["sequence"], "success": True, "revision": 4,
    }))
    thread.start()
    assert store.wait_result(queued["sequence"])["revision"] == 4
    assert store.applications("owner", "profile", "factor-new", 0) == []
    thread.join()


def test_expired_application_is_not_returned_to_a_page() -> None:
    store = PageAssistanceStore()
    store.publish("owner", "profile", {
        "tab_id": "tab",
        "assistance": {
            "schema_version": 1, "page_kind": "test", "revision": 1,
            "document_schema": {"type": "object"}, "document": {},
        },
    })
    queued = store.enqueue("owner", "profile", {
        "tab_id": "tab", "expected_revision": 1, "document": {},
    })
    store._applications[("owner", "profile", "tab")][0]["expires_at"] = time.time() - 1
    assert store.applications("owner", "profile", "tab", 0) == []
    assert queued["sequence"] > 0


def test_structured_document_rejects_stale_revision() -> None:
    store = PageAssistanceStore()
    store.publish("owner", "profile", {
        "tab_id": "tab", "assistance": {
            "schema_version": 1, "page_kind": "test", "revision": 4,
            "document_schema": {"type": "object"}, "document": {},
        },
    })
    try:
        store.enqueue("owner", "profile", {
            "tab_id": "tab", "expected_revision": 3, "document": {},
        })
    except ValueError as exc:
        assert "expected 4" in str(exc)
    else:
        raise AssertionError("stale update was accepted")
