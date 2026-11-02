from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from server.manager.services import test_authoring
from server.services import configuration_strategies
from server.services.strategy_bindings import compile_configuration_strategies
from server.services.strategy_library import StrategyLibraryService
from server.services.strategy_source_inspection import inspect_source
from server.identity.keycloak_authorization import keycloak_resource_uri
from server.identity.request_context import bind_verified_identity, identity_request


SOURCE = """from tools.testers.backtest.engines.native.strategy import Strategy

class Demo(Strategy):
    def on_bar(self, ctx, bar):
        return None
"""


SOURCE_V2 = SOURCE.replace("return None", "return {'changed': True}")


class TestKeycloak:
    """In-memory external policy server; metadata never grants access."""

    __test__ = False

    def __init__(self):
        self.permissions = {}

    @contextmanager
    def as_user(self, name):
        with identity_request():
            bind_verified_identity("token:" + name, {
                "username": name, "keycloak_subject": "subject:" + name,
                "keycloak_issuer": "https://identity.example/realms/trade",
            })
            yield

    def ensure(self, *, resource_type, resource_ref, owner_subject):
        uri = keycloak_resource_uri(resource_type, resource_ref)
        self.permissions[(uri, owner_subject)] = {"read", "write", "delete", "share"}

    def grant_read(self, strategy_ref, username):
        uri = keycloak_resource_uri("strategy", strategy_ref)
        self.permissions.setdefault((uri, "subject:" + username), set()).add("read")

    def authorize(self, token, *, permissions):
        assert token.startswith("token:")
        subject = "subject:" + token.removeprefix("token:")
        return {(uri, scope): scope in self.permissions.get((uri, subject), set())
                for uri, _name, scope in permissions}


@pytest.fixture(autouse=True)
def kc(monkeypatch):
    kc = TestKeycloak()
    monkeypatch.setattr("server.identity.keycloak_authorization.ensure_keycloak_resource", kc.ensure)
    monkeypatch.setattr("server.identity.keycloak_authorization.keycloak_authorized_many", kc.authorize)
    with kc.as_user("alice"):
        yield kc


def library(tmp_path: Path) -> StrategyLibraryService:
    return StrategyLibraryService(tmp_path / "manager.sqlite", account_provider=lambda: [])


def create_strategy(
    service: StrategyLibraryService,
    *,
    owner: str = "alice",
    source: str = SOURCE,
    visibility: str = "private",
    kc: TestKeycloak | None = None,
) -> dict:
    payload = {
        "name": "Demo strategy",
        "description": "A test actor",
        "visibility": visibility,
        "entrypoint": "Demo",
        "source_code": source,
    }
    if kc is not None:
        with kc.as_user(owner):
            return service.create(payload, principal=owner)["strategy"]
    return service.create(
        payload,
        principal=owner,
    )["strategy"]


def test_library_requires_a_native_strategy_entrypoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="native Strategy"):
        inspect_source("class NotAStrategy:\n    pass\n", "NotAStrategy")

    strategy = create_strategy(library(tmp_path))
    assert strategy["current_revision"]["entrypoint"] == "Demo"
    assert strategy["current_revision"]["hooks"][0]["name"] == "on_bar"


def test_source_inspection_includes_inherited_callbacks(tmp_path: Path) -> None:
    source = """from tools.testers.backtest.engines.native.strategy import Strategy

class Base(Strategy):
    def on_bar(self, ctx, bar):
        return None

class Child(Base):
    def on_order_filled(self, ctx, order):
        return None
"""
    inspection = inspect_source(source, "Child")
    assert inspection["callbacks"] == ["on_bar", "on_order_filled"]
    assert [hook["name"] for hook in inspection["hooks"]] == ["on_order_filled"]
    assert [hook["name"] for hook in inspection["effective_hooks"]] == [
        "on_order_filled", "on_bar",
    ]
    assert inspection["effective_hooks"][1]["declared_on"] == "Base"


