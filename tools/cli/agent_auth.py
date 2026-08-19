"""Read the short-lived FactorTester capability used by a server Profile Agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


AGENT_CAPABILITY_FILE_ENV = "FACTORTESTER_AGENT_CAPABILITY_FILE"
AGENT_CAPABILITY_KIND = "profile-agent"


@dataclass(frozen=True, slots=True)
class AgentCapability:
    """A Manager-issued capability for one server-side research identity."""

    base_url: str
    token: str
    profile_id: str
    claim_id: str


def capability_path() -> Path | None:
    value = str(os.environ.get(AGENT_CAPABILITY_FILE_ENV) or "").strip()
    return Path(value).expanduser() if value else None


def load_capability(path: str | Path | None = None) -> AgentCapability | None:
    """Load a capability without ever printing its bearer value."""
    target = Path(path).expanduser() if path else capability_path()
    if target is None or not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("FactorTester Agent capability file is invalid") from exc
    if not isinstance(payload, dict) or payload.get("kind") != AGENT_CAPABILITY_KIND:
        raise ValueError("FactorTester Agent capability kind is invalid")
    if payload.get("schema_version") != 1:
        raise ValueError("FactorTester Agent capability version is unsupported")
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    token = str(payload.get("token") or "").strip()
    profile_id = str(payload.get("profile_id") or "").strip()
    claim_id = str(payload.get("claim_id") or "").strip()
    if not base_url or not token or not profile_id or not claim_id:
        raise ValueError("FactorTester Agent capability is incomplete")
    return AgentCapability(
        base_url=base_url,
        token=token,
        profile_id=profile_id,
        claim_id=claim_id,
    )
