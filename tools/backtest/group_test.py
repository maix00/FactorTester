"""GroupTest — 分组回测整体模型。

将现有的 simulate_group_trading_book() 逻辑重构为：
- GroupTest Model（整体编排）
  - FeeModel   — 费率核算（open/close fixed+ratio）
  - MarginModel — 保证金占用（long_margin_ratio × 名义市值）
  - LiquidityModel — 流动性约束（percent of equity × capacity share）
  - ProductModel — 品种元数据（point_value, min_tick, lot_size, contract_value）
  - OrderStrategy — 订单执行（each_period / buy_and_hold / recycle）

事件驱动模式下（有摩擦）：
  GroupTest.run_des(ctx) → EventDrivenEngine.run()

纯向量化模式下（无摩擦）：
  GroupTest.run_vectorized(ctx) → 矩阵乘法直接计算 P&L
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from tools.backtest.context import BacktestContext
from tools.backtest.engine import EventDrivenEngine
from tools.backtest.events import BacktestEvent, EventCategory
from tools.backtest.state import WorldState


# ============================================================
# 默认 Model 实现（纯向量化，符合现有协议）
# ============================================================

class FlatFeeModel:
    """统一费率模型 — 每品种 (open_rate, close_rate, open_fixed, close_fixed)。"""

    def __init__(
        self,
        open_rate_mat: np.ndarray,      # (M, P) or (P,)
        close_rate_mat: np.ndarray,     # (M, P) or (P,)
        open_fixed_mat: np.ndarray,     # (M, P) or (P,)
        close_fixed_mat: np.ndarray,    # (M, P) or (P,)
    ):
        self.open_rate_mat = np.atleast_2d(open_rate_mat)
        self.close_rate_mat = np.atleast_2d(close_rate_mat)
        self.open_fixed_mat = np.atleast_2d(open_fixed_mat)
        self.close_fixed_mat = np.atleast_2d(close_fixed_mat)

    def compute(
        self,
        buy_notional: np.ndarray,       # (M, P) 买入名义金额
        sell_notional: np.ndarray,      # (M, P) 卖出名义金额
        ctx: Optional[BacktestContext] = None,
    ) -> np.ndarray:
        """计算费用 = buy * open_rate + sell * close_rate + fixed costs."""
        fees = np.zeros_like(buy_notional)
        fees += buy_notional * self.open_rate_mat + self.open_fixed_mat * (buy_notional > 0)
        fees += sell_notional * self.close_rate_mat + self.close_fixed_mat * (sell_notional > 0)
        return fees


class SimpleMarginModel:
    """简易保证金模型 — long_margin_ratio × 名义市值。"""

    def __init__(self, margin_ratio_mat: np.ndarray, is_margin_flags: np.ndarray):
        """
        Args:
            margin_ratio_mat: (M, P) 保证金率
            is_margin_flags: (P,) 哪些品种保证金交易
        """
        self.margin_ratio_mat = np.atleast_2d(margin_ratio_mat)
        self.is_margin_flags = np.asarray(is_margin_flags, dtype=bool)

    def occupy(
        self,
        position_notional: np.ndarray,  # (M, P)
        ctx: Optional[BacktestContext] = None,
    ) -> np.ndarray:
        """返回 (M,) 每组总保证金占用。"""
        margin_mask = self.is_margin_flags[np.newaxis, :]
        return np.nansum(
            np.where(margin_mask, np.abs(position_notional) * self.margin_ratio_mat, 0.0),
            axis=1,
        )


class PercentLiquidityModel:
    """百分比流动性模型 — 限制单品种交易不超过 equity × percent × capacity_share。"""

    def __init__(
        self,
        capacity_mat: np.ndarray,       # (T, P) 横截面流动性份额
        percent: float,                  # 总交易上限（如 0.20 = 20%）
    ):
        self.capacity_mat = np.asarray(capacity_mat, dtype=float)
        self.percent = float(percent)

    def cap(
        self,
        desired_notional: np.ndarray,   # (M, P) 目标名义金额
        current_notional: np.ndarray,   # (M, P) 当前名义金额
        equity: np.ndarray,             # (M,)
        t: int,
        ctx: Optional[BacktestContext] = None,
    ) -> np.ndarray:
        """返回流动性裁剪后的名义金额。"""
        if self.percent >= 1.0 or t >= len(self.capacity_mat):
            return desired_notional
        base_cap = self.capacity_mat[t] * equity[:, np.newaxis] * self.percent
        return np.minimum(desired_notional, base_cap)


class ProductMetaModel:
    """品种元数据模型 — 合约乘数、最小变动价位、最小手数。"""

    def __init__(
        self,
        point_values: np.ndarray,       # (P,)
        min_ticks: np.ndarray,          # (P,)
        lot_sizes: np.ndarray,          # (P,)
    ):
        self.point_values = np.asarray(point_values, dtype=float).flatten()
        self.min_ticks = np.asarray(min_ticks, dtype=float).flatten()
        self.lot_sizes = np.asarray(lot_sizes, dtype=float).flatten()
        # Fallback to 1.0 for non-positive
        self.point_values = np.where(
            np.isfinite(self.point_values) & (self.point_values > 0),
            self.point_values, 1.0,
        )
        self.lot_sizes = np.where(
            np.isfinite(self.lot_sizes) & (self.lot_sizes > 0),
            self.lot_sizes, 1.0,
        )

    def price_round(self, prices: np.ndarray) -> np.ndarray:
        """min_tick 规整。"""
        px = np.asarray(prices, dtype=float)
        valid_tick = np.isfinite(self.min_ticks) & (self.min_ticks > 0)
        rounded = px.copy()
        flat_ticks = np.broadcast_to(self.min_ticks, px.shape[-1:])
        if valid_tick.any():
            tick_vals = flat_ticks[valid_tick]
            if rounded.ndim == 1:
                rounded[valid_tick] = np.round(px[valid_tick] / tick_vals) * tick_vals
            else:
                rounded[:, valid_tick] = np.round(px[:, valid_tick] / tick_vals) * tick_vals
        no_tick = np.isfinite(px) & (~np.broadcast_to(valid_tick, px.shape))
        rounded[no_tick] = np.round(px[no_tick], 2)
        return np.where(np.isfinite(rounded) & (rounded > 0), rounded, np.nan)

    def quantity_round(self, quantities: np.ndarray) -> np.ndarray:
        """lot_size 取整（向下取到整数倍）。"""
        qty = np.asarray(quantities, dtype=float)
        sizes = np.broadcast_to(self.lot_sizes, qty.shape[-1:])
        return np.floor(qty / sizes) * sizes


# ============================================================
# GroupTest — 整体回测模型
# ============================================================

class GroupTest:
    """分组回测整体模型。

    整合费率、保证金、流动性、品种元数据、订单执行五大模块，
    提供 run_des()（事件驱动）和 run_vectorized()（纯向量化）两种后端。

    Usage:
        gt = GroupTest(
            membership_np=...,
            returns_np=...,
            price_np=...,
            fee_model=FlatFeeModel(...),
            margin_model=SimpleMarginModel(...),
            liquidity_model=PercentLiquidityModel(...),
            product_model=ProductMetaModel(...),
            rebalance_modes=["each_period", "buy_and_hold"],
        )
        result = gt.run()  # 自动选 DES 或 向量化
    """

    def __init__(
        self,
        *,
        membership_np: np.ndarray,          # (T, M, P)
        returns_np: np.ndarray,             # (T, P)
        price_np: np.ndarray,               # (T, P)
        fee_model: FlatFeeModel | None = None,
        margin_model: SimpleMarginModel | None = None,
        liquidity_model: PercentLiquidityModel | None = None,
        product_model: ProductMetaModel | None = None,
        rebalance_modes: list[str] | np.ndarray | None = None,
        initial_capital: float = 100_000_000.0,
        tradable_mask_np: np.ndarray | None = None,
    ):
        self.membership_np = np.asarray(membership_np)
        self.returns_np = np.asarray(returns_np, dtype=float)
        self.price_np = np.asarray(price_np, dtype=float)
        self.T, self.M, self.P = self.membership_np.shape

        if self.returns_np.shape != (self.T, self.P):
            raise ValueError(
                f"returns_np shape {self.returns_np.shape} != ({self.T}, {self.P})"
            )
        if self.price_np.shape != (self.T, self.P):
            raise ValueError(
                f"price_np shape {self.price_np.shape} != ({self.T}, {self.P})"
            )

        self.fee_model = fee_model
        self.margin_model = margin_model
        self.liquidity_model = liquidity_model
        self.product_model = product_model or ProductMetaModel(
            point_values=np.ones(self.P),
            min_ticks=np.zeros(self.P),
            lot_sizes=np.ones(self.P),
        )
        self.rebalance_modes = (
            np.asarray(rebalance_modes, dtype=object)
            if rebalance_modes is not None
            else np.full(self.M, "each_period", dtype=object)
        )
        self.initial_capital = float(initial_capital)
        self.tradable_mask_np = tradable_mask_np

    # ----------------------------------------------------------
    # 便捷：判断是否有摩擦
    # ----------------------------------------------------------

    @property
    def has_friction(self) -> bool:
        """是否有任何摩擦（费率/保证金/流动性）。"""
        return (
            self.fee_model is not None
            or self.margin_model is not None
            or self.liquidity_model is not None
        )

    # ----------------------------------------------------------
    # 主入口：自动选择后端
    # ----------------------------------------------------------

    def run(self) -> dict:
        """运行回测 — 无摩擦走向量化，有摩擦走事件驱动。"""
        if self.has_friction:
            return self.run_des()
        else:
            return self.run_vectorized()

    # ----------------------------------------------------------
    # 纯向量化路径（无摩擦）
    # ----------------------------------------------------------

    def run_vectorized(self) -> dict:
        """纯向量化分组回测：P&L = membership @ returns（一期矩阵乘法）。"""
        T, M, P = self.T, self.M, self.P
        membership = self.membership_np.astype(float)

        # 每期每组的成员数
        counts = membership.sum(axis=2)  # (T, M)
        counts_safe = np.where(counts > 0, counts, 1.0)

        # 等权分配 + 收益率
        weights = np.divide(
            membership,
            counts_safe[:, :, np.newaxis],
            where=counts_safe[:, :, np.newaxis] > 0,
        )
        # (T, M, P) @ (T, 1, P).T via sum over P
        net_returns = np.sum(weights * self.returns_np[:, np.newaxis, :], axis=2)  # (T, M)

        # NaN/inf 处理
        net_returns = np.where(
            np.isfinite(net_returns) & (net_returns > -1.0),
            net_returns,
            0.0,
        )

        # 累计净值：每期 returns 是收益率（相对于期初），cumulative = cumprod(1 + ret)
        cumulative_returns = np.cumprod(1.0 + net_returns, axis=0)

        equity = self.initial_capital * cumulative_returns  # (T, M)

        return {
            "net_returns_np": net_returns,
            "cumulative_returns_np": cumulative_returns,
            "equity_np": equity,
            "fee_costs_np": np.zeros((T, M)),
            "gross_returns_np": net_returns.copy(),
            "position_quantities_np": weights * self.initial_capital,
            "prev_end_amounts_np": np.zeros((T, M, P)),
            "total_equity_np": equity,
            "cash_np": np.zeros((T, M)),
            "margin_occupied_np": np.zeros((T, M)),
            "multi_session_triggered": 0,
        }

    # ----------------------------------------------------------
    # 事件驱动路径（有摩擦）
    # ----------------------------------------------------------

    def run_des(self) -> dict:
        """事件驱动分组回测 — DES 引擎逐期推进状态。

        主循环：for t in 0..T-1:
          1. MARKET_DATA   → 切片第 t 期价格/收益/membership
          2. SIGNAL        → 生成目标持仓（OrderStrategy）
          3. FEE           → 核算费用（FeeModel）
          4. MARGIN        → 保证金占用（MarginModel）
          5. LIQUIDITY     → 流动性裁剪（LiquidityModel）
          6. PNL           → 盯市盈亏
        """
        T, M, P = self.T, self.M, self.P
        pm = self.product_model

        # ---- 初始化状态 ----
        equity = np.full(M, self.initial_capital, dtype=float)
        quantities = np.zeros((M, P), dtype=float)
        amounts = np.zeros((M, P), dtype=float)  # 名义持仓

        # ---- 输出矩阵 ----
        net_returns_np = np.zeros((T, M), dtype=float)
        fee_costs_np = np.zeros((T, M), dtype=float)
        gross_returns_np = np.zeros((T, M), dtype=float)
        product_gross_contrib_np = np.zeros((T, M, P), dtype=float)
        product_fee_contrib_np = np.zeros((T, M, P), dtype=float)
        prev_end_amounts_np = np.zeros((T, M, P), dtype=float)
        position_quantities_np = np.zeros((T, M, P), dtype=float)
        margin_occupied_np = np.zeros((T, M), dtype=float)
        total_equity_np = np.zeros((T, M), dtype=float)
        cash_np = np.zeros((T, M), dtype=float)

        rebalance_arr = self.rebalance_modes
        hold_rows = np.isin(rebalance_arr, ["buy_and_hold", "recycle"])
        recycle_rows = rebalance_arr == "recycle"

        for t in range(T):
            # ---- 1. MARKET_DATA ----
            price_t = pm.price_round(self.price_np[t])
            returns_t = self.returns_np[t]   # (P,) 当期收益率
            membership_t = self.membership_np[t]  # (M, P) bool

            tradable = np.isfinite(price_t) & (price_t > 0)
            if self.tradable_mask_np is not None:
                tradable = tradable & self.tradable_mask_np[t]

            contract_value = price_t * pm.point_values
            contract_value = np.where(
                tradable & np.isfinite(contract_value) & (contract_value > 0),
                contract_value, np.nan,
            )

            # ---- 2. SIGNAL → target_notional ----
            target_notional = self._build_targets(
                membership_t, amounts, equity, t, tradable, contract_value,
            )

            # ---- 3. LIQUIDITY（在 target 之后、fee 之前）----
            if self.liquidity_model is not None:
                target_notional = self.liquidity_model.cap(
                    target_notional, amounts, equity, t,
                )

            # ---- 4. FEE ----
            delta_notional = target_notional - amounts
            buy_notional = np.clip(delta_notional, 0.0, None)
            sell_notional = np.clip(-delta_notional, 0.0, None)

            if self.fee_model is not None:
                fees_t = self.fee_model.compute(buy_notional, sell_notional)
            else:
                fees_t = np.zeros((M, P))

            # ---- 5. MARGIN ----
            if self.margin_model is not None:
                margin_t = self.margin_model.occupy(target_notional)
            else:
                margin_t = np.zeros(M)

            # ---- 6. 执行交易 ----
            amounts = target_notional
            raw_qty = np.divide(
                amounts,
                contract_value[np.newaxis, :],
                out=np.zeros_like(amounts),
                where=np.isfinite(contract_value[np.newaxis, :]) & (contract_value[np.newaxis, :] > 0),
            )
            quantities = pm.quantity_round(raw_qty)

            # hold/recycle modes
            if hold_rows.any():
                current_positive = quantities > 0
                staying = membership_t & current_positive
                quantities[hold_rows] = np.where(
                    staying[hold_rows],
                    quantities[hold_rows],
                    quantities[hold_rows],
                )
                if recycle_rows.any():
                    entering = membership_t & (~current_positive)
                    has_existing = np.any(current_positive, axis=1)
                    has_exiting = np.any(current_positive & (~membership_t), axis=1)
                    freeze = recycle_rows & has_existing & (~has_exiting)
                    quantities[freeze] = np.where(
                        entering[freeze], 0.0, quantities[freeze],
                    )

            # ---- 7. PNL ----
            # 持仓收益 = amounts * returns_t (名义 × 收益率)
            pnl_gross = np.nansum(amounts * returns_t[np.newaxis, :], axis=1)  # (M,)
            fees_per_group = np.nansum(fees_t, axis=1)
            pnl_net = pnl_gross - fees_per_group

            equity = equity + pnl_net

            # 记录
            prev_end_amounts_np[t] = amounts
            position_quantities_np[t] = quantities
            gross_returns_np[t] = pnl_gross / self.initial_capital
            net_returns_np[t] = pnl_net / self.initial_capital
            fee_costs_np[t] = fees_per_group / self.initial_capital
            product_gross_contrib_np[t] = amounts * returns_t[np.newaxis, :] / self.initial_capital
            product_fee_contrib_np[t] = fees_t / self.initial_capital
            margin_occupied_np[t] = margin_t
            total_equity_np[t] = equity
            cash_np[t] = equity - np.nansum(amounts, axis=1)

        return {
            "net_returns_np": net_returns_np,
            "gross_returns_np": gross_returns_np,
            "product_gross_contrib_np": product_gross_contrib_np,
            "product_fee_contrib_np": product_fee_contrib_np,
            "fee_costs_np": fee_costs_np,
            "prev_end_amounts_np": prev_end_amounts_np,
            "position_quantities_np": position_quantities_np,
            "margin_occupied_np": margin_occupied_np,
            "total_equity_np": total_equity_np,
            "cash_np": cash_np,
            "multi_session_triggered": 0,
        }

    # ----------------------------------------------------------
    # Internal: target builder (simplified)
    # ----------------------------------------------------------

    def _build_targets(
        self,
        membership_t: np.ndarray,       # (M, P) bool
        current_amounts: np.ndarray,    # (M, P)
        equity: np.ndarray,             # (M,)
        t: int,
        tradable: np.ndarray,           # (P,)
        contract_value: np.ndarray,     # (P,)
    ) -> np.ndarray:
        """构建当期目标名义金额。

        支持 each_period / buy_and_hold / recycle，含 close fee 扣除。
        """
        M, P = membership_t.shape
        executable = membership_t & tradable[np.newaxis, :]
        counts = executable.sum(axis=1).astype(float)

        targets = np.zeros((M, P), dtype=float)
        non_empty = counts > 0

        # each_period: 等权分配（含 sell fee）
        if self.fee_model is not None:
            close_fee = self.fee_model.close_rate_mat[:M, :P]
            # 卖出费 = 当前持仓中退出品种的 close fee
            exiting = (current_amounts > 0) & (~executable)
            sell_fee = np.nansum(current_amounts * exiting * close_fee, axis=1)
            available_wealth = np.maximum(0.0, equity - sell_fee)
        else:
            available_wealth = equity

        if non_empty.any():
            targets[non_empty] = (
                executable[non_empty].astype(float)
                * (available_wealth[non_empty] / counts[non_empty])[:, np.newaxis]
            )

        # buy_and_hold / recycle
        rebalance_arr = self.rebalance_modes
        hold_rows = np.isin(rebalance_arr, ["buy_and_hold", "recycle"])
        recycle_rows = rebalance_arr == "recycle"

        if hold_rows.any() and t > 0:
            staying = membership_t & (current_amounts > 0)
            entering = membership_t & (current_amounts == 0)
            # 保留持仓
            targets[hold_rows] = np.where(
                staying[hold_rows],
                current_amounts[hold_rows],
                targets[hold_rows],
            )
            # recycle: 有持仓无退出 → 不新开
            if recycle_rows.any():
                has_existing = np.any(current_amounts > 0, axis=1)
                has_exiting = np.any(
                    (current_amounts > 0) & (~membership_t), axis=1,
                )
                freeze = recycle_rows & has_existing & (~has_exiting)
                targets[freeze] = np.where(
                    entering[freeze], 0.0, targets[freeze],
                )

        return targets
