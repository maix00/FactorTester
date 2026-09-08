"""Project persisted Provider thread items into native ChatKit items.

The Provider thread remains the sole authority for conversation content.  This
module is only a schema adapter: it does not persist, redact, truncate, or
render conversation data.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


def _kind(value: object) -> str:
    return "".join(character for character in str(value or "").casefold()
                   if character.isalnum())


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


def _iso_timestamp(value: object, fallback: datetime) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if numeric >= 100_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, timezone.utc).isoformat()
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except ValueError:
            pass
    return fallback.isoformat()


def _item_id(item: Mapping[str, object], turn_index: int, item_index: int) -> str:
    value = str(item.get("id") or "").strip()
    if value:
        return value
    digest = sha256(
        f"{turn_index}\x1f{item_index}\x1f{item!r}".encode()
    ).hexdigest()[:32]
    return f"provider-item-{digest}"


def _turn_id(turn: Mapping[str, object], turn_index: int) -> str:
    value = str(turn.get("id") or "").strip()
    if value:
        return value
    canonical = json.dumps(
        turn, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    )
    digest = sha256(
        f"{turn_index}\x1f{canonical}".encode()
    ).hexdigest()[:32]
    return f"provider-turn-{digest}"


def _encode_cursor(turn_id: str, order: str) -> str:
    payload = json.dumps(
        {"turn_id": turn_id, "order": order}, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: object, order: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        padding = "=" * (-len(raw) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(raw + padding).decode("utf-8")
        )
        result = str(payload.get("turn_id") or "").strip()
        cursor_order = str(payload.get("order") or "").strip().casefold()
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("conversation cursor is invalid") from exc
    if not result or cursor_order != order:
        raise ValueError("conversation cursor is invalid")
    return result


def _cursor_turn_id(
    turns: list[Mapping[str, object]],
    value: object,
    order: str,
) -> str:
    """Accept both our opaque page cursor and ChatKit's boundary item id."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return _decode_cursor(raw, order)
    except ValueError:
        matches: list[str] = []
        for turn_index, turn in enumerate(turns):
            items = turn.get("items")
            for item_index, item in enumerate(items if isinstance(items, list) else []):
                if isinstance(item, Mapping) and _item_id(
                    item, turn_index, item_index,
                ) == raw:
                    matches.append(_turn_id(turn, turn_index))
        if len(matches) == 1:
            return matches[0]
        raise


def _base(
    item: Mapping[str, object],
    *,
    conversation_id: str,
    item_id: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "thread_id": conversation_id,
        "created_at": created_at,
    }


def _workflow(
    base: Mapping[str, object],
    *,
    workflow_type: str = "custom",
    tasks: list[dict[str, Any]],
    expanded: bool = False,
) -> dict[str, Any]:
    summary_title = str(
        next((task.get("title") for task in tasks if task.get("title")),
             "Research process")
    )
    return {
        **base,
        "type": "workflow",
        "workflow": {
            "type": workflow_type,
            "tasks": tasks,
            "summary": {"title": summary_title},
            "expanded": expanded,
        },
    }


def _status(value: object) -> str:
    return "loading" if _kind(value) in {"inprogress", "pending", "running"} \
        else "complete"


def _progress_item(
    item: Mapping[str, object],
    base: Mapping[str, object],
    text: str,
) -> dict[str, Any]:
    title = str(item.get("title") or "执行进度").strip()
    return _workflow(base, tasks=[{
        "type": "custom",
        "title": title,
        "content": text if text.strip() != title else None,
        "status_indicator": _status(item.get("status")),
    }], expanded=True)


def _reasoning_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any] | None:
    # Provider ``summary`` is explicitly intended for UI display.  Raw
    # reasoning ``content`` is not projected because it may contain private
    # hidden chain-of-thought rather than a user-visible summary.
    summary = _text(item.get("summary")).strip()
    if not summary:
        return None
    return _workflow(base, workflow_type="reasoning", tasks=[{
        "type": "thought",
        "title": str(item.get("title") or "Reasoning summary"),
        "content": summary,
        "status_indicator": "complete",
    }])


