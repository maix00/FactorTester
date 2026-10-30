"""Short-lived PKCE transactions for the Manager browser session."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import secrets
import threading
import time
from urllib.parse import urlsplit

from server.identity.keycloak import OIDCClient, oidc_authorization_url, oidc_logout_url
from server.identity.user_session import keycloak_session, oidc_settings


_FLOW_TTL_SECONDS = 600
_FLOW_LIMIT = 512
_FLOWS_LOCK = threading.Lock()


@dataclass(frozen=True)
class OIDCFlow:
    verifier: str
    redirect_uri: str
    next_path: str
    expires_at: float
    device_ticket: str = ""


_FLOWS: OrderedDict[str, OIDCFlow] = OrderedDict()


def _safe_next_path(value: str) -> str:
    candidate = str(value or "/app").strip()
    parsed = urlsplit(candidate)
    if (not candidate.startswith("/") or candidate.startswith("//")
            or parsed.scheme or parsed.netloc
            or parsed.path in {"/login", "/auth/oidc/start", "/auth/oidc/callback"}):
        return "/app"
    return candidate or "/app"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    import base64
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _prune_flows(now: float) -> None:
    expired = [key for key, value in _FLOWS.items() if value.expires_at <= now]
    for key in expired:
        _FLOWS.pop(key, None)
    while len(_FLOWS) >= _FLOW_LIMIT:
        _FLOWS.popitem(last=False)


def start_login(
    *, redirect_uri: str, next_path: str = "/app", device_ticket: str = "",
) -> tuple[str, str]:
    """Create one bounded PKCE transaction and its Keycloak authorization URL."""
    settings = oidc_settings()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    flow = OIDCFlow(
        verifier=verifier,
        redirect_uri=str(redirect_uri),
        next_path=_safe_next_path(next_path),
        expires_at=time.monotonic() + _FLOW_TTL_SECONDS,
        device_ticket=str(device_ticket or "").strip(),
    )
    with _FLOWS_LOCK:
        _prune_flows(time.monotonic())
        _FLOWS[state] = flow
    url = oidc_authorization_url(
        base_url=settings["base_url"], realm=settings["realm"],
        client_id=settings["client_id"], redirect_uri=str(redirect_uri),
        state=state, code_challenge=_challenge(verifier),
    )
    return state, url


def finish_login(
    *, state: str, code: str,
) -> tuple[str, dict[str, object], str, str]:
    """Exchange a one-use PKCE state and require a live Keycloak session."""
    now = time.monotonic()
    with _FLOWS_LOCK:
        _prune_flows(now)
        flow = _FLOWS.pop(str(state or ""), None)
    if flow is None or not code:
        raise ValueError("invalid or expired OIDC transaction")
    settings = oidc_settings()
    tokens = OIDCClient(
        settings.get("backchannel_base_url") or settings["base_url"],
        settings["realm"], settings["client_id"],
        client_secret=settings["client_secret"],
    ).exchange_code(code, flow.redirect_uri, code_verifier=flow.verifier)
    access_token = str(tokens.get("access_token") or "")
    session = keycloak_session(access_token)
    if not access_token or not session:
        raise PermissionError("Keycloak did not return a verifiable Manager session")
    return access_token, session, flow.next_path, flow.device_ticket


def logout_url(*, post_logout_redirect_uri: str) -> str:
    settings = oidc_settings()
    return oidc_logout_url(
        base_url=settings["base_url"], realm=settings["realm"],
        client_id=settings["client_id"],
        post_logout_redirect_uri=post_logout_redirect_uri,
    )


def admin_console_url() -> str:
    """Return the realm's Keycloak Admin Console without local credentials."""
    settings = oidc_settings()
    return f"/identity/admin/{settings['realm']}/console/"
