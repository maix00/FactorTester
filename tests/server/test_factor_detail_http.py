from contextlib import contextmanager
import json
import sqlite3
from types import SimpleNamespace
from urllib.parse import urlencode, urlparse

from server.manager.http import catalog_routes as routes
from server.manager.services.client_state import ClientStateService
from server.manager.storage.account_domain import local as local_store
from server.manager.storage.account_domain.local import LocalAccountDomainStore
from tools.data.sqlite.db import connect_sqlite
from tools.factors.formula_identity import freeze_factor_identity


class Handler(routes.CatalogRoutesMixin):
    def _session(self):
        return {"username": "alice"}

    def _visitor_mode(self):
        return None


class LocalCatalog:
    def __init__(self, values):
        self.values = values
        self.queries = []

    def factor_catalog(self, principal, *, factor_ref="", offset=0, limit=None):
        self.queries.append((principal, factor_ref, offset, limit))
        return [value for value in self.values.get(principal, [])
                if not factor_ref or value.get("factor_ref") == factor_ref][:limit]


class Accounts:
    def __init__(self, rows=None):
        self.rows = rows or [{
            "username": "alice", "alias": "Alice", "organization_id": "org",
            "active": True,
        }]

    def load_accounts(self):
        return self.rows


def factor_row(owner_ref="alice"):
    frozen = freeze_factor_identity(
        owner_ref=owner_ref,
        family_alias="Momentum",
        factor_alias="Fast",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"$F": "1d"},
    )
    return {
        **frozen,
        "factor_ref": frozen["ref"],
        "factor_alias": "Fast",
        "factor_family_alias": "Momentum",
        "factor_family_name": "Momentum",
        "factor_owner_ref": owner_ref,
        "owner_username": "alice",
        "owner_alias": "Alice",
        "factor_kind": "registered",
        "source": "registered",
        "family_formula_fingerprint": "a" * 64,
        "self_formula_fingerprint": "b" * 64,
        "params": [{"alias": "$F", "value": "1d"}],
        "math_expr": "x",
        "resolved_math_expr": "x",
    }


def test_factor_detail_reads_one_owner_scoped_factor_without_loading_library(
    monkeypatch, tmp_path,
):
    row = factor_row()
    row["factor_dependencies"] = [{
        "factor_ref": f"factor:v2:{'n' * 43}",
        "owner_username": "alice",
        "factor_alias": "NestedThreshold|N:5d",
    }]
    local = LocalCatalog({"alice": [row]})
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts(),
    )
    client.factor_library = lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("factor detail must not load the complete catalog")
    )
    from server.services.factor_source_catalog import FactorSourceCatalog

    monkeypatch.setattr(
        FactorSourceCatalog,
        "version",
        lambda *_a, **_kw: (_ for _ in ()).throw(FileNotFoundError("offline source")),
    )
    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    path = "/api/factor-library/factors/detail?" + urlencode({
        "factor_ref": row["factor_ref"], "owner_username": "alice",
    })

    assert handler._serve_factor_catalog(urlparse(path))

    payload, status = received[0]
    assert status == 200
    assert payload["success"] is True
    assert payload["factor"]["factor_ref"] == row["factor_ref"]
    assert payload["factor"]["owner_username"] == "alice"
    assert payload["factor"]["factor_dependencies"] == row["factor_dependencies"]
    assert local.queries == [("alice", row["factor_ref"], 0, 1)]


def test_factor_detail_requires_owner_when_ref_is_registered_by_two_visible_users(
    monkeypatch, tmp_path,
):
    row = factor_row(owner_ref="public")
    same_public_identity = {
        **row,
        "owner_username": "bob",
        "owner_alias": "Bob",
    }
    local = LocalCatalog({"alice": [row], "bob": [same_public_identity]})
    children = [{
        "username": "bob", "alias": "Bob", "organization_id": "org",
        "parent_username": "alice", "active": True,
    }]
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts([{
            "username": "alice", "alias": "Alice", "organization_id": "org",
            "active": True,
        }, *children]),
    )
    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    path = "/api/factor-library/factors/detail?" + urlencode({
        "factor_ref": row["factor_ref"],
    })

    assert handler._serve_factor_catalog(urlparse(path))

    payload, status = received[0]
    assert status == 409
    assert "所有者" in payload["error"]
    assert local.queries == [
        ("alice", row["factor_ref"], 0, 1),
        ("bob", row["factor_ref"], 0, 1),
    ]


def test_factor_detail_owner_hint_resolves_direct_subordinate(monkeypatch, tmp_path):
    row = {
        **factor_row(owner_ref="public"),
        "owner_username": "bob", "owner_alias": "Bob",
    }
    local = LocalCatalog({"bob": [row]})
    children = [{
        "username": "bob", "alias": "Bob", "organization_id": "org",
        "parent_username": "alice", "active": True,
    }]
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts([{
            "username": "alice", "alias": "Alice", "organization_id": "org",
            "active": True,
        }, *children]),
    )
    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    path = "/api/factor-library/factors/detail?" + urlencode({
        "factor_ref": row["factor_ref"], "owner_username": "bob",
    })

    assert handler._serve_factor_catalog(urlparse(path))
    payload, status = received[0]
    assert status == 200
    assert payload["factor"]["owner_username"] == "bob"
    assert local.queries == [("bob", row["factor_ref"], 0, 1)]


