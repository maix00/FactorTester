"""Origin-scoped visitor redirect and session state for public Manager entry."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


VISITOR_COOKIE = "ft-manager-visitor"
CLIENT_ACCESS_COOKIE = "ft-manager-client-access"
VISITOR_GRANT_TTL_SECONDS = 300
# A browser or ingress can replay a navigation while the first response is
# still in flight.  Keep this window short so the grant remains effectively
# one-time while making that normal retry safe.
VISITOR_GRANT_REPLAY_TTL_SECONDS = 30
VISITOR_SESSION_TTL_SECONDS = 12 * 60 * 60
CLIENT_ACCESS_TTL_SECONDS = 12 * 60 * 60
VISITOR_PRINCIPAL_PREFIX = "__public_jobs__:"


def normalize_visitor_id(value: object) -> str:
    """Return a canonical pseudonymous visitor id, or ``""``.

    The id is an owner namespace for bounded anonymous jobs.  It is not an
    authentication credential and is deliberately limited to UUID values so
    a caller cannot inject a Manager principal or an account name.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(uuid.UUID(raw)).lower()
    except (AttributeError, ValueError):
        return ""


def visitor_principal(visitor_id: object) -> str:
    """Map one visitor id to the private owner namespace used by Jobs."""
    normalized = normalize_visitor_id(visitor_id)
    return f"{VISITOR_PRINCIPAL_PREFIX}{normalized}" if normalized else "__public_jobs__"


@dataclass(frozen=True)
class VisitorMode:
    """The single anonymous capability set exposed by the public entry."""

    visitor_id: str = ""
    max_server_jobs: int = 20
    can_download_artifacts: bool = False
    can_submit: bool = True

    @property
    def principal(self) -> str:
        return visitor_principal(self.visitor_id)


VISITOR_MODE = VisitorMode()


def _origin(value: str) -> str:
    """Normalize a configured or request origin, returning ``""`` on error."""
    candidate = str(value or "").strip().rstrip("/")
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return ""
    hostname = parsed.hostname.lower()
    try:
        hostname = ipaddress.ip_address(hostname).compressed
    except ValueError:
        pass
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme == "https" else 80
    suffix = "" if port in {None, default_port} else f":{port}"
    return f"{parsed.scheme}://{hostname}{suffix}"


def configured_visitor_origins(raw: str | None = None) -> tuple[str, ...]:
    """Return explicitly trusted browser ingress origins.

    The public Manager endpoint is intentionally not included here.  A
    deployment must opt in each ingress origin (for example an ngrok origin)
    that is allowed to display the visitor entry.
    """
    value = raw
    if value is None:
        import os

        value = os.environ.get("FACTORTESTER_PUBLIC_VISITOR_ORIGINS", "")
    origins: list[str] = []
    for item in str(value or "").split(","):
        normalized = _origin(item)
        if normalized and normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def configured_public_visitor_login_allowlist(
    raw: str | None = None,
) -> tuple[str, ...]:
    """Return the case-sensitive account references allowed from visitors.

    The value is deliberately an explicit deployment setting rather than a
    built-in username.  Each item may be a canonical username, an
    ``organization@alias`` reference, or an alias.  Resolution against the
    current account rows happens in the session state, so a stale or
    ambiguous alias never authorizes a login.
    """
    value = raw
    if value is None:
        import os

        value = os.environ.get("FACTORTESTER_PUBLIC_VISITOR_LOGIN_ALLOWLIST", "")
    references: list[str] = []
    for item in str(value or "").split(","):
        reference = str(item or "").strip()
        if reference and reference not in references:
            references.append(reference)
    return tuple(references)


def configured_manager_endpoint(raw: str | None = None) -> str:
    """Return the configured Manager target used after visitor entry."""
    value = raw
    if value is None:
        import os

        value = os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", "")
    return _origin(str(value or ""))


def request_origin(*, scheme: str, host: str) -> str:
    """Normalize the origin represented by a request Host and scheme."""
    return _origin(f"{str(scheme or '').lower()}://{str(host or '').strip()}")


def target_visitor_url(target_origin: str, *, grant: str, next_path: str) -> str:
    """Build the IP-origin redemption URL without accepting a caller host."""
    return _target_url(
        target_origin,
        path="/visitor",
        grant=grant,
        next_path=next_path,
    )


def target_compliance_url(
    target_origin: str,
    *,
    grant: str,
    next_path: str,
) -> str:
    """Build an IP-origin compliance URL carrying an ingress grant."""
    return _target_url(
        target_origin,
        path="/compliance",
        grant=grant,
        next_path=next_path,
    )


def _target_url(
    target_origin: str,
    *,
    path: str,
    grant: str,
    next_path: str,
) -> str:
    """Build a target-origin URL without accepting a caller host."""
    parsed = urlsplit(target_origin)
    query = f"grant={_quote(grant)}&next={_quote(next_path)}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")


@dataclass(frozen=True)
class _VisitorRecord:
    kind: str
    target_origin: str
    expires_at: float
    visitor_id: str


@dataclass(frozen=True)
class _RedeemedGrant:
    """Short-lived idempotency state for a redeemed visitor grant."""

    target_origin: str
    expires_at: float
    session_token: str


