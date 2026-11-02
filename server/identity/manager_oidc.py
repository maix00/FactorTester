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
    *, state: str, code: str, include_refresh: bool = False,
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
    if include_refresh:
        session = dict(session)
        session['_browser_refresh'] = {
            'refresh_token': str(tokens.get('refresh_token') or ''),
            'refresh_expires_in': int(tokens.get('refresh_expires_in') or 0),
        }
    return access_token, session, flow.next_path, flow.device_ticket


# Rotation deduplication only, not an identity/session authority. Every request
# still validates the resulting access token and server admission normally.
_REFRESH_LOCK = threading.Lock()
_REFRESH_FLIGHTS = tuple(threading.Lock() for _ in range(32))
_REFRESH_RESULTS: OrderedDict[bytes, tuple[float, dict]] = OrderedDict()


def refresh_browser_tokens(refresh_token: str) -> dict:
    if not refresh_token or len(refresh_token) > 32768:
        raise PermissionError('invalid refresh credential')
    key = hashlib.sha256(refresh_token.encode()).digest()
    with _REFRESH_FLIGHTS[key[0] % len(_REFRESH_FLIGHTS)]:
        with _REFRESH_LOCK:
            now = time.monotonic()
            for old in [k for k, (expiry, _) in _REFRESH_RESULTS.items() if expiry <= now]:
                del _REFRESH_RESULTS[old]
            cached = _REFRESH_RESULTS.get(key)
        if cached:
            return dict(cached[1])
        settings = oidc_settings()
        tokens = OIDCClient(
            settings.get('backchannel_base_url') or settings['base_url'],
            settings['realm'], settings['client_id'], client_secret=settings['client_secret'],
        ).refresh(refresh_token)
        access = str(tokens.get('access_token') or '')
        if not access or not keycloak_session(access, fail_on_unavailable=True):
            raise PermissionError('unverified refreshed identity')
        result = {
            'access_token': access,
            'refresh_token': str(tokens.get('refresh_token') or refresh_token),
            'refresh_expires_in': int(tokens.get('refresh_expires_in') or 0),
        }
        with _REFRESH_LOCK:
            while len(_REFRESH_RESULTS) >= 256:
                _REFRESH_RESULTS.popitem(last=False)
            _REFRESH_RESULTS[key] = (time.monotonic() + 10, result)
        return dict(result)


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
