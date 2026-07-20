from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SESSION = ".factortester-research-session.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _looks_like_legacy_evidence(value: dict[str, Any]) -> bool:
    return (
        value.get("schema_version") == 1
        and isinstance(value.get("envelope_id"), str)
    )


def _agent_safe(value: Any) -> Any:
    if isinstance(value, dict):
        if _looks_like_legacy_evidence(value):
            return {"legacy_evidence_unavailable": True}
        return {
            str(key): _agent_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_agent_safe(item) for item in value]
    return value


@dataclass
class ResearchSession:
    status: str = "research_ready"
    operator_mode: str = "client_only"
    admin_port: int = 7998
    factor_families: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    configuration_file: str = ""
    plan: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    factor_source: dict[str, Any] = field(default_factory=dict)
    hypotheses_tested: int = 0
    skill_usage: list[dict[str, Any]] = field(default_factory=list)
    evidence_envelopes: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSession":
        return cls(
            status=str(payload.get("status") or "research_ready"),
            operator_mode=str(payload.get("operator_mode") or "client_only"),
            admin_port=int(payload.get("admin_port") or 7998),
            factor_families=[str(item) for item in payload.get("factor_families") or []],
            factors=[str(item) for item in payload.get("factors") or []],
            products=[str(item) for item in payload.get("products") or []],
            data_sources=[
                str(item) for item in payload.get("data_sources") or []
            ],
            configuration_file=str(payload.get("configuration_file") or ""),
            plan=list(payload.get("plan") or []),
            events=list(payload.get("events") or []),
            gaps=list(payload.get("gaps") or []),
            factor_source=dict(payload.get("factor_source") or {}),
            hypotheses_tested=int(payload.get("hypotheses_tested") or 0),
            skill_usage=list(payload.get("skill_usage") or []),
            evidence_envelopes=list(payload.get("evidence_envelopes") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the Agent-facing view without legacy evidence content."""
        payload = _agent_safe(self._base_dict())
        current_evidence = [
            _agent_safe(item)
            for item in self.evidence_envelopes
            if isinstance(item, dict)
            and item.get("schema_version") == 2
        ]
        payload["evidence_envelopes"] = current_evidence
        payload["legacy_evidence_unavailable_count"] = (
            len(self.evidence_envelopes) - len(current_evidence)
        )
        return payload

    def to_persisted_dict(self) -> dict[str, Any]:
        """Preserve historical records without exposing them to Agents."""
        payload = self._base_dict()
        payload["evidence_envelopes"] = self.evidence_envelopes
        return payload

    def _base_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "operator_mode": self.operator_mode,
            "admin_port": self.admin_port,
            "factor_families": self.factor_families,
            "factors": self.factors,
            "products": self.products,
            "data_sources": self.data_sources,
            "configuration_file": self.configuration_file,
            "plan": self.plan,
            "events": self.events,
            "gaps": self.gaps,
            "factor_source": self.factor_source,
            "hypotheses_tested": self.hypotheses_tested,
            "skill_usage": self.skill_usage,
        }


def load_session(path: str | os.PathLike[str] = DEFAULT_SESSION) -> ResearchSession:
    file_path = Path(path)
    if not file_path.exists():
        return ResearchSession()
    with file_path.open("r", encoding="utf-8") as handle:
        return ResearchSession.from_dict(json.load(handle))


def save_session(session: ResearchSession, path: str | os.PathLike[str] = DEFAULT_SESSION) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    initial = "{}" if not file_path.exists() else None
    with file_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if initial is not None:
                handle.write(initial)
                handle.flush()
            handle.seek(0)
            handle.truncate()
            json.dump(
                session.to_persisted_dict(),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_event(session: ResearchSession, event: str, **payload: Any) -> dict[str, Any]:
    row = {"time": utc_now(), "event": event, **payload}
    session.events.append(row)
    return row


def _sha256_json(value: dict[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def record_skill_usage(
    session: ResearchSession,
    *,
    capability_description: str,
    descriptor_hash: str,
    skill_name: str,
    skill_description: str,
    provider: str,
    version: str,
    source_fingerprint: str,
    approval_ref: str,
    load_mode: str,
    matching_rationale: str,
    skill_document_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict[str, Any]:
    """Append a tamper-evident local-only Skill usage audit record."""
    text_fields = {
        "capability_description": capability_description,
        "skill_name": skill_name,
        "skill_description": skill_description,
        "provider": provider,
        "version": version,
        "source_fingerprint": source_fingerprint,
        "approval_ref": approval_ref,
        "matching_rationale": matching_rationale,
    }
    for field, value in text_fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Skill usage requires {field}")
    for field, value in (
        ("descriptor_hash", descriptor_hash),
        ("source_fingerprint", source_fingerprint),
    ):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"Skill usage {field} must be sha256")
    if load_mode not in {"loaded", "reused"}:
        raise ValueError("Skill usage load_mode must be loaded or reused")
    for field, value in (
        ("skill_document_tokens", skill_document_tokens),
        ("cache_read_tokens", cache_read_tokens),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Skill usage {field} must be non-negative")
    if load_mode == "reused" and skill_document_tokens:
        raise ValueError(
            "reused Skill must not report newly loaded document tokens"
        )
    previous_hash = (
        str(session.skill_usage[-1].get("record_hash") or "")
        if session.skill_usage else ""
    )
    row = {
        "usage_id": f"skill-use-{len(session.skill_usage) + 1}",
        "time": utc_now(),
        **text_fields,
        "descriptor_hash": descriptor_hash,
        "load_mode": load_mode,
        "skill_document_tokens": skill_document_tokens,
        "cache_read_tokens": cache_read_tokens,
        "previous_record_hash": previous_hash,
    }
    row["record_hash"] = _sha256_json(row)
    session.skill_usage.append(row)
    return row


def record_gap(session: ResearchSession, title: str, detail: str, *, command: list[str] | None = None) -> dict[str, Any]:
    gap_id = f"gap-{len(session.gaps) + 1}"
    row = {
        "id": gap_id,
        "time": utc_now(),
        "status": "open",
        "title": title,
        "detail": detail,
        "command": command or [],
    }
    session.gaps.append(row)
    session.status = "code_improvement_required"
    return row


def resolve_gap(session: ResearchSession, gap_id: str, note: str = "") -> dict[str, Any]:
    for gap in session.gaps:
        if gap.get("id") == gap_id:
            gap["status"] = "resolved"
            gap["resolved_at"] = utc_now()
            if note:
                gap["resolution"] = note
            if not any(item.get("status") == "open" for item in session.gaps):
                session.status = "research_ready"
            return gap
    raise KeyError(f"unknown gap id: {gap_id}")


def mark_factor_improvement_required(session: ResearchSession, reason: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "time": utc_now(),
        "event": "factor_improvement_required",
        "reason": reason,
        "evidence": evidence or {},
    }
    session.events.append(row)
    session.status = "factor_improvement_required"
    return row
