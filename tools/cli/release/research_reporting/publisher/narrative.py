"""Validation and canonicalization for local Chinese research narratives."""

from __future__ import annotations

import json
import math
from typing import Any

from .identity import (
    bounded_text,
    chinese_text,
    contains_chinese,
    reference,
    safe_id,
)
from ..report_items import report_fragment_hash, report_item_hash
from ..assets import canonical_asset_descriptor


MAX_NARRATIVE_BYTES = 64 * 1024
MAX_ITEMS = 16
MAX_REPORT_SECTIONS = 64
_NARRATIVE_FIELDS = {"schema_version", "language", "title", "sections"}
_NARRATIVE_FIELDS_V3 = _NARRATIVE_FIELDS | {
    "research_occurred_at", "time_basis", "time_source_refs",
}
_SECTION_FIELDS_V1 = {"section_id", "title", "body", "links"}
_SECTION_FIELDS_V2 = {"section_id", "title", "blocks", "links"}
_SECTION_FIELDS_V2_WITH_BODY = {
    "section_id", "title", "body", "blocks", "links",
}
_SECTION_SEMANTIC_FIELDS = {"chapter_ref", "section_role"}
_LINK_FIELDS = {"link_id", "kind", "target_ref"}
_LINK_FIELDS_WITH_LABEL = {"link_id", "kind", "target_ref", "label"}
_LINK_KINDS = {
    "checkpoint", "trial_plan", "obligation", "claim", "evidence",
    "job", "run", "delta", "profile_handoff", "report_section",
}
_RESULT_NODES = {
    "job_evidence_ready", "statistical_robustness", "result_audit",
    "ic", "factor_evaluation", "backtest", "robustness",
}
_RESULT_KINDS = {"ic", "factor_evaluation", "backtest", "robustness"}


