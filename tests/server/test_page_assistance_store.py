import time
from threading import Thread

import pytest

from server.manager.http.page_assistance_routes import (
    PageAssistanceStore,
    page_assistance_turn_params,
    validate_document,
)


def _navigation() -> dict:
    return {
        "schema_version": 1,
        "root_id": "page",
        "nodes": {
            "page": {"id": "page", "kind": "page", "children": []},
        },
    }


def test_schema_rejects_derived_test_settings_as_agent_writable_fields() -> None:
    schema = {
        "type": "object",
        "x-forbidden-properties": ["local_settings", "settings"],
    }

    with pytest.raises(ValueError, match="read-only fields.*local_settings"):
        validate_document(schema, {"local_settings": {"start_date": "2024-01-01"}})


def test_json_schema_constraints_reject_incomplete_registered_values() -> None:
    schema = {
        "type": "object",
        "required": ["groups"],
        "properties": {
            "groups": {
                "type": "array", "minItems": 1, "maxItems": 1,
                "items": {
                    "type": "object",
                    "required": ["factor_ref", "delay"],
                    "properties": {
                        "factor_ref": {
                            "type": "string", "minLength": 1,
                            "pattern": r"factor:v2:[A-Za-z0-9_-]{43}",
                        },
                        "delay": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
        },
    }
    with pytest.raises(ValueError, match="too few items"):
        validate_document(schema, {"groups": []})
    with pytest.raises(ValueError, match="invalid format"):
        validate_document(schema, {"groups": [{"factor_ref": "alias", "delay": 0}]})
    with pytest.raises(ValueError, match="below its minimum"):
        validate_document(schema, {
            "groups": [{"factor_ref": "factor:v2:" + "a" * 43, "delay": -1}],
        })


def test_structured_document_is_validated_and_replaced_atomically() -> None:
    store = PageAssistanceStore()
    store.publish(
        "owner",
        "profile",
        {
            "tab_id": "factor-new",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "factor-create",
                "revision": 3,
                "document_schema": {
                    "type": "object",
                    "required": ["source"],
                    "properties": {"source": {"type": "string"}},
                    "additionalProperties": False,
                },
                "document": {"source": "class A: pass"},
            },
        },
    )
    page = store.current("owner", "profile")
    assert page and page["tab_id"] == "factor-new"

    store.validate("owner", "profile", {"source": "class B: pass"})
    queued = store.enqueue(
        "owner",
        "profile",
        {
            "tab_id": "factor-new",
            "expected_revision": 3,
            "document": {"source": "class B: pass"},
        },
    )
    assert queued["kind"] == "replace_document"
    assert queued["expires_at"] > time.time()
    assert store.applications("owner", "profile", "factor-new", 0) == [queued]
    thread = Thread(
        target=lambda: store.acknowledge(
            "owner",
            "profile",
            {
                "sequence": queued["sequence"],
                "success": True,
                "revision": 4,
            },
        )
    )
    thread.start()
    assert store.wait_result(queued["sequence"])["revision"] == 4
    assert store.applications("owner", "profile", "factor-new", 0) == []
    thread.join()


def test_expired_application_is_not_returned_to_a_page() -> None:
    store = PageAssistanceStore()
    store.publish(
        "owner",
        "profile",
        {
            "tab_id": "tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "test",
                "revision": 1,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )
    queued = store.enqueue(
        "owner",
        "profile",
        {
            "tab_id": "tab",
            "expected_revision": 1,
            "document": {},
        },
    )
    store._applications[("owner", "profile", "tab")][0]["expires_at"] = time.time() - 1
    assert store.applications("owner", "profile", "tab", 0) == []
    assert queued["sequence"] > 0


def test_application_long_poll_wakes_when_document_is_enqueued() -> None:
    store = PageAssistanceStore()
    store.publish(
        "owner",
        "profile",
        {
            "tab_id": "tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "test",
                "revision": 1,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )
    received: list[list[dict]] = []
    thread = Thread(
        target=lambda: received.append(
            store.applications(
                "owner",
                "profile",
                "tab",
                0,
                wait_seconds=1.0,
            )
        )
    )
    thread.start()
    time.sleep(0.02)
    queued = store.enqueue(
        "owner",
        "profile",
        {
            "tab_id": "tab",
            "expected_revision": 1,
            "document": {},
        },
    )
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert received == [[queued]]


def test_wait_timeout_keeps_application_queued_for_page_reconnect() -> None:
    store = PageAssistanceStore(ttl_seconds=900)
    store.publish(
        "owner", "profile", {
            "tab_id": "tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "test",
                "revision": 1,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )
    queued = store.enqueue(
        "owner", "profile", {
            "tab_id": "tab", "expected_revision": 1,
            "document": {}, "draft_id": "draft-1",
        },
    )
    duplicate = store.enqueue(
        "owner", "profile", {
            "tab_id": "tab", "expected_revision": 1,
            "document": {}, "draft_id": "draft-1",
        },
    )
    assert duplicate["sequence"] == queued["sequence"]

    with pytest.raises(TimeoutError, match="still queued"):
        store.wait_result(queued["sequence"], timeout=0.001)

    assert store.applications("owner", "profile", "tab", 0) == [queued]
    acknowledged = store.acknowledge(
        "owner", "profile", {
            "sequence": queued["sequence"], "success": True, "revision": 2,
        },
    )
    assert acknowledged["draft_id"] == "draft-1"


def test_structured_document_rejects_stale_revision() -> None:
    store = PageAssistanceStore()
    store.publish(
        "owner",
        "profile",
        {
            "tab_id": "tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "test",
                "revision": 4,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )
    try:
        store.enqueue(
            "owner",
            "profile",
            {
                "tab_id": "tab",
                "expected_revision": 3,
                "document": {},
            },
        )
    except ValueError as exc:
        assert "expected 4" in str(exc)
    else:
        raise AssertionError("stale update was accepted")


def test_draft_retargets_to_current_compatible_tab_after_source_tab_closes() -> None:
    store = PageAssistanceStore()
    schema = {
        "type": "object",
        "required": ["configuration_groups"],
        "properties": {"configuration_groups": {"type": "array"}},
        "additionalProperties": False,
    }
    document = {"configuration_groups": []}
    store.publish(
        "owner", "profile", {
            "tab_id": "deleted-ic-tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "ic-configuration",
                "revision": 8,
                "document_schema": schema,
                "document": document,
            },
        },
    )
    stale = store.enqueue(
        "owner", "profile", {
            "tab_id": "deleted-ic-tab",
            "expected_revision": 8,
            "document": document,
            "draft_id": "portable-draft",
        },
    )
    store.publish(
        "owner", "profile", {
            "tab_id": "new-ic-tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "ic-configuration",
                "revision": 1,
                "document_schema": schema,
                "document": document,
            },
        },
    )

    target = store.resolve_target(
        "owner", "profile",
        page_kind="ic-configuration",
        schema_version=1,
        document=document,
    )
    queued = store.enqueue(
        "owner", "profile", {
            "tab_id": target["tab_id"],
            "expected_revision": target["assistance"]["revision"],
            "document": document,
            "draft_id": "portable-draft",
        },
    )

    assert target["tab_id"] == "new-ic-tab"
    assert queued["expected_revision"] == 1
    assert queued["sequence"] != stale["sequence"]
    assert store.applications("owner", "profile", "deleted-ic-tab", 0) == []
    assert store.applications("owner", "profile", "new-ic-tab", 0) == [queued]


def test_draft_retarget_rejects_current_page_of_another_kind() -> None:
    store = PageAssistanceStore()
    document = {"configuration_groups": []}
    store.publish(
        "owner", "profile", {
            "tab_id": "backtest-tab",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "backtest-configuration",
                "revision": 2,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )

    with pytest.raises(ValueError, match="activate a compatible ic-configuration page"):
        store.resolve_target(
            "owner", "profile",
            page_kind="ic-configuration",
            schema_version=1,
            document=document,
        )


def test_assisted_turn_receives_builtin_cli_protocol_without_selected_skill() -> None:
    store = PageAssistanceStore()
    original = {
        "threadId": "thread-1",
        "input": [{"type": "text", "text": "fill this test configuration"}],
    }
    store.publish(
        "owner",
        "self",
        {
            "tab_id": "backtest-1",
            "assistance": {
                "schema_version": 1,
                "navigation": _navigation(),
                "page_kind": "test-configuration",
                "revision": 4,
                "document_schema": {"type": "object"},
                "document": {},
            },
        },
    )

    prepared = page_assistance_turn_params(
        "owner",
        "self",
        original,
        store=store,
    )

    assert prepared is not original
    assert prepared["input"][0] == original["input"][0]
    instruction = prepared["input"][1]["text"]
    assert "factortester assist inspect" in instruction
    assert "inspect --node <node-id>" in instruction
    assert "page-registered semantic node" in instruction
    assert "factortester assist drafts create --from-current" in instruction
    assert "inspect the registered `configurations` node" in instruction
    assert "`create_template`" in instruction
    assert "do not guess keys" in instruction
    assert "Never patch either schema_version" in instruction
    assert "factortester assist drafts patch <draft-id> --stdin" in instruction
    assert "factortester assist drafts validate <draft-id>" in instruction
    assert "factortester assist drafts apply <draft-id>" in instruction
    assert "do not inspect frontend source" in instruction.lower()


def test_unassisted_turn_is_not_modified() -> None:
    store = PageAssistanceStore()
    original = {"input": [{"type": "text", "text": "ordinary research"}]}
    assert (
        page_assistance_turn_params(
            "owner",
            "self",
            original,
            store=store,
        )
        == original
    )


def test_background_heartbeat_does_not_steal_the_assisted_page(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    store = PageAssistanceStore()
    def publish(tab, activate=None):
        payload = {'tab_id': tab, 'assistance': {
            'schema_version': 1, 'navigation': _navigation(),
        }}
        if activate is not None:
            payload['activate'] = activate
        store.publish('owner', 'self', payload)
    publish('old', True)
    clock[0] += 1
    publish('current', True)
    clock[0] += 1
    publish('old', False)
    publish('legacy')
    assert store.current('owner', 'self')['tab_id'] == 'current'
    clock[0] += 1
    publish('old', True)
    assert store.current('owner', 'self')['tab_id'] == 'old'


def test_workspace_targets_are_explicit_and_close_removes_pending():
    store = PageAssistanceStore()
    assistance = {"schema_version": 1, "page_kind": "example", "revision": 2,
                  "navigation": _navigation(), "document": {"name": "old"},
                  "document_schema": {"type": "object"}}
    workspace = {"active_tab_id": "a", "tabs": [
        {"tab_id": "a", "kind": "page", "assistance": assistance},
        {"tab_id": "b", "kind": "page", "assistance": assistance},
    ]}
    store.publish_workspace("owner", "self", workspace)
    target = store.resolve_target("owner", "self", page_kind="example",
                                  schema_version=1, document={"name": "new"}, tab_id="b")
    assert target["tab_id"] == "b"
    application = store.enqueue("owner", "self", {"tab_id": "b", "expected_revision": 2,
                                                   "document": {"name": "new"}})
    assert store.applications("owner", "self", "", 0) == [application]
    assert store.applications("other", "self", "", 0) == []
    store.publish_workspace("owner", "self", {"active_tab_id": "a", "tabs": workspace["tabs"][:1]})
    assert store.page("owner", "self", "b") is None
    assert store.applications("owner", "self", "", 0) == []
    with pytest.raises(ValueError):
        store.resolve_target("owner", "self", page_kind="example", schema_version=1,
                             document={}, tab_id="b")


def test_research_profile_workspace_scope_uses_membership():
    from server.manager.http.page_assistance_routes import PageAssistanceRoutesMixin

    class Routes(PageAssistanceRoutesMixin):
        def _profile(self, principal, profile_id):
            return {"profile_kind": "self" if profile_id == "self" else "research"}

        def _research_catalog_service(self):
            return self

        def list_members(self, research_id, *, viewer):
            assert viewer == "owner"
            return [{"profile_ref": "profile:bound"}] if research_id == "r1" else []

    routes = Routes()
    workspace = {"active_tab_id": "outside", "tabs": [
        {"tab_id": "folder", "kind": "research_folder", "research_id": "r1"},
        {"tab_id": "child", "parent_tab_id": "folder", "research_id": "r1"},
        {"tab_id": "outside", "research_id": ""},
        {"tab_id": "other", "research_id": "r2"},
    ]}
    assert routes._assistance_visible_workspace("owner", "self", workspace) == workspace
    scoped = routes._assistance_visible_workspace("owner", "bound", workspace)
    assert [tab["tab_id"] for tab in scoped["tabs"]] == ["folder", "child"]
    assert routes._assistance_visible_workspace("owner", "unbound", workspace)["tabs"] == []
