"""Request-local verified identity for non-Flask Manager domain services.

This is ephemeral context, not a session store. Only the HTTP adapter which
has verified the exact access token may bind it; each HTTP request resets it.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_identity = ContextVar("tr_verified_manager_identity", default=None)


@contextmanager
def identity_request():
    marker = _identity.set(None)
    try:
        yield
    finally:
        _identity.reset(marker)


def bind_verified_identity(token: str, session: dict | None) -> None:
    if not token or not session or not all(session.get(key) for key in (
        "keycloak_subject", "keycloak_issuer", "username",
    )):
        _identity.set(None)
        return
    _identity.set((token, dict(session)))


def current_verified_identity():
    value = _identity.get()
    return (value[0], dict(value[1])) if value else None
