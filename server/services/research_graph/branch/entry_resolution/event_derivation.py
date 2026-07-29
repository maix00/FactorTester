"""Derive ordered entry lifecycle events from three stack snapshots."""

from __future__ import annotations

from typing import Any

from .stack_state import active_frame


def departure_events(
    before: dict[str, Any],
    departure: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    previous = active_frame(before) or {}
    current = active_frame(departure) or {}
    if not current:
        return []
    events = []
    if current.get("entry_attempt_id") != previous.get("entry_attempt_id"):
        if (
            previous
            and previous.get("target_node") == current.get("target_node")
        ):
            events.append(("abandon", previous))
        events.append(("push", current))
        if current.get("selected_route"):
            events.append(("route", current))
        status = str(current.get("status") or "")
        if status == "waiting":
            events.append(("wait", current))
        if status in {"resolved", "abandoned"}:
            events.append((
                "resolve" if status == "resolved" else "abandon",
                current,
            ))
        return events
    if (
        current.get("selected_route")
        and current.get("selected_route") != previous.get("selected_route")
    ):
        events.append(("route", current))
    status = str(current.get("status") or "")
    if status == "waiting" and status != previous.get("status"):
        events.append(("wait", current))
    if status in {"resolved", "abandoned"} and status != previous.get("status"):
        events.append((
            "resolve" if status == "resolved" else "abandon",
            current,
        ))
    return events


def arrival_events(
    departure: dict[str, Any],
    after: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    departure_ids = [
        str(item["entry_attempt_id"]) for item in departure["frames"]
    ]
    after_ids = [str(item["entry_attempt_id"]) for item in after["frames"]]
    new_frames = [
        item for item in after["frames"]
        if str(item["entry_attempt_id"]) not in departure_ids
    ]
    if new_frames:
        events = []
        after_ids_set = set(after_ids)
        for item in new_frames:
            replaced = next(
                (
                    old for old in reversed(departure["frames"])
                    if old["target_node"] == item["target_node"]
                    and str(old["entry_attempt_id"]) not in after_ids_set
                ),
                None,
            )
            if replaced is not None:
                events.append(("abandon", replaced))
            events.append(("push", item))
            if item.get("status") == "resolved":
                events.append(("resolve", item))
            elif item.get("status") == "abandoned":
                events.append(("abandon", item))
        return events
    if len(after_ids) < len(departure_ids) and after["frames"]:
        resumed = after["frames"][-1]
        if str(resumed["entry_attempt_id"]) in departure_ids:
            return [("resume", resumed)]
    return []