def test_library_scopes_and_immutable_revisions(tmp_path: Path, kc: TestKeycloak) -> None:
    service = StrategyLibraryService(
        tmp_path / "manager.sqlite",
        account_provider=lambda: [{"username": "bob", "parent_username": "alice"},
                                  {"username": "charlie", "parent_username": "bob"}],
    )
    strategy = create_strategy(service)
    bobs_strategy = create_strategy(service, owner="bob", source=SOURCE_V2, kc=kc)
    charlies_strategy = create_strategy(service, owner="charlie", kc=kc)
    kc.grant_read(bobs_strategy["strategy_ref"], "alice")
    assert strategy["library_scope"] == "user_custom"
    assert strategy["library_kind"] == "nautilus_strategy_source"
    assert service.list(principal="alice", scope="mine")["total"] == 1
    assert service.list(principal="alice", scope="subordinates")["total"] == 1
    kc.grant_read(charlies_strategy["strategy_ref"], "alice")
    descendants = service.list(principal="alice", scope="subordinates")
    assert {item["strategy_ref"] for item in descendants["items"]} == {
        bobs_strategy["strategy_ref"], charlies_strategy["strategy_ref"],
    }
    with kc.as_user("bob"):
        assert service.list(principal="bob", scope="shared")["total"] == 0

    metadata_update = service.update(
        strategy["strategy_ref"], {"visibility": "shared"}, principal="alice",
    )
    assert "source_code" not in metadata_update["strategy"]["current_revision"]
    with kc.as_user("bob"):
        assert service.list(principal="bob", scope="shared")["total"] == 0
    kc.grant_read(strategy["strategy_ref"], "bob")
    with kc.as_user("bob"):
        assert service.list(principal="bob", scope="shared")["total"] == 1
    old_revision = strategy["current_revision"]["revision_ref"]
    updated = service.update(
        strategy["strategy_ref"],
        {"source_code": SOURCE_V2},
        principal="alice",
    )["strategy"]
    assert updated["current_revision"]["revision_ref"] != old_revision
    assert len(updated["revisions"]) == 2
    with kc.as_user("bob"):
        assert service.get_revision(
            strategy["strategy_ref"], old_revision, principal="bob", include_source=True,
        )["revision"]["source_code"] == SOURCE


def test_strategy_reads_can_omit_source_and_updates_are_atomic(tmp_path: Path) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service)
    current_ref = strategy["current_revision"]["revision_ref"]

    summary = service.get(
        strategy["strategy_ref"], principal="alice", include_source=False,
    )["strategy"]
    assert "source_code" not in summary["current_revision"]
    assert all("source" not in hook for hook in summary["current_revision"]["hooks"])
    assert all(
        "source" not in hook
        for hook in summary["revisions"][0]["hooks"]
    )
    listed = service.list(principal="alice", scope="mine")["items"][0]
    assert all("source" not in hook for hook in listed["current_revision"]["hooks"])

    with pytest.raises(KeyError):
        service.store.update_entry_with_revision(
            strategy["strategy_ref"],
            name="partially changed",
            description="should roll back",
            visibility="public",
            expected_revision_ref=current_ref,
            revision={"source_sha256": "missing-fields"},
        )
    unchanged = service.get(strategy["strategy_ref"], principal="alice")["strategy"]
    assert unchanged["name"] == strategy["name"]
    assert unchanged["visibility"] == strategy["visibility"]
    assert unchanged["current_revision"]["revision_ref"] == current_ref


def test_library_list_pages_visible_rows_at_the_database_boundary(tmp_path: Path, kc: TestKeycloak) -> None:
    service = library(tmp_path)
    mine = create_strategy(service)
    public = create_strategy(service, owner="bob", visibility="public", kc=kc)
    create_strategy(service, owner="carol", kc=kc)
    assert service.list(principal="alice", scope="all")["total"] == 1
    kc.grant_read(public["strategy_ref"], "alice")

    first_page = service.list(principal="alice", scope="all", page=1, limit=1)
    second_page = service.list(principal="alice", scope="all", page=2, limit=1)

    assert first_page["total"] == 2
    assert first_page["total_pages"] == 2
    assert len(first_page["items"]) == 1
    assert len(second_page["items"]) == 1
    assert {
        first_page["items"][0]["strategy_ref"],
        second_page["items"][0]["strategy_ref"],
    } == {mine["strategy_ref"], public["strategy_ref"]}


def test_configuration_inline_sources_are_deduplicated(tmp_path: Path) -> None:
    payload = {"shared": {}, "analyses": {"backtest": {}}}
    first = configuration_strategies.add_inline(
        payload, name="Temporary", source_code=SOURCE, entrypoint="Demo",
        target_strategy_id="group-1",
    )
    second = configuration_strategies.add_inline(
        payload, name="Same source", source_code=SOURCE, entrypoint="Demo",
        target_strategy_id="group-2",
    )
    configuration_strategies.validate(payload)
    assert first["strategy"]["temp_ref"] == second["strategy"]["temp_ref"]
    assert len(configuration_strategies.view(payload)["strategies"]) == 1
    metadata = configuration_strategies.view(payload, include_source=False)
    assert "source_code" not in metadata["strategies"][0]
    assert all("source" not in hook for hook in metadata["strategies"][0]["hooks"])
    assert configuration_strategies.view(payload, include_source=True)["strategies"][0]["source_code"] == SOURCE
    compiled = compile_configuration_strategies(payload, owner="alice")
    assert len(compiled["transient_strategy_sources"]) == 1
    assert len(compiled["strategy_specs"]) == 2
    assert {item["strategy_kind"] for item in _normalize(compiled)} == {"custom"}


