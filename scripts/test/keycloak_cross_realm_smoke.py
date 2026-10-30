#!/usr/bin/env python3
"""Exercise Keycloak's cross-realm chain in a disposable, loopback container.

The image must already exist; no dependency or image is downloaded. The
container uses a temporary H2 store, random credentials and a 1.2 GiB limit,
and is removed when the script exits. No existing realm is modified.
"""
from __future__ import annotations

import json
import secrets
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from server.identity.cross_realm_delegation import CrossRealmDelegation
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.user_session import UserSessionVerifier


class Sandbox:
    def __init__(self) -> None:
        self.name = "tr-kc-chain-" + secrets.token_hex(6)
        self.admin_password = secrets.token_urlsafe(30)
        self.base = ""
        self.admin = ""
        self.started = False

    def __enter__(self):
        command = ["docker", "run", "--rm", "-d", "--pull=never", "--name", self.name,
                   "--memory=1200m", "--cpus=2", "--pids-limit=400", "-p", "127.0.0.1::8080",
                   "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=tr-qa", "-e",
                   "KC_BOOTSTRAP_ADMIN_PASSWORD=" + self.admin_password,
                   "quay.io/keycloak/keycloak:26.8.1", "start-dev",
                   "--http-enabled=true", "--hostname=http://localhost:8080"]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.started = True
            port = subprocess.check_output(["docker", "port", self.name, "8080/tcp"], text=True).strip()
            self.base = "http://127.0.0.1:" + port.rsplit(":", 1)[1]
            deadline = time.monotonic() + 90
            while True:
                try:
                    self.request("GET", "/realms/master/.well-known/openid-configuration")
                    break
                except (OSError, ValueError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("temporary Keycloak did not start")
                    time.sleep(1)
            self.admin = self.request("POST", "/realms/master/protocol/openid-connect/token", form={
                "client_id": "admin-cli", "grant_type": "password", "username": "tr-qa",
                "password": self.admin_password,
            })["access_token"]
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if self.started:
            subprocess.run(["docker", "rm", "-f", self.name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.started = False

    def request(self, method, path, *, body=None, form=None, token=""):
        headers = {"Accept": "application/json"}
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body).encode()
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            raw = urlencode(form).encode()
        if token:
            headers["Authorization"] = "Bearer " + token
        with urlopen(Request(self.base + path, data=raw, headers=headers, method=method), timeout=15) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("temporary Keycloak response exceeds budget")
        return json.loads(data) if data else {}

    def api(self, method, realm, path="", body=None):
        return self.request(method, "/admin/realms/" + realm + ("/" + path if path else ""),
                            body=body, token=self.admin)

    def find(self, realm, path, name, *, field="name"):
        rows = self.api("GET", realm, path)
        matches = [row for row in rows if row.get(field) == name]
        if len(matches) != 1:
            raise RuntimeError("temporary Keycloak entity is missing or ambiguous")
        return matches[0]

    def protection(self, realm, method, path, *, token, body=None):
        return self.request(method, "/realms/" + realm + "/authz/protection/" + path,
                            body=body, token=token)


def denied(action) -> None:
    try:
        action()
    except (PermissionError, AuthorizationUnavailable, HTTPError):
        return
    raise AssertionError("an invalid or revoked identity unexpectedly gained access")


def run(sandbox: Sandbox) -> dict[str, object]:
    source_realm, target_realm = "chain-a", "chain-b"
    source_issuer = "http://localhost:8080/realms/" + source_realm
    target_issuer = "http://localhost:8080/realms/" + target_realm
    a_secret, b_secret, peer_secret, user_password = (secrets.token_urlsafe(24) for _ in range(4))
    for realm in (source_realm, target_realm):
        sandbox.request("POST", "/admin/realms", token=sandbox.admin,
                        body={"realm": realm, "enabled": True, "accessTokenLifespan": 120,
                              "registrationAllowed": False, "sslRequired": "none"})
        profile = sandbox.api("GET", realm, "users/profile")
        profile["attributes"].append({"name": "tr_identity_id", "displayName": "Stable ID",
                                      "permissions": {"view": ["admin"], "edit": ["admin"]}})
        sandbox.api("PUT", realm, "users/profile", profile)

    sandbox.api("POST", source_realm, "clients", {
        "clientId": target_issuer, "enabled": True, "protocol": "openid-connect", "publicClient": False,
        "secret": peer_secret, "redirectUris": [target_issuer + "/broker/chain-a/endpoint/*"],
    })
    sandbox.api("POST", source_realm, "clients", {
        "clientId": "chain-a-client", "enabled": True, "protocol": "openid-connect", "publicClient": False,
        "secret": a_secret, "standardFlowEnabled": True, "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": True, "authorizationServicesEnabled": True,
        "attributes": {"standard.token.exchange.enabled": "true"},
    })
    sandbox.api("POST", target_realm, "clients", {
        "clientId": "chain-b-client", "enabled": True, "protocol": "openid-connect", "publicClient": False,
        "secret": b_secret, "serviceAccountsEnabled": True, "authorizationServicesEnabled": True,
        "attributes": {"oauth2.jwt.authorization.grant.enabled": "true",
                       "oauth2.jwt.authorization.grant.idp": "chain-a"},
    })
    a_id = sandbox.find(source_realm, "clients?" + urlencode({"clientId": "chain-a-client"}),
                        "chain-a-client", field="clientId")["id"]
    b_id = sandbox.find(target_realm, "clients?" + urlencode({"clientId": "chain-b-client"}),
                        "chain-b-client", field="clientId")["id"]
    sandbox.api("POST", source_realm, "client-scopes", {
        "name": "access-chain-b", "protocol": "openid-connect",
        "attributes": {"include.in.token.scope": "true"},
    })
    scope_id = sandbox.find(source_realm, "client-scopes", "access-chain-b")["id"]
    sandbox.api("POST", source_realm, "client-scopes/" + scope_id + "/protocol-mappers/models", {
        "name": "target-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": target_issuer, "access.token.claim": "true",
                   "id.token.claim": "false"},
    })
    sandbox.api("PUT", source_realm, "clients/" + a_id + "/optional-client-scopes/" + scope_id)
    for realm, client_id in ((source_realm, a_id), (target_realm, b_id)):
        sandbox.api("POST", realm, "clients/" + client_id + "/protocol-mappers/models", {
            "name": "stable-id", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {"user.attribute": "tr_identity_id", "claim.name": "tr_identity_id",
                       "jsonType.label": "String", "access.token.claim": "true", "id.token.claim": "true",
                       "userinfo.token.claim": "true", "introspection.token.claim": "true"},
        })
    sandbox.api("POST", target_realm, "clients/" + b_id + "/protocol-mappers/models", {
        "name": "target-client-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": "chain-b-client", "access.token.claim": "true"},
    })
    sandbox.api("POST", target_realm, "identity-provider/instances", {
        "alias": "chain-a", "providerId": "oidc", "enabled": True, "trustEmail": False, "storeToken": False,
        "config": {"issuer": source_issuer, "authorizationUrl": source_issuer + "/protocol/openid-connect/auth",
                   "tokenUrl": source_issuer + "/protocol/openid-connect/token",
                   "userInfoUrl": source_issuer + "/protocol/openid-connect/userinfo",
                   "jwksUrl": source_issuer + "/protocol/openid-connect/certs", "useJwksUrl": "true",
                   "clientId": target_issuer, "clientSecret": peer_secret,
                   "jwtAuthorizationGrantEnabled": "true", "jwtAuthorizationGrantAssertionReuseAllowed": "false",
                   "jwtAuthorizationGrantMaxAllowedAssertionExpiration": "300",
                   "jwtAuthorizationGrantLimitAccessTokenExp": "true"},
    })

    for realm, name, stable in ((source_realm, "source-alice", "stable-alice"),
                                (target_realm, "target-alice", "stable-alice"),
                                (source_realm, "same", "source-other"),
                                (target_realm, "same", "target-other")):
        sandbox.api("POST", realm, "users", {
            "username": name, "enabled": True, "emailVerified": True, "firstName": "Temporary",
            "lastName": "User", "email": name + "@example.invalid", "attributes": {"tr_identity_id": [stable]},
            "credentials": [{"type": "password", "value": user_password, "temporary": False}],
        })
    def user(realm, name):
        return sandbox.find(realm, "users?" + urlencode({"username": name, "exact": "true"}), name, field="username")
    alice_a, alice_b = user(source_realm, "source-alice"), user(target_realm, "target-alice")
    other_a, other_b = user(source_realm, "same"), user(target_realm, "same")
    def link(source, target):
        sandbox.api("POST", target_realm, "users/" + target["id"] + "/federated-identity/chain-a",
                    {"identityProvider": "chain-a", "userId": source["id"], "userName": source["username"]})
    link(alice_a, alice_b)

    sandbox.api("POST", source_realm, "roles", {"name": "federation-access"})
    role = sandbox.api("GET", source_realm, "roles/federation-access")
    sandbox.api("POST", source_realm, "client-scopes/" + scope_id + "/scope-mappings/realm", [role])
    def role_change(user_row, method):
        sandbox.api(method, source_realm, "users/" + user_row["id"] + "/role-mappings/realm", [role])
    role_change(alice_a, "POST")
    a = ServiceOIDCClient(sandbox.base, source_realm, "chain-a-client", client_secret=a_secret)
    introspection = ServiceOIDCClient(sandbox.base, source_realm, target_issuer, client_secret=peer_secret)
    b = ServiceOIDCClient(sandbox.base, target_realm, "chain-b-client", client_secret=b_secret)
    target_session = UserSessionVerifier(b, issuer=target_issuer, audience="chain-b-client")

    def original(name):
        return a._token({"grant_type": "password", "client_id": "chain-a-client",
                         "username": name, "password": user_password})["access_token"]

    def assertion(name="source-alice"):
        return a.exchange_token(original(name), audience=target_issuer, scope="access-chain-b")["access_token"]

    a_pat, b_pat = a.client_credentials()["access_token"], b.client_credentials()["access_token"]
    def resource(realm, pat, name, scope):
        return sandbox.protection(realm, "POST", "resource_set", token=pat, body={
            "name": name, "ownerManagedAccess": True, "uris": ["/" + name], "resource_scopes": [scope],
        })["_id"]
    source_resource = resource(source_realm, a_pat, "source-operation", "use")
    target_resource = resource(target_realm, b_pat, "target-object", "read")
    prefix = "clients/" + a_id + "/authz/resource-server"
    sandbox.api("POST", source_realm, prefix + "/policy/role", {
        "name": "current-role", "logic": "POSITIVE", "fetchRoles": True,
        "roles": [{"id": role["id"], "required": True}],
    })
    sandbox.api("POST", source_realm, prefix + "/permission/scope", {
        "name": "source-operation-permission", "resources": [source_resource], "scopes": ["use"],
        "policies": ["current-role"], "decisionStrategy": "UNANIMOUS",
    })
    sandbox.protection(target_realm, "POST", "uma-policy/" + target_resource, token=b_pat, body={
        "name": "target-alice-read", "users": [alice_b["id"]], "scopes": ["read"], "logic": "POSITIVE",
    })

    verifier = CrossRealmDelegation(
        source_introspection=introspection, target_grant=b, source_issuer=source_issuer,
        target_issuer=target_issuer, source_client_id="chain-a-client", target_session=target_session.session,
        source_authorize=lambda _claims, token: a.authorize(token, audience="chain-a-client",
                                                           resource_id=source_resource, scope="use"),
        target_authorize=lambda _session, token: b.authorize(token, audience="chain-b-client",
                                                            resource_id=target_resource, scope="read"),
    )
    result = verifier.authenticate(assertion(), expected_identity="stable-alice")
    assert result.target_session["username"] == "target-alice"
    one_time = assertion()
    verifier.authenticate(one_time, expected_identity="stable-alice")
    denied(lambda: verifier.authenticate(one_time, expected_identity="stable-alice"))
    denied(lambda: verifier.authenticate(original("source-alice"), expected_identity="stable-alice"))
    client_config = sandbox.api("GET", target_realm, "clients/" + b_id)
    changed_attributes = {**client_config["attributes"], "oauth2.jwt.authorization.grant.idp": "not-chain-a"}
    sandbox.api("PUT", target_realm, "clients/" + b_id, {**client_config, "attributes": changed_attributes})
    try:
        denied(lambda: verifier.authenticate(assertion(), expected_identity="stable-alice"))
    finally:
        sandbox.api("PUT", target_realm, "clients/" + b_id, client_config)
    # A user without the source role cannot obtain an accepted target audience.
    denied(lambda: verifier.authenticate(assertion("same"), expected_identity="source-other"))
    role_change(other_a, "POST")
    try:
        # Same name without a link is rejected by Keycloak.
        denied(lambda: verifier.authenticate(assertion("same"), expected_identity="source-other"))
        # Even an erroneous administrator-created link cannot merge stable IDs.
        link(other_a, other_b)
        denied(lambda: verifier.authenticate(assertion("same"), expected_identity="source-other"))
    finally:
        role_change(other_a, "DELETE")
    pending = assertion()
    role_change(alice_a, "DELETE")
    try:
        denied(lambda: verifier.authenticate(pending, expected_identity="stable-alice"))
    finally:
        role_change(alice_a, "POST")
    pending = assertion()
    sandbox.api("PUT", source_realm, "users/" + alice_a["id"], {**alice_a, "enabled": False})
    try:
        denied(lambda: verifier.authenticate(pending, expected_identity="stable-alice"))
    finally:
        sandbox.api("PUT", source_realm, "users/" + alice_a["id"], {**alice_a, "enabled": True})
    pending = assertion()
    source_config = sandbox.api("GET", source_realm)
    sandbox.api("PUT", source_realm, body={**source_config, "enabled": False})
    try:
        denied(lambda: verifier.authenticate(pending, expected_identity="stable-alice"))
    finally:
        sandbox.api("PUT", source_realm, body={**source_config, "enabled": True})
    target_policy = next(row for row in sandbox.protection(
        target_realm, "GET", "uma-policy?" + urlencode({"resource": target_resource}), token=b_pat)
        if row.get("name") == "target-alice-read")
    sandbox.protection(target_realm, "DELETE", "uma-policy/" + quote(target_policy["id"], safe=""), token=b_pat)
    denied(lambda: verifier.authenticate(assertion(), expected_identity="stable-alice"))
    return {"different_names_same_identity": True, "same_names_different_identity": "denied",
            "source_offline_or_revoked": "denied", "target_object_revoked": "denied",
            "wrong_audience_replay_and_unlisted_idp": "denied"}


def main():
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({"isolated_keycloak_cross_realm": "passed", "checks": result,
                      "temporary_container_removed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
