"""Declarative outer/inner field scopes for nested strategy editors."""

from __future__ import annotations

from typing import Any


def build_scoped_fields() -> dict[str, Any]:
    """Return the reusable field-scope contract.

    ``visible_if`` and ``default_if`` describe one field inside one settings
    surface.  They are not enough for a nested editor, where the same field
    has a different source and edit policy on the outer and inner sides.
    Keeping that second dimension here lets Web, Swift, and future clients
    consume the same semantics.

    ``resolution`` is generic: a derived field can be computed from another
    registered field without becoming a second hand-written frontend rule.
    ``visible_when`` and ``required_when`` use one condition vocabulary for
    every scoped field.
    """

    return {
        "factor_candidates": {
            "label": "因子候选",
            "editor": "shared_object_multi_select",
            "outer": {
                "source": "factor_sources_or_inline_factor_catalog",
                "cardinality": "many",
                "selection_mode": "build_candidate_pool",
                "editable": True,
                "allow_inline_create": True,
            },
            "inner": {
                "source_when_outer_mounted": "outer_candidate_pool",
                "source_when_outer_unmounted": "visible_factor_catalog",
                "cardinality": "many",
                "selection_mode": "filter_or_build_candidates",
                "filter_only_when_outer_mounted": True,
                "allow_inline_create_when_outer_unmounted": True,
                "editable": True,
                "help_text": (
                    "外层存在时仅从外层候选池中筛选；没有外层时从当前可见因子目录构建候选。"
                ),
            },
        },
        "factor_role_bindings": {
            "outer": {
                "source": "factor_candidates",
                "cardinality": "mapping",
                "editable": True,
                "visible_when": {"min_items": {"factor_candidates": 2}},
            },
            "inner": {
                "source": "factor_candidates",
                "cardinality": "mapping",
                "editable": True,
                "visible_when": {"min_items": {"factor_candidates": 2}},
            },
        },
        "factor_mode": {
            "outer": {
                "source": "factor_execution",
                "cardinality": "one",
                "editable": True,
            },
            "inner": {
                "source": "outer_factor_execution",
                "cardinality": "one",
                "selection_mode": "override",
                "editable": True,
                "override_control": "direct",
            },
        },
        "warmup_mode": {
            "outer": {
                "source": "factor_execution",
                "cardinality": "one",
                "editable": True,
            },
            "inner": {
                "source": "outer_factor_execution",
                "cardinality": "one",
                "selection_mode": "override",
                "editable": True,
                "override_control": "direct",
            },
        },
        "warmup_window": {
            "outer": {
                "source": "factor_execution",
                "cardinality": "one",
                "editable": True,
                "visible_when": {"field_values": {"warmup_mode": ["fixed"]}},
            },
            "inner": {
                "source": "outer_factor_execution",
                "cardinality": "one",
                "selection_mode": "override",
                "editable": True,
                "override_control": "direct",
                "visible_when": {"field_values": {"warmup_mode": ["fixed"]}},
            },
        },
        "factor_combination_mode": {
            "label": "组合方式",
            "editor": "select",
            "outer": {
                "source": "factor_candidates",
                "cardinality": "one",
                "options": [],
                "editable": True,
                "visible_when": {"min_items": {"factor_candidates": 2}},
                "required_when": {"min_items": {"factor_candidates": 2}},
            },
            "inner": {
                "source": "factor_candidates",
                "cardinality": "one",
                "options": [],
                "editable": True,
                "visible_when": {"min_items": {"factor_candidates": 2}},
                "required_when": {"min_items": {"factor_candidates": 2}},
            },
        },
        "product_path_candidates": {
            "outer": {
                "source": "product_group_sources_or_inline_catalog",
                "cardinality": "many",
                "selection_mode": "build_candidate_pool",
                "editable": True,
                "allow_inline_create": True,
            },
            "inner": {
                "source_when_outer_mounted": "outer_product_group_pool",
                "source_when_outer_unmounted": "visible_product_group_catalog",
                "cardinality": "many",
                "selection_mode": "filter_or_build_candidates",
                "filter_only_when_outer_mounted": True,
                "allow_inline_create_when_outer_unmounted": True,
                "editable": True,
            },
        },
        "category_candidates": {
            "label": "产品分类候选",
            "editor": "shared_object_multi_select",
            "outer": {
                "source": "visible_category_catalog",
                "cardinality": "many",
                "selection_mode": "build_candidate_pool",
                "editable": True,
                "allow_inline_create": True,
            },
            "inner": {
                "source_when_outer_mounted": "outer_category_pool",
                "source_when_outer_unmounted": "visible_category_catalog",
                "cardinality": "many",
                "selection_mode": "filter_or_build_candidates",
                "filter_only_when_outer_mounted": True,
                "allow_inline_create_when_outer_unmounted": True,
                "editable": True,
            },
        },
        "category": {
            "label": "产品分类",
            "editor": "shared_object_single_select",
            "outer": {
                "source": "category_candidates",
                "cardinality": "one",
                "editable": True,
            },
            "inner": {
                "source": "category_candidates",
                "cardinality": "one",
                "selection_mode": "override",
                "editable": True,
                "override_control": "direct",
            },
        },
    }


__all__ = ["build_scoped_fields"]
