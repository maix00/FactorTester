"""Single-factor family test — 测试模块注册中心。

管理页面上显示的每个测试模块（单因子测试、分组回测、IC测试、
因子评估、因子类型分析）。
"""

from __future__ import annotations

from tools.testers.registry import ModuleRegistry
from .modules import (
    SingleFactorTestModule,
    GroupTestModule,
    ICTestModule,
    FactorEvaluationModule,
    FactorTypeAnalysisModule,
)


class SingleFactorFamilyTestModuleRegistry(ModuleRegistry):
    """single_factor_page 页面的测试模块注册中心。

    每个测试模块是一个 Module，包含 executor + app 两个维度。
    """

    def __init__(self) -> None:
        super().__init__()
        self.register(SingleFactorTestModule())
        self.register(GroupTestModule())
        self.register(ICTestModule())
        self.register(FactorEvaluationModule())
        self.register(FactorTypeAnalysisModule())

