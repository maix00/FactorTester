"""Registered user-facing fields for the built-in group intent policy."""

from tools.testers.backtest.engines.native.fields import FieldDefinition


def group_policy_fields() -> dict[str, FieldDefinition]:
    return {
        "split_count": FieldDefinition(
            public=True, label="分组数", default=5, frontend_only_default=True,
            control_template="number", tab="group_strategy", chip_template="分组数: {value}",
            tab_label="分组数量", tab_order=90, scope_policy="group_only",
        ),
        "group_index": FieldDefinition(
            public=True, label="分组", default=1, frontend_only_default=True,
            control_template="number", tab="group_strategy", chip_template="分组: {value}",
            tab_label="分组数量", tab_order=90, scope_policy="group_only", display_offset=1,
        ),
        "execution_timing": FieldDefinition(
            public=False, label="成交时机", default="next_bar", control_template="select", tab="order",
            options=(("next_bar", "下一 bar 开盘成交"),), chip_template="成交时机: {value}",
            tab_label="订单执行", tab_order=120,
        ),
        "execution_delay_bars": FieldDefinition(
            public=False, label="延迟", default=1, control_template="number", tab="order",
            visible_when={"execution_timing": ("next_bar",)}, chip_template="延迟: {value}bar",
            tab_label="订单执行", tab_order=120,
        ),
        "position_policy": FieldDefinition(
            public=True, label="持仓", default="rebalance_to_target", control_template="select",
            tab="position_policy", options=(("rebalance_to_target", "按目标调仓"), ("buy_and_hold", "买入持有"), ("incremental_buy_and_hold_fixed_leverage", "增量式 Hold（固定杠杆）")),
            chip_template="持仓: {value}", tab_label="持仓政策", tab_order=80,
        ),
        "rebalance_trigger": FieldDefinition(
            public=True, label="调仓", default="on_factor_signal", control_template="select",
            tab="rebalance_trigger", options=(("on_factor_signal", "因子信号事件"), ("membership_change", "成员变化事件")),
            chip_template="调仓: {value}", tab_label="调仓触发", tab_order=70,
        ),
        "allocation_policy": FieldDefinition(
            public=True, label="分配", default="equal_notional", control_template="select", tab="target_allocation",
            options=(("equal_notional", "等名义敞口"), ("inverse_volatility", "等风险（波动率倒数）"),
                     ("equal_margin", "等保证金（对照）"), ("factor_sizing", "按 sizing 因子")),
            chip_template="分配: {value}", tab_label="目标分配", tab_order=60,
        ),
        "sizing_transform": FieldDefinition(
            public=True, label="权重变换", default="proportional", control_template="select",
            tab="target_allocation", options=(("proportional", "正值比例"), ("inverse", "正值倒数")),
            visible_when={"allocation_policy": ("factor_sizing",)}, chip_template="权重变换: {value}",
            tab_label="目标分配", tab_order=60,
            help_text="只在已入选品种内归一化；缺失、非有限或非正值权重为零。",
        ),
        "volatility_lookback": FieldDefinition(
            public=True, label="波动窗口", default=20, control_template="number", tab="target_allocation",
            visible_when={"allocation_policy": ("inverse_volatility",)}, chip_template="波动窗口: {value}",
            tab_label="目标分配", tab_order=60,
        ),
        "volatility_warmup": FieldDefinition(
            public=True, label="预热", default="equal_notional", control_template="select", tab="target_allocation",
            options=(("equal_notional", "预热期使用等名义敞口并记录"), ("error", "数据不足即报错")),
            visible_when={"allocation_policy": ("inverse_volatility",)}, chip_template="预热: {value}",
            tab_label="目标分配", tab_order=60,
        ),
        "product_mask_names": FieldDefinition(public=False, label="品种范围", default=None),
        "screen_rule": FieldDefinition(
            public=True, label="动态筛选", default="disabled", control_template="select", tab="group_strategy",
            options=(("disabled", "关闭"), ("gte", "大于等于下限"), ("lte", "小于等于上限"), ("between", "区间内")),
            chip_template="动态筛选: {value}", tab_label="分组数量", tab_order=90,
            help_text="每个信号时点先按 screen 因子生成 eligibility universe，再在其中排名分组。",
        ),
        "screen_lower": FieldDefinition(
            public=True, label="筛选下限", default=0.0, control_template="number", tab="group_strategy",
            visible_when={"screen_rule": ("gte", "between")}, tab_label="分组数量", tab_order=90,
        ),
        "screen_upper": FieldDefinition(
            public=True, label="筛选上限", default=0.0, control_template="number", tab="group_strategy",
            visible_when={"screen_rule": ("lte", "between")}, tab_label="分组数量", tab_order=90,
        ),
        "dispatched_order_events": FieldDefinition(public=False, display_value_kind="event_draft_table"),
    }
