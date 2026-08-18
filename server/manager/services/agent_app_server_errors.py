"""Shared errors and public-method policy for Profile app-server sessions."""

from __future__ import annotations


class AgentAppServerError(RuntimeError):
    """A Profile app-server session cannot be started or used."""


PUBLIC_RPC_METHODS = frozenset({
    "model/list",
    "thread/list",
    "thread/read",
    "thread/start",
    "thread/resume",
    "turn/start",
    "turn/interrupt",
    "turn/steer",
})
