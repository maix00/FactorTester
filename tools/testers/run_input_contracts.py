"""Pure declarations for source-backed Job input controls.

This module imports no settings registry. Executable backtest modules are
loaded while that registry is assembled, so shared UI contracts must remain
free of registration side effects.
"""

from __future__ import annotations


FACTOR_SOURCE_INPUT = {
    "kind": "factor_source",
    "label": "上传临时因子源码",
    "description": "上传阶段不进入因子库；提交后作为任务输入保留，清空任务文件时一并删除",
    "accept": ".py,text/x-python",
    "extensions": (".py",),
    "multiple": False,
    "inspect_endpoint": "/api/factor-library/families/validate",
    "path_prefix": "custom_factors",
}


CUSTOM_STRATEGY_INPUTS = (
    {
        "kind": "strategy_source",
        "label": "上传策略 Hook",
        "description": "上传包含 on_start、on_bar、on_quote 或订单/持仓回调的自定义策略源码；提交后随 Job 冻结保存",
        "accept": ".py,text/x-python",
        "extensions": (".py",),
        "multiple": False,
        "inspect_endpoint": "/api/run-inputs/strategy/inspect",
        "path_prefix": "strategies",
    },
    {
        "kind": "strategy_spec",
        "label": "导入策略配置",
        "accept": ".json,application/json",
        "extensions": (".json",),
        "multiple": False,
        "inspect_endpoint": "/api/run-inputs/strategy/inspect",
    },
)

RUN_DEPENDENCY_INPUTS = (
    {
        "kind": "run_dependency",
        "label": "添加依赖文件",
        "accept": ".cfg,.csv,.ini,.json,.md,.py,.toml,.txt,.yaml,.yml,text/*",
        "extensions": (
            ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml",
            ".txt", ".yaml", ".yml",
        ),
        "multiple": True,
        "analyses": ("backtest",),
        "default_purpose": "strategy_configuration",
        "purpose_by_extension": {".py": "strategy_dependency"},
        "content_types": {
            ".csv": "text/csv",
            ".json": "application/json",
            ".md": "text/markdown",
            ".py": "text/x-python",
            ".toml": "application/toml",
            ".yaml": "application/yaml",
            ".yml": "application/yaml",
        },
        "purposes": (
            {"value": "", "label": "自动识别"},
            {
                "value": "strategy_configuration", "label": "策略配置",
                "path_prefix": "strategy-configs",
            },
            {
                "value": "strategy_dependency", "label": "策略依赖",
                "path_prefix": "strategy-configs",
            },
            {
                "value": "run_configuration", "label": "运行配置",
                "path_prefix": "run-configs",
            },
            {
                "value": "data_mapping", "label": "数据映射",
                "path_prefix": "data-mappings",
            },
            {
                "value": "documentation", "label": "说明文档",
                "path_prefix": "documentation",
            },
            {"value": "other", "label": "其他", "path_prefix": "run-inputs"},
        ),
    },
)

RUN_INPUTS = CUSTOM_STRATEGY_INPUTS + RUN_DEPENDENCY_INPUTS


def factor_source_content_options() -> dict:
    return {"inputs": (dict(FACTOR_SOURCE_INPUT),)}
