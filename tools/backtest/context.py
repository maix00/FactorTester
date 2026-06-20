"""回测上下文 — 事件之间传递的共享数据。

分为两部分：
1. 预计算矩阵（只读）— 向量化层一次性产出
2. 可变数据槽（读写）— 事件驱动层逐期更新
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class BacktestContext:
    """在 BacktestEvent 之间传递的共享上下文。"""

    # === 向量化预计算（只读） ===
    returns_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, P) 收益率矩阵"""

    membership_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, M, P) 分组归属矩阵"""

    factor_values: dict = field(default_factory=dict)
    """factor_name → (T, P) 预计算因子值"""

    fee_rate_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, P) 预计算费率矩阵"""

    margin_ratio_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, P) 保证金率矩阵"""

    price_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, P) 价格矩阵"""

    tradable_mask_mat: np.ndarray = field(default_factory=lambda: np.array([]))
    """(T, P) 可交易掩码"""

    # === 品种元数据（只读） ===
    point_values: np.ndarray = field(default_factory=lambda: np.array([]))
    """(P,) 合约乘数"""

    min_ticks: np.ndarray = field(default_factory=lambda: np.array([]))
    """(P,) 最小变动价位"""

    lot_sizes: np.ndarray = field(default_factory=lambda: np.array([]))
    """(P,) 最小交易手数"""

    # === 维度信息（只读） ===
    T: int = 0
    M: int = 0
    P: int = 0

    # === 可变数据槽（事件层读写） ===
    config: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stop: bool = False
