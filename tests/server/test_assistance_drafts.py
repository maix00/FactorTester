from __future__ import annotations

import pytest

from server.manager.services.assistance_drafts import (
    ASSISTANCE_DRAFT_RELATIVE_ROOT,
    AssistanceDraftError,
    AssistanceDraftStore,
)


def _create(store: AssistanceDraftStore, *, payload: str = "value") -> dict:
    return store.create(
        principal="owner",
        profile_id="self",
        tab_id="backtest-1",
        page_kind="backtest",
        page_revision=7,
        schema_version=1,
        document={"payload": payload},
        conversation_id="conversation-1",
    )


def test_drafts_are_flat_retained_and_explicitly_deleted(tmp_path) -> None:
    store = AssistanceDraftStore(tmp_path)
    created = _create(store)
    root = tmp_path / ASSISTANCE_DRAFT_RELATIVE_ROOT

    assert len(list(root.glob("*.json"))) == 1
    assert not [item for item in root.iterdir() if item.is_dir()]
    assert store.get(created["draft_id"])["document"] == {"payload": "value"}
    assert created["source_tab_id"] == "backtest-1"

    applied = store.set_status(
        created["draft_id"],
        "queued",
        target_tab_id="backtest-2",
        target_revision=2,
    )
    applied = store.set_status(created["draft_id"], "applied", applied_revision=3)
    assert applied["status"] == "applied"
    application = store.get(created["draft_id"])["application"]
    assert application["applied_revision"] == 3
    assert application["target_tab_id"] == "backtest-2"
    assert application["target_revision"] == 2
    assert store.delete(created["draft_id"]) is True
    assert list(root.glob("*.json")) == []


def test_draft_listing_omits_document_but_reports_quota(tmp_path) -> None:
    store = AssistanceDraftStore(tmp_path, quota_bytes=4096, warning_ratio=0.1)
    created = _create(store, payload="x" * 600)
    listed = store.list()

    assert listed["drafts"][0]["draft_id"] == created["draft_id"]
    assert "document" not in listed["drafts"][0]
    assert listed["quota"]["count"] == 1
    assert listed["quota"]["warning"] is True


def test_draft_merge_patch_updates_only_requested_document_fields(tmp_path) -> None:
    store = AssistanceDraftStore(tmp_path)
    created = store.create(
        principal="owner",
        profile_id="self",
        tab_id="backtest-1",
        page_kind="backtest",
        page_revision=7,
        schema_version=1,
        document={
            "configuration": {
                "task_name": "old",
                "settings": {"factor_mode": "native", "keep": True},
            },
        },
    )

    patched = store.patch(created["draft_id"], {
        "configuration": {
            "task_name": "new",
            "settings": {"factor_mode": "rank"},
        },
    })

    assert patched["document"] == {
        "configuration": {
            "task_name": "new",
            "settings": {"factor_mode": "rank", "keep": True},
        },
    }


def test_research_draft_rejects_schema_and_legacy_setting_guesses(tmp_path) -> None:
    store = AssistanceDraftStore(tmp_path)
    created = store.create(
        principal="owner",
        profile_id="self",
        tab_id="ic-1",
        page_kind="ic-configuration",
        page_revision=1,
        schema_version=1,
        document={
            "schema_version": 1,
            "document_kind": "research_configuration",
            "analyses": ["ic"],
            "configuration": {
                "schema_version": 3,
                "shared": {},
                "analyses": {"ic": {"configuration_groups": []}},
                "ui": {"ic": {"settings": {}}},
            },
            "run_fields": {},
        },
    )

    for patch in (
        {"configuration": {"schema_version": 2}},
        {"configuration": {"schema_version": None}},
        {"configuration": {"analyses": {"ic": {"local_settings": {}}}}},
        {"configuration": {"analyses": {"ic": {"settings": {}}}}},
    ):
        with pytest.raises(AssistanceDraftError, match="authoritative"):
            store.patch(created["draft_id"], patch)

    assert store.get(created["draft_id"])["document"]["configuration"][
        "schema_version"
    ] == 3


def test_draft_quota_refuses_new_content_without_deleting_old_drafts(tmp_path) -> None:
    store = AssistanceDraftStore(tmp_path, quota_bytes=1800)
    first = _create(store, payload="x" * 600)

    with pytest.raises(AssistanceDraftError, match="quota is full"):
        _create(store, payload="y" * 600)

    assert store.get(first["draft_id"])["document"]["payload"].startswith("x")
