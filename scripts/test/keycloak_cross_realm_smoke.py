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
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
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

    # The target's individual compute nodes use Keycloak resources, not the
    # Manager grant or Bundle visibility. Check with the same retained user
    # token both before and after the node-specific grant is revoked.
    from server.identity import keycloak_authorization as object_authz
    from server.identity.request_context import bind_verified_identity, identity_request
    from server.modules.single_factor_test import execution_nodes
    node_resources = []
    for node_id, subject in (("node-allowed", alice_b["id"]), ("node-denied", other_b["id"])):
        ref = execution_nodes.execution_node_resource_ref("target-manager", node_id)
        node_id_resource = sandbox.protection(target_realm, "POST", "resource_set", token=b_pat, body={
            "name": object_authz.keycloak_resource_name("execution_node", ref),
            "ownerManagedAccess": True, "uris": [object_authz.keycloak_resource_uri("execution_node", ref)],
            "resource_scopes": ["use"],
        })["_id"]
        sandbox.protection(target_realm, "POST", "uma-policy/" + node_id_resource, token=b_pat, body={
            "name": node_id + "-use", "users": [subject], "scopes": ["use"], "logic": "POSITIVE",
        })
        node_resources.append(node_id_resource)
    from types import SimpleNamespace
    rows = [{"deployment_id": node, "service_port": 8000, "online": True, "expires_at": time.time() + 60,
             "capabilities": {"execution_target": {"manager_id": "target-manager", "node_id": node},
                              "offers": [], "runtime_adapters": {}}}
            for node in ("node-allowed", "node-denied")]
    local_node_service = SimpleNamespace(manager_id="target-manager", directory=lambda: rows)
    object_settings = {"authz_client_id": "chain-b-client", "authz_client_secret": b_secret,
                       "base_url": sandbox.base, "realm": target_realm}
    with patch.object(execution_nodes, "node_service", return_value=local_node_service), \
         patch.object(object_authz, "oidc_settings", return_value=object_settings), \
         identity_request():
        bind_verified_identity(result.target_token, result.target_session)
        assert [row["target"]["node_id"] for row in execution_nodes.visible_targets("target-alice")] == ["node-allowed"]
        policy = next(row for row in sandbox.protection(
            target_realm, "GET", "uma-policy?" + urlencode({"resource": node_resources[0]}), token=b_pat)
            if row.get("name") == "node-allowed-use")
        sandbox.protection(target_realm, "DELETE", "uma-policy/" + quote(policy["id"], safe=""), token=b_pat)
        assert execution_nodes.visible_targets("target-alice") == []

    # Exercise the actual signed peer HTTP route with the real two-realm
    # Keycloak grant, online source UMA and target UMA. The temporary Manager's
    # admission and job repository are explicit test doubles; their respective
    # real admission and repository tests are separate.
    from server.identity import federated_peer_delegation as peer_delegation
    from server.manager import runtime as manager
    from server.manager.http.federation import jobs as peer_jobs
    from server.manager.http.peer_handler import peer_control_handler
    from server.manager.transfers.node_client import NodeControlClient
    from server.manager.transfers.node_keys import NodeKey

    route_resource = resource(target_realm, b_pat, "target-route", "read")
    sandbox.protection(target_realm, "POST", "uma-policy/" + route_resource, token=b_pat, body={
        "name": "target-alice-route-read", "users": [alice_b["id"]], "scopes": ["read"], "logic": "POSITIVE",
    })
    binding = peer_delegation.PeerBinding("source-manager", "", source_issuer, "chain-a-client",
        target_issuer, "chain-a-client", source_resource, route_resource, "access-chain-b")
    settings = {"issuer": target_issuer, "realm": target_realm, "backchannel_base_url": sandbox.base,
                "authz_client_id": "chain-b-client", "authz_client_secret": b_secret}
    def client_factory(_base, realm, _client, **_kwargs):
        return introspection if realm == source_realm else b
    with tempfile.TemporaryDirectory(prefix="tr-kc-route-") as directory:
        root = Path(directory)
        state = manager.ManagerState(root / "repo", "python", server_role="main",
                                     server_id="target-manager", state_root=root / "state")
        key = NodeKey.load_or_create(root / "source.key", node_id="source-manager")
        state.node_identities.enroll(key.public_record())
        observed = []
        def local_jobs(**kwargs):
            observed.append(kwargs)
            return {"jobs": [{"job_id": "isolated-job"}], "total": 1}
        state.aggregate_account_jobs = local_jobs
        server = ThreadingHTTPServer(("127.0.0.1", 0), peer_control_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        node = NodeControlClient(f"http://127.0.0.1:{server.server_address[1]}", key=key)
        def route_query(token):
            return node.signed_json("/api/federation/jobs/query", {
                "requester_server_id": "source-manager", "identity_id": "stable-alice",
                "delegation_assertion": token, "scope": "mine", "page": 1, "limit": 20,
            })
        try:
            with patch.object(peer_jobs, "bound_peer", return_value=binding), \
                 patch.object(peer_delegation, "oidc_settings", return_value=settings), \
                 patch.object(peer_delegation, "_peer_secret", return_value=peer_secret), \
                 patch.object(peer_delegation, "_local_client", return_value=b), \
                 patch.object(peer_delegation, "ServiceOIDCClient", side_effect=client_factory), \
                 patch.object(peer_delegation, "keycloak_session", side_effect=target_session.session), \
                 patch.object(peer_delegation, "server_admission", return_value=(True, "")):
                assert route_query(assertion())["jobs"][0]["job_id"] == "isolated-job"
                assert observed[0]["principal"] == "target-alice"
                assert observed[0]["delegated_user_token"] != original("source-alice")
                pending_route = assertion()
                role_change(alice_a, "DELETE")
                try:
                    denied(lambda: route_query(pending_route))
                finally:
                    role_change(alice_a, "POST")
                policy = next(row for row in sandbox.protection(
                    target_realm, "GET", "uma-policy?" + urlencode({"resource": route_resource}), token=b_pat)
                    if row.get("name") == "target-alice-route-read")
                sandbox.protection(target_realm, "DELETE", "uma-policy/" + quote(policy["id"], safe=""), token=b_pat)
                denied(lambda: route_query(assertion()))
                assert len(observed) == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
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
    return {"signed_manager_http_real_keycloak_uma": "passed_with_repository_and_admission_doubles",
            "real_node_specific_uma_same_token_revocation": "passed",
            "different_names_same_identity": True, "same_names_different_identity": "denied",
            "source_offline_or_revoked": "denied", "target_object_revoked": "denied",
            "wrong_audience_replay_and_unlisted_idp": "denied"}


def main():
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({"isolated_keycloak_cross_realm": "passed", "checks": result,
                      "temporary_container_removed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
