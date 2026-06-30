"""FactorModule — declares the `factor` field every strategy's signal
generation reads from. Field declaration only; FactorSignalModule (this
package's factor_signal.py) owns the Flows that actually use it."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


class FactorModule(ExecutableModule):
    key: ClassVar[str] = "factor"
    label: ClassVar[str] = "因子"
    order: ClassVar[int] = 20

    factor: ClassVar[FieldRef[Any]] = FieldRef("factor")  # a FactorExpr (tools.factors.expr.core.FactorExpr)
    factor_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_candidates")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "factor_candidates": FieldDefinition(
            public=True, default=[], control_template="custom", tab="factor",
            chip_template="因子候选: {value}", tab_label="因子执行", tab_order=20,
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
            serialization={
                "kind": "factor_candidate_list",
                "display_order": 10,
                "item_kind": "factor",
                "shared_page_field": "factor_candidates",
                "selection_field": "factor",
                "factor_library_source": "user_factor_library_overview",
                "fallback_policy": (
                    "copy_page_candidates",
                    "load_factor_library_when_page_empty",
                ),
                "id_keys": ("alias", "name", "factor_alias"),
                "label_keys": ("alias", "name", "label"),
                "mutation_scope": {
                    "page": "page_candidates_only",
                    "module": "module_candidates_only",
                },
            },
        ),
        "factor": FieldDefinition(
            public=True, default="", control_template="select", tab="factor",
            chip_template="因子: {value}", tab_label="因子执行", tab_order=20,
            info_overlay={"type": "factor_info"},
            serialization={
                "kind": "factor_selection",
                "display_order": 20,
                "candidate_field": "factor_candidates",
                "shared_page_field": "factor",
                "id_keys": ("alias", "name", "factor_alias"),
                "label_keys": ("alias", "name", "label"),
            },
        ),
    }
