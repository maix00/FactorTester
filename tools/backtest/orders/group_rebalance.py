"""分组调仓策略 — 从现有 simulate_group_trading_book 提取的核心逻辑。

支持多种调仓模式：
- each_period: 每期全额重新分配
- buy_and_hold: 买入持有，持仓品种不退出
- recycle: 已有持仓不退出时禁止新开仓
"""

import numpy as np


class GroupRebalanceStrategy:
    """分组调仓订单执行策略。

    对应现有 simulate_group_trading_book 中的 build_target_amounts +
    hold/recycle 逻辑。
    """

    def __init__(self, mode: str = "each_period"):
        """
        Args:
            mode: 调仓模式 — "each_period" | "buy_and_hold" | "recycle"
        """
        self.mode = mode

    def generate(
        self,
        membership: np.ndarray,      # (M, P)
        state: "WorldState",          # noqa: F821
        ctx: "BacktestContext",       # noqa: F821
    ) -> np.ndarray:
        """根据 membership 和当前状态生成 desired_quantities。

        简化实现 — 完整逻辑将逐步从 simulate_group_trading_book 迁移。
        """
        M, P = membership.shape
        desired = np.where(membership, 1.0, 0.0)

        if self.mode in ("buy_and_hold", "recycle"):
            current_positive = state.quantities > 0
            staying_mask = membership & current_positive
            # 保留已有持仓
            desired = np.where(staying_mask, state.quantities, desired)
            if self.mode == "recycle":
                # recycle: 已有持仓没退出 → 不新开仓
                entering_mask = membership & (~current_positive)
                has_existing = np.any(current_positive, axis=1)
                has_exiting = np.any(current_positive & (~membership), axis=1)
                freeze = has_existing & (~has_exiting)
                desired[freeze] = np.where(entering_mask[freeze], 0.0, desired[freeze])

        return desired
