"""Cross-check a frozen IC configuration against its authoring provenance."""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from tools.data.types import DataFreq
from tools.testers.ic_test.analysis_graph import ICAnalysisGraph
from tools.testers.ic_test.core import ICCoreTestBlock, expand_core_test_blocks

from .authoring import ICCoreTestRequest
from .horizon_resolution import ResolvedICHorizon


def validate_frozen_configuration(
    graph: ICAnalysisGraph,
    authoring: tuple[ICCoreTestRequest, ...],
    partitions: Mapping[str, tuple[str, ...]],
    subjects: tuple[str, ...],
    resolutions: Mapping[
        str, Mapping[str, tuple[ResolvedICHorizon, ...]]
    ],
) -> None:
    cores = {item.core_test_ref: item for item in graph.core_tests}
    requested_factors = {
        factor for request in authoring for factor in request.factor_refs
    }
    requested_scopes = {
        scope for request in authoring for scope in request.product_scope_refs
    }
    if requested_factors != {item.factor_ref for item in graph.core_tests}:
        raise ValueError("authoring factor refs do not match frozen core tests")
    if requested_scopes != {item.product_scope_ref for item in graph.core_tests}:
        raise ValueError("authoring product scopes do not match frozen core tests")
    _validate_partitions(cores, partitions)
    if set(resolutions) != {item.request_ref for item in authoring}:
        raise ValueError("resolved horizons must cover every core request")
    expected_cores = _expand_resolved_requests(authoring, resolutions)
    if {item.core_test_ref for item in expected_cores} != set(cores):
        raise ValueError("resolved horizons do not match frozen core tests")
    _validate_resolution_origins(authoring, resolutions)
    _validate_subjects(subjects, {item.factor_ref for item in graph.core_tests})


def _validate_partitions(cores, partitions) -> None:
    partition_refs = [ref for refs in partitions.values() for ref in refs]
    if (
        len(partition_refs) != len(set(partition_refs))
        or set(partition_refs) != set(cores)
    ):
        raise ValueError("job partitions must contain every core test exactly once")
    for scope, refs in partitions.items():
        if any(cores[ref].product_scope_ref != scope for ref in refs):
            raise ValueError("job partition scope does not match its core tests")


def _validate_subjects(subjects, executable_factors) -> None:
    for subject in subjects:
        if subject.startswith("factor:v1:") or subject.startswith("factor:sha256:"):
            if subject not in executable_factors:
                raise ValueError("standalone factor subject is not executable")
            continue
        if not subject.startswith("factor-set:v1:"):
            raise ValueError("factor_subject_refs must contain frozen factor identities")


def _expand_resolved_requests(authoring, resolutions):
    blocks = []
    for request in authoring:
        factors = resolutions[request.request_ref]
        if set(factors) != set(request.factor_refs):
            raise ValueError("resolved horizons must cover request factor refs")
        for factor_ref in request.factor_refs:
            blocks.append(ICCoreTestBlock(
                request.product_scope_refs,
                (factor_ref,),
                tuple(item.physical_frequency for item in factors[factor_ref]),
                request.entry_delay_bars,
                request.methods,
                request.return_price_basis,
            ))
    return expand_core_test_blocks(blocks)


def _validate_resolution_origins(authoring, resolutions) -> None:
    for request in authoring:
        for factor_entries in resolutions[request.request_ref].values():
            signal_duration: pd.Timedelta | None = None
            for entry in factor_entries:
                physical = DataFreq(entry.physical_frequency).value
                for origin in entry.origins:
                    base = physical / origin.multiplier
                    if origin.base == "signal":
                        if signal_duration is None:
                            signal_duration = base
                        elif signal_duration != base:
                            raise ValueError(
                                "signal-relative horizon origins are inconsistent"
                            )
                    elif DataFreq(origin.base).value != base:
                        raise ValueError(
                            "explicit horizon origin does not match physical frequency"
                        )
            expected = request.horizon.resolve_entries(
                DataFreq(signal_duration) if signal_duration is not None else None,
            )
            if tuple(item.to_dict() for item in expected) != tuple(
                item.to_dict() for item in factor_entries
            ):
                raise ValueError(
                    "horizon authoring policy does not match resolved horizons"
                )


__all__ = ["validate_frozen_configuration"]
