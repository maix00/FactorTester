"""Stable node identity and authentication value objects."""

from __future__ import annotations

from dataclasses import dataclass


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

