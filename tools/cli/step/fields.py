"""Lossless field lookup over one serialized step event."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def field_occurrences(data: Mapping[str, Any], qualified_field: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for section in ("inputs", "outputs", "output_changes", "ledger_changes"):
        for record in data.get(section) or []:
            if isinstance(record, Mapping) and record.get("field") == qualified_field:
                found.append({"section": section, "record": dict(record)})
    dmtm = data.get("dmtm")
    if isinstance(dmtm, Mapping):
        sections = (
            "accounting_inputs", "market_rule_inputs", "cash_changes",
            "position_changes", "margin_changes",
        )
        for section in sections:
            for record in dmtm.get(section) or []:
                if isinstance(record, Mapping) and record.get("field") == qualified_field:
                    found.append({"section": f"dmtm.{section}", "record": dict(record)})
    return found
