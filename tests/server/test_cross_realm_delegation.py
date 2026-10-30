from __future__ import annotations

import base64
import json
from urllib.error import HTTPError

import pytest

from server.identity.cross_realm_delegation import CrossRealmDelegation
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import AuthorizationUnavailable


SOURCE = "https://a.invalid/realms/a"
TARGET = "https://b.invalid/realms/b"


def assertion(**changes):
    claims = {"iss": SOURCE, "sub": "source-subject", "jti": "unique-token", "iat": 1000,
              "exp": 1120, "azp": "source-client", "aud": TARGET, "tr_identity_id": "stable-user"}
    claims.update(changes)
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return encode({"alg": "RS256"}) + "." + encode(claims) + ".signature", claims


class Provider:
    def __init__(self, claims):
        self.claims = {"active": True, **claims}
        self.calls = 0
        self.fail_after_grant = False
        self.unavailable = False
    def introspect(self, _token):
        self.calls += 1
        if self.unavailable:
            raise ConnectionError("offline")
        if self.fail_after_grant and self.calls > 1:
            return {"active": False}
        return dict(self.claims)


class Grant:
    calls = 0
    def jwt_authorization_grant(self, _assertion, *, scope):
        self.calls += 1
        assert scope == "openid"
        return {"access_token": "target-secret"}


def verifier(claims, **overrides):
    provider = Provider(claims)
    grant = Grant()
    source, target = [], []
    args = dict(source_introspection=provider, target_grant=grant, source_issuer=SOURCE,
        target_issuer=TARGET, source_client_id="source-client", clock=lambda: 1010,
        target_session=lambda _token: {"keycloak_issuer": TARGET, "keycloak_subject": "local-subject",
                                       "tr_identity_id": "stable-user", "username": "different-local-name",
                                       "expires_in": 100},
        source_authorize=lambda claim, _token: source.append(claim["sub"]) or True,
        target_authorize=lambda session, token: target.append((session["keycloak_subject"], token)) or True)
    args.update(overrides)
    return CrossRealmDelegation(**args), provider, grant, source, target


def test_online_source_target_identity_and_current_policy_are_required():
    token, claims = assertion()
    value, provider, grant, source, target = verifier(claims)
    result = value.authenticate(token, expected_identity="stable-user")
    assert result.identity_id == "stable-user" and result.target_session["username"] == "different-local-name"
    assert provider.calls == 2 and grant.calls == 1
    assert source == ["source-subject", "source-subject"] and target == [("local-subject", "target-secret")]
    assert "target-secret" not in repr(result)


def test_offline_disabled_and_revoked_source_never_grant():
    token, claims = assertion()
    value, provider, grant, _, _ = verifier(claims)
    provider.unavailable = True
    with pytest.raises(AuthorizationUnavailable, match="source"):
        value.authenticate(token, expected_identity="stable-user")
    assert grant.calls == 0
    provider.unavailable = False
    provider.claims["active"] = False
    with pytest.raises(PermissionError, match="not active"):
        value.authenticate(token, expected_identity="stable-user")
    provider.claims["active"] = True
    provider.fail_after_grant = True
    provider.calls = 0
    with pytest.raises(PermissionError, match="not active"):
        value.authenticate(token, expected_identity="stable-user")
    assert grant.calls == 1


@pytest.mark.parametrize("change", [
    {"aud": "https://elsewhere.invalid"}, {"aud": [TARGET, "other"]},
    {"iss": "https://other.invalid"}, {"azp": "other-client"},
    {"iat": 0}, {"exp": 1000}, {"jti": ""}, {"tr_identity_id": "another-user"},
])
def test_untrusted_source_issuer_audience_lifetime_and_identity_fail(change):
    token, claims = assertion(**change)
    value, _, grant, _, _ = verifier(claims)
    with pytest.raises(PermissionError):
        value.authenticate(token, expected_identity="stable-user")
    assert grant.calls == 0


def test_target_identity_and_object_policy_fail_closed():
    token, claims = assertion()
    # Even an admin-created, same-name Keycloak link cannot conflate IDs.
    value, _, _, _, _ = verifier(claims, target_session=lambda _token: {
        "keycloak_issuer": TARGET, "keycloak_subject": "different-subject",
        "tr_identity_id": "different-stable-user", "username": "source-alice"})
    with pytest.raises(PermissionError, match="does not match"):
        value.authenticate(token, expected_identity="stable-user")
    value, _, _, _, _ = verifier(claims, target_authorize=lambda _session, _token: False)
    with pytest.raises(PermissionError, match="object authorization"):
        value.authenticate(token, expected_identity="stable-user")
    value, _, _, _, _ = verifier(claims, source_authorize=lambda _claims, _token: False)
    with pytest.raises(PermissionError, match="source Keycloak"):
        value.authenticate(token, expected_identity="stable-user")


def test_introspection_must_validate_the_same_signed_claims():
    token, claims = assertion()
    value, provider, grant, _, _ = verifier(claims)
    provider.claims["sub"] = "different-subject"
    with pytest.raises(PermissionError, match="introspection differ"):
        value.authenticate(token, expected_identity="stable-user")
    assert grant.calls == 0


def test_target_token_cannot_outlive_source_assertion():
    token, claims = assertion()
    value, _, _, _, _ = verifier(claims, target_session=lambda _token: {
        "keycloak_issuer": TARGET, "keycloak_subject": "local-subject",
        "tr_identity_id": "stable-user", "expires_in": 200})
    with pytest.raises(PermissionError, match="outlives"):
        value.authenticate(token, expected_identity="stable-user")


def test_keycloak_jwt_grant_uses_the_existing_confidential_client():
    class Client(ServiceOIDCClient):
        def _token(self, form):
            return form
    client = Client("https://identity.invalid", "realm", "manager", client_secret="secret")
    form = client.jwt_authorization_grant("assertion", scope="openid")
    assert form == {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "client_id": "manager", "assertion": "assertion", "scope": "openid"}
    with pytest.raises(ValueError):
        client.jwt_authorization_grant("")


def test_target_bad_grant_and_provider_outage_are_not_success():
    token, claims = assertion()
    class Fails:
        def __init__(self, code):
            self.code = code
        def jwt_authorization_grant(self, *_args, **_kwargs):
            raise HTTPError("https://id.invalid", self.code, "error", {}, None)
    value, _, _, _, _ = verifier(claims, target_grant=Fails(400))
    with pytest.raises(PermissionError, match="rejected"):
        value.authenticate(token, expected_identity="stable-user")
    value, _, _, _, _ = verifier(claims, target_grant=Fails(503))
    with pytest.raises(AuthorizationUnavailable, match="unavailable"):
        value.authenticate(token, expected_identity="stable-user")
