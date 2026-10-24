"""Pinned Nautilus simulated-venue configuration contract.

The serialized shape follows the vendored NautilusTrader source version's
``BacktestEngine.add_venue`` / ``SimulatedVenueConfig`` surface.  It contains
only JSON values; runtime model objects are constructed at the engine edge.
The same schema is returned to the workbench so authoring and freezing do not
invent independent option lists.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from server.services.nautilus_bridge.config import UnsupportedExecutionConfig
from server.services.nautilus_bridge.version import NAUTILUS_VERSION

_FILL_MODELS = (
    "default", "best_price", "one_tick_slippage", "probabilistic", "two_tier",
    "three_tier", "limit_order_partial", "size_aware", "competition_aware",
    "volume_sensitive", "market_hours",
)
NAUTILUS_BOOK_TYPES = ("L1_MBP", "L2_MBP", "L3_MBO")
_FEE_MODELS = (
    "unconfigured", "inherit", "zero", "fixed", "per_contract",
    "maker_taker", "probability_price", "capped_option",
    "tiered_notional_option", "historical_schedule",
)
_NATIVE_VERSION = NAUTILUS_VERSION

_DEFAULTS: dict[str, Any] = {
    "book_type": "L1_MBP",
    "default_leverage": None,
    "leverages": {},
    "margin_model": "leveraged",
    "fill_model": {
        "type": "default", "prob_fill_on_limit": 1.0,
        "prob_slippage": 0.0, "random_seed": None, "liquidity_factor": 0.3,
    },
    # Nautilus requires an explicit fee model for every simulated Venue.
    # Keep an editor sentinel so drafts can be saved before the user chooses.
    "fee_model": {"type": "unconfigured"},
    "latency_model": {"type": "none"},
    "routing": False,
    "reject_stop_orders": True,
    "support_gtd_orders": True,
    "support_contingent_orders": True,
    "use_position_ids": True,
    "use_random_ids": False,
    "use_reduce_only": True,
    "use_message_queue": True,
    "use_market_order_acks": False,
    "bar_execution": True,
    "bar_adaptive_high_low_ordering": False,
    "trade_execution": True,
    "liquidity_consumption": False,
    "bar_volume_weights_bps": None,
    "bar_volume_remainder_to": "close",
    "allow_cash_borrowing": False,
    "frozen_account": False,
    "queue_position": False,
    "oto_trigger_mode": "PARTIAL",
    "price_protection_points": 0,
    "liquidation_enabled": False,
    "liquidation_trigger_ratio": 1.0,
    "liquidation_cancel_open_orders": True,
}

_BOOLEAN_FIELDS = (
    "routing", "reject_stop_orders", "support_gtd_orders",
    "support_contingent_orders", "use_position_ids", "use_random_ids",
    "use_reduce_only", "use_message_queue", "use_market_order_acks",
    "bar_execution", "bar_adaptive_high_low_ordering", "trade_execution",
    "liquidity_consumption", "allow_cash_borrowing", "frozen_account",
    "queue_position", "liquidation_enabled", "liquidation_cancel_open_orders",
)


def native_configuration_schema() -> dict[str, object]:
    """Project the pinned Nautilus API into one editor and RunSpec contract.

    Nautilus is the capability source.  The bridge schema only adds the JSON
    representation needed to freeze runtime model objects and records which
    arguments cannot currently be represented by this adapter.
    """
    fields: list[dict[str, object]] = []

    def add(path: str, label: str, kind: str, section: str, **extra: object) -> None:
        fields.append({"path": path, "label": label, "type": kind, "section": section, **extra})

    add("book_type", "簿记类型", "enum", "matching", options=list(NAUTILUS_BOOK_TYPES), default="L1_MBP")
    for key, label, default in (
        ("bar_execution", "Bar 撮合", True),
        ("bar_adaptive_high_low_ordering", "按开盘价自适应排列高低价", False),
        ("trade_execution", "逐笔成交撮合", True),
        ("liquidity_consumption", "撮合时消耗流动性", False),
        ("queue_position", "模拟被动单队列位置", False),
        ("routing", "允许跨 Venue 路由", False),
        ("reject_stop_orders", "拒绝已触发的止损单", True),
        ("support_gtd_orders", "支持 GTD 有效期", True),
        ("support_contingent_orders", "支持条件关联订单", True),
        ("use_position_ids", "生成持仓 ID", True),
        ("use_random_ids", "使用随机 ID", False),
        ("use_reduce_only", "执行 Reduce-only 限制", True),
        ("use_message_queue", "命令经消息队列处理", True),
        ("use_market_order_acks", "市价单先发确认事件", False),
        ("allow_cash_borrowing", "现金账户允许借款", False),
        ("frozen_account", "冻结模拟账户余额变化", False),
        ("oto_trigger_mode", "OTO 触发时机", "PARTIAL"),
        ("price_protection_points", "市价保护点数", 0),
        ("liquidation_enabled", "启用维持保证金强平", False),
        ("liquidation_trigger_ratio", "强平触发权益比", 1.0),
        ("liquidation_cancel_open_orders", "强平前撤销未成交订单", True),
    ):
        if key == "oto_trigger_mode":
            add(key, label, "enum", "matching", options=["PARTIAL", "FULL"], default=default)
        elif key in _BOOLEAN_FIELDS:
            add(key, label, "boolean", "matching", default=default)
        else:
            kind = "integer" if key == "price_protection_points" else "number"
            add(key, label, kind, "matching", default=default, minimum=0)
    add("bar_volume_weights_bps", "Bar 成交量 O/H/L/C 权重（基点）", "integer_array", "matching",
        length=4, minimum=0, maximum=10_000, nullable=True, default=None,
        help="四项顺序为 Open、High、Low、Close，合计必须为 10000；空值保留 Nautilus 原生分配。")
    add("bar_volume_remainder_to", "Bar 成交量取整余数", "enum", "matching",
        options=["open", "high", "low", "close"], default="close")
    add("default_leverage", "默认杠杆", "decimal", "account", nullable=True, default=None, minimum=0,
        help="留空使用 Nautilus 账户默认杠杆；单品种覆盖写入 leverages。")
    add("leverages", "品种杠杆覆盖", "decimal_map", "account", default={},
        help="键为 Nautilus InstrumentId；只存特殊覆盖，不复制产品组成员。")
    add("margin_model", "保证金模型", "enum", "account", options=["leveraged", "standard"], default="leveraged",
        help="leveraged 将名义金额除以杠杆后乘 Instrument 保证金率；standard 直接使用 Instrument 保证金率。")
    add("fill_model.type", "成交模型", "enum", "fills", options=list(_FILL_MODELS), default="default")
    add("fill_model.prob_fill_on_limit", "限价成交概率", "number", "fills", default=1.0, minimum=0, maximum=1)
    add("fill_model.prob_slippage", "概率滑点", "number", "fills", default=0.0, minimum=0, maximum=1)
    add("fill_model.random_seed", "成交模型随机种子", "integer", "fills", nullable=True, default=None, minimum=0)
    add("fill_model.liquidity_factor", "竞争流动性系数", "number", "fills", default=0.3, minimum=0,
        visible_if={"fill_model.type": ["competition_aware"]})
    add("fee_model.type", "手续费模型", "enum", "fees", options=[
        {"value": "unconfigured", "label": "请选择手续费模型"},
        {"value": "zero", "label": "ZeroFeeModel · 零手续费"},
        {"value": "fixed", "label": "FixedFeeModel · 固定费用"},
        {"value": "per_contract", "label": "PerContractFeeModel · 按数量"},
        {"value": "maker_taker", "label": "MakerTakerFeeModel · Maker/Taker"},
        {"value": "probability_price", "label": "ProbabilityPriceFeeModel · 概率价格"},
        {"value": "capped_option", "label": "CappedOptionFeeModel · 封顶期权费率"},
        {"value": "tiered_notional_option", "label": "TieredNotionalOptionFeeModel · 分层名义金额"},
        {"value": "historical_schedule", "label": "历史费率表适配器"},
    ], default="unconfigured")
    add("fee_model.commission", "手续费金额", "money", "fees", nullable=True, default=None,
        visible_if={"fee_model.type": ["fixed", "per_contract"]})
    add("fee_model.charge_commission_once", "每个订单只收一次固定手续费", "boolean", "fees", default=True,
        visible_if={"fee_model.type": ["fixed"]})
    add("fee_model.maker_rate", "Maker 费率", "decimal", "fees", nullable=True, default=None,
        visible_if={"fee_model.type": [
            "maker_taker", "probability_price", "capped_option", "tiered_notional_option",
        ]})
    add("fee_model.taker_rate", "Taker 费率", "decimal", "fees", nullable=True, default=None,
        visible_if={"fee_model.type": [
            "maker_taker", "probability_price", "capped_option", "tiered_notional_option",
        ]})
    add("fee_model.overrides", "品种费率覆盖", "rate_map", "fees", default={},
        visible_if={"fee_model.type": [
            "maker_taker", "probability_price", "capped_option", "tiered_notional_option",
        ]})
    add("fee_model.cap_rate", "费率上限", "decimal", "fees", nullable=True, default=None,
        visible_if={"fee_model.type": ["capped_option"]})
    add("fee_model.schedule_ref", "历史费率规则集引用", "reference", "fees", nullable=True, default=None,
        visible_if={"fee_model.type": ["historical_schedule"]})
    add("latency_model.type", "延迟模型", "enum", "latency", options=["none", "static"], default="none")
    for key, label in (
        ("base_latency_nanos", "基础延迟（ns）"),
        ("insert_latency_nanos", "下单延迟（ns）"),
        ("update_latency_nanos", "改单延迟（ns）"),
        ("cancel_latency_nanos", "撤单延迟（ns）"),
    ):
        add(f"latency_model.{key}", label, "integer", "latency", minimum=0, default=0,
            visible_if={"latency_model.type": ["static"]})
    venue_fields = [
        {
            "path": "base_currency", "native_parameter": "base_currency",
            "label": "账户基础币种", "type": "text", "section": "account",
            "default": "CNY", "editable": False,
            "help": "当前由 RunSpec 的统一基础币种提供；多币种估值尚未接入。",
        },
        {
            "path": "account_type", "native_parameter": "account_type",
            "label": "账户类型", "type": "enum", "section": "account",
            "options": [
                {"value": "MARGIN", "label": "MARGIN · 保证金"},
                {"value": "CASH", "label": "CASH · 现金"},
                {"value": "BETTING", "label": "BETTING · 博彩"},
            ], "default": "MARGIN",
        },
        {
            "path": "oms_type", "native_parameter": "oms_type",
            "label": "订单管理模式", "type": "enum", "section": "account",
            "options": [
                {"value": "NETTING", "label": "NETTING · 净持仓"},
                {"value": "HEDGING", "label": "HEDGING · 对冲持仓"},
            ], "default": "NETTING",
        },
        {
            "path": "starting_balances", "native_parameter": "starting_balances",
            "label": "初始余额（Nautilus Money）", "type": "money_array",
            "section": "account", "default": [],
            "help": "每行一个 '<金额> <币种>'；FactorTester 当前只接受 RunSpec 基础币种。",
        },
    ]
    native_parameters = [
        "venue", "oms_type", "account_type", "starting_balances", "base_currency",
        "default_leverage", "leverages", "margin_model", "fill_model", "fee_model",
        "latency_model", "modules", "book_type", "routing", "reject_stop_orders",
        "support_gtd_orders", "support_contingent_orders", "use_position_ids",
        "use_random_ids", "use_reduce_only", "use_message_queue", "use_market_order_acks",
        "bar_execution", "bar_adaptive_high_low_ordering", "trade_execution",
        "liquidity_consumption", "queue_position", "allow_cash_borrowing", "frozen_account",
        "oto_trigger_mode", "price_protection_points", "liquidation_enabled",
        "liquidation_trigger_ratio", "liquidation_cancel_open_orders",
        "bar_volume_weights_bps", "bar_volume_remainder_to",
    ]
    native_config_parameters = {str(field["path"]).split(".", 1)[0] for field in fields}
    venue_field_parameters = {str(field["native_parameter"]) for field in venue_fields}

    # Most add_venue arguments pass straight through to the Nautilus Python
    # API.  Model handles and FactorTester's one-currency rule need a thin
    # serialization adapter; they are not independent matching/account logic.
    adapter_parameters = {
        "margin_model": "RunSpec selects StandardMarginModel or LeveragedMarginModel.",
        "fill_model": "RunSpec tags a Nautilus FillModel; the engine factory constructs that native model.",
        "fee_model": "RunSpec tags a Nautilus FeeModel or a FactorTester historical-fee adapter.",
        "latency_model": "RunSpec tags a Nautilus LatencyModel; the engine factory constructs that native model.",
    }
    fixed_mappings = {
        "venue": ("FactorTester Venue identity", "nt_native", "venues[].name", "Passed as Nautilus Venue."),
        "base_currency": ("RunSpec shared account currency", "mapped", "base_currency", "FactorTester currently freezes one base currency for every Venue."),
    }
    direct_parameters = {
        "oms_type": "venues[].oms_type",
        "account_type": "venues[].account_type",
        "starting_balances": "venues[].starting_balances",
        "default_leverage": "venues[].native_config.default_leverage",
        "leverages": "venues[].native_config.leverages",
        "book_type": "venues[].native_config.book_type",
        "routing": "venues[].native_config.routing",
        "reject_stop_orders": "venues[].native_config.reject_stop_orders",
        "support_gtd_orders": "venues[].native_config.support_gtd_orders",
        "support_contingent_orders": "venues[].native_config.support_contingent_orders",
        "use_position_ids": "venues[].native_config.use_position_ids",
        "use_random_ids": "venues[].native_config.use_random_ids",
        "use_reduce_only": "venues[].native_config.use_reduce_only",
        "use_message_queue": "venues[].native_config.use_message_queue",
        "use_market_order_acks": "venues[].native_config.use_market_order_acks",
        "bar_execution": "venues[].native_config.bar_execution",
        "bar_adaptive_high_low_ordering": "venues[].native_config.bar_adaptive_high_low_ordering",
        "trade_execution": "venues[].native_config.trade_execution",
        "liquidity_consumption": "venues[].native_config.liquidity_consumption",
        "queue_position": "venues[].native_config.queue_position",
        "allow_cash_borrowing": "venues[].native_config.allow_cash_borrowing",
        "frozen_account": "venues[].native_config.frozen_account",
        "oto_trigger_mode": "venues[].native_config.oto_trigger_mode",
        "price_protection_points": "venues[].native_config.price_protection_points",
        "liquidation_enabled": "venues[].native_config.liquidation_enabled",
        "liquidation_trigger_ratio": "venues[].native_config.liquidation_trigger_ratio",
        "liquidation_cancel_open_orders": "venues[].native_config.liquidation_cancel_open_orders",
        "bar_volume_weights_bps": "venues[].native_config.bar_volume_weights_bps",
        "bar_volume_remainder_to": "venues[].native_config.bar_volume_remainder_to",
    }
    for descriptor in fields:
        parameter = str(descriptor["path"]).split(".", 1)[0]
        descriptor["native_parameter"] = parameter
        descriptor["status"] = "ft_adapter" if parameter in adapter_parameters else "nt_native"
        if parameter in adapter_parameters:
            descriptor["implementation_note"] = adapter_parameters[parameter]
    for descriptor in venue_fields:
        descriptor["status"] = "mapped" if descriptor["native_parameter"] == "base_currency" else "nt_native"

    parameter_coverage: list[dict[str, str]] = []
    for parameter in native_parameters:
        if parameter in fixed_mappings:
            owner, status, path, note = fixed_mappings[parameter]
            row = {"parameter": parameter, "owner": owner, "status": status, "runspec_path": path, "note": note}
        elif parameter == "modules":
            row = {
                "parameter": parameter, "owner": "Nautilus SimulationModule",
                "status": "unsupported", "runspec_path": "—",
                "note": "没有版本化模块注册目录；禁止把任意 Python 对象写入 RunSpec。",
            }
        elif parameter in adapter_parameters:
            row = {
                "parameter": parameter, "owner": "FactorTester 序列化适配器",
                "status": "ft_adapter",
                "runspec_path": f"venues[].native_config.{parameter}",
                "note": adapter_parameters[parameter],
            }
        elif parameter in venue_field_parameters:
            row = {
                "parameter": parameter, "owner": "Nautilus Venue field",
                "status": "nt_native", "runspec_path": f"venues[].{parameter}",
            }
        elif parameter in native_config_parameters:
            row = {
                "parameter": parameter, "owner": "Nautilus Venue config",
                "status": "nt_native", "runspec_path": f"venues[].native_config.{parameter}",
            }
        elif parameter in direct_parameters:
            row = {
                "parameter": parameter, "owner": "Nautilus Venue config",
                "status": "nt_native", "runspec_path": direct_parameters[parameter],
            }
        else:
            row = {
                "parameter": parameter, "owner": "unmapped",
                "status": "unsupported", "runspec_path": "—",
                "note": "Nautilus API 参数尚无对应 RunSpec 字段。",
            }
        parameter_coverage.append(row)
    execution_policy_coverage = [
        {
            "parameter": "execution_timing",
            "owner": "Nautilus Bar matching + TimeInForce.AT_THE_OPEN adapter",
            "status": "ft_adapter",
            "runspec_path": "execution_timing",
            "native_parameters": "bar_execution, TimeInForce.AT_THE_OPEN",
            "note": (
                "RunSpec 固定为 next_bar_open；真实 Nautilus 引擎合成事件测试通过。"
                "信号策略与 Job worker 尚未接入该执行器。"
            ),
        },
        {
            "parameter": "position_cost_basis",
            "owner": "Nautilus ExecutionEngineConfig",
            "status": "nt_native",
            "runspec_path": "instrument_execution_policy.position_cost_basis.default",
            "native_parameters": "position_cost_basis",
            "note": (
                "支持 WEIGHTED_AVERAGE、FIFO、LIFO、HIFO；构建器传入原生全局成本基准，"
                "产品组/Instrument 例外映射到 position_cost_basis_by_instrument。"
            ),
        },
        {
            "parameter": "position_cost_basis_by_instrument",
            "owner": "Nautilus ExecutionEngineConfig",
            "status": "nt_native",
            "runspec_path": (
                "instrument_execution_policy.position_cost_basis.scope_overrides/"
                "instrument_overrides"
            ),
            "native_parameters": "position_cost_basis_by_instrument",
            "note": "RunSpec 只保存产品组和合约例外；执行前展开为 Nautilus 稀疏 InstrumentId 覆盖。",
        },
        {
            "parameter": "daily_settlement",
            "owner": "FactorTester official-settlement InstrumentClose adapter",
            "status": "unsupported",
            "runspec_path": "instrument_execution_policy.daily_settlement",
            "native_parameters": "InstrumentClose(DAILY_SETTLEMENT)",
            "note": (
                "RunSpec 已冻结默认值、产品组/合约例外及规则集引用；当前没有完成结算事件"
                "注入和账户入账，engine_factory 会拒绝开启 DMTM。"
            ),
        },
    ]
    return {
        "native_version": _NATIVE_VERSION,
        "object": "SimulatedVenueConfig",
        "python_entrypoint": "nautilus_trader.backtest.BacktestEngine.add_venue",
        "venue_identity": {
            "path": "name", "native_parameter": "venue", "label": "Venue ID",
            "type": "venue_id", "section": "account",
        },
        "native_source": "vendor/nautilus_trader/crates/backtest/src/config.rs",
        "parameter_source": "vendor/nautilus_trader/python/nautilus_trader/backtest/__init__.pyi",
        "native_parameters": native_parameters,
        "parameter_coverage": parameter_coverage,
        "execution_policy_coverage": execution_policy_coverage,
        "legacy_authoring_keys_hidden": [
            "fee_mode", "transaction_fee_source", "fixed_fee_rate", "fee_per_contract",
            "fee_currency", "fee_schedule_ref", "fee_custom_product_fields",
            "slippage_mode", "slippage_bps", "matching_model", "liquidity_mode",
            "participation_rate", "volume_execution_price_basis", "nt_capacity_policy",
            "nt_matching_policy", "nt_price_protection_points", "nautilus_venue",
            "margin_mode", "fixed_margin_ratio", "margin_call_mode",
            "liquidation_target_buffer", "target_margin_utilization", "max_margin_utilization",
        ],
        "venue_fields": venue_fields,
        "defaults": default_native_venue_config(),
        "sections": [
            {"id": "matching", "label": "撮合与订单生命周期"},
            {"id": "account", "label": "杠杆与保证金"},
            {"id": "fills", "label": "Nautilus FillModel"},
            {"id": "fees", "label": "Nautilus FeeModel"},
            {"id": "latency", "label": "Nautilus LatencyModel"},
        ],
        "fields": fields,
        "excluded": {
            "modules": "只能使用已登记的版本化 SimulationModule；当前没有可供 RunSpec 选择的注册模块。",
            "defer_option_settlement": "Rust SimulatedVenueConfig 有此字段，但 Python BacktestEngine.add_venue 未暴露；Nautilus 默认值为 true。",
            "base_currency": "Nautilus 支持 Venue 多币种账户；当前 FactorTester RunSpec 使用统一基础币种并将其映射到各 Venue。",
            "python_model_objects": "不能把运行时对象或任意 Python 实例写入 RunSpec。",
        },
    }


def default_native_venue_config() -> dict[str, Any]:
    """Return a fresh JSON-ready object with pinned Nautilus defaults."""
    return {
        **_DEFAULTS,
        "fill_model": dict(_DEFAULTS["fill_model"]),
        "fee_model": dict(_DEFAULTS["fee_model"]),
        "latency_model": dict(_DEFAULTS["latency_model"]),
        "leverages": {},
    }


def freeze_native_venue_config(value: object = None) -> dict[str, Any]:
    """Validate and freeze serializable settings for one simulated Venue."""
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig("venues.native_config", "must be an object")
    unknown = set(value) - set(_DEFAULTS)
    if unknown:
        raise UnsupportedExecutionConfig(
            "venues.native_config", "unknown Nautilus options: " + ", ".join(sorted(map(str, unknown))),
        )
    result = default_native_venue_config()
    if "book_type" in value:
        result["book_type"] = _enum(
            value["book_type"], "venues.native_config.book_type", NAUTILUS_BOOK_TYPES,
        )
    if "margin_model" in value:
        result["margin_model"] = _enum(value["margin_model"], "venues.native_config.margin_model", ("leveraged", "standard"))
    for key in _BOOLEAN_FIELDS:
        if key in value:
            if not isinstance(value[key], bool):
                raise UnsupportedExecutionConfig(f"venues.native_config.{key}", "must be boolean")
            result[key] = value[key]
    for key in ("default_leverage",):
        if key in value:
            result[key] = _optional_decimal(value[key], f"venues.native_config.{key}", positive=True)
    if "leverages" in value:
        raw = value["leverages"]
        if not isinstance(raw, Mapping):
            raise UnsupportedExecutionConfig("venues.native_config.leverages", "must map InstrumentId to positive leverage")
        result["leverages"] = {
            _nonempty_text(instrument, "venues.native_config.leverages"): str(
                _optional_decimal(leverage, f"venues.native_config.leverages.{instrument}", positive=True)
            ) for instrument, leverage in sorted(raw.items(), key=lambda item: str(item[0]))
        }
    result["fill_model"] = _fill_model(value.get("fill_model", result["fill_model"]))
    result["fee_model"] = _fee_model(value.get("fee_model", result["fee_model"]))
    result["latency_model"] = _latency_model(value.get("latency_model", result["latency_model"]))
    if "oto_trigger_mode" in value:
        result["oto_trigger_mode"] = _enum(value["oto_trigger_mode"], "venues.native_config.oto_trigger_mode", ("PARTIAL", "FULL"))
    if "bar_volume_remainder_to" in value:
        result["bar_volume_remainder_to"] = _enum(value["bar_volume_remainder_to"], "venues.native_config.bar_volume_remainder_to", ("open", "high", "low", "close"))
    if "price_protection_points" in value:
        result["price_protection_points"] = _nonnegative_int(value["price_protection_points"], "venues.native_config.price_protection_points")
    if "liquidation_trigger_ratio" in value:
        ratio = _finite_number(value["liquidation_trigger_ratio"], "venues.native_config.liquidation_trigger_ratio")
        if ratio <= 0:
            raise UnsupportedExecutionConfig("venues.native_config.liquidation_trigger_ratio", "must be positive")
        result["liquidation_trigger_ratio"] = ratio
    if "bar_volume_weights_bps" in value:
        weights = value["bar_volume_weights_bps"]
        if weights is not None:
            if not isinstance(weights, (list, tuple)) or len(weights) != 4:
                raise UnsupportedExecutionConfig("venues.native_config.bar_volume_weights_bps", "requires four Open/High/Low/Close weights")
            normalized = [_nonnegative_int(item, "venues.native_config.bar_volume_weights_bps") for item in weights]
            if sum(normalized) != 10_000:
                raise UnsupportedExecutionConfig("venues.native_config.bar_volume_weights_bps", "weights must sum to 10000")
            result["bar_volume_weights_bps"] = normalized
    if result["bar_volume_weights_bps"] is not None and not (
        result["bar_execution"] and result["liquidity_consumption"]
    ):
        raise UnsupportedExecutionConfig(
            "venues.native_config.bar_volume_weights_bps",
            "requires bar_execution and liquidity_consumption",
        )
    return result


def _fill_model(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig("venues.native_config.fill_model", "must be a tagged model object")
    model_type = _enum(value.get("type"), "venues.native_config.fill_model.type", _FILL_MODELS)
    allowed = {"type", "prob_fill_on_limit", "prob_slippage", "random_seed", "liquidity_factor"}
    _reject_unknown(value, allowed, "venues.native_config.fill_model")
    fill = {
        "type": model_type,
        "prob_fill_on_limit": _probability(value.get("prob_fill_on_limit", 1.0), "prob_fill_on_limit"),
        "prob_slippage": _probability(value.get("prob_slippage", 0.0), "prob_slippage"),
        "random_seed": None if value.get("random_seed") in (None, "") else _nonnegative_int(value["random_seed"], "random_seed"),
        "liquidity_factor": _finite_number(value.get("liquidity_factor", 0.3), "liquidity_factor"),
    }
    if model_type == "competition_aware" and fill["liquidity_factor"] < 0:
        raise UnsupportedExecutionConfig("venues.native_config.fill_model.liquidity_factor", "must be nonnegative")
    if model_type != "competition_aware":
        fill.pop("liquidity_factor")
    return fill


def _fee_model(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig("venues.native_config.fee_model", "must be a tagged model object")
    model_type = _enum(value.get("type"), "venues.native_config.fee_model.type", _FEE_MODELS)
    if model_type in {"inherit", "unconfigured"}:
        _reject_unknown(value, {"type"}, "venues.native_config.fee_model")
        return {"type": model_type}
    if model_type == "zero":
        _reject_unknown(value, {"type"}, "venues.native_config.fee_model")
        return {"type": "zero"}
    if model_type in {"fixed", "per_contract"}:
        _reject_unknown(value, {"type", "commission", "charge_commission_once"}, "venues.native_config.fee_model")
        commission = _money_string(value.get("commission"), "venues.native_config.fee_model.commission")
        result = {"type": model_type, "commission": commission}
        if model_type == "fixed":
            once = value.get("charge_commission_once", True)
            if not isinstance(once, bool):
                raise UnsupportedExecutionConfig("venues.native_config.fee_model.charge_commission_once", "must be boolean")
            result["charge_commission_once"] = once
        return result
    if model_type in {
        "maker_taker", "probability_price", "capped_option", "tiered_notional_option",
    }:
        allowed = {"type", "maker_rate", "taker_rate", "overrides"}
        if model_type == "capped_option":
            allowed.add("cap_rate")
        _reject_unknown(value, allowed, "venues.native_config.fee_model")
        maker = _decimal_text(value.get("maker_rate"), "venues.native_config.fee_model.maker_rate")
        taker = _decimal_text(value.get("taker_rate"), "venues.native_config.fee_model.taker_rate")
        overrides = value.get("overrides", {})
        if not isinstance(overrides, Mapping):
            raise UnsupportedExecutionConfig("venues.native_config.fee_model.overrides", "must map InstrumentId to maker/taker rate pairs")
        normalized = {}
        for instrument, rates in overrides.items():
            if not isinstance(rates, (list, tuple)) or len(rates) != 2:
                raise UnsupportedExecutionConfig("venues.native_config.fee_model.overrides", "each entry must be [maker_rate, taker_rate]")
            normalized[_nonempty_text(instrument, "fee_model.overrides")] = [
                _decimal_text(rates[0], "fee_model.overrides.maker_rate"),
                _decimal_text(rates[1], "fee_model.overrides.taker_rate"),
            ]
        result = {"type": model_type, "maker_rate": maker, "taker_rate": taker, "overrides": normalized}
        if model_type == "capped_option":
            cap = value.get("cap_rate")
            result["cap_rate"] = None if cap in (None, "") else _decimal_text(
                cap, "venues.native_config.fee_model.cap_rate",
            )
        return result
    _reject_unknown(value, {"type", "schedule_ref"}, "venues.native_config.fee_model")
    return {"type": "historical_schedule", "schedule_ref": _nonempty_text(value.get("schedule_ref"), "fee_model.schedule_ref")}


def _latency_model(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig("venues.native_config.latency_model", "must be a tagged model object")
    model_type = _enum(value.get("type"), "venues.native_config.latency_model.type", ("none", "static"))
    if model_type == "none":
        _reject_unknown(value, {"type"}, "venues.native_config.latency_model")
        return {"type": "none"}
    allowed = {"type", "base_latency_nanos", "insert_latency_nanos", "update_latency_nanos", "cancel_latency_nanos"}
    _reject_unknown(value, allowed, "venues.native_config.latency_model")
    return {
        "type": "static",
        **{
            key: _nonnegative_int(value.get(key, 0), f"latency_model.{key}")
            for key in allowed - {"type"}
        },
    }


def _money_string(value: object, field: str) -> str:
    parts = str(value or "").strip().replace(",", "").rsplit(None, 1)
    if len(parts) != 2:
        raise UnsupportedExecutionConfig(field, "must use Nautilus Money format '<amount> <currency>'")
    amount = _decimal_text(parts[0], f"{field}.amount")
    if Decimal(amount) < 0:
        raise UnsupportedExecutionConfig(field, "amount must be nonnegative")
    currency = _nonempty_text(parts[1], f"{field}.currency").upper()
    return f"{amount} {currency}"


def _optional_decimal(value: object, field: str, *, positive: bool) -> str | None:
    if value in (None, ""):
        return None
    result = _decimal_text(value, field)
    amount = Decimal(result)
    if amount < 0 or (positive and amount == 0):
        raise UnsupportedExecutionConfig(field, "must be positive" if positive else "must be nonnegative")
    return result


def _decimal_text(value: object, field: str) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnsupportedExecutionConfig(field, "must be a finite decimal") from exc
    if not amount.is_finite():
        raise UnsupportedExecutionConfig(field, "must be a finite decimal")
    return str(amount)


def _finite_number(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedExecutionConfig(field, "must be a finite number") from exc
    if not math.isfinite(number):
        raise UnsupportedExecutionConfig(field, "must be a finite number")
    return number


def _probability(value: object, field: str) -> float:
    number = _finite_number(value, field)
    if not 0 <= number <= 1:
        raise UnsupportedExecutionConfig(f"venues.native_config.fill_model.{field}", "must be between 0 and 1")
    return number


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer") from exc
    if number < 0 or str(number) != str(value).strip():
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer")
    return number


def _enum(value: object, field: str, options: tuple[str, ...]) -> str:
    result = str(value or "").strip()
    if result not in options:
        raise UnsupportedExecutionConfig(field, f"must be one of {', '.join(options)}")
    return result


def _nonempty_text(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise UnsupportedExecutionConfig(field, "must be nonempty")
    return result


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise UnsupportedExecutionConfig(field, "unknown model parameters: " + ", ".join(sorted(map(str, unknown))))


__all__ = ["default_native_venue_config", "freeze_native_venue_config", "native_configuration_schema"]
