from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SESSION = ".factortester-research-session.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ResearchSession:
    status: str = "research_ready"
    operator_mode: str = "client_only"
    admin_port: int = 7998
    factor_family: str = ""
    template: str = ""
    product_groups: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    factor_source: dict[str, Any] = field(default_factory=dict)
    hypotheses_tested: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSession":
        return cls(
            status=str(payload.get("status") or "research_ready"),
            operator_mode=str(payload.get("operator_mode") or "client_only"),
            admin_port=int(payload.get("admin_port") or 7998),
            factor_family=str(payload.get("factor_family") or ""),
            template=str(payload.get("template") or ""),
            product_groups=list(payload.get("product_groups") or []),
            plan=list(payload.get("plan") or []),
            events=list(payload.get("events") or []),
            gaps=list(payload.get("gaps") or []),
            factor_source=dict(payload.get("factor_source") or {}),
            hypotheses_tested=int(payload.get("hypotheses_tested") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "operator_mode": self.operator_mode,
            "admin_port": self.admin_port,
            "factor_family": self.factor_family,
            "template": self.template,
            "product_groups": self.product_groups,
            "plan": self.plan,
            "events": self.events,
            "gaps": self.gaps,
            "factor_source": self.factor_source,
            "hypotheses_tested": self.hypotheses_tested,
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
            json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_event(session: ResearchSession, event: str, **payload: Any) -> dict[str, Any]:
    row = {"time": utc_now(), "event": event, **payload}
    session.events.append(row)
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
