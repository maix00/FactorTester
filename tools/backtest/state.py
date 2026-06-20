"""世界状态 — equity, quantities, cash 等跨期可变状态。

事件驱动层逐期读写这些状态，构成马尔可夫链。
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class WorldState:
    """回测期间逐期推进的世界状态。

    维度约定：
    - M: 分组数
    - P: 品种数
    - T: 总期数
    """

    # === 当前状态 ===
    equity: np.ndarray = field(default_factory=lambda: np.array([]))
    """(M,) 每组当前净值"""

    quantities: np.ndarray = field(default_factory=lambda: np.array([]))
    """(M, P) 每组每品种当前持仓手数"""

    cash: np.ndarray = field(default_factory=lambda: np.array([]))
    """(M,) 每组当前现金"""

    # === 历史记录（逐期追加） ===
    equity_history: list[np.ndarray] = field(default_factory=list)
    """list of (M,) — 每期净值快照"""

    quantities_history: list[np.ndarray] = field(default_factory=list)
    """list of (M, P) — 每期持仓快照"""

    pnl_history: list[np.ndarray] = field(default_factory=list)
    """list of (M,) — 每期盈亏"""

    fee_history: list[np.ndarray] = field(default_factory=list)
    """list of (M,) — 每期费用"""

    # === 配置 ===
    initial_capital: float = 100_000_000.0

    def init(self, M: int, P: int, initial_capital: float | None = None) -> None:
        """初始化状态。"""
        if initial_capital is not None:
            self.initial_capital = initial_capital
        self.equity = np.full(M, self.initial_capital, dtype=float)
        self.quantities = np.zeros((M, P), dtype=float)
        self.cash = np.full(M, self.initial_capital, dtype=float)
        self.equity_history.clear()
        self.quantities_history.clear()
        self.pnl_history.clear()
        self.fee_history.clear()

    def snapshot(self) -> None:
        """保存当前状态到历史记录。"""
        self.equity_history.append(self.equity.copy())
        self.quantities_history.append(self.quantities.copy())