class VisitorAccessStore:
    """Hold short-lived grants and origin-bound visitor sessions in memory.

    Visitor mode is deliberately anonymous and non-authoritative.  Losing
    these records on a Manager restart only requires the user to click the
    explicitly configured ingress entry again; it never creates an account or
    changes PostgreSQL state.
    """

    def __init__(self) -> None:
        self._records: dict[str, _VisitorRecord] = {}
        self._redeemed_grants: dict[str, _RedeemedGrant] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _purge(self, now: float) -> None:
        for digest, record in tuple(self._records.items()):
            if record.expires_at <= now:
                self._records.pop(digest, None)
        for digest, record in tuple(self._redeemed_grants.items()):
            if record.expires_at <= now:
                self._redeemed_grants.pop(digest, None)

    def _issue_locked(
        self,
        *,
        kind: str,
        target_origin: str,
        ttl: int,
        visitor_id: str,
        now: float,
    ) -> str:
        """Issue a record while the store lock is already held."""
        token = secrets.token_urlsafe(32)
        normalized_visitor_id = normalize_visitor_id(visitor_id) or str(
            uuid.uuid4()
        )
        self._records[self._digest(token)] = _VisitorRecord(
            kind=kind,
            target_origin=target_origin,
            expires_at=now + ttl,
            visitor_id=normalized_visitor_id,
        )
        return token

    def _issue(
        self,
        *,
        kind: str,
        target_origin: str,
        ttl: int,
        visitor_id: str = "",
    ) -> str:
        now = time.time()
        with self._lock:
            self._purge(now)
            return self._issue_locked(
                kind=kind,
                target_origin=target_origin,
                ttl=ttl,
                visitor_id=visitor_id,
                now=now,
            )

    def issue_grant(self, target_origin: str) -> str:
        return self._issue(
            kind="grant",
            target_origin=target_origin,
            ttl=VISITOR_GRANT_TTL_SECONDS,
        )

    def issue_client_access(
        self, target_origin: str, *, visitor_id: str = ""
    ) -> str:
        """Issue a short-lived capability for an identified native client.

        This capability only enables the visitor entry on the canonical
        public-origin compliance page.  It is deliberately separate from a
        visitor session and never authorizes account, device, or Manager
        operations.
        """
        return self._issue(
            kind="client-access",
            target_origin=target_origin,
            ttl=CLIENT_ACCESS_TTL_SECONDS,
            visitor_id=visitor_id,
        )

    def issue_session(
        self, target_origin: str, *, visitor_id: str = ""
    ) -> str:
        """Create a visitor session after an explicit entry action."""
        return self._issue(
            kind="session",
            target_origin=target_origin,
            ttl=VISITOR_SESSION_TTL_SECONDS,
            visitor_id=visitor_id,
        )

    def valid_client_access(self, token: str, *, target_origin: str) -> bool:
        return bool(
            self.client_access_visitor_id(token, target_origin=target_origin)
        )

    def client_access_visitor_id(
        self, token: str, *, target_origin: str
    ) -> str:
        now = time.time()
        with self._lock:
            self._purge(now)
            record = self._records.get(self._digest(token))
            if not (
                record
                and record.kind == "client-access"
                and record.target_origin == target_origin
                and record.expires_at > now
            ):
                return ""
            return record.visitor_id

    def redeem_grant(self, token: str, *, target_origin: str) -> str | None:
        now = time.time()
        with self._lock:
            self._purge(now)
            digest = self._digest(token)

            replay = self._redeemed_grants.get(digest)
            if replay and (
                replay.target_origin == target_origin
                and replay.expires_at > now
            ):
                return replay.session_token

            record = self._records.pop(digest, None)
            if (
                record is None
                or record.kind != "grant"
                or record.target_origin != target_origin
                or record.expires_at <= now
            ):
                return None
            session_token = self._issue_locked(
                kind="session",
                target_origin=target_origin,
                ttl=VISITOR_SESSION_TTL_SECONDS,
                visitor_id=record.visitor_id,
                now=now,
            )
            self._redeemed_grants[digest] = _RedeemedGrant(
                target_origin=target_origin,
                expires_at=now + VISITOR_GRANT_REPLAY_TTL_SECONDS,
                session_token=session_token,
            )
            return session_token

    def valid_grant(self, token: str, *, target_origin: str) -> bool:
        """Check an unconsumed ingress grant without enabling visitor mode."""
        now = time.time()
        with self._lock:
            self._purge(now)
            digest = self._digest(token)
            record = self._records.get(digest)
            return bool(
                record
                and record.kind == "grant"
                and record.target_origin == target_origin
                and record.expires_at > now
            )

    def valid_session(self, token: str, *, target_origin: str) -> bool:
        return bool(self.visitor_id_for_session(token, target_origin=target_origin))

    def visitor_id_for_session(
        self, token: str, *, target_origin: str
    ) -> str:
        now = time.time()
        with self._lock:
            self._purge(now)
            record = self._records.get(self._digest(token))
            if not (
                record
                and record.kind == "session"
                and record.target_origin == target_origin
                and record.expires_at > now
            ):
                return ""
            return record.visitor_id


def visitor_cookie(token: str, *, secure: bool = True) -> str:
    secure_flag = " Secure;" if secure else ""
    return (
        f"{VISITOR_COOKIE}={token}; Max-Age={VISITOR_SESSION_TTL_SECONDS};"
        f" HttpOnly; SameSite=Lax;{secure_flag} Path=/"
    )


def clear_visitor_cookie(*, secure: bool = True) -> str:
    """Expire the anonymous visitor capability after account login."""
    secure_flag = " Secure;" if secure else ""
    return (
        f"{VISITOR_COOKIE}=; Max-Age=0;"
        " Expires=Thu, 01 Jan 1970 00:00:00 GMT;"
        f" HttpOnly; SameSite=Lax;{secure_flag} Path=/"
    )


def client_access_cookie(token: str, *, secure: bool = True) -> str:
    secure_flag = " Secure;" if secure else ""
    return (
        f"{CLIENT_ACCESS_COOKIE}={token}; Max-Age={CLIENT_ACCESS_TTL_SECONDS};"
        f" HttpOnly; SameSite=Lax;{secure_flag} Path=/"
    )
