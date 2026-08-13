"""One immutable IC Job plan for a single product scope."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty text")
    return text


def _refs(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    refs = tuple(_required_text(item, field) for item in value)
    if not allow_empty and not refs:
        raise ValueError(f"{field} must not be empty")
    if len(refs) != len(set(refs)):
        raise ValueError(f"{field} must contain unique refs")
    return refs


@dataclass(frozen=True, slots=True)
class ICJobExecutionPlan:
    configuration_ref: str
    product_scope_ref: str
    core_test_refs: tuple[str, ...]
    analysis_node_ids: tuple[str, ...]
    factor_subject_refs: tuple[str, ...] = ()
    output_requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "configuration_ref",
            _required_text(self.configuration_ref, "configuration_ref"),
        )
        object.__setattr__(
            self, "product_scope_ref",
            _required_text(self.product_scope_ref, "product_scope_ref"),
        )
        object.__setattr__(
            self, "core_test_refs",
            tuple(sorted(_refs(self.core_test_refs, "core_test_refs", allow_empty=False))),
        )
        object.__setattr__(
            self, "analysis_node_ids",
            _refs(self.analysis_node_ids, "analysis_node_ids"),
        )
        object.__setattr__(
            self, "factor_subject_refs",
            tuple(sorted(_refs(self.factor_subject_refs, "factor_subject_refs"))),
        )
        object.__setattr__(
            self, "output_requests",
            tuple(sorted(_refs(self.output_requests, "output_requests"))),
        )
    @property
    def plan_ref(self) -> str:
        encoded = json.dumps(
            self.identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return f"ic-job-plan:v2:{hashlib.sha256(encoded).hexdigest()}"

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "configuration_ref": self.configuration_ref,
            "product_scope_ref": self.product_scope_ref,
            "core_test_refs": list(self.core_test_refs),
            "analysis_node_ids": list(self.analysis_node_ids),
            "factor_subject_refs": list(self.factor_subject_refs),
            "output_requests": list(self.output_requests),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 2, "plan_ref": self.plan_ref, **self.identity}

    @classmethod
    def from_dict(cls, value: Any) -> ICJobExecutionPlan:
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise ValueError("IC Job execution plan schema_version must be 2")
        item = cls(
            configuration_ref=value.get("configuration_ref"),
            product_scope_ref=value.get("product_scope_ref"),
            core_test_refs=_refs(value.get("core_test_refs"), "core_test_refs"),
            analysis_node_ids=_refs(
                value.get("analysis_node_ids"), "analysis_node_ids",
            ),
            factor_subject_refs=_refs(
                value.get("factor_subject_refs", []), "factor_subject_refs",
            ),
            output_requests=_refs(
                value.get("output_requests", []), "output_requests",
            ),
        )
        if str(value.get("plan_ref") or "") != item.plan_ref:
            raise ValueError("plan_ref does not match the frozen IC Job plan")
        return item


__all__ = ["ICJobExecutionPlan"]
