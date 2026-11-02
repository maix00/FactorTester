"""Bind cross-realm user delegation to an enrolled, signed Manager peer.

Keycloak is the authority for the peer's issuer and delegation policy.  The
existing signed node advertisement and enrollment remain the authority for
its network endpoint and key; this module maintains no second node directory.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from server.identity.cross_realm_delegation import CrossRealmDelegation
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.server_admission import manager_binding_group_path, server_admission
from server.identity.user_session import keycloak_session, oidc_settings


@dataclass(frozen=True)
class PeerBinding:
    node_id: str
    endpoint: str
    issuer: str
    exchange_client: str
    introspection_client: str
    authorization_client: str
    authorization_resource: str
    incoming_authorization_resource: str
    exchange_scope: str


def _single(attributes: dict, name: str, *, optional: bool = False) -> str:
    value = attributes.get(name)
    if optional and value is None:
        return ""
    if (not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str)
            or not value[0].strip() or value[0] != value[0].strip() or len(value[0]) > 2048):
        raise AuthorizationUnavailable("Keycloak peer binding is incomplete or ambiguous")
    return value[0]


def _issuer(value: str) -> tuple[str, str]:
    base, separator, realm = value.rpartition("/realms/")
    parsed = urlsplit(base)
    if (not separator or not realm or "/" in realm or value.endswith("/")
            or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise AuthorizationUnavailable("Keycloak peer issuer is invalid")
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(parsed.hostname)
            private = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            private = "." not in parsed.hostname or parsed.hostname.endswith((".internal", ".local"))
        if not private:
            raise AuthorizationUnavailable("Keycloak peer issuer requires TLS")
    return base, realm


def _secret_file(path: str) -> str:
    """Read a bounded secret from a local mount, never from peer metadata."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("not a regular file")
            value = os.read(fd, 4097)
        finally:
            os.close(fd)
        if not value or len(value) > 4096:
            raise ValueError("invalid secret length")
        secret = value.decode("utf-8").strip()
        if not secret:
            raise ValueError("empty secret")
        return secret
    except (OSError, UnicodeError, ValueError) as exc:
        raise AuthorizationUnavailable("federated Keycloak credential is unavailable") from exc


def _local_client(settings: dict) -> ServiceOIDCClient:
    client_id = str(os.environ.get("TR_FEDERATION_USER_CLIENT_ID") or "").strip()
    secret_path = str(os.environ.get("TR_FEDERATION_USER_CLIENT_SECRET_FILE") or "").strip()
    if not client_id or not secret_path:
        raise AuthorizationUnavailable("federated Keycloak client is not configured")
    return ServiceOIDCClient(settings["backchannel_base_url"], settings["realm"], client_id,
                             client_secret=_secret_file(secret_path), timeout=5.0)


def _peer_secret(node_id: str) -> str:
    root = str(os.environ.get("TR_FEDERATION_PEER_SECRET_DIR") or "").strip()
    if not root:
        raise AuthorizationUnavailable("peer introspection credentials are not configured")
    # The filename is derived locally, not supplied by the network or group.
    filename = hashlib.sha256(node_id.encode("utf-8")).hexdigest() + ".secret"
    return _secret_file(str(Path(root) / filename))


