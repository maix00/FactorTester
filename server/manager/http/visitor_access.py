"""Origin-scoped visitor redirect and session state for public Manager entry."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


VISITOR_COOKIE = "ft-manager-visitor"
CLIENT_ACCESS_COOKIE = "ft-manager-client-access"
VISITOR_GRANT_TTL_SECONDS = 300
VISITOR_SESSION_TTL_SECONDS = 12 * 60 * 60
CLIENT_ACCESS_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class VisitorMode:
    """The single anonymous capability set exposed by the public entry."""

    principal: str = "__public_jobs__"
    max_server_jobs: int = 20
    can_download_artifacts: bool = False
    can_submit: bool = False


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


class VisitorAccessStore:
    """Hold short-lived grants and origin-bound visitor sessions in memory.

    Visitor mode is deliberately anonymous and non-authoritative.  Losing
    these records on a Manager restart only requires the user to click the
    explicitly configured ingress entry again; it never creates an account or
    changes PostgreSQL state.
    """

    def __init__(self) -> None:
        self._records: dict[str, _VisitorRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _purge(self, now: float) -> None:
        for digest, record in tuple(self._records.items()):
            if record.expires_at <= now:
                self._records.pop(digest, None)

    def _issue(self, *, kind: str, target_origin: str, ttl: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._purge(now)
            self._records[self._digest(token)] = _VisitorRecord(
                kind=kind,
                target_origin=target_origin,
                expires_at=now + ttl,
            )
        return token

    def issue_grant(self, target_origin: str) -> str:
        return self._issue(
            kind="grant",
            target_origin=target_origin,
            ttl=VISITOR_GRANT_TTL_SECONDS,
        )

    def issue_client_access(self, target_origin: str) -> str:
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
        )

    def issue_session(self, target_origin: str) -> str:
        """Create a visitor session after an explicit entry action."""
        return self._issue(
            kind="session",
            target_origin=target_origin,
            ttl=VISITOR_SESSION_TTL_SECONDS,
        )

    def valid_client_access(self, token: str, *, target_origin: str) -> bool:
        now = time.time()
        with self._lock:
            self._purge(now)
            record = self._records.get(self._digest(token))
            return bool(
                record
                and record.kind == "client-access"
                and record.target_origin == target_origin
                and record.expires_at > now
            )

    def redeem_grant(self, token: str, *, target_origin: str) -> str | None:
        now = time.time()
        with self._lock:
            self._purge(now)
            digest = self._digest(token)
            record = self._records.pop(digest, None)
            if (
                record is None
                or record.kind != "grant"
                or record.target_origin != target_origin
                or record.expires_at <= now
            ):
                return None
        return self._issue(
            kind="session",
            target_origin=target_origin,
            ttl=VISITOR_SESSION_TTL_SECONDS,
        )

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
        now = time.time()
        with self._lock:
            self._purge(now)
            record = self._records.get(self._digest(token))
            return bool(
                record
                and record.kind == "session"
                and record.target_origin == target_origin
                and record.expires_at > now
            )


def visitor_cookie(token: str, *, secure: bool = True) -> str:
    secure_flag = " Secure;" if secure else ""
    return (
        f"{VISITOR_COOKIE}={token}; Max-Age={VISITOR_SESSION_TTL_SECONDS};"
        f" HttpOnly; SameSite=Lax;{secure_flag} Path=/"
    )


def client_access_cookie(token: str, *, secure: bool = True) -> str:
    secure_flag = " Secure;" if secure else ""
    return (
        f"{CLIENT_ACCESS_COOKIE}={token}; Max-Age={CLIENT_ACCESS_TTL_SECONDS};"
        f" HttpOnly; SameSite=Lax;{secure_flag} Path=/"
    )
