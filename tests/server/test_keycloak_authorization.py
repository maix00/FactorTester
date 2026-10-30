import json
from urllib.parse import parse_qs

import pytest

from server.identity import keycloak_authorization as authz
from server.identity.keycloak import ServiceOIDCClient


def test_resource_name_is_stable_and_does_not_reveal_reference():
    first = authz.keycloak_resource_name("factor_version", "factor:v2:private-name")
    second = authz.keycloak_resource_name("factor_version", "factor:v2:private-name")
    assert first == second
    assert "private-name" not in first
    assert first.startswith("tr:factor_version:")


def test_authorization_is_cached_for_short_bounded_window(monkeypatch):
    authz.clear_authorization_cache()
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def authorize(self, token, **kwargs):
            calls.append((token, kwargs))
            return True

    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)

    assert authz.keycloak_authorized("user-token", resource_id="r1", scope="read")
    assert authz.keycloak_authorized("user-token", resource_id="r1", scope="read")
    assert len(calls) == 1
    authz.clear_authorization_cache()


def test_resource_creation_reuses_registered_resource(monkeypatch):
    policy = {}
    from server.identity import federation_identity_sync
    class Directory:
        def _get(self, path):
            assert path == "users/subject-alice"
            return {"id": "subject-alice", "username": "alice"}
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", Directory)

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def client_credentials(self, *, scope=""):
            assert scope == ""
            return {"access_token": "pat"}

    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    def protection(_settings, _token, method, path, body=None):
        if method == "GET" and path.startswith("resource_set?"):
            return 200, [{
                "_id": "kc-resource-1",
                "name": authz.keycloak_resource_name("factor_version", "factor:v2:x"),
                "attributes": {"traderesearch_owner_subject": ["subject-alice"]},
                "uris": [authz.keycloak_resource_uri("factor_version", "factor:v2:x")],
            }], ""
        if method == "GET" and path == "resource_set/kc-resource-1":
            return 200, {"attributes": {"traderesearch_owner_subject": ["subject-alice"]}}, ""
        if method == "GET" and path.startswith("uma-policy?"):
            return 200, [dict(policy)] if policy else [], ""
        if method == "POST" and path == "uma-policy/kc-resource-1":
            policy.update(body)
            policy["users"] = ["alice"]  # Real UMA responses use canonical usernames.
            return 201, dict(policy), ""
        raise AssertionError((method, path, body))

    monkeypatch.setattr(authz, "_protection_request", protection)

    assert authz.ensure_keycloak_resource(
        resource_type="factor_version", resource_ref="factor:v2:x",
        owner_subject="subject-alice",
    ) == "kc-resource-1"
    assert policy["users"] == ["alice"]
    assert "read" in policy["scopes"]
    assert "manage" in policy["scopes"]


def test_resource_creation_rejects_mismatched_existing_owner(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def client_credentials(self, *, scope=""):
            return {"access_token": "pat"}

    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    monkeypatch.setattr(authz, "_protection_request", lambda *_args, **_kwargs: (
        200, [{"_id": "kc-resource-1", "name": authz.keycloak_resource_name(
            "factor_version", "factor:v2:x",
        ), "owner": "subject-mallory"}], "",
    ))

    try:
        authz.ensure_keycloak_resource(
            resource_type="factor_version", resource_ref="factor:v2:x",
            owner_subject="subject-alice",
        )
    except authz.AuthorizationUnavailable:
        pass
    else:
        raise AssertionError("resource owned by another user must not be reused")


def test_authorize_many_batches_and_returns_only_explicit_grants(monkeypatch):
    from urllib.parse import parse_qs

    requests = []

    class Response:
        status = 200
        body = b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.body

    class Transport:
        def open(self, request, *, timeout):
            requests.append(request)
            response = Response()
            if len(requests) == 1:
                response.body = json.dumps([
                    {"rsid": "internal-id", "rsname": "source-name-0", "scopes": ["read"]},
                ]).encode()
            else:
                response.body = json.dumps([
                    {"rsid": "internal-id", "rsname": "source-name-64", "scopes": ["read"]},
                ]).encode()
            return response

    monkeypatch.setattr(
        "server.manager.domain.federation_transport.FederationTransport", Transport,
    )
    permissions = [
        (f"/objects/factor/{index}", f"source-name-{index}", "read")
        for index in range(65)
    ]

    granted = ServiceOIDCClient(
        "https://id.example", "research", "tr-api", timeout=1.5,
    ).authorize_many(
        "user-token", audience="tr-api", permissions=permissions,
    )

    assert len(requests) == 2
    forms = [parse_qs(request.data.decode()) for request in requests]
    assert [len(form["permission"]) for form in forms] == [64, 1]
    assert all(form["permission_resource_format"] == ["uri"] for form in forms)
    assert all(form["response_mode"] == ["permissions"] for form in forms)
    assert granted == {
        ("/objects/factor/0", "read"),
        ("/objects/factor/64", "read"),
    }


def test_authorize_many_rejects_oversized_batches_and_invalid_scope():
    client = ServiceOIDCClient("https://id.example", "research", "tr-api")
    with pytest.raises(ValueError, match="exceeds 256"):
        client.authorize_many(
            "token", audience="tr-api",
            permissions=[("/r", "resource", "read")] * 257,
        )
    with pytest.raises(ValueError, match="invalid Keycloak"):
        client.authorize_many(
            "token", audience="tr-api",
            permissions=[("/r", "resource", "read#write")],
        )


def test_factor_source_permissions_are_deduplicated_and_bounded(monkeypatch):
    calls = []

    def authorize_many(_token, *, permissions):
        offset = sum(len(batch) for batch in calls)
        calls.append(list(permissions))
        return {
            (uri, scope): offset + index in {0, 259}
            for index, (uri, _name, scope) in enumerate(permissions)
        }

    monkeypatch.setattr(authz, "keycloak_authorized_many", authorize_many)
    refs = [("owner", f"Factor{index}") for index in range(260)]
    refs.extend([("owner", "Factor0")])

    allowed = authz.keycloak_authorized_factor_sources(
        "verified-user-token", refs=refs,
    )

    assert [len(batch) for batch in calls] == [256, 4]
    assert allowed == {("owner", "Factor0"), ("owner", "Factor259")}


def test_request_credentials_only_uses_verified_flask_session_claims():
    from flask import Flask, g

    app = Flask(__name__)
    with app.test_request_context(
        "/", headers={"Authorization": "Bearer user-token"},
    ):
        assert authz.keycloak_request_credentials() is None
        g.keycloak_user_session = {
            "keycloak_subject": "subject-123", "keycloak_issuer": "https://id.example/realms/tr",
            "username": "alice",
        }
        g.keycloak_access_token = "user-token"
        assert authz.keycloak_request_credentials() == (
            "user-token", "subject-123", "alice",
        )
        identity = authz.keycloak_request_identity()
        assert identity is not None
        assert (identity.issuer, identity.subject, identity.username) == (
            "https://id.example/realms/tr", "subject-123", "alice",
        )
        assert "user-token" not in repr(identity)


def test_request_identity_never_reuses_a_different_unverified_bearer():
    from flask import Flask, g

    app = Flask(__name__)
    with app.test_request_context(
        "/", headers={"Authorization": "Bearer attacker-token"},
    ):
        g.keycloak_user_session = {
            "keycloak_subject": "subject-123",
            "keycloak_issuer": "https://id.example/realms/tr",
            "username": "alice",
        }
        g.keycloak_access_token = "verified-token"
        identity = authz.keycloak_request_identity()
        assert identity is not None
        assert identity.token == "verified-token"
