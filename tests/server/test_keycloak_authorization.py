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


def test_uncached_mutation_check_observes_revocation_and_invalidates_local_entry(monkeypatch):
    authz.clear_authorization_cache()
    state, calls = {"allow": True}, []
    class Client:
        def __init__(self, *_args, **_kwargs):
            pass
        def authorize_many(self, _token, *, permissions, **_kwargs):
            calls.append(len(permissions))
            return {(uri, scope) for uri, _name, scope in permissions} if state["allow"] else set()
    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    uri = authz.keycloak_resource_uri("research_profile", "p")
    permissions = [(uri, "name", "write")]
    assert authz.keycloak_authorized_many("token", permissions=permissions)[(uri, "write")]
    state["allow"] = False
    assert authz.keycloak_authorized_many("token", permissions=permissions)[(uri, "write")]
    assert not authz.keycloak_authorized_many("token", permissions=permissions, use_cache=False)[(uri, "write")]
    assert not authz.keycloak_authorized_many("token", permissions=permissions)[(uri, "write")]
    assert calls == [1, 1, 1]
    authz.clear_authorization_cache()


def test_single_resource_uncached_check_observes_revocation(monkeypatch):
    authz.clear_authorization_cache()
    state, calls = {"allow": True}, []
    class Client:
        def __init__(self, *_args, **_kwargs): pass
        def authorize(self, _token, **_kwargs):
            calls.append(1)
            return state["allow"]
    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research"})
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    assert authz.keycloak_authorized("token", resource_id="resource", scope="write")
    state["allow"] = False
    assert not authz.keycloak_authorized("token", resource_id="resource", scope="write", use_cache=False)
    assert not authz.keycloak_authorized("token", resource_id="resource", scope="write")
    assert len(calls) == 3
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


def test_profile_owner_may_only_share_and_existing_scope_conflict_fails(monkeypatch):
    from server.identity import federation_identity_sync

    class Directory:
        def _get(self, path):
            assert path == "users/subject-alice"
            return {"id": "subject-alice", "username": "alice"}
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", Directory)
    policy = {}
    def protection(_settings, _token, method, path, body=None):
        if method == "GET" and path == "resource_set/r":
            return 200, {"attributes": {"traderesearch_owner_subject": ["subject-alice"]}}, ""
        if method == "GET" and path.startswith("uma-policy?"):
            return 200, [dict(policy)] if policy else [], ""
        if method == "POST" and path == "uma-policy/r":
            policy.update(body)
            return 201, {}, ""
        raise AssertionError((method, path))
    monkeypatch.setattr(authz, "_protection_request", protection)
    authz._ensure_owner_policy({}, "pat", "r", "profile", "subject-alice", ("share",))
    assert policy["scopes"] == ["share"]
    authz._ensure_owner_policy({}, "pat", "r", "profile", "subject-alice", ("share",))
    with pytest.raises(authz.AuthorizationUnavailable, match="conflicting"):
        authz._ensure_owner_policy({}, "pat", "r", "profile", "subject-alice")
    assert policy["scopes"] == ["share"]
    policy["roles"] = ["anyone"]
    with pytest.raises(authz.AuthorizationUnavailable, match="conflicting"):
        authz._ensure_owner_policy({}, "pat", "r", "profile", "subject-alice", ("share",))


def test_invalid_owner_scopes_are_rejected_before_accessing_keycloak():
    with pytest.raises(ValueError, match="owner scopes"):
        authz.ensure_keycloak_resource(resource_type="research_profile", resource_ref="p",
                                       owner_subject="subject", owner_scopes=("all",))
    with pytest.raises(ValueError, match="owner scopes"):
        authz.ensure_keycloak_resource(resource_type="research_profile", resource_ref="p",
                                       owner_subject="subject", owner_scopes=())


