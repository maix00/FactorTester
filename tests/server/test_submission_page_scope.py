from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from flask import Flask

import server.services.page_runtime as runtime_state
from server.modules.shared import submissions as submission_routes
from server.modules.shared import page_lifecycle as page_lifecycle_routes
from server.modules.single_factor_test import page as page_routes
from server.modules.single_factor_test import view_helpers


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
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.json.ensure_ascii = False
    return app


@pytest.fixture
def two_page_testers():
    original = runtime_state.factor_testers
    original_page_factor_testers = dict(runtime_state.page_factor_testers)
    original_page_owners = dict(runtime_state.page_owners)
    original_time_store = dict(runtime_state.page_time_store)
    page_a = [_Tester("a1", "page-a"), _Tester("a2", "page-a")]
    page_b = [_Tester("b1", "page-b"), _Tester("b2", "page-b")]
    runtime_state.factor_testers = [page_a[0], page_b[0], page_a[1], page_b[1]]
    runtime_state.page_factor_testers = {"page-a": [page_a[0], page_a[1]], "page-b": [page_b[0], page_b[1]]}
    runtime_state.page_owners = {"page-a": "user-a", "page-b": "user-b"}
    runtime_state.page_time_store = {"page-a": ("start", "end", "start"), "page-b": ("start", "end", "start")}
    try:
        yield page_a, page_b
    finally:
        runtime_state.factor_testers = original
        runtime_state.page_factor_testers = original_page_factor_testers
        runtime_state.page_owners = original_page_owners
        runtime_state.page_time_store = original_time_store


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


def test_single_factor_page_generates_and_registers_page_uuid(app, monkeypatch):
    captured = {}

    monkeypatch.setattr(page_routes.runtime_state, "create_page_uuid", lambda: "page-new")
    monkeypatch.setattr(
        page_routes.runtime_state,
        "register_page",
        lambda page_uuid, owner=None, **state: captured.update({"page_uuid": page_uuid, "owner": owner, **state}),
    )
    monkeypatch.setattr(page_routes, "render_template", lambda template, **ctx: ctx)
    monkeypatch.setattr(page_routes, "current_user", lambda: "alice@1")

    with app.test_request_context("/single_factor_test"):
        ctx = page_routes.single_factor_page()

    assert ctx["page_uuid"] == "page-new"
    assert ctx["initial_factor"] == ""
    assert captured == {"page_uuid": "page-new", "owner": "alice@1"}


def test_single_factor_page_shows_runtime_ids_for_developer(app, monkeypatch):
    captured = {}

    monkeypatch.setattr(page_routes.runtime_state, "create_page_uuid", lambda: "page-dev")
    monkeypatch.setattr(page_routes, "get_session_id", lambda: "sid-dev")
    monkeypatch.setattr(
        page_routes.runtime_state,
        "register_page",
        lambda page_uuid, owner=None, **state: captured.update({"page_uuid": page_uuid, "owner": owner, **state}),
    )
    monkeypatch.setattr(page_routes, "render_template", lambda template, **ctx: ctx)
    monkeypatch.setattr(page_routes, "current_user", lambda: "dev@1")
    monkeypatch.setattr(page_routes, "get_account", lambda username: {"username": username, "role": "super_admin", "is_developer": 1})

    with app.test_request_context("/single_factor_test"):
        ctx = page_routes.single_factor_page()

    assert ctx["show_runtime_ids"] is True
    assert ctx["session_id"] == "sid-dev"
    assert captured["page_uuid"] == "page-dev"


def test_close_page_unregisters_page_resources(app):
    from server.services.factor_registry import page_families, page_factors

    class _FakeFamily:
        alias = "Mm"

    class _FakeFactor:
        def __init__(self):
            self.family = _FakeFamily()
            self.cleared = False
            self.deleted = False

        def clear(self):
            self.cleared = True

        def delete(self):
            self.deleted = True

    fake_factor = _FakeFactor()
    page_families["page-a"] = {"Mm": _FakeFamily()}
    page_factors["page-a"] = {"Mm|A:1": fake_factor}
    runtime_state.page_owners["page-a"] = "alice@1"
    runtime_state.page_states["page-a"] = {"page_kind": "single_factor_test"}

    with app.test_request_context(
        "/close_page",
        method="POST",
        json={"page_uuid": "page-a", "factor_family_alias": "Mm"},
    ):
        response = page_lifecycle_routes.close_page()

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert "page-a" not in page_families or "Mm" not in page_families.get("page-a", {})
    assert "page-a" not in page_factors or "Mm|A:1" not in page_factors.get("page-a", {})
    assert fake_factor.cleared is True
    assert fake_factor.deleted is True
    assert runtime_state.page_owners.get("page-a") == "alice@1"
    assert runtime_state.page_states.get("page-a", {}).get("page_kind") == "single_factor_test"
    page_families.pop("page-a", None)
    page_factors.pop("page-a", None)
    runtime_state.page_owners.pop("page-a", None)
    runtime_state.page_states.pop("page-a", None)


