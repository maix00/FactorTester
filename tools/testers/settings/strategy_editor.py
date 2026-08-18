"""Backend contract for nested strategy editors.

The web client renders the editor, but it must not invent which outer tabs
control a strategy group's candidate scope.  This small manifest extension is
shared by backtest and IC-test applications so the same rule can be consumed
by web, Swift, and future clients.
"""

from __future__ import annotations

from typing import Any


_INNER_DEFAULT_TABS = (
    {
        "key": "__strategy__",
        "label": "分组",
        "kind": "structure",
        "mount_policy": "default",
    },
    {
        "key": "factor",
        "label": "因子执行",
        "kind": "factor_scope",
        "mount_policy": "default",
    },
    {
        "key": "product_path_selection",
        "label": "产品组",
        "kind": "product_scope",
        "mount_policy": "default",
    },
)


def _contract(*, application: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "editor": "nested_strategy",
        "application": application,
        "inner_default_tabs": [dict(item) for item in _INNER_DEFAULT_TABS],
        "outer_scope_tabs": {
            "factor": {
                "mounted_tab": "factor",
                "candidate_fields": ["factor_candidates"],
                "selection_fields": ["factor_selections", "factor"],
                "family_fields": ["factor_family_ref"],
                "set_fields": ["factor_set_selections"],
                "candidate_kind": "factor",
            },
            "product_path_selection": {
                "mounted_tab": "product_path_selection",
                "candidate_fields": ["product_path_candidates"],
                "selection_fields": [
                    "product_path_selections",
                    "product_path_selection",
                ],
                "candidate_kind": "product_group",
            },
        },
        # These fields are authored once by the outer test form.  They are
        # never silently copied into a strategy's inner override tab.
        "outer_only_tabs": [
            "run_context",
            "test_template",
            "run_inputs",
            "time",
            "calendar",
        ],
        "manual_inner_tabs": True,
        "inner_override_scope": "overridable",
        "factor_scope": {
            "selection_kind": "factor",
            "family_kind": "factor_family",
            "inline_create": True,
            "inner_hide_fields": [
                "factor_set_selections",
                "factor_set",
                "factor_family_ref",
            ],
        },
        "product_scope": {
            "selection_kind": "product_group",
            "inline_create": True,
            "category_source": "outer_or_visible_catalog",
        },
        "derived_strategy": {
            "kind": "normal_strategy",
            "override_parent_fields": True,
        },
    }


def register_strategy_editor_contract(app: Any) -> None:
    """Register the nested strategy editor rules on an application manifest."""

    application = getattr(app, "application", "")
    if application not in {"group_test", "ic_test"}:
        raise ValueError(f"nested strategy editor is not supported by {application!r}")
    app.register_manifest_extension(
        "strategy_editor",
        _contract(application=application),
    )


__all__ = ["register_strategy_editor_contract"]
