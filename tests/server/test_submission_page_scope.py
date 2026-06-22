from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from flask import Flask

import server.services.page_runtime as runtime_state
from server.modules.shared import submissions as submission_routes
from server.modules.shared import factor_data as factor_data_routes
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
    original_page_factor_testers = dict(runtime_state.page_factor_testers)
    original_page_product_selections = dict(runtime_state.page_product_selections)
    original_page_owners = dict(runtime_state.page_owners)
    original_time_store = dict(runtime_state.page_time_store)
    page_a = [_Tester("a1", "page-a"), _Tester("a2", "page-a")]
    page_b = [_Tester("b1", "page-b"), _Tester("b2", "page-b")]
    runtime_state.page_factor_testers = {"page-a": [page_a[0], page_a[1]], "page-b": [page_b[0], page_b[1]]}
    runtime_state.page_owners = {"page-a": "user-a", "page-b": "user-b"}
    runtime_state.page_time_store = {"page-a": ("start", "end", "start"), "page-b": ("start", "end", "start")}
    try:
        yield page_a, page_b
    finally:
        runtime_state.page_factor_testers = original_page_factor_testers
        runtime_state.page_product_selections = original_page_product_selections
        runtime_state.page_owners = original_page_owners
        runtime_state.page_time_store = original_time_store


def test_rename_response_only_contains_current_page_submissions(app, two_page_testers):
    with app.test_request_context(
        "/rename_submission",
        method="POST",
        json={"id_time": "a1", "new_name": "A new name", "page_uuid": "page-a"},
    ):
        response = submission_routes.rename_submission()

    assert response.status_code == 200
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
        response = submission_routes.reorder_submissions()

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert runtime_state.page_factor_testers["page-a"] == [page_a[0], page_a[1]]
    assert runtime_state.page_factor_testers["page-b"] == page_b


def test_submit_selected_products_registers_selection_not_factor_tester(app, monkeypatch):
    from server.modules.shared.submission_model import ProductPathSelection

    original_page_product_selections = dict(runtime_state.page_product_selections)
    original_page_factor_testers = dict(runtime_state.page_factor_testers)
    runtime_state.page_product_selections = {}
    runtime_state.page_factor_testers = {}
    monkeypatch.setattr(
        "server.modules.shared.submission_model.resolve_products_from_paths",
        lambda paths: (list(paths), ["CU.SHF", "AL.SHF"]),
    )

    try:
        with app.test_request_context(
            "/submit_selected_products",
            method="POST",
            json={
                "id_time": "sel-1",
                "selected_paths": ["Futures/Metals"],
                "group_name": "Metals",
                "page_uuid": "page-a",
            },
        ):
            response = submission_routes.submit_selected_products()

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        assert payload["submissions"][0]["product_path_selection_id"] == "sel-1"
        assert payload["submissions"][0]["source_type"] == "user_product_group_template"
        assert runtime_state.page_factor_testers == {}
        selection = runtime_state.get_product_selection("sel-1", page_uuid="page-a")
        assert isinstance(selection, ProductPathSelection)
        assert selection.product_group == "Metals"
    finally:
        runtime_state.page_product_selections = original_page_product_selections
        runtime_state.page_factor_testers = original_page_factor_testers


def test_runtime_tester_is_created_from_test_owned_product_selection(monkeypatch):
    from server.modules.shared.factor_tester_runtime import create_factor_tester_from_request

    created = {}

    class _RuntimeTester:
        def __init__(self, *, products, alias, start_dt, end_dt, user):
            created.update({
                "products": products,
                "alias": alias,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "user": user,
            })
            self.products = products
            self.alias = alias
            self.selected_paths = []

    original_page_product_selections = dict(runtime_state.page_product_selections)
    original_page_factor_testers = dict(runtime_state.page_factor_testers)
    original_time_store = dict(runtime_state.page_time_store)
    runtime_state.page_product_selections = {}
    runtime_state.page_factor_testers = {}
    runtime_state.page_time_store = {"page-a": ("run-start", "run-end", "run-start")}
    monkeypatch.setattr(
        "server.modules.shared.submission_model.resolve_products_from_paths",
        lambda paths: (list(paths), ["CU.SHF"]),
    )
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.current_user_obj",
        lambda: "alice",
    )
    monkeypatch.setattr(
        "tools.factors.FactorTester.FactorTester",
        _RuntimeTester,
    )

    try:
        tester = create_factor_tester_from_request(
            {
                "product_path_selection": {
                    "product_path_selection_id": "sel-run",
                    "selected_paths": ["Futures/Metals"],
                    "product_group": "Metals",
                },
            },
            page_uuid="page-a",
        )

        assert tester.alias == "sel-run"
        assert tester.product_group == "Metals"
        assert tester.selection_source_type == "manual_selection"
        assert created == {
            "products": ["CU.SHF"],
            "alias": "sel-run",
            "start_dt": "run-start",
            "end_dt": "run-end",
            "user": "alice",
        }
        assert runtime_state.get_factor_tester("sel-run", page_uuid="page-a") is tester
    finally:
        runtime_state.page_product_selections = original_page_product_selections
        runtime_state.page_factor_testers = original_page_factor_testers
        runtime_state.page_time_store = original_time_store