def canonical_narrative(
    narrative: Any,
    carrier: dict[str, Any],
    *,
    local_reference_allowlist: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a bounded narrative whose links belong to one Carrier."""
    if not isinstance(narrative, dict):
        raise ValueError("local narrative fields are invalid")
    encoded = json.dumps(
        narrative, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_NARRATIVE_BYTES:
        raise ValueError(
            f"local narrative exceeds {MAX_NARRATIVE_BYTES} bytes"
        )
    schema_version = narrative.get("schema_version")
    expected_fields = (
        _NARRATIVE_FIELDS_V3 if schema_version == 3 else _NARRATIVE_FIELDS
    )
    if set(narrative) != expected_fields:
        raise ValueError("local narrative fields are invalid")
    if schema_version not in {1, 2, 3} or narrative["language"] != "zh-Hans":
        raise ValueError("local narrative language must be zh-Hans")
    timing = _timing(narrative, carrier) if schema_version == 3 else None
    expected_report_items = _expected_report_items(carrier)
    if expected_report_items and schema_version != 3:
        raise ValueError("report-enforced checkpoint requires narrative v3")
    title = chinese_text(narrative["title"], "narrative.title", maximum=256)
    sections = narrative["sections"]
    if (
        not isinstance(sections, list)
        or not sections
        or len(sections) > MAX_REPORT_SECTIONS
    ):
        raise ValueError("local narrative sections must be a bounded array")
    allowed_refs = _carrier_reference_allowlist(carrier)
    for item in local_reference_allowlist:
        reference(item, "narrative.local_reference_allowlist")
        allowed_refs.add(item)
    result = []
    seen_ids = set()
    declared_target_refs: set[str] = set()
    used_report_bindings: set[tuple[str, str]] = set()
    for item in sections:
        fields = set(item) if isinstance(item, dict) else set()
        base_section_fields = (
            (_SECTION_FIELDS_V2, _SECTION_FIELDS_V2_WITH_BODY)
            if schema_version in {2, 3} else (_SECTION_FIELDS_V1,)
        )
        expected_fields = tuple(
            candidate
            for base in base_section_fields
            for candidate in (base, base | _SECTION_SEMANTIC_FIELDS)
        )
        if fields not in expected_fields:
            raise ValueError("local narrative section fields are invalid")
        section_id = safe_id(item["section_id"], "narrative.section_id")
        if section_id in seen_ids:
            raise ValueError("local narrative section_id must be unique")
        seen_ids.add(section_id)
        links = item["links"]
        if not isinstance(links, list) or len(links) > MAX_ITEMS:
            raise ValueError("local narrative links must be a bounded array")
        projected_links = []
        link_ids = set()
        for link in links:
            if not isinstance(link, dict) or frozenset(link) not in {
                frozenset(_LINK_FIELDS), frozenset(_LINK_FIELDS_WITH_LABEL),
            }:
                raise ValueError("local narrative link fields are invalid")
            if link["kind"] not in _LINK_KINDS:
                raise ValueError("local narrative link kind is invalid")
            link_id = safe_id(link["link_id"], "narrative.link_id")
            if link_id in link_ids:
                raise ValueError("narrative.link_id must be unique")
            link_ids.add(link_id)
            reference(link["target_ref"], "narrative.target_ref")
            if link["target_ref"] not in allowed_refs:
                raise ValueError(
                    "narrative links must belong to the same checkpoint carrier"
                )
            declared_target_refs.add(link["target_ref"])
            projected = dict(link)
            if "label" in projected:
                projected["label"] = chinese_text(
                    projected["label"], "narrative.link.label", maximum=160,
                )
            projected_links.append(projected)
        section = {
            "section_id": section_id,
            "title": chinese_text(item["title"], "narrative.section.title"),
            "links": projected_links,
        }
        if _SECTION_SEMANTIC_FIELDS.issubset(fields):
            chapter_ref = reference(
                item["chapter_ref"], "narrative.section.chapter_ref"
            )
            if not chapter_ref.startswith("node:"):
                raise ValueError("section.chapter_ref must identify a node")
            section["chapter_ref"] = chapter_ref
            section["section_role"] = safe_id(
                item["section_role"], "narrative.section.section_role"
            )
        if schema_version in {2, 3}:
            if "body" in item:
                section["body"] = _zh_body(item["body"])
            section["blocks"] = _canonical_blocks(
                item["blocks"],
                declared_link_ids=link_ids,
                recorded_at=carrier["latest_transition"]["created_at"],
                expected_report_items=(
                    (expected_report_items or None)
                    if schema_version == 3
                    else None
                ),
                used_report_bindings=used_report_bindings,
            )
        else:
            section["body"] = _zh_body(item["body"])
        result.append(section)
    missing = _required_narrative_targets(carrier) - declared_target_refs
    if missing:
        raise ValueError(
            "narrative must link every checkpoint object: "
            + ", ".join(sorted(missing))
        )
    if expected_report_items and used_report_bindings != set(
        expected_report_items
    ):
        missing_bindings = sorted(
            set(expected_report_items) - used_report_bindings
        )
        raise ValueError(
            "narrative must cover every Graph report item: "
            + ", ".join(f"{a}@{b}" for a, b in missing_bindings)
        )
    if schema_version in {2, 3}:
        _validate_result_table_bindings(carrier, result)
    value = {
        "schema_version": schema_version,
        "language": "zh-Hans",
        "title": title,
        "sections": result,
    }
    if timing is not None:
        value.update(timing)
    return value


def _validate_result_table_bindings(
    carrier: dict[str, Any], sections: list[dict[str, Any]]
) -> None:
    """Require result refs to be reachable from a structured result table."""
    transition = carrier["latest_transition"]
    if not _is_result_checkpoint(carrier, transition):
        return
    result_targets = set(carrier["job_refs"] + carrier["run_refs"])
    result_targets.update(
        ref for ref in (
            carrier["evidence_refs"] + transition["evidence_refs"]
        ) if ref.startswith("evidence:")
    )
    if not result_targets:
        return
    links_by_id = {
        link["link_id"]: link
        for section in sections
        for link in section["links"]
    }
    table_link_ids = {
        link_id
        for section in sections
        for block in section.get("blocks", [])
        if block["kind"] == "table"
        for row in block["rows"]
        for link_id in row["link_ids"]
    }
    missing = sorted(
        target for target in result_targets
        if not any(
            link_id in table_link_ids
            and links_by_id.get(link_id, {}).get("target_ref") == target
            for link_id in links_by_id
        )
    )
    if missing:
        raise ValueError(
            "result table must bind every Job/run/result evidence ref: "
            + ", ".join(missing)
        )


def _is_result_checkpoint(
    carrier: dict[str, Any], transition: dict[str, Any]
) -> bool:
    if transition.get("edge_ref") == "graph-edge:__current_node_report__":
        return False
    nodes = {carrier["current_node"], transition["to_node"]}
    if nodes & _RESULT_NODES:
        return True
    return any(
        transition["edge_ref"].endswith(f"__{node}")
        for node in _RESULT_NODES
    )


def _canonical_blocks(
    value: Any, *, declared_link_ids: set[str],
    recorded_at: float,
    expected_report_items: dict[tuple[str, str], dict[str, str]] | None = None,
    used_report_bindings: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("narrative blocks must be a bounded array")
    blocks = []
    used_link_ids: set[str] = set()
    for block in value:
        if not isinstance(block, dict):
            raise ValueError("narrative block must be an object")
        report_binding = block.get("report_binding")
        report_timing = block.get("report_timing")
        if "report_binding" in block or "report_timing" in block:
            block = {
                key: item for key, item in block.items()
                if key not in {"report_binding", "report_timing"}
            }
        kind = block.get("kind")
        if kind == "math" and set(block) == {
            "kind", "latex", "fallback", "link_ids",
        }:
            refs = block["link_ids"]
            _validate_link_ids(
                refs, declared_link_ids, used_link_ids, "math",
            )
            projected = {
                "kind": kind,
                "latex": bounded_text(
                    block["latex"], "narrative.math.latex", 2000,
                ),
                "fallback": _zh_body(block["fallback"]),
                "link_ids": list(refs),
            }
            blocks.append(_bind_report_item(
                projected,
                report_binding=report_binding,
                report_timing=report_timing,
                recorded_at=recorded_at,
                expected=expected_report_items,
                used=used_report_bindings,
            ))
            continue
        if kind == "figure" and set(block) == {
            "kind", "asset", "link_ids",
        }:
            refs = block["link_ids"]
            _validate_link_ids(
                refs, declared_link_ids, used_link_ids, "figure",
            )
            blocks.append(_bind_report_item(
                {
                    "kind": kind,
                    "asset": canonical_asset_descriptor(block["asset"]),
                    "link_ids": list(refs),
                },
                report_binding=report_binding,
                report_timing=report_timing,
                recorded_at=recorded_at,
                expected=expected_report_items,
                used=used_report_bindings,
            ))
            continue
        if kind == "paragraph" and set(block) in (
            {"kind", "text"}, {"kind", "text", "link_ids"}
        ):
            projected = {"kind": kind, "text": _zh_body(block["text"])}
            if "link_ids" in block:
                refs = block["link_ids"]
                _validate_link_ids(
                    refs, declared_link_ids, used_link_ids, "paragraph",
                )
                projected["link_ids"] = list(refs)
            blocks.append(_bind_report_item(
                projected,
                report_binding=report_binding,
                report_timing=report_timing,
                recorded_at=recorded_at,
                expected=expected_report_items,
                used=used_report_bindings,
            ))
            continue
        if kind == "list" and set(block) == {"kind", "rows"}:
            rows = _canonical_rows(
                block["rows"], declared_link_ids=declared_link_ids,
                used_link_ids=used_link_ids, table_columns=None,
            )
            blocks.append(_bind_report_item(
                {"kind": kind, "rows": rows},
                report_binding=report_binding,
                report_timing=report_timing,
                recorded_at=recorded_at,
                expected=expected_report_items,
                used=used_report_bindings,
            ))
            continue
        if kind == "table" and set(block) in (
            {"kind", "columns", "rows"},
            {"kind", "columns", "rows", "result_kind"},
        ):
            columns = block["columns"]
            if not isinstance(columns, list) or not 1 <= len(columns) <= 12:
                raise ValueError("narrative table columns are invalid")
            canonical_columns = [
                chinese_text(item, "narrative.table.column", maximum=128)
                for item in columns
            ]
            rows = _canonical_rows(
                block["rows"], declared_link_ids=declared_link_ids,
                used_link_ids=used_link_ids,
                table_columns=len(canonical_columns),
            )
            projected = {
                "kind": kind, "columns": canonical_columns, "rows": rows,
            }
            if "result_kind" in block:
                result_kind = block["result_kind"]
                if result_kind not in _RESULT_KINDS:
                    raise ValueError("narrative table result_kind is invalid")
                projected["result_kind"] = result_kind
            blocks.append(_bind_report_item(
                projected,
                report_binding=report_binding,
                report_timing=report_timing,
                recorded_at=recorded_at,
                expected=expected_report_items,
                used=used_report_bindings,
            ))
            continue
        raise ValueError("narrative block fields are invalid")
    if used_link_ids != declared_link_ids:
        raise ValueError(
            "every declared section link must be bound to one list or table row"
        )
    return blocks


def _bind_report_item(
    content: dict[str, Any],
    *,
    report_binding: Any,
    report_timing: Any,
    recorded_at: float,
    expected: dict[tuple[str, str], dict[str, str]] | None,
    used: set[tuple[str, str]] | None,
) -> dict[str, Any]:
    if expected is None:
        if report_binding is not None or report_timing is not None:
            raise ValueError("report binding and timing require narrative v3")
        return content
    if not isinstance(report_binding, dict) or set(report_binding) != {
        "report_requirement_id", "subject_ref",
    }:
        raise ValueError("narrative v3 block needs one report_binding")
    key = (
        str(report_binding["report_requirement_id"]),
        str(report_binding["subject_ref"]),
    )
    expected_item = expected.get(key)
    if expected_item is None:
        raise ValueError("narrative report_binding is not in the Carrier")
    if used is None or key in used:
        raise ValueError("narrative report_binding must be unique")
    content_kind = {
        "paragraph": "sentence",
        "list": "list",
        "table": "table",
        "math": "figure",
        "figure": "figure",
    }[content["kind"]]
    if expected_item["content_kind"] != content_kind:
        raise ValueError("narrative report content kind does not match Carrier")
    item_hash = report_item_hash(
        report_requirement_id=key[0],
        subject_ref=key[1],
        content_kind=content_kind,
        content=content,
    )
    if expected_item["report_item_ref"] != f"report-item:sha256:{item_hash}":
        raise ValueError("narrative report item hash does not match Carrier")
    used.add(key)
    result = {
        **content,
        "report_binding": {
            "report_requirement_id": key[0],
            "subject_ref": key[1],
            "report_item_ref": expected_item["report_item_ref"],
        },
    }
    if report_timing is not None:
        result["report_timing"] = _report_timing(
            report_timing,
            recorded_at=recorded_at,
        )
    return result


def _expected_report_items(
    carrier: dict[str, Any],
) -> dict[tuple[str, str], dict[str, str]]:
    transition = carrier["latest_transition"]
    items = transition.get("report_items") or []
    expected = {
        (str(item["report_requirement_id"]), str(item["subject_ref"])): item
        for item in items
    }
    if len(expected) != len(items):
        raise ValueError("Carrier report item bindings must be unique")
    if expected:
        records = [
            {
                "report_requirement_id": key[0],
                "subject_ref": key[1],
                "content_kind": item["content_kind"],
                "item_hash": item["report_item_ref"].removeprefix(
                    "report-item:sha256:"
                ),
            }
            for key, item in expected.items()
        ]
        actual = f"report-fragment:sha256:{report_fragment_hash(records)}"
        if transition.get("report_fragment_ref") != actual:
            raise ValueError("Carrier report fragment hash is invalid")
    return expected


def _timing(
    narrative: dict[str, Any], carrier: dict[str, Any]
) -> dict[str, Any]:
    occurred_at = narrative.get("research_occurred_at")
    recorded_at = carrier["latest_transition"]["created_at"]
    time_basis = narrative.get("time_basis")
    refs = narrative.get("time_source_refs")
    timing = _canonical_timing(
        occurred_at=occurred_at,
        time_basis=time_basis,
        refs=refs,
        recorded_at=recorded_at,
        field="research",
    )
    return {
        "research_occurred_at": timing["occurred_at"],
        "time_basis": timing["time_basis"],
        "time_source_refs": timing["time_source_refs"],
    }


def _report_timing(value: Any, *, recorded_at: float) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "occurred_at", "time_basis", "time_source_refs",
    }:
        raise ValueError("report_timing fields are invalid")
    return _canonical_timing(
        occurred_at=value["occurred_at"],
        time_basis=value["time_basis"],
        refs=value["time_source_refs"],
        recorded_at=recorded_at,
        field="report",
    )


def _canonical_timing(
    *, occurred_at: Any, time_basis: Any, refs: Any,
    recorded_at: float, field: str,
) -> dict[str, Any]:
    if (
        type(occurred_at) not in {int, float}
        or not math.isfinite(occurred_at)
        or occurred_at < 0
        or occurred_at > recorded_at
    ):
        raise ValueError(
            f"{field} occurred_at must be finite, non-negative, and not later "
            "than the trusted trace"
        )
    if time_basis not in {"transition", "historical_backfill"}:
        raise ValueError(f"{field} time_basis is invalid")
    if (
        not isinstance(refs, list) or len(refs) > MAX_ITEMS
        or not all(isinstance(item, str) and item for item in refs)
    ):
        raise ValueError(
            f"{field} time_source_refs must be a bounded reference array"
        )
    for item in refs:
        reference(item, f"narrative.{field}.time_source_ref")
    refs = sorted(set(refs))
    if time_basis == "transition" and occurred_at != recorded_at:
        raise ValueError(
            f"{field} transition time must equal the trusted trace"
        )
    if time_basis == "historical_backfill" and not refs:
        raise ValueError(
            f"{field} historical_backfill requires time_source_refs"
        )
    return {
        "occurred_at": float(occurred_at),
        "time_basis": time_basis,
        "time_source_refs": refs,
    }


def _validate_link_ids(
    refs: Any,
    declared_link_ids: set[str],
    used_link_ids: set[str],
    owner: str,
    *,
    allow_empty: bool = False,
) -> None:
    if (
        not isinstance(refs, list)
        or (not refs and not allow_empty)
        or len(refs) > MAX_ITEMS
    ):
        raise ValueError(f"narrative {owner} link_ids are invalid")
    for link_id in refs:
        safe_id(link_id, f"narrative.{owner}.link_id")
        if link_id not in declared_link_ids:
            raise ValueError(
                f"{owner} chip must reference a declared section link"
            )
        used_link_ids.add(link_id)


def _canonical_rows(
    value: Any,
    *,
    declared_link_ids: set[str],
    used_link_ids: set[str],
    table_columns: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise ValueError("narrative block rows must be a bounded array")
    rows = []
    for item in value:
        expected = (
            {"cells", "link_ids"}
            if table_columns is not None else {"text", "link_ids"}
        )
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("narrative row fields are invalid")
        link_ids = item["link_ids"]
        _validate_link_ids(
            link_ids,
            declared_link_ids,
            used_link_ids,
            "row",
            allow_empty=True,
        )
        if table_columns is None:
            rows.append({
                "text": _zh_body(item["text"]),
                "link_ids": list(link_ids),
            })
            continue
        cells = item["cells"]
        if not isinstance(cells, list) or len(cells) != table_columns:
            raise ValueError("narrative table row width is invalid")
        rows.append({
            "cells": [
                bounded_text(cell, "narrative.table.cell", maximum=512)
                for cell in cells
            ],
            "link_ids": list(link_ids),
        })
    return rows


def _carrier_reference_allowlist(carrier: dict[str, Any]) -> set[str]:
    transition = carrier["latest_transition"]
    values = {
        carrier["checkpoint_ref"], carrier["research_cycle_ref"],
        transition["step_ref"], transition["edge_ref"],
        *carrier["evidence_refs"], *carrier["job_refs"], *carrier["run_refs"],
        *transition["evidence_refs"], *transition["trial_plan_refs"],
        *transition["obligation_refs"], *transition["claim_refs"],
        *transition["job_refs"], *transition["run_refs"],
        *transition["delta_refs"],
        *(item["claim_ref"] for item in carrier["claims"]),
        *(item["obligation_ref"] for item in carrier["open_obligations"]),
    }
    values.update(
        f"obligation:{item['obligation_id']}"
        for item in transition["obligation_changes"]
    )
    values.update(
        f"claim:{item['claim_id']}" for item in transition["claim_changes"]
    )
    return values


def _required_narrative_targets(carrier: dict[str, Any]) -> set[str]:
    """Return checkpoint objects that must remain inspectable from prose."""
    transition = carrier["latest_transition"]
    return set(
        transition["evidence_refs"]
        + transition["trial_plan_refs"]
        + transition["obligation_refs"]
        + transition["claim_refs"]
        + transition["job_refs"]
        + transition["run_refs"]
        + transition["delta_refs"]
        + [
            f"obligation:{item['obligation_id']}"
            for item in transition["obligation_changes"]
        ]
        + [
            f"claim:{item['claim_id']}"
            for item in transition["claim_changes"]
        ]
    )


def _zh_body(value: Any) -> str:
    text = bounded_text(value, "narrative.section.body", maximum=4000)
    in_code = False
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not line or in_code:
            continue
        if not contains_chinese(line):
            raise ValueError(
                "narrative.section.body lines must contain Chinese prose"
            )
    return text
