"""Immutable, validated IC run configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph

from .authoring import ICCoreTestRequest
from .horizon_resolution import ResolvedICHorizon
from .validation import validate_frozen_configuration


@dataclass(frozen=True, slots=True)
class CompiledICRunConfiguration:
    authoring_core_tests: tuple[ICCoreTestRequest, ...]
    resolved_horizons_by_request: Mapping[
        str, Mapping[str, tuple[ResolvedICHorizon, ...]]
    ]
    analysis_graph: ICAnalysisGraph
    job_partitions: Mapping[str, tuple[str, ...]]
    factor_subject_refs: tuple[str, ...] = ()
    output_requests: tuple[str, ...] = ()

    @property
    def configuration_ref(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return f"ic-run-configuration:v2:{hashlib.sha256(payload).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "authoring_core_tests": [
                item.to_dict() for item in self.authoring_core_tests
            ],
            "resolved_horizons_by_request": {
                request_ref: {
                    factor_ref: [item.to_dict() for item in values]
                    for factor_ref, values in sorted(factors.items())
                }
                for request_ref, factors in sorted(
                    self.resolved_horizons_by_request.items()
                )
            },
            "analysis_graph": self.analysis_graph.to_dict(),
            "job_partitions": {
                key: list(value) for key, value in sorted(self.job_partitions.items())
            },
            "factor_subject_refs": list(self.factor_subject_refs),
            "output_requests": list(self.output_requests),
        }

    @classmethod
    def from_dict(cls, value: Any) -> CompiledICRunConfiguration:
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise ValueError("IC run configuration schema_version must be 2")
        graph = ICAnalysisGraph.from_dict(value.get("analysis_graph"))
        raw_authoring = value.get("authoring_core_tests")
        if not isinstance(raw_authoring, list) or not raw_authoring:
            raise ValueError("authoring_core_tests must be a non-empty list")
        authoring = tuple(
            ICCoreTestRequest.from_frozen_dict(item) for item in raw_authoring
        )
        resolutions = _resolved_horizons_by_request(
            value.get("resolved_horizons_by_request"),
        )
        outputs = _text_list(value.get("output_requests", []), "output_requests")
        subjects = _text_list(
            value.get("factor_subject_refs", []), "factor_subject_refs",
        )
        raw_partitions = value.get("job_partitions")
        if not isinstance(raw_partitions, dict):
            raise ValueError("job_partitions must be an object")
        partitions = {
            str(scope): _text_list(refs, f"job_partitions.{scope}")
            for scope, refs in raw_partitions.items()
        }
        validate_frozen_configuration(
            graph, authoring, partitions, subjects, resolutions,
        )
        return cls(
            authoring_core_tests=authoring,
            resolved_horizons_by_request=resolutions,
            analysis_graph=graph,
            job_partitions={
                key: tuple(sorted(refs)) for key, refs in sorted(partitions.items())
            },
            factor_subject_refs=tuple(sorted(subjects)),
            output_requests=tuple(sorted(outputs)),
        )


def _text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    items = tuple(str(item or "").strip() for item in value)
    if any(not item for item in items) or len(items) != len(set(items)):
        raise ValueError(f"{field} must contain unique non-empty refs")
    return items


def _resolved_horizons_by_request(
    value: Any,
) -> dict[str, dict[str, tuple[ResolvedICHorizon, ...]]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("resolved_horizons_by_request must be a non-empty object")
    result: dict[str, dict[str, tuple[ResolvedICHorizon, ...]]] = {}
    for request_ref, raw_factors in value.items():
        if not isinstance(raw_factors, dict) or not raw_factors:
            raise ValueError("each core request requires resolved factor horizons")
        result[str(request_ref)] = {}
        for factor_ref, raw_items in raw_factors.items():
            if not isinstance(raw_items, list) or not raw_items:
                raise ValueError("each factor requires at least one resolved horizon")
            items = tuple(ResolvedICHorizon.from_dict(item) for item in raw_items)
            frequencies = [item.physical_frequency for item in items]
            if len(frequencies) != len(set(frequencies)):
                raise ValueError("resolved factor horizons must be unique")
            result[str(request_ref)][str(factor_ref)] = items
    return dict(sorted(result.items()))


__all__ = ["CompiledICRunConfiguration"]
