"""One-time title migration for obligation ledgers and report source trees."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .ledger import append_event, canonicalize_ledger
from .definitions import validate_definition_candidate
from tools.cli.release.report_link_kinds import report_link_kind_for_ref
from tools.cli.release.research_reporting.authoring.inline_links import (
    MARKDOWN_LINK_PATTERN,
    decode_typed_url,
    typed_markdown_link,
)


_LINK = re.compile(MARKDOWN_LINK_PATTERN)


def migrate_ledger_titles(
    ledger: dict[str, Any],
    *,
    obligation_titles: dict[str, str],
    requirement_titles: dict[str, str],
) -> dict[str, Any]:
    value = deepcopy(ledger)
    _migrate_obligations(
        value["current_projection"]["obligations"], obligation_titles,
    )
    _migrate_coverage(
        value["current_projection"]["requirement_coverage"],
        requirement_titles,
    )
    for event in value["history"]:
        _migrate_obligations(
            event.get("obligations_snapshot") or [], obligation_titles,
        )
        _migrate_coverage(
            event.get("coverage_snapshot") or [], requirement_titles,
        )
        for delta in event.get("obligation_delta") or []:
            body = delta.get("obligation")
            if isinstance(body, dict):
                _migrate_obligations([body], obligation_titles)
        for delta in event.get("server_obligation_delta") or []:
            body = delta.get("obligation")
            if isinstance(body, dict):
                _migrate_obligations([body], obligation_titles)
    value = canonicalize_ledger(value)
    if value == ledger:
        return value
    return append_event(
        value,
        event_type="title_migrated",
        payload={
            "title_map_hash": _title_map_hash(
                obligation_titles=obligation_titles,
                requirement_titles=requirement_titles,
            ),
            "obligation_title_count": len(obligation_titles),
            "requirement_title_count": len(requirement_titles),
        },
    )


def _title_map_hash(
    *,
    obligation_titles: dict[str, str],
    requirement_titles: dict[str, str],
) -> str:
    payload = json.dumps(
        {
            "obligations": obligation_titles,
            "requirements": requirement_titles,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def report_title_operations(
    snapshot: dict[str, Any],
    *,
    obligation_titles: dict[str, str],
    requirement_titles: dict[str, str],
    reference_rewrites: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    titles = {
        "obligation": {
            f"obligation:{key.removeprefix('obligation:')}": title
            for key, title in obligation_titles.items()
        },
        "entry_requirement": {
            f"requirement:{key.removeprefix('requirement:')}": title
            for key, title in requirement_titles.items()
        },
    }
    rewrites = reference_rewrites or {}
    bindings_by_component: dict[str, list[dict[str, Any]]] = {}
    for binding in snapshot["bindings"]:
        item = deepcopy(binding)
        component_id = str(item.pop("component_id"))
        bindings_by_component.setdefault(component_id, []).append(item)
    operations = []
    for component in snapshot["components"]:
        component_id = str(component["component_id"])
        original_bindings = bindings_by_component.get(component_id, [])
        bindings = [
            _migrate_binding(item, titles, rewrites)
            for item in original_bindings
        ]
        replacement = {
            "op": "replace",
            "component_id": component_id,
            "kind": str(component["kind"]),
            "title": _rewrite_value(component["title"], titles, rewrites),
            "body": _rewrite_value(component["body"], titles, rewrites),
            "content": _rewrite_value(component["content"], titles, rewrites),
            "display_kind": str(component["display_kind"]),
            "bindings": bindings,
        }
        if _retargets_bindings(original_bindings, bindings):
            replacement["_trusted_binding_retarget"] = True
        if _changed(component, bindings_by_component, replacement):
            operations.append(replacement)
    return operations


def _migrate_obligations(
    obligations: list[dict[str, Any]],
    titles: dict[str, str],
) -> None:
    for obligation in obligations:
        obligation_id = str(obligation.get("obligation_id") or "")
        title = str(
            titles.get(obligation_id)
            or titles.get(f"obligation:{obligation_id}")
            or ""
        ).strip()
        if not title:
            raise ValueError(
                f"obligation title migration is missing {obligation_id}"
            )
        existing = str(obligation.get("title_zh") or "")
        if existing:
            validate_definition_candidate(
                obligation,
                {"title_zh": title},
                obligation_id=obligation_id,
                source="title migration",
            )
        obligation["title_zh"] = title


def _migrate_coverage(
    coverage: list[dict[str, Any]],
    titles: dict[str, str],
) -> None:
    for row in coverage:
        requirement_id = str(row.get("requirement_id") or "")
        title = str(
            titles.get(requirement_id)
            or titles.get(f"requirement:{requirement_id}")
            or ""
        ).strip()
        if not title:
            raise ValueError(
                "requirement title migration is missing " + requirement_id
            )
        row["description"] = title


def _migrate_binding(
    binding: dict[str, Any],
    titles: dict[str, dict[str, str]],
    rewrites: dict[str, dict[str, str]],
) -> dict[str, Any]:
    value = deepcopy(binding)
    kind = str(value.get("kind") or "")
    target = str(value.get("target_ref") or "")
    rewrite = rewrites.get(f"{kind}|{target}")
    if rewrite is not None:
        value = _rewritten_binding(value, rewrite)
        kind = str(value["kind"])
        target = str(value["target_ref"])
    expected_prefix = {
        "obligation": "obligation:",
        "entry_requirement": "requirement:",
    }.get(kind)
    if expected_prefix and not target.startswith(expected_prefix):
        value["kind"] = report_link_kind_for_ref(target)
        data = deepcopy(value.get("data") or {})
        data["migrated_from_kind"] = kind
        value["data"] = data
        kind = value["kind"]
    title = (titles.get(kind) or {}).get(target)
    if kind in titles and not title:
        raise ValueError(
            f"title migration is missing {kind} binding {target}"
        )
    if title:
        value["label"] = title
        data = deepcopy(value.get("data") or {})
        data["title_zh"] = title
        value["data"] = data
    return value


def _rewrite_value(
    value: Any,
    titles: dict[str, dict[str, str]],
    rewrites: dict[str, dict[str, str]],
) -> Any:
    if isinstance(value, str):
        return _LINK.sub(
            lambda match: _rewrite_link(
                match.group(0), match.group(2), titles, rewrites,
            ),
            value,
        )
    if isinstance(value, list):
        return [_rewrite_value(item, titles, rewrites) for item in value]
    if isinstance(value, dict):
        return {
            key: _rewrite_value(item, titles, rewrites)
            for key, item in value.items()
        }
    return value


def _rewrite_link(
    original: str,
    target_url: str,
    titles: dict[str, dict[str, str]],
    rewrites: dict[str, dict[str, str]],
) -> str:
    if not target_url.startswith("factortester://"):
        return original
    kind, target = decode_typed_url(
        target_url, field="obligation title migration",
    )
    rewrite = rewrites.get(f"{kind}|{target}")
    if rewrite is not None:
        return typed_markdown_link(
            kind=str(rewrite["kind"]),
            target_ref=str(rewrite["target_ref"]),
            label=str(rewrite["title_zh"]),
        )
    title = (titles.get(kind) or {}).get(target)
    if kind in titles and not title:
        raise ValueError(
            f"title migration is missing {kind} reference {target}"
        )
    if not title:
        return original
    return typed_markdown_link(kind=kind, target_ref=target, label=title)


def _rewritten_binding(
    binding: dict[str, Any],
    rewrite: dict[str, str],
) -> dict[str, Any]:
    value = deepcopy(binding)
    old_kind = str(value.get("kind") or "")
    old_target = str(value.get("target_ref") or "")
    value["kind"] = str(rewrite["kind"])
    value["target_ref"] = str(rewrite["target_ref"])
    value["label"] = str(rewrite["title_zh"])
    data = deepcopy(value.get("data") or {})
    data.update({
        "migrated_from_kind": old_kind,
        "migrated_from_target_ref": old_target,
        "title_zh": value["label"],
    })
    value["data"] = data
    return value


def _retargets_bindings(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> bool:
    previous = {
        str(item["binding_id"]): (
            str(item.get("kind") or ""),
            str(item.get("target_ref") or ""),
        )
        for item in before
    }
    return any(
        previous.get(str(item["binding_id"])) != (
            str(item.get("kind") or ""),
            str(item.get("target_ref") or ""),
        )
        for item in after
    )


def _changed(
    component: dict[str, Any],
    bindings_by_component: dict[str, list[dict[str, Any]]],
    replacement: dict[str, Any],
) -> bool:
    component_id = str(component["component_id"])
    return any((
        component["title"] != replacement["title"],
        component["body"] != replacement["body"],
        component["content"] != replacement["content"],
        bindings_by_component.get(component_id, []) != replacement["bindings"],
    ))
