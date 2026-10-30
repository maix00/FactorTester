"""Provision one node-bound Keycloak service client without human/admin grants.

Operator-only deployment adapter. Credentials are written to a new protected
output directory; existing clients are never overwritten or silently rebound. Additional nodes
explicitly reuse the Manager verifier from its first protected receipt; they do
not rotate that verifier or copy its secret into node credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlencode

SCOPE = "tr:execution:node"


def provision(adapter, *, manager_id: str, node_id: str, output: Path,
              verifier_client_id: str | None = None) -> dict:
    for value in (manager_id, node_id):
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
            raise ValueError("explicit stable Manager and node identifiers are required")
    if output.exists():
        raise FileExistsError("credential directory exists; refusing credential rotation")
    # Do all conflict checks before mutation. Client IDs carry no user identity.
    import hashlib
    namespace = hashlib.sha256((manager_id + "\0" + node_id).encode()).hexdigest()[:24]
    clients = {"node": "tr-node-" + namespace, "verifier": "tr-node-verifier-" + namespace}
    if verifier_client_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", verifier_client_id):
            raise ValueError("invalid explicit Manager verifier client")
        clients["verifier"] = verifier_client_id
        existing = adapter._get("clients?" + urlencode({"clientId": verifier_client_id}))
        if len(existing) != 1 or not existing[0].get("id"):
            raise ValueError("explicit Manager verifier client is missing or ambiguous")
        verifier = adapter._get("clients/" + str(existing[0]["id"]))
        if (verifier.get("clientId") != verifier_client_id
                or verifier.get("enabled") is not True
                or verifier.get("publicClient") is not False
                or verifier.get("serviceAccountsEnabled") is not True
                or verifier.get("protocol") != "openid-connect"
                or verifier.get("standardFlowEnabled") is not False
                or verifier.get("directAccessGrantsEnabled") is not False
                or verifier.get("fullScopeAllowed") is not False):
            raise ValueError("Manager verifier must be a restricted confidential service client")
    created_clients = {k: v for k, v in clients.items()
                       if k != "verifier" or verifier_client_id is None}
    for client in created_clients.values():
        if adapter._get("clients?" + urlencode({"clientId": client})):
            raise ValueError("node client already exists; inspect its protected deployment receipt")
    scope = next((s for s in adapter._get("client-scopes") if s.get("name") == SCOPE), None)
    if scope is None:
        adapter._post("client-scopes", {"name": SCOPE, "protocol": "openid-connect",
            "attributes": {"include.in.token.scope": "true"}})
        scope = next(s for s in adapter._get("client-scopes") if s.get("name") == SCOPE)
    if scope.get("protocol") != "openid-connect":
        raise ValueError("execution scope has an incompatible protocol")
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    receipt = {"manager_id": manager_id, "node_id": node_id, "clients": clients, "scope": SCOPE}
    # Persist each secret before registering its client, for recoverable partial failure.
    for kind, client_id in created_clients.items():
        secret = secrets.token_urlsafe(48)
        path = output / (kind + ".secret")
        with open(path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
            f.write(secret)
        mappers = []
        if kind == "node":
            mappers = [
                {"name": "owning-manager", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                 "config": {"included.custom.audience": manager_id, "access.token.claim": "true", "introspection.token.claim": "true"}},
                {"name": "execution-node", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper",
                 "config": {"claim.name": "tr_node_id", "claim.value": node_id, "jsonType.label": "String",
                            "access.token.claim": "true", "introspection.token.claim": "true"}}]
        if kind == "node":
            # Keycloak also requires the introspecting confidential client in aud.
            mappers.append({"name": "manager-introspection", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper", "config": {
                    "included.custom.audience": clients["verifier"], "access.token.claim": "true",
                    "introspection.token.claim": "true"}})
        adapter._post("clients", {"clientId": client_id, "secret": secret, "protocol": "openid-connect",
            "enabled": True, "publicClient": False, "serviceAccountsEnabled": True,
            "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
            "fullScopeAllowed": False, "defaultClientScopes": [SCOPE] if kind == "node" else [],
            "optionalClientScopes": [], "protocolMappers": mappers})
    path = output / "receipt.json"
    with open(path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
        json.dump(receipt, f, sort_keys=True)
    return receipt
