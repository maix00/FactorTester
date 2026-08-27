from server.manager.http.page_assistance_routes import PageAssistanceStore


def test_page_context_and_registered_actions_round_trip() -> None:
    store = PageAssistanceStore()
    store.publish("owner", "profile", {
        "tab_id": "factor-new",
        "context": {"schema_version": 1, "sections": [{"id": "editor"}]},
    })
    page = store.current("owner", "profile")
    assert page and page["tab_id"] == "factor-new"

    queued = store.enqueue("owner", "profile", {
        "tab_id": "factor-new",
        "section_id": "editor",
        "action": {"field": "source", "value": "class A: pass"},
    })
    assert store.actions("owner", "profile", "factor-new", 0) == [queued]
    assert store.actions("owner", "profile", "factor-new", queued["sequence"]) == []
