"""Shared factor and product-scope chip declarations."""

from __future__ import annotations

from tools.testers.settings.contracts import ChipDefinition


def register_factor_product_scope_chips(app: object) -> None:
    """Register the identity chips shared by backtest and IC group rows."""
    app.register_chip_field(ChipDefinition(
        "factor_candidates", "因子候选", "identity",
        "因子候选: {factorCandidateLabel}", ("factorCandidateLabel",),
        module="factor_execution", target_tab="factor", order=10,
        inherit_from_root=True, batch_owned=True,
        source_adapter="selected_factor_candidates", clickable=True,
        detail_overlay={
            "kind": "factor_set", "mode": "view",
            "source_key": "factor_candidates", "ref_key": "target_ref",
        },
    ))
    app.register_chip_field(ChipDefinition(
        "product_path_selection", "产品组", "identity",
        "产品组: {productPathSelectionLabel}", ("product_group",),
        module="product_selection", target_tab="product_path_selection", order=20,
        inherit_from_root=True, batch_owned=True,
        value_resolvers={
            "productPathSelectionLabel": "product_path_selection_label",
        },
        clickable=True, source_adapter="selected_product_paths",
        detail_overlay={
            "kind": "product_group", "mode": "view",
            "source_key": "product_group",
        },
    ))