def test_runtime_tester_rejects_missing_product_path_selection():
    from server.modules.shared.factor_tester_runtime import selection_from_request

    with pytest.raises(AssertionError, match="测试配置缺少产品组设置"):
        selection_from_request({"submission_id": "missing"}, page_uuid="page-a")


def test_runtime_tester_accepts_captured_user_outside_request(monkeypatch):
    from server.modules.shared.factor_tester_runtime import create_factor_tester_from_request

    created = {}

    class _RuntimeTester:
        def __init__(self, *, products, alias, start_dt, end_dt, user):
            created.update({"products": products, "alias": alias, "user": user})
            self.products = products
            self.alias = alias
            self.selected_paths = []

    original_page_factor_testers = dict(runtime_state.page_factor_testers)
    original_time_store = dict(runtime_state.page_time_store)
    runtime_state.page_factor_testers = {}
    runtime_state.page_time_store = {"page-a": ("run-start", "run-end", "run-start")}
    monkeypatch.setattr(
        "server.modules.shared.submission_model.resolve_products_from_paths",
        lambda paths: (list(paths), ["CU.SHF"]),
    )
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.current_user_obj",
        lambda: (_ for _ in ()).throw(RuntimeError("request context touched")),
    )
    monkeypatch.setattr("tools.factors.FactorTester.FactorTester", _RuntimeTester)

    try:
        tester = create_factor_tester_from_request(
            {
                "product_path_selection": {
                    "product_path_selection_id": "sel-run",
                    "paths": ["Futures/Metals"],
                    "path_id": "pg-metals",
                },
            },
            page_uuid="page-a",
            user="captured-user",
        )

        assert tester.alias == "sel-run"
        assert tester.product_group_template_id == "pg-metals"
        assert created == {"products": ["CU.SHF"], "alias": "sel-run", "user": "captured-user"}
    finally:
        runtime_state.page_factor_testers = original_page_factor_testers
        runtime_state.page_time_store = original_time_store


def test_product_path_selection_inherits_from_parent_group(monkeypatch):
    from server.modules.shared.factor_tester_runtime import selection_for_product_path_selection

    monkeypatch.setattr(
        "server.modules.shared.submission_model.resolve_products_from_paths",
        lambda paths: (list(paths), ["CU.SHF"]),
    )

    selection = selection_for_product_path_selection(
        {
            "groups": [
                {
                    "id": "parent",
                    "product_path_selection": {
                        "product_path_selection_id": "sel-parent",
                        "paths": ["Futures/Metals"],
                        "path_id": "pg-metals",
                    },
                },
                {
                    "id": "child",
                    "parentId": "parent",
                },
            ]
        },
        "sel-parent",
        page_uuid="page-a",
    )

    assert selection.product_group_template_id == "pg-metals"
    assert selection.selected_paths == ["Futures/Metals"]


def test_scoped_mutation_cannot_target_another_page(app, two_page_testers):
    _, page_b = two_page_testers

    with app.test_request_context(
        "/rename_submission",
        method="POST",
        json={"id_time": "b1", "new_name": "Wrong page", "page_uuid": "page-a"},
    ):
        response = submission_routes.rename_submission()

    assert response.status_code == 200
    assert response.get_json()["success"] is False
    assert page_b[0].label == ""


def test_factor_tester_lookup_is_isolated_by_page(two_page_testers):
    page_a, page_b = two_page_testers
    page_a[0].alias = "user-a:same-submission"
    page_b[0].alias = "user-b:same-submission"

    assert runtime_state.get_factor_tester(
        "same-submission", page_uuid="page-a"
    ) is page_a[0]
    assert runtime_state.get_factor_tester(
        "same-submission", page_uuid="page-b"
    ) is page_b[0]


def test_factor_data_requires_page_uuid(app):
    with app.test_request_context(
        "/get_factor_series",
        method="POST",
        json={"submission_id": "same-submission"},
    ):
        response, status = factor_data_routes.get_factor_series()

    assert status == 400
    assert response.get_json()["error"] == "缺少 page_uuid"


def test_factor_data_rejects_another_users_page(app, two_page_testers, monkeypatch):
    monkeypatch.setattr(factor_data_routes, "current_user", lambda: "user-b")
    with app.test_request_context(
        "/get_factor_series",
        method="POST",
        json={"submission_id": "a1", "page_uuid": "page-a"},
    ):
        response, status = factor_data_routes.get_factor_series()

    assert status == 403
    assert response.get_json()["error"] == "page_uuid 不属于当前用户"


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
    assert captured == {
        "page_uuid": "page-new",
        "owner": "alice@1",
        "page_kind": "single_factor_test",
        "factor_family_alias": "",
    }


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


