"""Backend contract for nested strategy editors.

The web client renders the editor, but it must not invent which outer tabs
control a strategy group's candidate scope.  This small manifest extension is
shared by backtest and IC-test applications so the same rule can be consumed
by web, Swift, and future clients.
"""

from __future__ import annotations

from typing import Any

from .strategy_editor_scope import build_scoped_fields


_SHARED_INNER_DEFAULT_TABS = (
    {
        "key": "product_path_selection",
        "label": "产品组",
        "kind": "product_scope",
        "mount_policy": "default",
    },
)


def _inner_default_tabs(application: str) -> tuple[dict[str, Any], ...]:
    structure = {
        "key": "__configuration__" if application == "ic_test" else "__strategy__",
        "label": "配置" if application == "ic_test" else "分组",
        "kind": "structure",
        "mount_policy": "default",
    }
    factor = {
        "key": "factor",
        # The IC page already has an outer “因子执行” catalog launcher.  The
        # grouped editor owns the selected concrete factor, so repeating the
        # outer label here is ambiguous.  Backtest keeps its established
        # execution-oriented label.
        "label": "因子" if application == "ic_test" else "因子执行",
        "kind": "factor_scope",
        "mount_policy": "default",
    }
    return (structure, factor, *_SHARED_INNER_DEFAULT_TABS)


_SHARED_INNER_MANUAL_TABS = (
    {
        "key": "category",
        "label": "产品分类",
        "kind": "category_scope",
        "mount_policy": "manual",
        "scope_policy": "overridable",
    },
    {
        "key": "trading_product_filter",
        "label": "交易产品",
        "kind": "product_filter",
        "mount_policy": "manual",
        "field": "productMask",
        "item_field": "productMask",
        "item_default": {},
        "scope_policy": "overridable",
        "independent_of": "derived_strategy",
    },
)


def _inner_manual_tabs(application: str, app: Any | None = None) -> tuple[dict[str, Any], ...]:
    if application != "ic_test":
        return _SHARED_INNER_MANUAL_TABS
    projections = []
    for tab_key, field_key in (("delay", "ic_lags"),):
        tab = app.tabs.get(tab_key) if app is not None else None
        field = app.settings.get(field_key) if app is not None else None
        if tab is None or field is None or field.tab != tab_key:
            continue
        projection = {
            "key": tab.key, "label": tab.label,
            "kind": "registered_setting", "field": field.key,
            "mount_policy": "manual", "scope_policy": "overridable",
            "registration_source": {"tab": tab.key, "field": field.key},
        }
        if field_key == "ic_lags":
            projection.update(
                cardinality="one",
                minimum=0,
                item_field="entry_delay_bars",
                item_default=0,
            )
        projections.append(projection)
    return tuple(projections)


