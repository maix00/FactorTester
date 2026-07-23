"""Validation and canonicalization for local Chinese research narratives."""

from __future__ import annotations

import json
from typing import Any

from .identity import (
    bounded_text,
    chinese_text,
    contains_chinese,
    reference,
    safe_id,
)


MAX_NARRATIVE_BYTES = 64 * 1024
MAX_ITEMS = 16
_NARRATIVE_FIELDS = {"schema_version", "language", "title", "sections"}
_SECTION_FIELDS_V1 = {"section_id", "title", "body", "links"}
_SECTION_FIELDS_V2 = {"section_id", "title", "blocks", "links"}
_SECTION_FIELDS_V2_WITH_BODY = {
    "section_id", "title", "body", "blocks", "links",
}
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
) -> dict[str, Any]:
    """Return a bounded narrative whose links belong to one Carrier."""
    if not isinstance(narrative, dict) or set(narrative) != _NARRATIVE_FIELDS:
        raise ValueError("local narrative fields are invalid")
    encoded = json.dumps(
        narrative, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_NARRATIVE_BYTES:
        raise ValueError(
            f"local narrative exceeds {MAX_NARRATIVE_BYTES} bytes"
        )
    schema_version = narrative["schema_version"]
    if schema_version not in {1, 2} or narrative["language"] != "zh-Hans":
        raise ValueError("local narrative language must be zh-Hans")
    title = chinese_text(narrative["title"], "narrative.title", maximum=256)
    sections = narrative["sections"]
    if not isinstance(sections, list) or not sections or len(sections) > 8:
        raise ValueError("local narrative sections must be a bounded array")
    allowed_refs = _carrier_reference_allowlist(carrier)
    result = []
    seen_ids = set()
    declared_target_refs: set[str] = set()
    for item in sections:
        fields = set(item) if isinstance(item, dict) else set()
        expected_fields = (
            (_SECTION_FIELDS_V2, _SECTION_FIELDS_V2_WITH_BODY)
            if schema_version == 2 else (_SECTION_FIELDS_V1,)
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
        if schema_version == 2:
            if "body" in item:
                section["body"] = _zh_body(item["body"])
            section["blocks"] = _canonical_blocks(
                item["blocks"], declared_link_ids=link_ids,
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
    if schema_version == 2:
        _validate_result_table_bindings(carrier, result)
    return {
        "schema_version": schema_version,
        "language": "zh-Hans",
        "title": title,
        "sections": result,
    }


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
    nodes = {carrier["current_node"], transition["to_node"]}
    if nodes & _RESULT_NODES:
        return True
    return any(
        transition["edge_ref"].endswith(f"__{node}")
        for node in _RESULT_NODES
    )


def _canonical_blocks(
    value: Any, *, declared_link_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("narrative blocks must be a bounded array")
    blocks = []
    used_link_ids: set[str] = set()
    for block in value:
        if not isinstance(block, dict):
            raise ValueError("narrative block must be an object")
        kind = block.get("kind")
        if kind == "math" and set(block) == {
            "kind", "latex", "fallback", "link_ids",
        }:
            refs = block["link_ids"]
            _validate_link_ids(
                refs, declared_link_ids, used_link_ids, "math",
            )
            blocks.append({
                "kind": kind,
                "latex": bounded_text(
                    block["latex"], "narrative.math.latex", 2000,
                ),
                "fallback": _zh_body(block["fallback"]),
                "link_ids": list(refs),
            })
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
            blocks.append(projected)
            continue
        if kind == "list" and set(block) == {"kind", "rows"}:
            rows = _canonical_rows(
                block["rows"], declared_link_ids=declared_link_ids,
                used_link_ids=used_link_ids, table_columns=None,
            )
            blocks.append({"kind": kind, "rows": rows})
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
            blocks.append(projected)
            continue
        raise ValueError("narrative block fields are invalid")
    if used_link_ids != declared_link_ids:
        raise ValueError(
            "every declared section link must be bound to one list or table row"
        )
    return blocks


def _validate_link_ids(
    refs: Any,
    declared_link_ids: set[str],
    used_link_ids: set[str],
    owner: str,
) -> None:
    if not isinstance(refs, list) or not refs or len(refs) > MAX_ITEMS:
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
            link_ids, declared_link_ids, used_link_ids, "row",
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