def test_unload_unregisters_all_page_owned_objects(app, monkeypatch):
    from server.services.factor_registry import page_families, page_factors

    tester = _Tester("alice:submission-1", "page-unload")
    runtime_state.page_factor_testers["page-unload"] = [tester]
    runtime_state.page_owners["page-unload"] = "alice"
    runtime_state.page_states["page-unload"] = {"latest_group_execution": object()}
    runtime_state.page_time_store["page-unload"] = ("start", "end", "start")
    page_families["page-unload"] = {}
    page_factors["page-unload"] = {}
    monkeypatch.setattr(page_lifecycle_routes, "current_user", lambda: "alice")

    with app.test_request_context(
        "/unregister_page",
        method="POST",
        json={"page_uuid": "page-unload"},
    ):
        response = page_lifecycle_routes.unregister_page()

    assert response.status_code == 200
    assert tester.deleted is True
    assert "page-unload" not in runtime_state.page_factor_testers
    assert "page-unload" not in runtime_state.page_owners
    assert "page-unload" not in runtime_state.page_states
    assert "page-unload" not in runtime_state.page_time_store
    assert "page-unload" not in page_families
    assert "page-unload" not in page_factors


def test_debug_page_state_reports_page_scope(app, monkeypatch):
    runtime_state.page_owners["page-a"] = "alice@1"
    runtime_state.page_states["page-a"] = {"page_kind": "single_factor_test"}

    with app.test_request_context("/api/debug/page_state?page_uuid=page-a"):
        from flask import session
        session["username"] = "alice@1"
        session["_sid"] = "session-a"
        response = page_lifecycle_routes.debug_page_state()

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["page_uuid"] == "page-a"
    assert payload["found"] is True
    assert set(payload) == {"success", "page_uuid", "found", "debug_sections"}
    identity = next(section for section in payload["debug_sections"] if section["title"] == "页面标识")
    assert identity["items"] == [
        {"label": "page_uuid", "value": "page-a"},
        {"label": "session_id", "value": "session-a"},
    ]

    runtime_state.page_owners.pop("page-a", None)
    runtime_state.page_states.pop("page-a", None)


def test_debug_page_state_reads_single_factor_registry_without_building_factors(app):
    class _FakeFactor:
        alias = "Mm|A:1"

    class _FakeFamily:
        def get_factors(self, *, params_list=None, page_uuid=None):
            raise AssertionError("debug probing must not construct factors")

    runtime_state.page_states["page-z"] = {"page_kind": "single_factor_test", "factor_family_alias": "Mm"}
    runtime_state.page_time_store["page-z"] = ("start", "end", "calc")
    from server.services.factor_registry import page_families
    from server.services.factor_registry import page_factors
    page_families["page-z"] = {"Mm": _FakeFamily()}
    page_factors["page-z"] = {"Mm|A:1": _FakeFactor()}
    try:
        with app.test_request_context("/api/debug/page_state?page_uuid=page-z"):
            from flask import session
            session["username"] = "alice@1"
            response = page_lifecycle_routes.debug_page_state()
    finally:
        runtime_state.page_states.pop("page-z", None)
        runtime_state.page_time_store.pop("page-z", None)
        page_families.pop("page-z", None)
        page_factors.pop("page-z", None)

    payload = response.get_json()
    assert response.status_code == 200
    assert response.content_type == "application/json; charset=utf-8"
    module_section = next(section for section in payload["debug_sections"] if section["title"] == "单因子测试对象")
    items = {item["label"]: item["value"] for item in module_section["items"]}
    assert items == {
        "page_uuid": "page-z",
        "factor_family_count": 1,
        "factor_family_aliases": ["Mm"],
        "factor_count": 1,
        "factor_aliases": ["Mm|A:1"],
    }
    assert "单因子测试" in response.get_data(as_text=True)


def test_page_debug_registration_replaces_same_section_and_filters_page_kind(monkeypatch):
    from server.services import page_state_debug

    monkeypatch.setattr(page_state_debug, "_global_providers", {})
    monkeypatch.setattr(page_state_debug, "_page_kind_providers", {})
    def first(page_uuid):
        return [{"label": "page_uuid", "value": page_uuid}, {"label": "version", "value": 1}]

    def second(page_uuid):
        return [{"label": "page_uuid", "value": page_uuid}, {"label": "version", "value": 2}]

    def other(page_uuid):
        return [{"label": "page_uuid", "value": page_uuid}]

    page_state_debug.register_page_debug_section("single_factor_test", "factor_registry", "旧标题", first)
    page_state_debug.register_page_debug_section("single_factor_test", "factor_registry", "新标题", second)
    page_state_debug.register_page_debug_section("multi_factor_test", "multi_registry", "多因子测试", other)

    assert page_state_debug._collect_sections("page-a", "single_factor_test") == [{
        "title": "新标题",
        "items": [
            {"label": "page_uuid", "value": "page-a"},
            {"label": "version", "value": 2},
        ],
    }]


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
