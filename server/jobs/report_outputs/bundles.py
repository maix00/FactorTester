"""Group physical renditions under one logical output and receipt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import GeneratedReport


@dataclass(frozen=True)
class ReportBundle:
    name: str
    reports: tuple[GeneratedReport, ...]
    receipt: dict

    @property
    def receipt_name(self) -> str:
        return f"{self.name}_receipt"


def bundle_reports(reports: Iterable[GeneratedReport]) -> list[ReportBundle]:
    """Preserve builder order while enforcing one receipt per logical output."""
    grouped: dict[str, list[GeneratedReport]] = {}
    receipts: dict[str, dict] = {}
    for report in reports:
        name = str(report.receipt.get("artifact_kind") or "").strip()
        if not name:
            raise ValueError(f"report {report.name!r} has no artifact_kind")
        previous = receipts.setdefault(name, report.receipt)
        if previous != report.receipt:
            raise ValueError(f"logical output {name!r} emitted inconsistent receipts")
        grouped.setdefault(name, []).append(report)
    return [
        ReportBundle(name=name, reports=tuple(grouped[name]), receipt=receipts[name])
        for name in grouped
    ]