def _command_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any]:
    command = _text(item.get("command")).strip() or "Command"
    output = _text(item.get("aggregatedOutput") or item.get("aggregated_output")).rstrip()
    exit_code = item.get("exitCode", item.get("exit_code"))
    content = f"```text\n{output}\n```" if output else None
    if exit_code not in (None, ""):
        suffix = f"Exit code: {exit_code}"
        content = f"{content}\n\n{suffix}" if content else suffix
    return _workflow(base, tasks=[{
        "type": "custom",
        "title": command,
        "content": content,
        "status_indicator": _status(item.get("status")),
    }])


def _file_change_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    changes = item.get("changes")
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, Mapping):
            continue
        path = str(change.get("path") or "changed file").strip()
        diff = _text(change.get("diff")).rstrip()
        tasks.append({
            "type": "custom",
            "title": f"{change.get('kind') or 'update'!s} · {path}",
            "content": f"```diff\n{diff}\n```" if diff else None,
            "status_indicator": _status(item.get("status")),
        })
    if not tasks:
        tasks.append({
            "type": "custom",
            "title": "File changes",
            "content": None,
            "status_indicator": _status(item.get("status")),
        })
    return _workflow(base, tasks=tasks)


def _tool_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any]:
    server = str(item.get("server") or item.get("serverName") or "").strip()
    tool = str(item.get("tool") or item.get("toolName") or item.get("name") or "tool").strip()
    name = f"{server}.{tool}" if server else tool
    arguments = item.get("arguments") or item.get("args") or {}
    return {
        **base,
        "type": "client_tool_call",
        "status": "pending" if _status(item.get("status")) == "loading" else "completed",
        "call_id": str(item.get("callId") or item.get("call_id") or base["id"]),
        "name": name,
        "arguments": dict(arguments) if isinstance(arguments, Mapping) else {"input": arguments},
        "output": item.get("result", item.get("output")),
    }


def _web_search_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any]:
    query = str(item.get("query") or "").strip()
    queries = item.get("queries")
    values = [str(value) for value in queries] if isinstance(queries, list) else []
    if query and query not in values:
        values.insert(0, query)
    return _workflow(base, tasks=[{
        "type": "web_search",
        "title": "Web search",
        "title_query": query or None,
        "queries": values,
        "sources": [],
        "status_indicator": _status(item.get("status")),
    }])


def _error_item(item: Mapping[str, object], base: Mapping[str, object]) -> dict[str, Any]:
    message = _text(item.get("message") or item.get("error") or item).strip()
    return _workflow(base, tasks=[{
        "type": "custom",
        "title": "Error",
        "content": message,
        "status_indicator": "complete",
    }])


def _turn_outcome_item(
    turn: Mapping[str, object],
    *,
    conversation_id: str,
    turn_index: int,
    created_at: str,
) -> dict[str, Any] | None:
    status = _kind(turn.get("status"))
    if status not in {"interrupted", "failed"}:
        return None
    interrupted = status == "interrupted"
    title = "Agent turn interrupted" if interrupted else "Agent turn failed"
    content = (
        "The Agent stopped before producing a final response. You can continue "
        "the conversation with a new message."
        if interrupted else
        _text(turn.get("error")).strip() or "The Agent turn failed."
    )
    return _workflow(
        _base(
            turn,
            conversation_id=conversation_id,
            item_id=f"{_turn_id(turn, turn_index)}-outcome",
            created_at=created_at,
        ),
        tasks=[{
            "type": "custom",
            "title": title,
            "content": content,
            "status_indicator": "complete",
        }],
    )


