"""Shared errors and public-method policy for Profile app-server sessions."""

from __future__ import annotations


class AgentAppServerError(RuntimeError):
    """A Profile app-server session cannot be started or used."""

    def __init__(self, message: str, *, code: str = "agent_runtime_error") -> None:
        super().__init__(message)
        self.code = str(code or "agent_runtime_error")


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
