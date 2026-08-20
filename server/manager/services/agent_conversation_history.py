"""Normalize Provider thread history for the Manager conversation catalog."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping


def _normalized_type(value: object) -> str:
    return "".join(
        character for character in str(value or "").casefold()
        if character.isalnum()
    )


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "".join(_text(item) for item in value)
    if not isinstance(value, Mapping):
        return ""
    for key in ("text", "value", "output_text", "content", "parts", "message"):
        result = _text(value.get(key))
        if result:
            return result
    return ""


def _timestamp(value: object, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        return numeric / 1000.0 if numeric >= 100_000_000_000 else numeric
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return fallback


def _role(item: Mapping[str, object]) -> str:
    raw = _normalized_type(
        item.get("role") or item.get("type")
        or item.get("kind") or item.get("item_type")
    )
    if raw in {"user", "usermessage", "inputmessage"}:
        return "user"
    if raw in {"assistant", "assistantmessage", "agentmessage"}:
        return "assistant"
    return ""


def thread_messages(thread: Mapping[str, object]) -> list[dict[str, Any]]:
    """Return only textual user/assistant messages from a Provider thread.

    Tool calls, file operations, approvals, and other Provider-specific items
    are intentionally omitted.  The Manager catalog is a read-only transcript
    projection, not a second copy of the Provider's complete thread state.
    """
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return []
    fallback = _timestamp(
        thread.get("createdAt") or thread.get("created_at"),
        0.0,
    )
    if fallback <= 0:
        fallback = datetime.now(timezone.utc).timestamp()
    result: list[dict[str, Any]] = []
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, Mapping):
            continue
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        turn_time = _timestamp(
            turn.get("startedAt") or turn.get("started_at"), fallback,
        )
        for item_index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            role = _role(item)
            if not role:
                continue
            text = _text(
                item.get("content") if role == "user" else (
                    item.get("text") or item.get("content") or item.get("message")
                )
            ).strip()
            if not text:
                continue
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                digest = sha256(
                    f"{turn_index}\x1f{item_index}\x1f{role}\x1f{text}".encode(
                        "utf-8",
                    )
                ).hexdigest()[:32]
                item_id = f"history-{digest}"
            result.append({
                "item_id": item_id,
                "role": role,
                "text": text,
                "created_at": _timestamp(
                    item.get("createdAt") or item.get("created_at"),
                    turn_time,
                ),
            })
    return result


__all__ = ["thread_messages"]
