from types import SimpleNamespace

from server.modules.shared import submission_helpers
import server.services.runtime_state as runtime_state


def _tester(alias, page_uuid, products=(object(),), paths=None):
    tester = SimpleNamespace(
        alias=alias,
        name=f"tester-{alias}",
        products=list(products),
        selected_paths=paths or [f"path/{alias}"],
    )
    if page_uuid is not None:
        tester._page_uuid = page_uuid
    return tester


def test_submissions_payload_can_filter_by_page_uuid(monkeypatch):
    monkeypatch.setattr(runtime_state, "factor_testers", [
        _tester("a", "page-a"),
        _tester("b", "page-b"),
        _tester("empty", "page-a", products=()),
    ])

    payload = submission_helpers.submissions_payload("page-a")

    assert [item["id"] for item in payload] == ["a"]
    assert payload[0]["selected_paths"] == ["path/a"]


def test_submissions_payload_without_page_uuid_keeps_existing_behavior(monkeypatch):
    monkeypatch.setattr(runtime_state, "factor_testers", [
        _tester("a", "page-a"),
        _tester("b", "page-b"),
    ])

    payload = submission_helpers.submissions_payload()

    assert [item["id"] for item in payload] == ["a", "b"]