def _contract(*, application: str, app: Any | None = None) -> dict[str, Any]:
    scoped_fields = build_scoped_fields()
    inner_factor_candidates = scoped_fields["factor_candidates"]["inner"]
    inner_combination = scoped_fields["factor_combination_mode"]["inner"]
    inner_default_tabs = _inner_default_tabs(application)
    return {
        "schema_version": 2,
        "editor": "nested_strategy",
        "application": application,
        # Keep the pre-mounted set explicit.  Clients must not infer it from
        # whichever fields happen to be visible in the current manifest.
        "outer_pre_mounted_tabs": [dict(item) for item in inner_default_tabs],
        "pre_mounted_tabs": [dict(item) for item in inner_default_tabs],
        "inner_default_tabs": [dict(item) for item in inner_default_tabs],
        "inner_manual_tabs": [
            dict(item) for item in _inner_manual_tabs(application, app)
        ],
        "outer_scope_tabs": {
            "factor": {
                "mounted_tab": "factor",
                "candidate_fields": ["factor_candidates"],
                "source_fields": [
                    "factor_source_selections", "factor_set_selections",
                ],
                "scope_fields": ["factor_candidates"],
                "selection_fields": ["factor_candidates"],
                "set_fields": ["factor_set_selections"],
                "candidate_kind": "factor",
            },
            "product_path_selection": {
                "mounted_tab": "product_path_selection",
                "candidate_fields": ["product_path_candidates"],
                "scope_fields": ["product_path_candidates"],
                "selection_fields": [
                    "product_path_selections",
                    "product_path_selection",
                ],
                "candidate_kind": "product_group",
            },
            "category": {
                "mounted_tab": "category",
                "candidate_fields": ["category_candidates"],
                "scope_fields": ["category_candidates"],
                "selection_fields": ["category"],
                "candidate_kind": "category",
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
            "data_source",
        ],
        "candidate_constraints": {
            "category_candidates": {
                "source_field": "data_source",
                "mode_field": "data_source_mode",
                "automatic_mode": "auto",
                "coverage": "complete_path_coverage",
                "side": "outer",
            },
            "product_path_candidates": {
                "source_field": "data_source",
                "mode_field": "data_source_mode",
                "automatic_mode": "auto",
                "coverage": "complete_product_coverage",
                "side": "outer",
            },
        },
        "manual_inner_tabs": True,
        "inner_override_scope": "overridable",
        # This is the reusable, client-neutral contract consumed by Web,
        # Swift and CLI clients.  Factor-family authoring is intentionally
        # not a task field; it lives only inside the factor-create overlay.
        "scoped_fields": scoped_fields,
        "factor_scope": {
            "selection_kind": "factor",
            "identity_field": "factor_ref",
            "strategy_selection_field": "factor_candidate_refs",
            "runtime_resolution_field": "factor",
            "family_kind": "factor_family",
            "inline_create": True,
        },
        "factor_candidate_sources": {
            "outer": [
                {
                    "key": "factor_set_selections",
                    "label": "因子集合",
                    "editor": "shared_object_multi_select",
                    "cardinality": "many",
                    "derived_field": "factor_candidates",
                    "item_fields": [
                        "schema_version", "ref", "alias", "owner_ref",
                        "identity", "source_kind", "transient_factor_id",
                    ],
                },
                {
                    "key": "factor_source_selections",
                    "label": "因子",
                    "editor": "shared_object_multi_select",
                    "cardinality": "many",
                    "derived_field": "factor_candidates",
                    "item_fields": [
                        "schema_version", "ref", "alias", "owner_ref",
                        "identity", "source_kind", "transient_factor_id",
                    ],
                },
            ],
            "inner": {
                "source_when_outer_mounted": "factor_candidates",
                "selection_mode_when_outer_mounted": "filter",
                "sources_when_outer_unmounted": [
                    "factor_set_selections", "factor_source_selections",
                ],
                "selection_mode_when_outer_unmounted": "build_candidate_pool",
                "editor": "shared_object_multi_select",
            },
        },
        # The outer factor tab builds this pool.  A nested strategy never
        # edits the pool itself: it selects one or more members from it.  The
        # second field is intentionally registered here even while the
        # registry has no combination algorithms; the UI can therefore show
        # the empty, required field instead of inventing a client-side rule.
        "inner_factor_fields": {
            "candidate_selection": {
                "key": "factor_candidates",
                "label": "因子候选",
                "kind": "candidate_filter",
                "editor": "shared_object_multi_select",
                **inner_factor_candidates,
            },
            "combination_mode": {
                "key": "factor_combination_mode",
                "label": "组合方式",
                "kind": "factor_combination_mode",
                "editor": inner_combination.get("editor", "select"),
                **inner_combination,
                "help_text": "一个候选时按单因子策略运行；多个候选需要一种组合方式。",
            },
            # These are registered FactorSignal fields, but the strategy
            # editor contract makes their inner/outer availability explicit
            # for clients that do not render the full manifest themselves.
            "shared_overridable_fields": [
                "factor_role_bindings",
                "factor_mode",
                "warmup_mode",
                "warmup_window",
            ],
        },
        "product_scope": {
            "selection_kind": "product_group",
            "inline_create": True,
            "category_source": "outer_or_visible_catalog",
        },
        "trading_product_filter": {
            "field": "productMask",
            "candidate_kind": "product",
            "editor": "shared_object_multi_select",
            "mount_policy": "manual",
            "independent_of": "derived_strategy",
            "empty_value": "no_filter",
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
        _contract(application=application, app=app),
    )


__all__ = ["register_strategy_editor_contract"]
