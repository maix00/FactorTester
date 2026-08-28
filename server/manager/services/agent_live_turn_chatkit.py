"""Project the in-memory active Agent turn into a ChatKit item page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from server.manager.services.provider_thread_chatkit import provider_item


def _text(value: object) -> str:
    return str(value or "")


def active_turn_items(
    events: Sequence[Mapping[str, Any]],
    conversation_id: str,
    provider_thread_id: str,
) -> list[dict[str, Any]]:
    """Return the latest visible form of every active-turn item."""
    projected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    assistant_text: dict[str, str] = {}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        params_value = payload.get("params")
        params = params_value if isinstance(params_value, Mapping) else {}
        thread_id = _text(
            params.get("threadId") or params.get("thread_id")
        ).strip()
        if thread_id != provider_thread_id:
            continue
        item = params.get("item")
        if isinstance(item, Mapping):
            value = provider_item(item, conversation_id)
            if value is not None:
                identifier = _text(value.get("id"))
                if identifier not in projected:
                    order.append(identifier)
                projected[identifier] = value
        method = _text(payload.get("method") or payload.get("type")).strip()
        if method != "item/agentMessage/delta":
            continue
        identifier = _text(
            params.get("itemId") or params.get("item_id")
            or "active-agent-message"
        ).strip()
        delta = _text(params.get("delta"))
        if not delta:
            continue
        assistant_text[identifier] = assistant_text.get(identifier, "") + delta
        synthetic = provider_item({
            "id": identifier,
            "type": "agentMessage",
            "text": assistant_text[identifier],
            "phase": _text(params.get("phase") or "commentary"),
            "status": "running",
        }, conversation_id)
        if synthetic is not None:
            if identifier not in projected:
                order.append(identifier)
            projected[identifier] = synthetic
    return [projected[identifier] for identifier in order]


def merge_active_turn(
    page: Mapping[str, Any],
    live_items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge active items into a newest-first Provider page by stable id."""
    result = dict(page)
    existing = [
        dict(item) for item in page.get("items", [])
        if isinstance(item, Mapping)
    ]
    by_id = {_text(item.get("id")): item for item in live_items}
    existing_ids = {_text(item.get("id")) for item in existing}
    additions = [
        dict(item) for item in live_items
        if _text(item.get("id")) not in existing_ids
    ]
    replaced = [
        dict(by_id.get(_text(item.get("id")), item)) for item in existing
    ]
    # conversation-items pages are newest-first. The browser adapter turns
    # them back into chronological order before handing them to ChatKit.
    result["items"] = list(reversed(additions)) + replaced
    return result


__all__ = ["active_turn_items", "merge_active_turn"]
