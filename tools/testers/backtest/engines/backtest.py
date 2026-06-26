"""Backtest 整体模型 — 事件驱动 DES + 向量化预计算混合架构。

对标 simulate_group_trading_book()（~300 行硬编码），提供：
- 统一 Backtest.run() 入口
- 可注入 FeeModel / MarginModel / LiquidityModel / ProductModel / OrderStrategy
- 无摩擦快速路径（纯向量化）
- BacktestResult 输出与现有 GroupRunResult 兼容
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .clock import SimulationClock
from .context import BacktestContext
from .engine import EventDrivenEngine
from .events import BacktestEvent, EventCategory
from .event_queue import EventQueue
from .models.fee_model import FeeModel, FlatFeeModel
from .models.margin_model import FixedRatioMarginModel, MarginModel
from .models.liquidity_model import ExecutableCapacityModel, LiquidityModel
from .models.product_model import CtxProductModel, ProductModel
from .orders.group_rebalance import GroupRebalanceStrategy
from .orders.order_strategy import OrderStrategy
from .state import WorldState


@dataclass
class BacktestResult:
    """回测结果 — 对标 simulate_group_trading_book() 返回的 dict。

    所有数组形状: T=期数, M=组数, P=品种数。
    """

    # --- 收益矩阵 ---
    net_returns_np: np.ndarray          # (M, T) 每组每期净收益
    gross_returns_np: np.ndarray        # (M, T) 每组每期毛收益（交易成本前）
    product_gross_contrib_np: np.ndarray  # (M, P, T) 每组每品种的毛收益贡献
    product_fee_contrib_np: np.ndarray  # (M, P, T) 每组每品种的费用贡献

    # --- 费用 ---
    fee_costs_np: np.ndarray            # (M, T) 每组每期总费用

    # --- 交易量 ---
    trade_notional_ratio_np: np.ndarray  # (M, T) 每组每期换手率

    # --- 持仓 ---
    position_quantities_np: np.ndarray  # (M, P) 最后一期的持仓量

    # --- 权益 ---
    total_equity_np: np.ndarray         # (M, T) 每组每期总权益
    cash_np: np.ndarray                 # (M, T) 每组每期现金

    # --- 保证金 ---
    margin_occupied_np: np.ndarray      # (M, T) 每组每期保证金占用

    # --- 元信息 ---
    multi_session_triggered: int        # 多时段品种触发次数

    # 上一期持仓额（用于 GroupRunResult.hold_amounts_np）
    prev_end_amounts_np: np.ndarray | None = None

    def as_dict(self) -> dict[str, Any]:
        """转换为 dict（兼容现有 simulate_group_trading_book 返回值）。"""
        return {
            'net_returns_np': self.net_returns_np,
            'gross_returns_np': self.gross_returns_np,
            'product_gross_contrib_np': self.product_gross_contrib_np,
            'product_fee_contrib_np': self.product_fee_contrib_np,
            'fee_costs_np': self.fee_costs_np,
            'trade_notional_ratio_np': self.trade_notional_ratio_np,
            'position_quantities_np': self.position_quantities_np,
            'total_equity_np': self.total_equity_np,
            'cash_np': self.cash_np,
            'margin_occupied_np': self.margin_occupied_np,
            'multi_session_triggered': self.multi_session_triggered,
            'prev_end_amounts_np': self.prev_end_amounts_np,
        }


class Backtest:
    """整体回测模型 — 事件驱动 DES + 向量化预计算混合架构。

    用法::

        bt = Backtest(
            membership_np=..., returns_np=..., price_np=...,
            initial_capital=...,
            fee_model=FlatFeeModel(...),
            order_strategy=GroupRebalanceStrategy("each_period"),
        )
        result: BacktestResult = bt.run()

    无摩擦场景自动走纯向量化快速路径。
    """

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    def __init__(
        self,
        # --- 预计算矩阵（必需） ---
        membership_np: np.ndarray,       # (T, M, P) bool 成员 mask
        returns_np: np.ndarray,          # (T, P) 各品种每期收益率
        price_np: np.ndarray,            # (T, P) 各品种每期价格
        initial_capital: float = 1.0,
        # --- 可注入组件 ---
        fee_model: FeeModel | None = None,
        margin_model: MarginModel | None = None,
        liquidity_model: LiquidityModel | None = None,
        product_model: ProductModel | None = None,
        order_strategy: OrderStrategy | None = None,
        # --- 费率矩阵（供 FlatFeeModel 默认使用） ---
        open_ratio_mat: np.ndarray | None = None,       # (M, P) 开仓费率
        close_ratio_mat: np.ndarray | None = None,      # (M, P) 平仓费率
        open_fixed_mat: np.ndarray | None = None,       # (M, P) 开仓固定费
        close_fixed_mat: np.ndarray | None = None,      # (M, P) 平仓固定费
        # --- 保证金 ---
        margin_ratio_mat: np.ndarray | None = None,     # (M, P) 保证金率
        is_margin_traded_vec: np.ndarray | None = None, # (P,) 是否保证金品种
        # --- 流动性 ---
        liquidity_capacity_np: np.ndarray | None = None, # (T,) 或 (M, P) 流动性容限
        # --- 品种元数据 ---
        point_value_vec: np.ndarray | None = None,      # (P,) 合约乘数
        min_tick_vec: np.ndarray | None = None,         # (P,) 最小变动价位
        min_trade_quantity_vec: np.ndarray | None = None,  # (P,) 最小交易量
        # --- 多时段 ---
        multi_session_active: bool = False,
        # --- 元信息 ---
        factor_alias: str = "",
    ):
        self._membership = np.asarray(membership_np, dtype=bool)  # (T, M, P)
        self._returns = np.asarray(returns_np, dtype=float)        # (T, P)
        self._price = np.asarray(price_np, dtype=float)            # (T, P)
        self._initial_capital = float(initial_capital)

        T, M, P = self._membership.shape
        self._T = T
        self._M = M
        self._P = P

        # 时间索引
        self._index_list = list(range(T))

        # --- 组件构造（有则用，无则默认） ---
        self._fee_model = fee_model or FlatFeeModel(
            open_ratio_vec=open_ratio_mat[0] if open_ratio_mat is not None else None,
            open_fixed_vec=open_fixed_mat[0] if open_fixed_mat is not None else None,
            close_ratio_vec=close_ratio_mat[0] if close_ratio_mat is not None else None,
            close_fixed_vec=close_fixed_mat[0] if close_fixed_mat is not None else None,
        )
        self._margin_model = margin_model or FixedRatioMarginModel(
            margin_ratio_vec=margin_ratio_mat[0] if margin_ratio_mat is not None else None,
            is_margin_traded_vec=is_margin_traded_vec,
        )
        self._liquidity_model = liquidity_model or ExecutableCapacityModel(
            capacity_np=liquidity_capacity_np,
            open_ratio_mat=open_ratio_mat,
            close_ratio_mat=close_ratio_mat,
        )
        self._product_model = product_model or CtxProductModel()
        self._order_strategy = order_strategy or GroupRebalanceStrategy("each_period")

        # 存储矩阵引用（供默认 model 使用）
        self._open_ratio_mat = open_ratio_mat
        self._close_ratio_mat = close_ratio_mat
        self._open_fixed_mat = open_fixed_mat
        self._close_fixed_mat = close_fixed_mat
        self._margin_ratio_mat = margin_ratio_mat
        self._is_margin_traded_vec = is_margin_traded_vec
        self._liquidity_capacity_np = liquidity_capacity_np
        self._point_value_vec = point_value_vec
        self._min_tick_vec = min_tick_vec
        self._min_trade_quantity_vec = min_trade_quantity_vec
        self._multi_session_active = multi_session_active
        self._factor_alias = factor_alias

        # 判断是否有摩擦
        self._has_friction = self._detect_friction()

    # ------------------------------------------------------------------
    # 无摩擦检测
    # ------------------------------------------------------------------

    def _detect_friction(self) -> bool:
        """检测是否存在摩擦（费率/保证金/流动性约束）。"""
        # 费率
        for mat in [self._open_ratio_mat, self._close_ratio_mat,
                     self._open_fixed_mat, self._close_fixed_mat]:
            if mat is not None and np.any(mat > 0):
                return True

        # 保证金
        if self._margin_ratio_mat is not None and self._is_margin_traded_vec is not None:
            if np.any(self._is_margin_traded_vec) and np.any(self._margin_ratio_mat > 0):
                return True

        # 流动性
        if self._liquidity_capacity_np is not None and np.any(
            np.isfinite(self._liquidity_capacity_np) & (self._liquidity_capacity_np >= 0)
        ):
            return True

        return False

    # ------------------------------------------------------------------
    # 运行入口
    # ------------------------------------------------------------------

    def run(self) -> BacktestResult:
        """执行回测。

        无摩擦 → 纯向量化快速路径
        有摩擦 → 事件驱动 DES 路径
        """
        if not self._has_friction:
            return self._run_vectorized()
        return self._run_native()

    # ------------------------------------------------------------------
    # 纯向量化路径（无摩擦）
    # ------------------------------------------------------------------

    def _run_vectorized(self) -> BacktestResult:
        """无摩擦纯向量化路径: net_returns = membership @ returns。

        等价于 simulate_group_trading_book 在 all_fees_zero 时的行为。
        """
        T, M, P = self._T, self._M, self._P
        membership_t = self._membership  # (T, M, P)

        # --- 每期分组收益 ---
        gross_contrib = np.zeros((M, P, T), dtype=float)  # (M, P, T)
        net_returns = np.zeros((M, T), dtype=float)        # (M, T)
        gross_returns = np.zeros((M, T), dtype=float)      # (M, T)

        for t in range(T):
            rets = self._returns[t]  # (P,)
            mask = membership_t[t]   # (M, P)
            n_members = mask.sum(axis=1)  # (M,)

            contrib = np.zeros((M, P), dtype=float)
            with np.errstate(invalid='ignore'):
                contrib = np.where(
                    mask & (n_members[:, np.newaxis] > 0),
                    rets[np.newaxis, :] / n_members[:, np.newaxis],
                    0.0,
                )

            gross_contrib[:, :, t] = contrib
            net_returns[:, t] = contrib.sum(axis=1)
            gross_returns[:, t] = contrib.sum(axis=1)

        # --- 累计权益 ---
        cum_returns = np.cumprod(1.0 + net_returns, axis=1)  # (M, T)
        total_equity = self._initial_capital * cum_returns    # (M, T)

        # --- 持仓量（最后一期等权） ---
        last_mask = membership_t[-1]  # (M, P)
        last_counts = last_mask.sum(axis=1, keepdims=True)
        with np.errstate(invalid='ignore'):
            position_quantities = np.where(
                last_mask & (last_counts > 0),
                total_equity[-1, :][:, np.newaxis] / (last_counts * self._price[-1][np.newaxis, :]),
                0.0,
            )

        # --- 费用全为零 ---
        zeros_m_t = np.zeros((M, T), dtype=float)
        zeros_m_p_t = np.zeros((M, P, T), dtype=float)

        return BacktestResult(
            net_returns_np=net_returns,
            gross_returns_np=gross_returns,
            product_gross_contrib_np=gross_contrib,
            product_fee_contrib_np=zeros_m_p_t.copy(),
            fee_costs_np=zeros_m_t.copy(),
            trade_notional_ratio_np=zeros_m_t.copy(),
            position_quantities_np=position_quantities,
            total_equity_np=total_equity,
            cash_np=total_equity.copy(),
            margin_occupied_np=zeros_m_t.copy(),
            multi_session_triggered=0,
        )

    # ------------------------------------------------------------------
    # 事件驱动路径（有摩擦）
    # ------------------------------------------------------------------

    def _run_native(self) -> BacktestResult:
        """事件驱动 DES 回测。

        对标 simulate_group_trading_book() 的主循环：
        每期 = MARKET_DATA → FACTOR → SIGNAL → ORDER → FEE → LIQUIDITY → FILL → MARGIN → PNL → REPORT
        """
        T, M, P = self._T, self._M, self._P
        initial_capital = self._initial_capital

        # --- 构建 BacktestContext ---
        ctx = BacktestContext(
            returns_np=self._returns,
            price_np=self._price,
            membership_np=self._membership,
            point_value_vec=self._point_value_vec,
            min_tick_vec=self._min_tick_vec,
            min_trade_quantity_vec=self._min_trade_quantity_vec,
            open_ratio_mat=self._open_ratio_mat,
            close_ratio_mat=self._close_ratio_mat,
            open_fixed_mat=self._open_fixed_mat,
            close_fixed_mat=self._close_fixed_mat,
            margin_ratio_mat=self._margin_ratio_mat,
            is_margin_traded_vec=self._is_margin_traded_vec,
            liquidity_capacity_np=self._liquidity_capacity_np,
        )

        # --- 构建 WorldState ---
        state = WorldState(
            num_groups=M,
            num_products=P,
            initial_capital=initial_capital,
        )

        # --- 累积结果 ---
        net_returns_arr = np.zeros((M, T), dtype=float)
        gross_returns_arr = np.zeros((M, T), dtype=float)
        fee_costs_arr = np.zeros((M, T), dtype=float)
        trade_notional_arr = np.zeros((M, T), dtype=float)
        total_equity_arr = np.zeros((M, T), dtype=float)
        cash_arr = np.zeros((M, T), dtype=float)
        margin_occupied_arr = np.zeros((M, T), dtype=float)
        product_gross_contrib_arr = np.zeros((M, P, T), dtype=float)
        product_fee_contrib_arr = np.zeros((M, P, T), dtype=float)
        prev_end_amounts_arr = np.zeros((M, P), dtype=float)
        multi_session_count = 0

        # --- 逐期推进 ---
        for t in range(T):
            # --- MARKET_DATA ---
            prices_t = self._price[t]                             # (P,)
            returns_t = self._returns[t]                          # (P,)
            membership_t = self._membership[t]                    # (M, P)
            contract_value_t = prices_t * (
                self._point_value_vec if self._point_value_vec is not None
                else np.ones(P)
            )

            # --- 当前持仓名义市值 ---
            curr_position = state.quantities[t] if t < len(state.quantities) else np.zeros((M, P))
            position_notional = curr_position * contract_value_t[np.newaxis, :]

            # --- FACTOR → SIGNAL（由 ORDER 策略消费） ---
            # membership_t 即为当期信号

            # --- ORDER ---
            wealth_before = state.equity_history[t] if t < len(state.equity_history) else np.full(M, initial_capital)
            target_amounts = self._order_strategy.compute(
                membership=membership_t,
                prev_amounts=curr_position * contract_value_t[np.newaxis, :],
                wealth=wealth_before,
                ctx=ctx,
            )

            # --- LIQUIDITY ---
            if self._liquidity_capacity_np is not None:
                target_amounts = self._liquidity_model.cap(
                    desired_quantities=target_amounts,
                    quantities=curr_position * contract_value_t[np.newaxis, :],
                    equity=wealth_before,
                    ctx=ctx,
                )

            # --- FILL ---
            new_position_nominal = target_amounts
            trade_notional = np.abs(new_position_nominal - position_notional)
            trade_notional_arr[:, t] = trade_notional.sum(axis=1)

            # --- FEE ---
            delta_qty = (new_position_nominal - position_notional)
            with np.errstate(invalid='ignore'):
                safe_value = contract_value_t.copy()
                safe_value[safe_value == 0] = 1.0
                buy_qty = np.maximum(delta_qty, 0.0) / safe_value[np.newaxis, :]
                sell_qty = np.maximum(-delta_qty, 0.0) / safe_value[np.newaxis, :]

            fee_matrix = self._fee_model.compute(
                buy_qty=buy_qty,
                sell_qty=sell_qty,
                contract_value=contract_value_t[np.newaxis, :],
                ctx=ctx,
            )
            fee_costs_arr[:, t] = fee_matrix.sum(axis=1)

            # --- MARGIN ---
            margin_occupied_arr[:, t] = self._margin_model.occupy(
                position_notional=new_position_nominal,
                ctx=ctx,
            )

            # --- PNL ---
            # 基于上一期持仓计算收益
            if t > 0:
                prev_position = state.quantities[t - 1]
                prev_notional = prev_position * contract_value_t[np.newaxis, :]
                gross_contrib = prev_notional * returns_t[np.newaxis, :]  # (M, P)
                gross_returns_arr[:, t] = gross_contrib.sum(axis=1)
                product_gross_contrib_arr[:, :, t] = gross_contrib
                product_fee_contrib_arr[:, :, t] = fee_matrix

                # 净收益 = 毛收益 - 费用
                net_ret = gross_returns_arr[:, t] - fee_costs_arr[:, t]
                # 用上一期权益做分母
                prev_equity = state.equity_history[t - 1]
                with np.errstate(invalid='ignore'):
                    net_returns_arr[:, t] = np.where(
                        prev_equity > 0,
                        net_ret / prev_equity,
                        0.0,
                    )
            else:
                gross_returns_arr[:, 0] = 0.0
                net_returns_arr[:, 0] = 0.0

            # --- 更新状态 ---
            new_equity = state.equity_history[t] + gross_returns_arr[:, t] - fee_costs_arr[:, t]
            state.equity_history[t] = new_equity
            total_equity_arr[:, t] = new_equity

            # 现金 = 权益 - 持仓市值
            new_cash = new_equity - np.nansum(new_position_nominal, axis=1) - margin_occupied_arr[:, t]
            cash_arr[:, t] = new_cash

            # 更新持仓
            if t < T - 1:
                state.quantities[t + 1] = new_position_nominal / contract_value_t[np.newaxis, :]

            prev_end_amounts_arr = new_position_nominal

            # --- REPORT ---
            # 多时段检测（简化）
            if self._multi_session_active and t > 0:
                # 如果 membership 跨 session 仍有 bar 的品种退出，记录触发
                pass

        # 最终持仓量
        final_quantities = state.quantities[-1]

        return BacktestResult(
            net_returns_np=net_returns_arr,
            gross_returns_np=gross_returns_arr,
            product_gross_contrib_np=product_gross_contrib_arr,
            product_fee_contrib_np=product_fee_contrib_arr,
            fee_costs_np=fee_costs_arr,
            trade_notional_ratio_np=trade_notional_arr,
            position_quantities_np=final_quantities,
            total_equity_np=total_equity_arr,
            cash_np=cash_arr,
            margin_occupied_np=margin_occupied_arr,
            multi_session_triggered=multi_session_count,
            prev_end_amounts_np=prev_end_amounts_arr,
        )