def test_library_binding_freezes_the_selected_revision(tmp_path: Path) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service)
    old_revision = strategy["current_revision"]["revision_ref"]
    service.update(strategy["strategy_ref"], {"source_code": SOURCE_V2}, principal="alice")
    payload = {"shared": {}, "analyses": {"backtest": {}}}
    configuration_strategies.add_library(
        payload,
        strategy_ref=strategy["strategy_ref"],
        revision_ref=old_revision,
        target_strategy_id="group-1",
    )
    configuration_strategies.validate(payload)
    compiled = compile_configuration_strategies(
        payload, owner="alice", library=service,
    )
    assert compiled["transient_strategy_sources"][0]["source_code"] == SOURCE
    normalized = _normalize(compiled)[0]
    assert normalized["strategy_kind"] == "library"
    assert normalized["revision_ref"] == old_revision
    assert normalized["source"].startswith("profile:strategies/frozen/")


def test_configuration_library_binding_validates_access_and_hash(tmp_path: Path, kc: TestKeycloak) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service)
    revision = strategy["current_revision"]

    payload = {"shared": {}, "analyses": {"backtest": {}}}
    binding = configuration_strategies.add_library(
        payload,
        strategy_ref=strategy["strategy_ref"],
        revision_ref=str(revision["revision_ref"]),
        target_strategy_id="group-1",
        source_sha256=str(revision["source_sha256"]),
        library=service,
        owner="alice",
    )
    assert binding["binding"]["source"]["source_sha256"] == revision["source_sha256"]

    rejected = {"shared": {}, "analyses": {"backtest": {}}}
    with pytest.raises(ValueError, match="source hash mismatch"):
        configuration_strategies.add_library(
            rejected,
            strategy_ref=strategy["strategy_ref"],
            revision_ref=str(revision["revision_ref"]),
            target_strategy_id="group-1",
            source_sha256="0" * 64,
            library=service,
            owner="alice",
        )
    assert configuration_strategies.view(rejected)["bindings"] == []

    with kc.as_user("bob"), pytest.raises(PermissionError):
        configuration_strategies.add_library(
            {"shared": {}, "analyses": {"backtest": {}}},
            strategy_ref=strategy["strategy_ref"],
            revision_ref=str(revision["revision_ref"]),
            target_strategy_id="group-1",
            library=service,
            owner="bob",
        )

    with pytest.raises(KeyError, match="strategy revision not found"):
        configuration_strategies.add_library(
            {"shared": {}, "analyses": {"backtest": {}}},
            strategy_ref=strategy["strategy_ref"],
            revision_ref="revision:missing",
            target_strategy_id="group-1",
            library=service,
            owner="alice",
        )


def test_test_authoring_put_rejects_inaccessible_library_revision(tmp_path: Path, kc: TestKeycloak) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service, owner="alice")
    revision = strategy["current_revision"]["revision_ref"]
    authoring = test_authoring.TestAuthoringService()
    authoring.strategy_library = service

    with kc.as_user("bob"), pytest.raises(test_authoring.TestAuthoringError) as error:
        authoring.write(
            "PUT",
            "/api/test-authoring/workspaces/workspace-one/configuration",
            owner="bob",
            payload={
                "expected_revision": 1,
                "payload": {
                    "shared": {},
                    "analyses": {"backtest": {"strategy_bindings": [{
                        "binding_id": "binding-1",
                        "target_strategy_id": "group-1",
                        "source": {
                            "kind": "library",
                            "strategy_ref": strategy["strategy_ref"],
                            "revision_ref": revision,
                        },
                    }]}},
                },
            },
        )
    assert error.value.status == 403


def _normalize(compiled: dict) -> list[dict]:
    from server.services.strategy_plans import normalize_strategy_plan

    paths = [item["path"] for item in compiled["transient_strategy_sources"]]
    return normalize_strategy_plan(compiled["strategy_specs"], uploaded_paths=paths)