def bound_peer(state, node_id: str, *, expected_endpoint: str = "") -> PeerBinding:
    """Require a current signed lease plus the matching admin-owned KC group."""
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    from urllib.parse import quote

    selected = str(node_id or "").strip()
    if not selected or selected == str(state.server_id):
        raise PermissionError("registered peer Manager is required")
    try:
        node = state.node_identities.require(selected)
        endpoint = state.transfer_endpoints.require(selected)
        server = state.federation_registry.describe(selected)
        if not isinstance(server, dict) or not endpoint.online:
            raise PermissionError("peer Manager is offline or unregistered")
        advertised = server.get("transfer_node")
        if (not isinstance(advertised, dict)
                or str(advertised.get("node_id") or "") != selected
                or str((advertised.get("identity") or {}).get("fingerprint") or "") != node.fingerprint
                or str(advertised.get("peer_control_endpoint") or "").rstrip("/") != endpoint.peer_control_endpoint.rstrip("/")
                or (expected_endpoint and expected_endpoint.rstrip("/") != endpoint.peer_control_endpoint.rstrip("/"))):
            raise PermissionError("peer Manager signed identity or endpoint changed")
        path = manager_binding_group_path(selected)
        row = manager_keycloak_admin_adapter()._get("group-by-path/" + quote(path.lstrip("/"), safe="/"))
        attributes = row.get("attributes") if isinstance(row, dict) and row.get("path") == path else None
        if not isinstance(attributes, dict):
            raise AuthorizationUnavailable("Keycloak peer binding is unavailable")
        manager_id = attributes.get("tr_manager_id", attributes.get("tr_internal_manager_id"))
        if manager_id != [selected] or attributes.get("tr_node_key_fingerprint") != [node.fingerprint]:
            raise PermissionError("Keycloak peer Manager or node key binding changed")
        issuer = _single(attributes, "tr_federation_oidc_issuer")
        _issuer(issuer)
        return PeerBinding(selected, endpoint.peer_control_endpoint.rstrip("/"), issuer,
            _single(attributes, "tr_federation_exchange_client_id"),
            _single(attributes, "tr_federation_introspection_client_id"),
            _single(attributes, "tr_federation_authz_client_id"),
            _single(attributes, "tr_federation_authz_resource_id"),
            _single(attributes, "tr_federation_incoming_authz_resource_id"),
            _single(attributes, "tr_federation_exchange_scope", optional=True))
    except (PermissionError, AuthorizationUnavailable):
        raise
    except (KeyError, AttributeError, OSError, TypeError, ValueError) as exc:
        raise AuthorizationUnavailable("peer Manager identity binding is unavailable") from exc


def exchange_for_peer(state, binding: PeerBinding, *, token: str, principal: str) -> tuple[str, str]:
    """Exchange a currently authorized local user for one peer-bound assertion."""
    session = state.session(token)
    if not isinstance(session, dict) or session.get("username") != principal:
        raise PermissionError("verified source user session is required")
    allowed, _reason = server_admission(session, state=state, use_cache=False)
    stable = str(session.get("tr_identity_id") or "").strip()
    if not allowed or not stable:
        raise PermissionError("source user is not currently authorized")
    try:
        client = _local_client(oidc_settings())
        value = client.exchange_token(token, audience=binding.issuer, scope=binding.exchange_scope)
        assertion = value.get("access_token") if isinstance(value, dict) else None
        if not isinstance(assertion, str) or not assertion or len(assertion) > 32768:
            raise ValueError("missing assertion")
    except (OSError, ValueError, KeyError) as exc:
        raise AuthorizationUnavailable("source Keycloak delegation is unavailable") from exc
    return assertion, stable


def accept_from_peer(state, binding: PeerBinding, *, assertion: str, stable_id: str,
                     target_scope: str):
    """Return a verified target-realm identity; never treat the assertion as local."""
    source_base, source_realm = _issuer(binding.issuer)
    settings = oidc_settings()
    source = ServiceOIDCClient(source_base, source_realm, binding.introspection_client,
                               client_secret=_peer_secret(binding.node_id), timeout=5.0)
    target = _local_client(settings)
    if target_scope not in {"read", "write"}:
        raise ValueError("unsupported federated target scope")
    local_policy = ServiceOIDCClient(settings["backchannel_base_url"], settings["realm"],
        settings["authz_client_id"], client_secret=settings["authz_client_secret"], timeout=5.0)

    def allowed_source(_claims, source_token):
        return source.authorize(source_token, audience=binding.authorization_client,
                                resource_id=binding.authorization_resource, scope="use", timeout=5.0)

    def allowed_target(session, target_token):
        admitted, _reason = server_admission(session, state=state, use_cache=False)
        return bool(admitted and local_policy.authorize(target_token,
            audience=settings["authz_client_id"], resource_id=binding.incoming_authorization_resource,
            scope=target_scope, timeout=5.0))

    return CrossRealmDelegation(
        source_introspection=source, target_grant=target, source_issuer=binding.issuer,
        target_issuer=settings["issuer"], source_client_id=binding.exchange_client,
        target_session=keycloak_session, source_authorize=allowed_source,
        target_authorize=allowed_target,
    ).authenticate(assertion, expected_identity=stable_id)