def test_debug_page_state_reports_page_scope(app, monkeypatch):
    tester = _Tester("a1", "page-a")
    runtime_state.page_factor_testers["page-a"] = [tester]
    runtime_state.page_owners["page-a"] = "alice@1"
    runtime_state.page_time_store["page-a"] = ("start", "end", "calc")

    with app.test_request_context("/api/debug/page_state?page_uuid=page-a"):
        from flask import session
        session["username"] = "alice@1"
        response, status = page_lifecycle_routes.debug_page_state()

    payload = response.get_json()
    assert status == 200
    assert payload["success"] is True
    assert payload["page_uuid"] == "page-a"
    assert payload["tester_count"] == 1
    assert payload["owner"] == "alice@1"
    assert payload["found"] is True
    assert isinstance(payload.get("debug_sections"), list)
    assert payload["debug_sections"][0]["title"] == "通用"


def test_debug_page_state_includes_module_sections(app):
    class _FakeFactor:
        alias = "Mm|A:1"

    class _FakeFamily:
        def get_factors(self, *, params_list=None, page_uuid=None):
            return [_FakeFactor()]

    runtime_state.page_states["page-z"] = {"page_kind": "single_factor_test", "factor_family_alias": "Mm"}
    runtime_state.page_time_store["page-z"] = ("start", "end", "calc")
    from server.services.factor_registry import page_families
    page_families["page-z"] = {"Mm": _FakeFamily()}
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(page_routes, "get_session_params", lambda *args, **kwargs: [{"A": 1}])
    try:
        with app.test_request_context("/api/debug/page_state?page_uuid=page-z"):
            from flask import session
            session["username"] = "alice@1"
            response = page_lifecycle_routes.debug_page_state()
    finally:
        monkeypatch.undo()
        runtime_state.page_states.pop("page-z", None)
        runtime_state.page_time_store.pop("page-z", None)
        page_families.pop("page-z", None)

    payload = response.get_json()
    assert response.status_code == 200
    assert response.content_type == "application/json; charset=utf-8"
    assert any(section.get("title") == "单因子测试" for section in payload.get("debug_sections", []))
    assert payload["factor_count"] == payload["factor_family_count"]
    assert payload["factor_count"] == 1
    assert payload["factor_aliases"] == ["Mm|A:1"]
    module_section = next(section for section in payload["debug_sections"] if section.get("title") == "单因子测试")
    labels = {item.get("label") for item in module_section.get("items", [])}
    assert "page_kind" not in labels
    assert "factor_family_alias" not in labels
    assert "factor_count" not in labels
    assert "单因子测试" in response.get_data(as_text=True)


def test_factor_main_section_does_not_build_defaults_when_session_params_empty(app, monkeypatch):
    captured = {}

    class _FakeFamily:
        params = []
        desc = "Fake"
        math_expr = ""
        description = ""

        def get_factors(self, *, params_list=None, page_uuid=None):
            captured["params_list"] = params_list
            captured["page_uuid"] = page_uuid
            return []

    monkeypatch.setattr(view_helpers, "get_factor_family_instance", lambda *args, **kwargs: _FakeFamily())
    monkeypatch.setattr(view_helpers, "get_session_params", lambda *args, **kwargs: [])
    monkeypatch.setattr(view_helpers, "render_template", lambda template, **ctx: ctx)

    with app.test_request_context("/single_factor_test/api/content?page_uuid=page-x"):
        ctx = view_helpers.get_factor_main_section_html("Mm", page_uuid="page-x")

    assert ctx["factor_family_alias"] == "Mm"
    assert captured == {"params_list": [], "page_uuid": "page-x"}
