from __future__ import annotations

import hashlib

from server.manager.http.service_selection import ServiceSelectionRoutesMixin
from server.manager.services import data_plane_client, factor_source_hydration
from server.manager.services.test_authoring import TestAuthoringError as AuthoringError


def test_hydrates_referenced_factor_source_from_provider(monkeypatch) -> None:
    source = "class DemoFactor:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    entities = [{"payload": {
        "source_kind": "custom", "owner_username": "alice",
        "factor_id": "DemoFactor", "factor_name": "Demo",
        "source_sha256": digest, "source_bytes": len(raw),
        "storage_server_id": "office-a",
    }}]

    class Sync:
        def entities(self, *args, **kwargs):
            return entities

    class State:
        server_id = "public-1"
        account_domain_sync = Sync()
        @staticmethod
        def prepare_object_download(**kwargs):
            assert kwargs["storage_server_id"] == "office-a"
            assert kwargs["object_id"] == "alice:DemoFactor"
            return {
                "url": "https://public.example:7997/source",
                "path": "/api/transfers/source",
                "bearer": "ticket",
            }

    saved = []
    requested = []
    recorded = []
    monkeypatch.setattr(
        factor_source_hydration, "urlopen",
        lambda request, **kwargs: (
            requested.append((request.full_url, kwargs.get("context")))
            or _Response(raw)
        ),
    )
    monkeypatch.setattr(
        factor_source_hydration, "upsert_factor_source",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    monkeypatch.setattr(
        factor_source_hydration, "record_factor_formula_version",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    assert factor_source_hydration.FactorSourceHydrator(State()).hydrate(
        "DemoFactor", principal="alice",
    )
    # Hydration now threads the formula fingerprint through the upsert payload
    # (so the outbox sync publishes the immutable version identity) and records
    # the formula version snapshot locally.
    assert saved == [(
        ("custom", "alice", "DemoFactor", "Demo", source),
        {
            "chinese_name": "", "description": "", "category": "",
            "family_formula_fingerprint": "",
        },
    )]
    assert requested == [("https://public.example:7997/source", None)]
    # The DemoFactor source is not a FactorFamily subclass, so no stable formula
    # fingerprint can be derived and no version snapshot is recorded.
    assert recorded == []


def test_internal_download_uses_loopback_http_client_listener() -> None:
    access = {
        "url": "http://10.98.186.177:7997/v1/transfers/attempt/download",
    }

    url, context = data_plane_client.loopback_client_access(access["url"])

    assert url == "http://127.0.0.1:7997/v1/transfers/attempt/download"
    assert context is None


def test_internal_download_trusts_mounted_tls_certificate(
    monkeypatch, tmp_path,
) -> None:
    certificate = tmp_path / "manager.crt"
    certificate.write_text("certificate-placeholder")
    sentinel = object()
    monkeypatch.setenv("FACTORTESTER_ARTIFACT_TLS_CERT", str(certificate))
    monkeypatch.setattr(
        data_plane_client.ssl, "create_default_context",
        lambda *, cafile: sentinel if cafile == str(certificate) else None,
    )

    url, context = data_plane_client.loopback_client_access(
        "https://101.133.144.27:7997/v1/transfers/attempt/download",
    )

    assert url == "https://localhost:7997/v1/transfers/attempt/download"
    assert context is sentinel


class _Response:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int) -> bytes:
        return self.value


def test_run_context_retries_after_hydrating_missing_source(monkeypatch) -> None:
    calls = []

    class Authoring:
        @staticmethod
        def prepare_run_context(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise AuthoringError(
                    "source missing", 400,
                    code="factor_source_unavailable",
                    detail="Cannot load factor family source for 'DemoFactor'",
                )
            return {"prepared": True}

    class State:
        server_id = "public-1"
        test_authoring = Authoring()

    class Routes(ServiceSelectionRoutesMixin):
        state = State()

    hydrated = []
    monkeypatch.setattr(
        factor_source_hydration.FactorSourceHydrator,
        "hydrate",
        lambda _self, ref, *, principal: hydrated.append((ref, principal)) or True,
    )

    result = Routes()._prepare_run_context_with_sources(
        {}, principal="alice", source_entries=[],
    )

    assert result == {"prepared": True}
    assert hydrated == [("DemoFactor", "alice")]
    assert len(calls) == 2


def test_run_context_passes_direct_child_source_authority() -> None:
    calls = []

    class Accounts:
        @staticmethod
        def load_accounts():
            return [
                {"username": "parent", "organization_id": "org"},
                {
                    "username": "child", "organization_id": "org",
                    "parent_username": "parent", "active": True,
                },
                {
                    "username": "grandchild", "organization_id": "org",
                    "parent_username": "child", "active": True,
                },
            ]

    class Authoring:
        @staticmethod
        def prepare_run_context(*args, **kwargs):
            calls.append(kwargs)
            return {"prepared": True}

    class ClientState:
        local_account_store = Accounts()

    class State:
        server_id = "public-1"
        test_authoring = Authoring()
        client_state = ClientState()

    class Routes(ServiceSelectionRoutesMixin):
        state = State()

    result = Routes()._prepare_run_context_with_sources(
        {}, principal="parent", source_entries=[],
    )

    assert result == {"prepared": True}
    assert calls[0]["authorized_factor_owners"] == [
        "parent", "principal:parent", "child", "principal:child",
    ]


def test_hydration_repairs_missing_provider_metadata_from_control_store() -> None:
    provider = {"payload": {
        "source_kind": "custom", "owner_username": "alice",
        "factor_id": "DemoFactor", "source_sha256": "a" * 64,
        "source_bytes": 12, "storage_server_id": "office-a",
    }}

    class Local:
        applied = []

        def apply_remote(self, row):
            self.applied.append(row)

    class Control:
        calls = []

        def pull_account_domain_entities(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["after_revision"] == 0:
                return {
                    "entities": [
                        {"payload": {"factor_id": f"Other{index}"}}
                        for index in range(1000)
                    ],
                    "next_revision": 1000,
                }
            assert kwargs == {
                "after_revision": 1000, "principal": "alice", "limit": 1000,
            }
            return {"entities": [provider], "next_revision": 1001}

    class Sync:
        local = Local()
        control_store = Control()

        @staticmethod
        def entities(*args, **kwargs):
            return []

    class State:
        server_id = "public-1"
        account_domain_sync = Sync()

    values = factor_source_hydration.FactorSourceHydrator(State())._candidates(
        "alice", "DemoFactor", principal="alice",
    )

    assert values == [provider["payload"]]
    assert Sync.local.applied == [provider]
    assert len(Sync.control_store.calls) == 2


def test_delegated_hydration_queries_the_authorized_source_owner() -> None:
    calls = []

    class Sync:
        control_store = None

        @staticmethod
        def entities(principal, **kwargs):
            calls.append((principal, kwargs))
            return []

    class State:
        server_id = "public-1"
        account_domain_sync = Sync()

    values = factor_source_hydration.FactorSourceHydrator(State())._candidates(
        "child", "DemoFactor", principal="parent",
    )

    assert values == []
    assert calls == [("child", {
        "entity_type": "factor_source",
        "include_shared": True,
        "sync": True,
    })]


def test_hydration_skips_stale_provider_and_uses_current_replica(monkeypatch) -> None:
    source = "class DemoFactor:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()

    class State:
        server_id = "public-1"

        def prepare_object_download(self, **kwargs):
            if kwargs["storage_server_id"] == "retired-node":
                raise ValueError("node is not registered")
            return {"url": "http://data/source", "bearer": "ticket"}

    saved = []
    hydrator = factor_source_hydration.FactorSourceHydrator(State())
    monkeypatch.setattr(hydrator, "_candidates", lambda *_args, **_kwargs: [
        {"factor_id": "DemoFactor", "source_sha256": digest,
         "source_bytes": len(raw), "storage_server_id": "retired-node"},
        {"factor_id": "DemoFactor", "source_sha256": digest,
         "source_bytes": len(raw), "storage_server_id": "office-a"},
    ])
    monkeypatch.setattr(
        factor_source_hydration, "urlopen",
        lambda *_args, **_kwargs: _Response(raw),
    )
    monkeypatch.setattr(
        factor_source_hydration, "upsert_factor_source",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    assert hydrator.hydrate("DemoFactor", principal="alice")
    assert saved[0][0][2] == "DemoFactor"
