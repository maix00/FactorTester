"""Bound, online Keycloak identity chaining for trusted Manager peers.

A Manager must first authenticate the peer and choose this verifier from its
administrator-owned peer configuration.  The source assertion is not a local
bearer.  Source introspection, Keycloak's JWT grant, target session admission
and the caller's current object decision must all succeed for every request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable
from urllib.error import HTTPError, URLError

from server.identity.keycloak import jwt_claims
from server.identity.keycloak_authorization import AuthorizationUnavailable


@dataclass(frozen=True)
class DelegatedIdentity:
    # These credentials remain inside the trusted server-to-server request.
    target_token: str = field(repr=False, compare=False)
    target_session: dict = field(repr=False, compare=False)
    identity_id: str
    source_issuer: str
    source_subject: str


class CrossRealmDelegation:
    """Validate an already-targeted assertion without a local identity bypass."""

    def __init__(self, *, source_introspection, target_grant, source_issuer: str,
                 target_issuer: str, source_client_id: str,
                 target_session: Callable[[str], dict | None],
                 source_authorize: Callable[[dict, str], bool],
                 target_authorize: Callable[[dict, str], bool],
                 clock: Callable[[], float] = time.time,
                 max_assertion_lifetime: int = 300) -> None:
        self.source_introspection = source_introspection
        self.target_grant = target_grant
        self.source_issuer = str(source_issuer or "").rstrip("/")
        self.target_issuer = str(target_issuer or "").rstrip("/")
        self.source_client_id = str(source_client_id or "").strip()
        if (not self.source_issuer or not self.target_issuer or not self.source_client_id
                or self.source_issuer == self.target_issuer):
            raise ValueError("trusted source, target and source client are required")
        if (type(max_assertion_lifetime) is not int or not 1 <= max_assertion_lifetime <= 300):
            raise ValueError("assertion lifetime must be between 1 and 300 seconds")
        if not all(callable(value) for value in (target_session, source_authorize, target_authorize, clock)):
            raise ValueError("live identity and authorization callbacks are required")
        self.target_session = target_session
        self.source_authorize = source_authorize
        self.target_authorize = target_authorize
        self.clock = clock
        self.max_assertion_lifetime = max_assertion_lifetime

    def _source(self, assertion: str, *, expected_identity: str) -> dict:
        try:
            claims = self.source_introspection.introspect(assertion)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            raise AuthorizationUnavailable("source Keycloak introspection is unavailable") from exc
        if not isinstance(claims, dict) or claims.get("active") is not True:
            raise PermissionError("source Keycloak assertion is not active")
        # The signature is validated by source introspection above. Decode the
        # same JWT only to enforce its actual single audience; Keycloak's
        # introspection can report extra mapped audiences not present in it.
        try:
            if len(assertion.split(".")) != 3:
                raise ValueError("not a JWT")
            signed = jwt_claims(assertion)
        except (IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PermissionError("source assertion is malformed") from exc
        if not isinstance(signed, dict):
            raise PermissionError("source assertion claims are invalid")
        for key in ("iss", "sub", "jti", "exp", "iat", "azp", "tr_identity_id"):
            if signed.get(key) != claims.get(key):
                raise PermissionError("source assertion and introspection differ")
        audience = signed.get("aud")
        if audience != self.target_issuer and audience != [self.target_issuer]:
            raise PermissionError("source assertion audience is not the target realm")
        subject, identifier = signed.get("sub"), signed.get("jti")
        if (signed.get("iss") != self.source_issuer or signed.get("azp") != self.source_client_id
                or not isinstance(subject, str) or not subject or len(subject) > 512
                or not isinstance(identifier, str) or not identifier or len(identifier) > 512
                or signed.get("tr_identity_id") != expected_identity):
            raise PermissionError("source assertion identity or issuer is invalid")
        issued, expires = signed.get("iat"), signed.get("exp")
        now = self.clock()
        if (type(issued) not in (int, float) or type(expires) not in (int, float)
                or not math.isfinite(issued) or not math.isfinite(expires) or not math.isfinite(now)
                or issued > now + 5 or expires <= now or expires <= issued
                or expires - issued > self.max_assertion_lifetime):
            raise PermissionError("source assertion lifetime is invalid")
        if self.source_authorize(claims, assertion) is not True:
            raise PermissionError("source Keycloak current authorization was denied")
        return claims

    def authenticate(self, assertion: str, *, expected_identity: str) -> DelegatedIdentity:
        """Return a local token only after online identity and object checks."""
        if (not isinstance(assertion, str) or not assertion or len(assertion) > 32768
                or not isinstance(expected_identity, str) or not expected_identity.strip()
                or len(expected_identity) > 512):
            raise ValueError("foreign assertion and stable identity are required")
        source = self._source(assertion, expected_identity=expected_identity)
        try:
            result = self.target_grant.jwt_authorization_grant(assertion, scope="openid")
        except HTTPError as exc:
            if exc.code in (400, 401, 403):
                raise PermissionError("target Keycloak rejected the assertion") from exc
            raise AuthorizationUnavailable("target Keycloak grant is unavailable") from exc
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            raise AuthorizationUnavailable("target Keycloak grant is unavailable") from exc
        target_token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(target_token, str) or not target_token or len(target_token) > 32768:
            raise AuthorizationUnavailable("target Keycloak returned no access token")
        session = self.target_session(target_token)
        if (not isinstance(session, dict) or session.get("keycloak_issuer") != self.target_issuer
                or session.get("tr_identity_id") != expected_identity
                or not session.get("keycloak_subject")):
            raise PermissionError("target Keycloak identity does not match the source")
        remaining = session.get("expires_in")
        if (type(remaining) is not int or remaining <= 0
                or remaining > max(0, source["exp"] - self.clock()) + 5):
            raise PermissionError("target token outlives the source assertion")
        # Keycloak verifies a signature, but by itself may accept a previously
        # issued assertion after the source user or source realm is disabled.
        again = self._source(assertion, expected_identity=expected_identity)
        if any(again.get(key) != source.get(key) for key in ("iss", "sub", "jti", "tr_identity_id")):
            raise PermissionError("source assertion identity changed during exchange")
        if self.target_authorize(session, target_token) is not True:
            raise PermissionError("target Keycloak current object authorization was denied")
        return DelegatedIdentity(target_token, dict(session), expected_identity,
                                 self.source_issuer, str(source["sub"]))