def test_creation_intent_recovers_lost_response_but_rejects_foreign_resource(monkeypatch):
    class Client:
        def __init__(self, *_args, **_kwargs):
            pass
        def client_credentials(self):
            return {"access_token": "pat"}
    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    monkeypatch.setattr(authz, "_ensure_owner_policy", lambda *_args: None)
    state = {"resource": None, "fail": True, "posts": 0}
    def protection(_settings, _token, method, path, body=None):
        if method == "GET" and path.startswith("resource_set?"):
            return 200, [state["resource"]] if state["resource"] else [], ""
        if method == "POST" and path == "resource_set":
            state["posts"] += 1
            state["resource"] = {**body, "_id": "kc-report"}
            if state["fail"]:
                state["fail"] = False
                raise OSError("response lost after registration")
            return 201, state["resource"], ""
        if method == "GET" and path == "resource_set/kc-report":
            return 200, state["resource"], ""
        raise AssertionError((method, path))
    monkeypatch.setattr(authz, "_protection_request", protection)
    args = dict(resource_type="research_report", resource_ref="report", owner_subject="subject-alice")
    intent = "a" * 64
    with pytest.raises(authz.AuthorizationUnavailable, match="registration failed"):
        authz.ensure_keycloak_resource(**args, creation_intent=intent)
    assert authz.ensure_keycloak_resource(**args, creation_intent=intent) == "kc-report"
    assert state["posts"] == 1
    with pytest.raises(authz.AuthorizationUnavailable, match="another creation intent"):
        authz.ensure_keycloak_resource(**args, creation_intent="b" * 64)
    assert state["posts"] == 1
    with pytest.raises(ValueError, match="creation intent"):
        authz.ensure_keycloak_resource(**args, creation_intent="bad")


def test_creation_intent_requires_confirmed_resource_attributes(monkeypatch):
    class Client:
        def __init__(self, *_args, **_kwargs):
            pass
        def client_credentials(self):
            return {"access_token": "pat"}
    monkeypatch.setattr(authz, "oidc_settings", lambda: {
        "authz_client_id": "tr-api", "authz_client_secret": "secret",
        "base_url": "https://id.example", "realm": "research",
    })
    monkeypatch.setattr(authz, "ServiceOIDCClient", Client)
    monkeypatch.setattr(authz, "_protection_request", lambda _s, _t, method, path, body=None:
        (200, [], "") if method == "GET" and path.startswith("resource_set?") else
        (201, {"_id": "kc-report"}, "") if method == "POST" else
        (200, {"attributes": {"traderesearch_owner_subject": ["subject-alice"]}}, ""))
    with pytest.raises(authz.AuthorizationUnavailable, match="creation intent was not confirmed"):
        authz.ensure_keycloak_resource(resource_type="research_report", resource_ref="report",
                                       owner_subject="subject-alice", creation_intent="a" * 64)


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


def test_authorize_many_isolates_missing_resources_and_keeps_valid_decisions(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit):
            return json.dumps([{"rsname": "valid", "scopes": ["read", "use"]}]).encode()
    class Transport:
        def open(self, request, *, timeout):
            form = parse_qs(request.data.decode())
            permissions = form["permission"]
            requests.append(permissions)
            missing = next((item.split("#", 1)[0] for item in permissions if item.startswith("/missing")), None)
            if missing:
                payload = {"error": "invalid_resource",
                           "error_description": f"Resource with uri [{missing}] does not exist."}
                raise HTTPError(request.full_url, 400, "Bad Request", {}, BytesIO(json.dumps(payload).encode()))
            return Response()
    monkeypatch.setattr("server.manager.domain.federation_transport.FederationTransport", Transport)
    values = [("/valid", "valid", "read"), ("/missing1", "missing1", "read"),
              ("/missing1", "missing1", "write"), ("/missing2", "missing2", "read"),
              ("/valid", "valid", "use")]
    assert ServiceOIDCClient("https://id.example", "research", "api").authorize_many(
        "verified-token", audience="api", permissions=values) == {("/valid", "read"), ("/valid", "use")}
    assert [len(items) for items in requests] == [5, 3, 2]


@pytest.mark.parametrize("status,payload", [
    (401, {"error": "invalid_token"}),
    (400, {"error": "invalid_request"}),
    (400, {"error": "invalid_resource", "error_description": "Resource with uri [/other] does not exist."}),
    (400, {"error": "invalid_resource", "error_description": "other problem"}),
])
def test_authorize_many_does_not_hide_unrelated_errors(monkeypatch, status, payload):
    from io import BytesIO
    from urllib.error import HTTPError
    class Transport:
        def open(self, request, *, timeout):
            raise HTTPError(request.full_url, status, "failure", {}, BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr("server.manager.domain.federation_transport.FederationTransport", Transport)
    with pytest.raises(HTTPError) as raised:
        ServiceOIDCClient("https://id.example", "research", "api").authorize_many(
            "token", audience="api", permissions=[("/candidate", "candidate", "read")])
    assert raised.value.code == status


def test_single_authorization_does_not_turn_unauthorized_into_denial(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    class Transport:
        def open(self, request, *, timeout):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, BytesIO(b'{}'))
    monkeypatch.setattr("server.manager.domain.federation_transport.FederationTransport", Transport)
    with pytest.raises(HTTPError) as raised:
        ServiceOIDCClient("https://id.example", "research", "api").authorize(
            "token", audience="api", resource_id="existing", scope="read")
    assert raised.value.code == 401


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