def _project_item(
    item: Mapping[str, object],
    base: Mapping[str, object],
    *,
    agent_phase: str = "",
) -> dict[str, Any] | None:
    kind = _kind(item.get("type") or item.get("kind"))
    if kind == "message":
        kind = {"user": "usermessage", "assistant": "assistantmessage"}.get(
            str(item.get("role") or "").lower(), kind,
        )
    if kind in {"usermessage", "inputmessage", "user"}:
        text = _text(item.get("content") or item.get("text")).strip()
        return ({
            **base,
            "type": "user_message",
            "content": [{"type": "input_text", "text": text}],
            "attachments": [],
            "quoted_text": None,
            "inference_options": {},
        } if text else None)
    if kind in {"agentmessage", "assistantmessage", "assistant"}:
        text = _text(item.get("text") or item.get("content")).strip()
        if text and agent_phase == "commentary":
            return _progress_item(item, base, text)
        return ({
            **base,
            "type": "assistant_message",
            "content": [{
                "type": "output_text", "text": text, "annotations": [],
            }],
        } if text else None)
    if kind == "reasoning":
        return _reasoning_item(item, base)
    if kind == "commandexecution":
        return _command_item(item, base)
    if kind == "filechange":
        return _file_change_item(item, base)
    if kind in {"mcptoolcall", "collabtoolcall", "toolcall"}:
        return _tool_item(item, base)
    if kind == "websearch":
        return _web_search_item(item, base)
    if kind in {"error", "erroritem"}:
        return _error_item(item, base)
    if kind in {"plan", "todolist"}:
        text = _text(item.get("text") or item.get("items")).strip()
        return _workflow(base, tasks=[{
            "type": "custom",
            "title": "Plan",
            "content": text or None,
            "status_indicator": _status(item.get("status")),
        }])
    return None


def provider_item(
    item: Mapping[str, object],
    conversation_id: str,
    *,
    created_at: object = None,
) -> dict[str, Any] | None:
    """Project one live or persisted Provider item into ChatKit schema."""
    identifier = str(conversation_id or "").strip()
    if not identifier:
        raise ValueError("conversation_id is required")
    now = datetime.now(timezone.utc)
    item_id = _item_id(item, 0, 0)
    timestamp = _iso_timestamp(
        item.get("createdAt") or item.get("created_at") or created_at, now,
    )
    phase = _kind(item.get("phase"))
    return _project_item(
        item,
        _base(
            item,
            conversation_id=identifier,
            item_id=item_id,
            created_at=timestamp,
        ),
        agent_phase="commentary" if phase == "commentary" else "final",
    )


def provider_thread_items(
    thread: Mapping[str, object],
    conversation_id: str,
    *,
    turn_offset: int = 0,
) -> list[dict[str, Any]]:
    """Return ChatKit-native items from one authoritative Provider thread."""
    identifier = str(conversation_id or "").strip()
    if not identifier:
        raise ValueError("conversation_id is required")
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return []
    fallback = datetime.now(timezone.utc)
    result: list[dict[str, Any]] = []
    for relative_turn_index, turn in enumerate(turns):
        if not isinstance(turn, Mapping):
            continue
        turn_index = turn_offset + relative_turn_index
        turn_time = _iso_timestamp(
            turn.get("startedAt") or turn.get("started_at"), fallback,
        )
        items = turn.get("items")
        turn_items = items if isinstance(items, list) else []
        agent_indexes = [
            index for index, item in enumerate(turn_items)
            if isinstance(item, Mapping)
            and _kind(item.get("type") or item.get("kind"))
            in {"agentmessage", "assistantmessage", "assistant"}
        ]
        last_agent_index = agent_indexes[-1] if agent_indexes else -1
        for item_index, item in enumerate(turn_items):
            if not isinstance(item, Mapping):
                continue
            item_id = _item_id(item, turn_index, item_index)
            created_at = _iso_timestamp(
                item.get("createdAt") or item.get("created_at"),
                datetime.fromisoformat(turn_time),
            )
            base = _base(
                item,
                conversation_id=identifier,
                item_id=item_id,
                created_at=created_at,
            )
            phase = _kind(item.get("phase"))
            if item_index in agent_indexes:
                # Current Codex marks these explicitly as commentary or
                # final_answer.  Legacy providers may omit phase; in that
                # case only the final Agent message closes the turn and prior
                # Agent narration remains in the process section.
                phase = "commentary" if phase == "commentary" else (
                    "finalanswer" if phase == "finalanswer"
                    or item_index == last_agent_index else "commentary"
                )
            projected = _project_item(
                item, base,
                agent_phase="commentary" if phase == "commentary" else "final",
            )
            if projected is not None:
                projected["turn_id"] = _turn_id(turn, turn_index)
                result.append(projected)
        outcome = _turn_outcome_item(
            turn,
            conversation_id=identifier,
            turn_index=turn_index,
            created_at=_iso_timestamp(
                turn.get("completedAt") or turn.get("completed_at"),
                datetime.fromisoformat(turn_time),
            ),
        )
        if outcome is not None:
            result.append(outcome)
    return result


