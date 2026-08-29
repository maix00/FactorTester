"""Compose the backend-owned IC core and auxiliary-analysis registry."""

from functools import lru_cache

from tools.testers.analysis_graph import AnalysisGraphDefinition, CoreTestDefinition
from tools.testers.ic_test.core import IC_CORE_AXES, IC_CORE_OUTPUT_KINDS

from .registration import builtin_ic_analyses, ic_core_axis_definitions


def ic_configuration_group_schema() -> dict:
    """Return the canonical authoring contract for one IC configuration group."""
    return {
        "type": "object",
        "required": [
            "config_group_id", "batch_id", "name", "factor_ref",
            "product_scope_ref", "entry_delay_bars", "horizon", "methods",
            "return_price_basis",
        ],
        "properties": {
            "config_group_id": {
                "type": "string", "minLength": 1, "title": "配置组 ID",
            },
            "batch_id": {"type": "string", "minLength": 1, "title": "批次 ID"},
            "name": {"type": "string", "minLength": 1, "title": "名称"},
            "factor_ref": {
                "type": "string", "minLength": 1, "title": "因子",
                "pattern": r"factor:v2:[A-Za-z0-9_-]{43}",
            },
            "product_scope_ref": {
                "type": "string", "minLength": 1, "title": "产品组",
                "format": "product-scope-ref",
            },
            "entry_delay_bars": {
                "type": "integer", "minimum": 0, "title": "入场延迟",
            },
            "horizon": {
                "type": "object", "title": "前瞻收益期",
                "required": ["sampling"],
                "properties": {
                    "sampling": {
                        "type": "string", "enum": ["scale_aware", "explicit"],
                    },
                    "bases": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "multipliers": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
                "additionalProperties": False,
            },
            "methods": {
                "type": "array", "minItems": 1, "title": "IC 类型",
                "items": {"enum": ["rank", "pearson"]},
            },
            "return_price_basis": {
                "type": "string", "title": "收益价格基准",
                "enum": [
                    "next_open_to_open_adjusted", "next_close_to_close_adjusted",
                ],
            },
            "analysis_attachments": {
                "type": "array", "maxItems": 0, "title": "附加分析（当前禁用）",
            },
            "factor_source_selections": {"type": "array", "title": "因子来源"},
            "factor_set_selections": {"type": "array", "title": "因子集合来源"},
            "editor_mounted_tabs": {
                "type": "array", "title": "已挂载设置",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


@lru_cache(maxsize=1)
def ic_analysis_graph_definition() -> AnalysisGraphDefinition:
    """Return the sole backend-owned IC analysis registry."""

    return AnalysisGraphDefinition(
        key="ic_analysis_graph",
        label="IC 核心测试与附加分析",
        core_test=CoreTestDefinition(
            label="核心 IC 测试",
            axes=IC_CORE_AXES,
            output_kinds=IC_CORE_OUTPUT_KINDS,
            axis_definitions=ic_core_axis_definitions(),
        ),
        analysis_types=builtin_ic_analyses(),
        authoring_contract={
            "schema_version": 1,
            "core_tests_key": "core_tests",
            "analyses_key": "analyses",
            "factor_subject_refs_key": "factor_subject_refs",
            "output_requests_key": "output_requests",
            "configuration_group_schema": ic_configuration_group_schema(),
        },
    )


__all__ = ["ic_analysis_graph_definition", "ic_configuration_group_schema"]
