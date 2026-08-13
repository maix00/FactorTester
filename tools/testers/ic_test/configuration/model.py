"""Immutable, validated IC run configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph

from .horizon import ICHorizonPolicy
from .horizon_resolution import ResolvedICHorizon


@dataclass(frozen=True, slots=True)
class CompiledICRunConfiguration:
    horizon_policy: ICHorizonPolicy
    resolved_horizons_by_factor: Mapping[str, tuple[ResolvedICHorizon, ...]]
    analysis_graph: ICAnalysisGraph
    primary_core_refs: tuple[str, ...]
    job_partitions: Mapping[str, tuple[str, ...]]
    factor_subject_refs: tuple[str, ...] = ()
    output_requests: tuple[str, ...] = ()

    @property
    def configuration_ref(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return f"ic-run-configuration:v1:{hashlib.sha256(payload).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "horizon_policy": self.horizon_policy.to_dict(),
            "resolved_horizons_by_factor": {
                factor_ref: [item.to_dict() for item in values]
                for factor_ref, values in sorted(
                    self.resolved_horizons_by_factor.items()
                )
            },
            "analysis_graph": self.analysis_graph.to_dict(),
            "primary_core_refs": list(self.primary_core_refs),
            "job_partitions": {
                key: list(value) for key, value in sorted(self.job_partitions.items())
            },
            "factor_subject_refs": list(self.factor_subject_refs),
            "output_requests": list(self.output_requests),
        }

    @classmethod
    def from_dict(cls, value: Any) -> CompiledICRunConfiguration:
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("IC run configuration schema_version must be 1")
        graph = ICAnalysisGraph.from_dict(value.get("analysis_graph"))
        resolutions = _resolved_horizons(
            value.get("resolved_horizons_by_factor"),
        )
        primary = _text_list(value.get("primary_core_refs"), "primary_core_refs")
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
        _validate_frozen_refs(
            graph, primary, partitions, subjects, resolutions,
        )
        return cls(
            horizon_policy=ICHorizonPolicy.from_dict(value.get("horizon_policy")),
            resolved_horizons_by_factor=resolutions,
            analysis_graph=graph,
            primary_core_refs=tuple(sorted(primary)),
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


def _validate_frozen_refs(
    graph: ICAnalysisGraph,
    primary_refs: tuple[str, ...],
    partitions: Mapping[str, tuple[str, ...]],
    subjects: tuple[str, ...],
    resolutions: Mapping[str, tuple[ResolvedICHorizon, ...]],
) -> None:
    cores = {item.core_test_ref: item for item in graph.core_tests}
    if not set(primary_refs) <= set(cores):
        raise ValueError("primary_core_refs contains an unknown core test")
    partition_refs = [ref for refs in partitions.values() for ref in refs]
    if len(partition_refs) != len(set(partition_refs)) or set(partition_refs) != set(cores):
        raise ValueError("job partitions must contain every core test exactly once")
    for scope, refs in partitions.items():
        if any(cores[ref].product_scope_ref != scope for ref in refs):
            raise ValueError("job partition scope does not match its core tests")
    executable_factors = {item.factor_ref for item in graph.core_tests}
    if set(resolutions) != executable_factors:
        raise ValueError("resolved horizons must cover every executable factor")
    for factor_ref in executable_factors:
        resolved = {
            item.physical_frequency for item in resolutions[factor_ref]
        }
        frozen = {
            item.horizon for item in graph.core_tests
            if item.factor_ref == factor_ref
        }
        if resolved != frozen:
            raise ValueError("resolved horizons do not match frozen core tests")
    for subject in subjects:
        if subject.startswith("factor:v1:"):
            if subject not in executable_factors:
                raise ValueError("standalone factor subject is not executable")
            continue
        if not subject.startswith("factor-set:v1:"):
            raise ValueError("factor_subject_refs must contain frozen factor identities")


def _resolved_horizons(
    value: Any,
) -> dict[str, tuple[ResolvedICHorizon, ...]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("resolved_horizons_by_factor must be a non-empty object")
    result: dict[str, tuple[ResolvedICHorizon, ...]] = {}
    for factor_ref, raw_items in value.items():
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("each factor requires at least one resolved horizon")
        items = tuple(ResolvedICHorizon.from_dict(item) for item in raw_items)
        frequencies = [item.physical_frequency for item in items]
        if len(frequencies) != len(set(frequencies)):
            raise ValueError("resolved factor horizons must be unique")
        result[str(factor_ref)] = items
    return dict(sorted(result.items()))


__all__ = ["CompiledICRunConfiguration"]
