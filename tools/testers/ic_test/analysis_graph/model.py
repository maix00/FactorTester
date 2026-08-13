"""Normalized nodes and container for the IC auxiliary-analysis DAG."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from tools.testers.ic_test.core import ICCoreTest


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty text")
    return text


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("analysis parameters must be JSON serializable") from exc


@dataclass(frozen=True, slots=True)
class ICAnalysisNode:
    node_id: str
    analysis_type: str
    target_refs: tuple[str, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required_text(self.node_id, "node_id"))
        object.__setattr__(
            self,
            "analysis_type",
            _required_text(self.analysis_type, "analysis_type"),
        )
        targets = tuple(_required_text(item, "target_ref") for item in self.target_refs)
        if not targets:
            raise ValueError("analysis node requires at least one target")
        if len(targets) != len(set(targets)):
            raise ValueError(f"analysis node {self.node_id} contains duplicate targets")
        object.__setattr__(self, "target_refs", targets)
        object.__setattr__(self, "parameters", _json_copy(dict(self.parameters)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "analysis_type": self.analysis_type,
            "target_refs": list(self.target_refs),
            "parameters": _json_copy(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: Any) -> ICAnalysisNode:
        if not isinstance(value, dict):
            raise ValueError("IC analysis node must be an object")
        targets = value.get("target_refs")
        if not isinstance(targets, list):
            raise ValueError("IC analysis target_refs must be a list")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("IC analysis parameters must be an object")
        return cls(
            node_id=value.get("node_id"),
            analysis_type=value.get("analysis_type"),
            target_refs=tuple(targets),
            parameters=parameters,
        )


@dataclass(frozen=True, slots=True)
class ICAnalysisGraph:
    core_tests: tuple[ICCoreTest, ...]
    analyses: tuple[ICAnalysisNode, ...] = ()

    def validate(self) -> ICAnalysisGraph:
        from .validation import validate_ic_analysis_graph

        validate_ic_analysis_graph(self)
        return self

    def output_kind(self, ref: str) -> str:
        from .registry import ic_analysis_graph_definition

        for node in self.analyses:
            if node.node_id == ref:
                return ic_analysis_graph_definition().type_by_key(
                    node.analysis_type,
                ).output_kind
        if any(item.core_test_ref == ref for item in self.core_tests):
            raise ValueError("core tests expose multiple output kinds")
        raise KeyError(f"unknown IC graph ref: {ref}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": 1,
            "core_tests": [
                item.to_dict()
                for item in sorted(self.core_tests, key=lambda value: value.core_test_ref)
            ],
            "analyses": [
                item.to_dict()
                for item in sorted(self.analyses, key=lambda value: value.node_id)
            ],
        }

    @classmethod
    def from_dict(cls, value: Any) -> ICAnalysisGraph:
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("IC analysis graph schema_version must be 1")
        core_values = value.get("core_tests")
        analysis_values = value.get("analyses")
        if not isinstance(core_values, list) or not isinstance(analysis_values, list):
            raise ValueError("IC analysis graph nodes must be lists")
        return cls(
            core_tests=tuple(ICCoreTest.from_dict(item) for item in core_values),
            analyses=tuple(ICAnalysisNode.from_dict(item) for item in analysis_values),
        ).validate()


__all__ = ["ICAnalysisGraph", "ICAnalysisNode"]