def provider_thread_page(
    thread: Mapping[str, object],
    conversation_id: str,
    *,
    limit: int = 10,
    after: str = "",
    view: str = "timeline",
    order: str = "desc",
) -> dict[str, Any]:
    """Return one newest-first navigation page in chronological item order.

    Pagination is anchored to the first Provider turn in the current page.
    New turns can therefore arrive without shifting the cursor for older
    history.  A turn is never split because its messages and tool activity
    belong to one conversational unit.
    """
    raw_turns = thread.get("turns")
    turns = [turn for turn in raw_turns or [] if isinstance(turn, Mapping)] \
        if isinstance(raw_turns, list) else []
    size = max(1, min(int(limit), 50))
    selected_order = str(order or "desc").strip().casefold()
    if selected_order not in {"asc", "desc"}:
        raise ValueError("conversation item order is invalid")
    detail_cursor = str(after or "").startswith("detail:")
    anchor_turn_id = _cursor_turn_id(
        turns, str(after)[7:] if detail_cursor else after, selected_order,
    )
    anchor_index = None
    if anchor_turn_id:
        matches = [
            index for index, turn in enumerate(turns)
            if _turn_id(turn, index) == anchor_turn_id
        ]
        if not matches:
            raise ValueError("conversation cursor no longer matches this thread")
        anchor_index = matches[0]
    if detail_cursor:
        # Details address the recorded turn itself, including when it was the
        # newest turn at outline load time and newer turns have since arrived.
        if anchor_index is None:
            raise ValueError("conversation detail cursor is invalid")
        start, end, has_more = anchor_index, anchor_index + 1, False
    elif selected_order == "desc":
        end = anchor_index if anchor_index is not None else len(turns)
        start = max(0, end - size)
        has_more = start > 0
    else:
        start = anchor_index + 1 if anchor_index is not None else 0
        end = min(len(turns), start + size)
        has_more = end < len(turns)
    selected = turns[start:end]
    page_thread = {**thread, "turns": selected}
    if has_more and selected:
        cursor_index = start if selected_order == "desc" else end - 1
        cursor = _encode_cursor(
            _turn_id(turns[cursor_index], cursor_index), selected_order,
        )
    else:
        cursor = None
    projected = provider_thread_items(
        page_thread, conversation_id, turn_offset=start,
    )
    selected_view = str(view or "timeline").strip().casefold()
    if selected_view not in {"timeline", "outline"}:
        raise ValueError("conversation item view is invalid")
    if selected_view == "outline":
        # Preserve stable item/turn identities while deferring potentially large
        # command output. The existing timeline view remains the detail source.
        turn_indexes = {_turn_id(turn, index): index for index, turn in enumerate(turns)}
        for item in projected:
            if item.get("type") not in {"workflow", "client_tool_call"}:
                continue
            index = turn_indexes.get(item.get("turn_id"), len(turns) - 1)
            item["detail_after"] = "detail:" + _encode_cursor(
                _turn_id(turns[index], index), "desc",
            )
            item["details_deferred"] = True
            if item.get("type") == "client_tool_call":
                item.pop("arguments", None)
                item.pop("output", None)
                continue
            item["workflow"] = {
                **item["workflow"],
                "tasks": [{key: task[key] for key in ("type", "title", "status_indicator")
                           if key in task} for task in item["workflow"].get("tasks", [])],
            }
    if selected_order == "desc":
        projected.reverse()
    return {
        "items": projected,
        "has_more": has_more,
        "after": cursor,
        "turn_count": len(selected),
        "view": selected_view,
        "order": selected_order,
    }


__all__ = ["provider_item", "provider_thread_items", "provider_thread_page"]
