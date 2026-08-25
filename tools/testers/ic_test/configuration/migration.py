"""One-way conversion from the removed flat IC settings shape."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from tools.testers.analysis_graph import AnalysisMapping
from tools.testers.ic_test.analysis_graph import ic_analysis_graph_definition
from tools.testers.ic_test.core import (
    ICCoreTest,
    ICCoreTestBlock,
    expand_core_test_blocks,
)

from .authoring import (
    ICAnalysisAttachmentRequest,
    ICCoreTestRequest,
    ICRunAuthoringConfiguration,
)
from .flat_migration import migrate_analysis_nodes
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


def migrate_flat_ic_settings(
    settings: Mapping[str, Any],
    *,
    factor_frequencies: Mapping[str, Any],
    factor_set_members: Mapping[str, Iterable[str]] | None = None,
    output_requests: Iterable[str] = (),
) -> ICRunAuthoringConfiguration:
    """Translate one old payload; normal writers must not call this function."""

    reject_unimplemented_cross_section_settings(settings)
    factors = factor_refs(settings.get("factor_selections"))
    selected_sets = factor_set_refs(settings.get("factor_set_selections"))
    subjects = _factor_subjects(factors, selected_sets, factor_set_members or {})
    request = ICCoreTestRequest(
        product_scope_refs=product_scope_refs(
            settings.get("product_path_selections"),
        ),
        factor_refs=factors,
        horizon=ICHorizonPolicy.from_value(
            settings.get("forward_return_horizons"),
        ),
        entry_delay_bars=entry_delays(settings.get("ic_lags", (0,))),
        methods=correlation_methods(settings.get("ic_correlation", "rank")),
        return_price_basis=str(
            settings.get("return_price_basis")
            or "next_open_to_open_adjusted"
        ).strip(),
    )
    cores, primary_refs = _migrated_core_targets(request, factor_frequencies)
    nodes = migrate_analysis_nodes(
        settings,
        cores,
        primary_core_refs=primary_refs,
    )
    registry = ic_analysis_graph_definition()
    attachments: dict[tuple[str, str, str], list[str]] = {}
    parameters_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for node in nodes:
        parameter_key = json.dumps(
            node.parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        mapping = registry.type_by_key(
            node.analysis_type,
        ).input_contract.mapping
        combine_key = node.node_id if mapping is AnalysisMapping.COMBINE else ""
        key = (node.analysis_type, parameter_key, combine_key)
        attachments.setdefault(key, []).extend(node.target_refs)
        parameters_by_key[key] = node.parameters
    return ICRunAuthoringConfiguration(
        core_tests=(request,),
        analyses=tuple(
            ICAnalysisAttachmentRequest(
                analysis_type,
                tuple(target_refs),
                parameters_by_key[(analysis_type, parameter_key, combine_key)],
            )
            for (analysis_type, parameter_key, combine_key), target_refs in sorted(
                attachments.items()
            )
        ),
        factor_subject_refs=subjects,
        output_requests=unique_texts(output_requests),
    )


def _migrated_core_targets(
    request: ICCoreTestRequest,
    factor_frequencies: Mapping[str, Any],
) -> tuple[tuple[ICCoreTest, ...], tuple[str, ...]]:
    factor_horizons = {
        factor_ref: request.horizon.resolve(factor_frequencies.get(factor_ref))
        for factor_ref in request.factor_refs
    }
    blocks = tuple(
        ICCoreTestBlock(
            request.product_scope_refs,
            (factor_ref,),
            factor_horizons[factor_ref],
            request.entry_delay_bars,
            request.methods,
            request.return_price_basis,
        )
        for factor_ref in request.factor_refs
    )
    cores = expand_core_test_blocks(blocks)
    primary = tuple(sorted(
        item.core_test_ref
        for item in cores
        if item.entry_delay_bars == request.entry_delay_bars[0]
        and item.horizon == factor_horizons[item.factor_ref][0]
    ))
    return cores, primary


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
        if any(not _is_v2_factor_ref(ref) for ref in members):
            raise ValueError("factor-set members must be factor:v2 values")
        if set(members) - factor_set:
            raise ValueError("factor-set members are missing from factor_selections")
        covered.update(members)
    return tuple(sorted((*selected_sets, *(factor_set - covered))))


def _is_v2_factor_ref(value: str) -> bool:
    from tools.factors.formula_identity import is_factor_reference

    return is_factor_reference(value)


__all__ = ["migrate_flat_ic_settings"]
