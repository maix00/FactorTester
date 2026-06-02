from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from flask import Flask

import server.services.runtime_state as runtime_state
from server.modules.shared import submissions as submission_routes


@dataclass
class _Tester:
    alias: str
    _page_uuid: str
    products: set[str] = field(default_factory=lambda: {"P"})
    selected_paths: list[str] = field(default_factory=list)
    name: str = ""
    label: str = ""
    deleted: bool = False

    def __post_init__(self):
        self.name = self.alias

    def delete(self):
        self.deleted = True


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def two_page_testers():
    original = runtime_state.factor_testers
    page_a = [_Tester("a1", "page-a"), _Tester("a2", "page-a")]
    page_b = [_Tester("b1", "page-b"), _Tester("b2", "page-b")]
    runtime_state.factor_testers = [page_a[0], page_b[0], page_a[1], page_b[1]]
    try:
        yield page_a, page_b
    finally:
        runtime_state.factor_testers = original


def test_rename_response_only_contains_current_page_submissions(app, two_page_testers):
    with app.test_request_context(
        "/rename_submission",
        method="POST",
        json={"id_time": "a1", "new_name": "A new name", "page_uuid": "page-a"},
    ):
        response, status = submission_routes.rename_submission()

    assert status == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert [item["id"] for item in payload["submissions"]] == ["a1", "a2"]


def test_reorder_only_reorders_testers_from_current_page(app, two_page_testers):
    page_a, page_b = two_page_testers

    with app.test_request_context(
        "/reorder_submissions",
        method="POST",
        json={"new_order": ["a2", "a1"], "page_uuid": "page-a"},
    ):
        response, status = submission_routes.reorder_submissions()

    assert status == 200
    assert response.get_json()["success"] is True
    assert runtime_state.factor_testers == [page_a[1], page_b[0], page_a[0], page_b[1]]


def test_scoped_mutation_cannot_target_another_page(app, two_page_testers):
    _, page_b = two_page_testers

    with app.test_request_context(
        "/rename_submission",
        method="POST",
        json={"id_time": "b1", "new_name": "Wrong page", "page_uuid": "page-a"},
    ):
        response, status = submission_routes.rename_submission()

    assert status == 200
    assert response.get_json()["success"] is False
    assert page_b[0].label == ""
