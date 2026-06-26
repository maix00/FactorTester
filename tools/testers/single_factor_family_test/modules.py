"""单因子家族测试页面 — 各测试模块定义。

每个 Module = key + label + order + executor(可选) + app(可选)。
"""

from __future__ import annotations

from tools.testers.settings.applications import (
    single_factor_page_settings,
    group_test_settings,
    ic_test_settings,
    factor_evaluation_settings,
    factor_type_analysis_settings,
)


class _BaseModule:
    """Module 基类：key + label + order + executor + app"""

    key: str = ""
    label: str = ""
    order: int = 0
    executor: type | None = None

    @property
    def app(self):
        if not hasattr(self, "_app") or self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self):
        raise NotImplementedError


class SingleFactorTestModule(_BaseModule):
    key = "single_factor_page"
    label = "单因子测试"
    order = 10

    def _build_app(self):
        return single_factor_page_settings()


class GroupTestModule(_BaseModule):
    key = "group_test"
    label = "分组回测"
    order = 20

    def _build_app(self):
        return group_test_settings()


class ICTestModule(_BaseModule):
    key = "ic_test"
    label = "IC 测试"
    order = 30

    def _build_app(self):
        return ic_test_settings()


class FactorEvaluationModule(_BaseModule):
    key = "factor_evaluation"
    label = "因子评估"
    order = 40

    def _build_app(self):
        return factor_evaluation_settings()


class FactorTypeAnalysisModule(_BaseModule):
    key = "factor_type_analysis"
    label = "因子类型分析"
    order = 50

    def _build_app(self):
        return factor_type_analysis_settings()