def test_public_factor_templates_are_a_distinct_read_only_library_scope() -> None:
    from server.services.factor_strategy_templates import factor_strategy_catalog

    catalog = factor_strategy_catalog()
    assert catalog["scope"] == "public"
    assert catalog["families"]
    assert catalog["items"]
    assert all(item["object_kind"] == "strategy_family" for item in catalog["families"])
    assert all(item["object_kind"] == "strategy" for item in catalog["items"])
    assert all(item["library_scope"] == "public" for item in catalog["items"])
    assert all(item["library_kind"] == "factor_strategy_template" for item in catalog["items"])
    assert all(item["read_only"] is True for item in catalog["items"])
    assert {item["kind"] for item in catalog["items"]} == {
        "cross_sectional_group", "threshold",
    }
    group = next(item for item in catalog["families"]
                 if item["family_ref"] == "nautilus-strategy-family:factor-cross-sectional-group")
    fields = group["configuration_schema"]["fields"]
    assert [(field["key"], field["type"]) for field in fields] == [
        ("signal", "factor_ref"),
        ("product_group_ref", "product_group_ref"),
        ("split_count", "integer"),
        ("group_index", "integer"),
    ]


def test_group_strategy_binding_freezes_family_schema_and_required_product_group() -> None:
    from server.services.factor_strategy_templates import normalize_factor_strategy_binding

    base = {
        "template_ref": "nautilus-factor-strategy:cross-sectional-group",
        "revision_ref": "nautilus-factor-strategy-revision:cross-sectional-group:1",
        "strategy_id": "strategy-group-1", "binding_id": "binding-1",
        "factor_bindings": {"signal": f"factor:v2:{'A' * 43}"},
        "parameters": {"split_count": 5, "group_index": 2},
    }
    with pytest.raises(ValueError, match="product_group_ref"):
        normalize_factor_strategy_binding(base)

    result = normalize_factor_strategy_binding({**base, "product_group_ref": "products:agriculture"})
    assert result["family_ref"] == "nautilus-strategy-family:factor-cross-sectional-group"
    assert result["strategy_ref"] == base["template_ref"]
    assert result["configuration_schema_ref"].endswith("configuration-schema:1")
    assert result["product_group_ref"] == "products:agriculture"


def test_registered_strategy_boolean_parameter_keeps_false_as_a_value() -> None:
    from server.services.factor_strategy_templates import _normalize_parameters

    template = {
        "kind": "test",
        "parameters": [{
            "key": "allow_short", "type": "boolean", "default": False,
        }],
    }
    assert _normalize_parameters(template, {"allow_short": False}) == {
        "allow_short": False,
    }
    with pytest.raises(ValueError, match="boolean"):
        _normalize_parameters(template, {"allow_short": "false"})


def test_couchdb_publication_uses_new_local_revision_not_remote_head(tmp_path, monkeypatch):
    service = library(tmp_path)
    initial = create_strategy(service)
    store = service.store
    old_ref = initial['current_revision']['revision_ref']
    published = []
    monkeypatch.setenv('TRADERESEARCH_COUCHDB_AUTHORITY', '1')
    monkeypatch.setenv('FACTORTESTER_COUCHDB_URL', 'http://unused.invalid')
    monkeypatch.setattr('server.jobs.storage.couchdb_reports.CouchDBObjectStore', lambda *args: object())
    monkeypatch.setattr('server.jobs.storage.couchdb_library_reader.CouchDBLibraryWriter.upsert_strategy',
                        lambda self, ref, entry, revision: published.append((ref, entry, revision)))
    # Normal reads may still see the old remote head while publication runs.
    monkeypatch.setattr(store, 'get_entry', lambda *args: {**initial, 'current_revision_ref':old_ref})
    monkeypatch.setattr(store, 'get_revision', lambda *args: initial['current_revision'])
    revision = {**initial['current_revision'], 'source_code':SOURCE_V2,
                'source_sha256':__import__('hashlib').sha256(SOURCE_V2.encode()).hexdigest()}
    updated = store.update_entry_with_revision(initial['strategy_ref'], name='Updated',
        description='', visibility='private', expected_revision_ref=old_ref, revision=revision)
    assert len(published) == 1
    _, entry, actual = published[0]
    assert entry['name'] == 'Updated'
    assert entry['current_revision_ref'] == updated['revision_ref'] != old_ref
    assert actual['revision_ref'] == updated['revision_ref']
    assert actual['source_code'] == SOURCE_V2
