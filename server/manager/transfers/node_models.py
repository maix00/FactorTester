"""Stable node identity and authentication value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NodeIdentityRecord:
    node_id: str
    algorithm: str
    public_key: str
    fingerprint: str
    enrolled_at: float
    rotated_at: float | None
    revoked_at: float | None


@dataclass(frozen=True, slots=True)
class NodeChallenge:
    challenge_id: str
    challenge: str
    node_id: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class NewNodeCommand:
    idempotency_key: str
    transfer_id: str
    attempt_id: str
    command_type: str
    target_server_id: str
    payload: dict[str, Any]
    expires_at: float


@dataclass(frozen=True, slots=True)
class NodeCommandRecord:
    command_id: str
    idempotency_key: str
    transfer_id: str
    attempt_id: str
    command_type: str
    target_server_id: str
    sequence: int
    payload: dict[str, Any]
    payload_hash: str
    created_at: float
    expires_at: float
    acknowledged_at: float | None


@dataclass(frozen=True, slots=True)
class NodePresenceRecord:
    node_id: str
    connection_owner_manager_id: str
    connection_id: str
    data_endpoint: str
    reachable_from: frozenset[str]
    observed_at: float
    expires_at: float
    online: bool


@dataclass(frozen=True, slots=True)
class NodeConnection:
    node_id: str
    connection_id: str
