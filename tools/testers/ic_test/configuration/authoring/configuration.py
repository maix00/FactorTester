"""Top-level IC authoring configuration accepted from clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .attachment import ICAnalysisAttachmentRequest
from .core import ICCoreTestRequest


@dataclass(frozen=True, slots=True)
class ICRunAuthoringConfiguration:
    core_tests: tuple[ICCoreTestRequest, ...]
    analyses: tuple[ICAnalysisAttachmentRequest, ...] = ()
    factor_subject_refs: tuple[str, ...] = ()
    output_requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.core_tests:
            raise ValueError("IC authoring configuration requires a core test")
        cores = {item.request_ref: item for item in self.core_tests}
        object.__setattr__(
            self, "core_tests", tuple(cores[key] for key in sorted(cores)),
        )
        object.__setattr__(
            self,
            "factor_subject_refs",
            tuple(sorted({str(item).strip() for item in self.factor_subject_refs})),
        )
        object.__setattr__(
            self,
            "output_requests",
            tuple(sorted({str(item).strip() for item in self.output_requests})),
        )
        if "" in self.factor_subject_refs or "" in self.output_requests:
            raise ValueError("authoring references must be non-empty")

    def to_dict(self, *, include_refs: bool = True) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "core_tests": [
                item.to_dict(include_ref=include_refs) for item in self.core_tests
            ],
            "analyses": [item.to_dict() for item in self.analyses],
            "factor_subject_refs": list(self.factor_subject_refs),
            "output_requests": list(self.output_requests),
        }

    @classmethod
    def from_dict(cls, value: Any) -> ICRunAuthoringConfiguration:
        if isinstance(value, dict) and value.get("schema_version") == 2:
            return _from_grouped_schema2(value)
        raw_cores, raw_analyses = _raw_items(value)
        return cls(
            tuple(ICCoreTestRequest.from_authoring_dict(item) for item in raw_cores),
            tuple(ICAnalysisAttachmentRequest.from_dict(item) for item in raw_analyses),
            tuple(value.get("factor_subject_refs") or ()),
            tuple(value.get("output_requests") or ()),
        )

    @classmethod
    def from_frozen_dict(cls, value: Any) -> ICRunAuthoringConfiguration:
        raw_cores, raw_analyses = _raw_items(value)
        return cls(
            tuple(ICCoreTestRequest.from_frozen_dict(item) for item in raw_cores),
            tuple(ICAnalysisAttachmentRequest.from_dict(item) for item in raw_analyses),
            tuple(value.get("factor_subject_refs") or ()),
            tuple(value.get("output_requests") or ()),
        )


def _from_grouped_schema2(value: dict[str, Any]) -> ICRunAuthoringConfiguration:
    groups = value.get("configuration_groups")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("Slice 1 requires exactly one configuration group")
    seen: set[str] = set()
    cores: list[ICCoreTestRequest] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("configuration_groups must contain objects")
        group_id = str(group.get("config_group_id") or "").strip()
        if not group_id:
            raise ValueError("config_group_id must be non-empty")
        if group_id in seen:
            raise ValueError("config_group_id must be unique")
        seen.add(group_id)
        delay = group.get("entry_delay_bars")
        cores.append(ICCoreTestRequest(
            product_scope_refs=(str(group.get("product_scope_ref") or "").strip(),),
            factor_refs=(str(group.get("factor_ref") or "").strip(),),
            horizon=group.get("horizon"),
            entry_delay_bars=(delay,),
            methods=tuple(group.get("methods") or ()),
            return_price_basis=group.get("return_price_basis"),
        ))
    return ICRunAuthoringConfiguration(tuple(cores))


def _raw_items(value: Any) -> tuple[list, list]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("IC authoring configuration schema_version must be 1")
    raw_cores = value.get("core_tests")
    raw_analyses = value.get("analyses", [])
    if not isinstance(raw_cores, list) or not isinstance(raw_analyses, list):
        raise ValueError("IC authoring core_tests and analyses must be lists")
    return raw_cores, raw_analyses


__all__ = ["ICRunAuthoringConfiguration"]
