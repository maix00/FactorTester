"""Compile authoring fields into an immutable IC run configuration."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph
from tools.testers.ic_test.core import ICCoreTestBlock, expand_core_test_blocks

from .analyses import analysis_nodes_from_settings
from .horizon import ICHorizonPolicy
from .inputs import (
    correlation_methods,
    entry_delays,
    factor_refs,
    factor_set_refs,
    product_scope_refs,
    reject_unimplemented_cross_section_settings,
    unique_texts,
)
from .model import CompiledICRunConfiguration


def compile_ic_run_configuration(
    settings: Mapping[str, Any],
    *,
    factor_frequencies: Mapping[str, Any] | None = None,
    factor_set_members: Mapping[str, Iterable[str]] | None = None,
    output_requests: Iterable[str] = (),
) -> CompiledICRunConfiguration:
    reject_unimplemented_cross_section_settings(settings)
    factors = factor_refs(settings.get("factor_selections"))
    selected_sets = factor_set_refs(settings.get("factor_set_selections"))
    subjects = _factor_subjects(factors, selected_sets, factor_set_members or {})
    scopes = product_scope_refs(settings.get("product_path_selections"))
    policy = ICHorizonPolicy.from_value(settings.get("forward_return_horizons"))
    delays = entry_delays(settings.get("ic_lags", (0,)))
    methods = correlation_methods(settings.get("ic_correlation", "rank"))
    basis = str(
        settings.get("return_price_basis") or "next_open_to_open_adjusted"
    ).strip()
    frequencies = factor_frequencies or {}
    factor_horizons = {
        factor_ref: policy.resolve(frequencies.get(factor_ref))
        for factor_ref in factors
    }
    blocks = tuple(
        ICCoreTestBlock(
            product_scope_refs=scopes,
            factor_refs=(factor_ref,),
            horizons=factor_horizons[factor_ref],
            entry_delay_bars=delays,
            methods=methods,
            return_price_basis=basis,
        )
        for factor_ref in factors
    )
    core_tests = expand_core_test_blocks(blocks)
    primary_refs = tuple(sorted(
        item.core_test_ref
        for item in core_tests
        if item.entry_delay_bars == delays[0]
        and item.horizon == factor_horizons[item.factor_ref][0]
    ))
    analyses = analysis_nodes_from_settings(
        settings, core_tests, primary_core_refs=primary_refs,
    )
    partitions = {
        scope: tuple(
            item.core_test_ref
            for item in core_tests
            if item.product_scope_ref == scope
        )
        for scope in scopes
    }
    return CompiledICRunConfiguration(
        horizon_policy=policy,
        analysis_graph=ICAnalysisGraph(core_tests, analyses),
        primary_core_refs=primary_refs,
        job_partitions=partitions,
        factor_subject_refs=subjects,
        output_requests=unique_texts(output_requests),
    )


def _factor_subjects(
    factors: tuple[str, ...],
    selected_sets: tuple[str, ...],
    set_members: Mapping[str, Iterable[str]],
) -> tuple[str, ...]:
    factor_set = set(factors)
    covered: set[str] = set()
    for target_ref in selected_sets:
        members = unique_texts(set_members.get(target_ref, ()))
        if not members:
            raise ValueError(f"factor-set descriptor is missing: {target_ref}")
        invalid = [ref for ref in members if not ref.startswith("factor:v1:")]
        if invalid:
            raise ValueError("factor-set members must be frozen factor_ref values")
        missing = set(members) - factor_set
        if missing:
            raise ValueError("factor-set members are missing from factor_selections")
        covered.update(members)
    standalone = factor_set - covered
    return tuple(sorted((*selected_sets, *standalone)))


__all__ = ["CompiledICRunConfiguration", "compile_ic_run_configuration"]