def test_factor_detail_reads_public_family_from_its_exact_local_version(
    monkeypatch, tmp_path,
):
    row = factor_row(owner_ref="public")
    local = LocalCatalog({"alice": [row]})
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts(),
    )
    from server.services.factor_source_catalog import FactorSourceCatalog

    calls = []
    monkeypatch.setattr(
        FactorSourceCatalog,
        "version",
        lambda _self, *args, **kwargs: calls.append((args, kwargs)) or {
            "math_expr": r"\\operatorname{Fast}(x)",
            "params": [{
                "alias": "$F", "type": "FactorParam", "default_value": "1d",
            }],
        },
    )

    value = client.factor_detail("alice", row["factor_ref"], owner_username="alice")

    assert calls == [(('alice', 'public', 'Momentum', 'a' * 64),
                      {"owner_username": ""})]
    assert value["source_metadata_available"] is True
    assert value["family"]["owner_username"] == "__public_jobs__"
    assert value["family"]["parameter_definitions"][0]["type"] == "FactorParam"


def test_factor_detail_reports_missing_and_malformed_references(
    monkeypatch, tmp_path,
):
    local = LocalCatalog({})
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts(),
    )
    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    for reference, expected_status in [
        (factor_row()["factor_ref"], 404),
        ("not-a-factor-reference", 400),
    ]:
        path = "/api/factor-library/factors/detail?" + urlencode({
            "factor_ref": reference, "owner_username": "alice",
        })
        assert handler._serve_factor_catalog(urlparse(path))
        assert received[-1][1] == expected_status
    assert local.queries == [
        ("alice", factor_row()["factor_ref"], 0, 1),
    ]


def test_factor_detail_never_queries_an_unrelated_requested_owner(monkeypatch, tmp_path):
    local = LocalCatalog({})
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts(),
    )

    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    path = "/api/factor-library/factors/detail?" + urlencode({
        "factor_ref": factor_row()["factor_ref"], "owner_username": "mallory",
    })
    assert handler._serve_factor_catalog(urlparse(path))
    assert received[0][1] == 403
    assert local.queries == []


def test_factor_detail_index_failure_is_reported_as_unavailable(monkeypatch, tmp_path):
    class UnavailableCatalog:
        def factor_catalog(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=UnavailableCatalog()),
        local_account_store=Accounts(),
    )
    handler = Handler()
    handler.state = SimpleNamespace(client_state=client, federated_public_data=None)
    received = []
    monkeypatch.setattr(
        routes, "json_response",
        lambda _handler, payload, status=200: received.append((payload, status)),
    )
    path = "/api/factor-library/factors/detail?" + urlencode({
        "factor_ref": factor_row()["factor_ref"], "owner_username": "alice",
    })

    assert handler._serve_factor_catalog(urlparse(path))
    assert received[0][1] == 503
    assert received[0][0]["error"] == "本机因子详情索引暂时不可用"


def test_exact_factor_catalog_read_uses_the_factor_ref_index(tmp_path, monkeypatch):
    store = LocalAccountDomainStore(tmp_path / "account-domain.sqlite3")
    wanted = factor_row()
    with connect_sqlite(store.path) as conn:
        conn.executemany(
            """
            INSERT INTO account_domain_entities(
                principal, entity_type, entity_id, payload_json, deleted,
                origin_manager_id, updated_at
            ) VALUES (?, 'factor_catalog_entry', ?, ?, 0, '', 1)
            """,
            [
                (
                    "alice", f"entry-{index:04d}",
                    json.dumps({
                        "factor": {
                            "factor_ref": wanted["factor_ref"] if index == 500
                            else f"factor:v2:{index:043x}",
                            "factor_alias": f"Factor{index}",
                        },
                    }),
                )
                for index in range(1000)
            ],
        )
        conn.commit()

    statements = []
    connect = local_store.connect_sqlite

    @contextmanager
    def traced_connect(path):
        with connect(path) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(local_store, "connect_sqlite", traced_connect)
    result = store.factor_catalog("alice", factor_ref=wanted["factor_ref"], limit=1)
    assert len(result) == 1
    assert result[0]["factor_ref"] == wanted["factor_ref"]
    actual_query = next(
        statement for statement in reversed(statements)
        if statement.startswith("SELECT payload_json FROM account_domain_entities")
    )
    with connect(store.path) as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + actual_query).fetchall()
    assert any(
        "account_domain_factor_catalog_ref" in str(row[3]) for row in plan
    )


def test_factor_detail_enriches_only_the_exact_family_version(monkeypatch, tmp_path):
    row = factor_row()
    local = LocalCatalog({"alice": [row]})
    client = ClientStateService(
        client_root=tmp_path,
        account_domain_sync=SimpleNamespace(local=local),
        local_account_store=Accounts(),
    )
    from server.services.factor_source_catalog import FactorSourceCatalog

    received = []
    monkeypatch.setattr(
        FactorSourceCatalog,
        "version",
        lambda _self, *args, **kwargs: received.append((args, kwargs)) or {
            "math_expr": r"\\operatorname{Fast}(x)",
            "params": [{"alias": "$F", "type": "WindowParam", "default_value": "1d"}],
        },
    )

    value = client.factor_detail("alice", row["factor_ref"], owner_username="alice")

    assert received == [(("alice", "custom", "Momentum", "a" * 64),
                         {"owner_username": "alice"})]
    assert value["source_metadata_available"] is True
    assert value["family"]["math_expr"] == r"\\operatorname{Fast}(x)"
    assert value["family"]["parameter_definitions"][0]["type"] == "WindowParam"
