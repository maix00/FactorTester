"""Direct report entry for one server-owned entry-resolution event."""

from __future__ import annotations

import hashlib
from typing import Any


_TITLES = {
    "push": "进入要求入栈",
    "route": "进入要求分流",
    "wait": "等待进入要求",
    "resume": "恢复进入要求",
    "resolve": "完成进入要求",
    "abandon": "放弃进入要求",
}


def entry_resolution_operations(
    envelope: dict[str, Any] | None,
    *,
    parent_id: str,
    component_exists,
) -> list[dict[str, Any]]:
    if envelope is None:
        return []
    return [
        operation for item in envelope["events"]
        for operation in _event_operations(
            envelope, item, parent_id=parent_id,
            component_exists=component_exists,
        )
    ]


def _event_operations(
    envelope: dict[str, Any],
    item: dict[str, Any],
    *,
    parent_id: str,
    component_exists,
) -> list[dict[str, Any]]:
    trace_ref = str(envelope["trace_ref"])
    report_item = item["report_item"]
    kind = str(report_item["kind"]).removeprefix("entry_resolution.")
    ordinal = int(item["ordinal"])
    attempt = str(report_item.get("entry_attempt_id") or "")
    suffix = hashlib.sha256(
        f"{trace_ref}\x1f{ordinal}\x1f{kind}\x1f{attempt}".encode()
    ).hexdigest()[:48]
    component_id = "entry-resolution-" + suffix
    if component_exists(component_id):
        return []
    bindings = [{
        "binding_id": "entry-resolution-trace-" + suffix,
        "kind": "checkpoint", "target_ref": trace_ref,
        "label": "进入要求处理步骤",
        "data": {"role": "entry_resolution_event", "event": kind},
    }]
    target = str(report_item.get("target_node") or "")
    if target:
        bindings.append({
            "binding_id": "entry-resolution-node-" + suffix,
            "kind": "graph_reference", "target_ref": f"node:{target}",
            "label": "目标节点",
            "data": {"role": "entry_resolution_target"},
        })
    if attempt:
        bindings.append({
            "binding_id": "entry-resolution-attempt-" + suffix,
            "kind": "graph_reference",
            "target_ref": f"entry-attempt:{attempt}",
            "label": "进入处理尝试",
            "data": {"role": "entry_resolution_attempt"},
        })
    return [{
        "op": "add", "component_id": component_id, "kind": "entry",
        "title": _TITLES[kind], "parent_id": parent_id,
        "body": (
            f"{_TITLES[kind]}，处理栈深度由 "
            f"{envelope['depth_before']} 变为 {envelope['depth_after']}"
        ),
        "content": {
            "schema_version": 1, "event": kind, "ordinal": ordinal,
            "trace_ref": trace_ref,
            "stack_hash_before": envelope["stack_hash_before"],
            "stack_hash_after": envelope["stack_hash_after"],
            "depth_before": envelope["depth_before"],
            "depth_after": envelope["depth_after"],
            "entry_attempt_ref": (
                f"entry-attempt:{attempt}" if attempt else ""
            ),
            "target_node_ref": f"node:{target}" if target else "",
        },
        "display_kind": "", "bindings": bindings,
    }]
