"""Compile the authoring backtest settings into a compact Nautilus contract.

The authoring registry contains many FactorTester controls.  This module is
the explicit boundary between those controls and Nautilus execution: it only
copies settings with a verified semantic mapping and reports every setting
that still needs an adapter instead of passing legacy keys through.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from server.services.nautilus_bridge.config import (
    UnsupportedExecutionConfig,
)
from server.services.nautilus_bridge.source_registry import (
    AdapterContract,
    NautilusSourceRegistry,
    UnsupportedNautilusSource,
    from_server_sources,
)
from server.services.nautilus_bridge.version import NAUTILUS_VERSION


def freeze_execution_contract(
    settings: dict[str, Any], *, product_scope_refs: list[str],
    native_venue_plan: dict[str, Any], instrument_execution_policy: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the exact subset currently expressible by the Nautilus adapter.

    Returned values are canonical Nautilus bridge keys.  ``blockers`` is
    persisted with the RunSpec for review but is never accepted as an
    executable contract by the runner.
    """
    contract: dict[str, Any] = {
        "contract_version": 2,
        "native_configuration_version": NAUTILUS_VERSION,
        "settings": {
            "product_scope_refs": list(product_scope_refs),
            "venues": [dict(item) for item in native_venue_plan["venues"]],
            "strategy_venue_bindings": native_venue_plan["strategy_bindings"],
            "account_model": native_venue_plan["account_model"],
            "execution_model": native_venue_plan["execution_model"],
            "shared_market_data": native_venue_plan["shared_market_data"],
            "initial_capital_major": str(_positive_decimal(settings.get("initial_capital_major")) or ""),
            "base_currency": str(settings.get("base_currency") or "").strip().upper(),
            "instrument_execution_policy": instrument_execution_policy,
        },
        "fields": [],
        "blockers": [],
    }
    target = contract["settings"]
    fields: list[dict[str, Any]] = contract["fields"]
    blockers: list[dict[str, str]] = contract["blockers"]

    def mapped(path: str, note: str = "") -> None:
        fields.append({"path": path, "status": "mapped", **({"note": note} if note else {})})

    def blocked(path: str, reason: str) -> None:
        fields.append({"path": path, "status": "unsupported", "reason": reason})
        blockers.append({"path": path, "reason": reason})

    target["venues"] = _resolve_venue_fee_models(
        target["venues"], settings, mapped=mapped, blocked=blocked,
    )
    settings["venues"] = target["venues"]

    source_adapter, source_reason = _source_adapter(settings)
    if source_adapter is None:
        blocked("data_source", source_reason)
    else:
        target["data_source_ref"] = source_adapter.member_key
        # Source data is not yet revisioned independently of the file store.
        # Keep that limitation explicit instead of fabricating a content version.
        target["source_version"] = None
        target["bar_end_timestamps"] = True
        fields.extend((
            {"path": "data_source", "status": "mapped"},
            {"path": "freq_fixed", "status": "mapped"},
        ))
        contract["source_adapter"] = {
            "adapter_id": source_adapter.adapter_id,
            "frequency": source_adapter.frequency,
            "feed_kind": "bar",
            "bar_time_semantics": source_adapter.bar_time_semantics,
            "clock_policy": source_adapter.clock_policy,
            "supported_book_types": list(source_adapter.supported_book_types),
        }
        supported_book_types = set(source_adapter.supported_book_types)
        for venue in target["venues"]:
            native = venue.get("native_config") or {}
            book_type = str(native.get("book_type") or "")
            if book_type not in supported_book_types:
                blocked(
                    f"venues.{venue.get('name', '')}.native_config.book_type",
                    f"数据源适配器 {source_adapter.adapter_id} 未声明支持 Nautilus BookType {book_type or '—'}；"
                    f"可用类型：{', '.join(sorted(supported_book_types)) or '无'}",
                )

    window, window_reason = _utc_window(settings)
    if window is None:
        blocked("start_date/end_date", window_reason)
    else:
        target.update(window)
        mapped("start_date/end_date/timezone", "固定为带 UTC 偏移的回测边界")

    basis = str(settings.get("execution_price_basis") or "open").strip().lower()
    if basis != "open":
        blocked("execution_price_basis", "当前 Nautilus 合同只支持下一 Bar 开盘价")
    else:
        target["execution_price_basis"] = "open"
        target["execution_timing"] = "next_bar_open"
        mapped("execution_price_basis", "订单在下一根 Bar 的开盘撮合腿提交")

    order_type = str(settings.get("order_type") or "market").strip().lower()
    if order_type != "market":
        blocked("order_type", "当前已验证的 RunSpec 路径只接受市价单")
    else:
        mapped("order_type")

    # Matching and liquidity are now selected per Nautilus Venue. Only reject
    # legacy modes whose semantics cannot be expressed by those native fields.
    liquidity = str(settings.get("liquidity_mode") or "infinite").strip().lower()
    matching = str(settings.get("matching_model") or "auto").strip().lower()
    if liquidity == "volume_participation" or matching == "bar_volume_limited":
        blocked(
            "matching_model/liquidity_mode",
            "旧整 Bar 成交量参与率与 Nautilus 按 OHLC 撮合腿/盘口消耗的语义不同；请在 Venue 原生配置中选择",
        )
    else:
        fields.append({
            "path": "matching_model/liquidity_mode", "status": "not_applicable",
            "note": "撮合簿类型、FillModel 与流动性消耗已按 Nautilus Venue 配置",
        })

    # FeeModel is a Venue property in Nautilus. The RunSpec above freezes one
    # concrete model per Venue; the old global fee selector no longer chooses
    # the execution model.
    fields.append({
        "path": "fee_mode", "status": "not_applicable",
        "note": "费用模型已按 Nautilus Venue 固定在 venues[].native_config.fee_model",
    })

    slippage = str(settings.get("slippage_mode") or "none").strip().lower()
    if slippage == "none":
        fields.append({
            "path": "slippage_mode", "status": "not_applicable",
            "note": "滑点由每个 Venue 的 Nautilus FillModel 参数决定",
        })
    else:
        blocked(
            "slippage_mode",
            "固定基点滑点尚未接入 Nautilus FillModel，不能当作零滑点执行",
        )

    # These values affect account state or order lifecycle and must be consumed
    # by a tested Nautilus adapter before the job can be submitted.
    fields.extend((
        {"path": "venues", "status": "mapped",
         "note": "按 Nautilus SimulatedVenueConfig 冻结每个 Venue 的账户、成交模型、费用、延迟和撮合参数"},
        {"path": "strategy_venue_bindings", "status": "mapped",
         "note": "策略实例可绑定多个 Venue；同 Venue 策略共用账户和撮合状态"},
        {"path": "initial_capital_major/base_currency", "status": "mapped",
         "note": "所有 Venue 初始余额之和校验为 RunSpec 总资金"},
    ))
    _append_native_venue_fields(target["venues"], fields, blockers)
    _append_execution_policy_fields(target, fields, blockers)
    unsupported_fields = {
        "margin_mode": "保证金设置尚未按品种映射为 Nautilus Instrument/账户规则",
        "margin_call_mode": "强平策略尚未映射到 Nautilus 风控/订单生命周期",
        "rollover_policy": "换月规则尚未映射到具体合约和 Nautilus 订单操作",
    }
    for key, reason in unsupported_fields.items():
        if settings.get(key) not in (None, ""):
            blocked(key, reason)

    _complete_authoring_field_coverage(
        settings, fields, blockers,
        source_adapter_available=source_adapter is not None,
    )

    return contract


def _resolve_venue_fee_models(
    venues: list[dict[str, Any]], settings: dict[str, Any], *, mapped, blocked,
) -> list[dict[str, Any]]:
    """Freeze one explicit Nautilus FeeModel per Venue.

    A legacy global fee choice is used only to fill venues whose editor model
    remains unset. Explicit Venue FeeModels always take precedence.
    """
    mode = str(settings.get("fee_mode") or "").strip().lower()
    normalized: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for original in venues:
        venue = dict(original)
        native = dict(venue.get("native_config") or {})
        fee = dict(native.get("fee_model") or {"type": "unconfigured"})
        if fee.get("type") in {"unconfigured", "inherit"}:
            if mode == "zero":
                fee = {"type": "zero"}
            elif mode == "per_contract":
                try:
                    amount = Decimal(str(settings.get("fee_per_contract")))
                except (InvalidOperation, ValueError):
                    amount = Decimal("NaN")
                currency = str(settings.get("fee_currency") or venue.get("base_currency") or "").upper()
                if amount.is_finite() and amount >= 0 and currency:
                    fee = {"type": "per_contract", "commission": f"{amount} {currency}"}
            elif mode == "historical_schedule" and settings.get("fee_schedule_ref"):
                fee = {
                    "type": "historical_schedule",
                    "schedule_ref": str(settings["fee_schedule_ref"]),
                }
        if fee.get("type") in {"unconfigured", "inherit"}:
            unresolved.append(str(venue.get("name") or "(unknown)"))
        native["fee_model"] = fee
        venue["native_config"] = native
        normalized.append(venue)
    if unresolved:
        blocked(
            "venues.native_config.fee_model",
            "Nautilus 要求每个 Venue 明确指定 FeeModel；未配置：" + ", ".join(unresolved),
        )
    else:
        mapped(
            "venues.native_config.fee_model",
            "每个 Venue 均冻结为明确的 Nautilus FeeModel",
        )
    return normalized


def _append_native_venue_fields(
    venues: list[dict[str, Any]], fields: list[dict[str, Any]],
    blockers: list[dict[str, str]],
) -> None:
    """Expose the same native schema consumed by the Venue editor and freezer."""
    from server.services.nautilus_bridge.native_configuration import native_configuration_schema

    schema = native_configuration_schema()
    for venue in venues:
        name = str(venue["name"])
        venue_values = {**venue, "base_currency": venue["base_currency"]}
        identity = schema["venue_identity"]
        fields.append({
            "path": f"venues.{name}.{identity['path']}",
            "label": f"{name} · {identity['label']}",
            "value": name,
            "status": "nt_native",
            "section": identity["section"],
            "review_section": "account",
            "type": identity["type"],
        })
        for descriptor in schema["venue_fields"]:
            path = str(descriptor["path"])
            value: Any = venue_values
            for component in path.split("."):
                value = value.get(component) if isinstance(value, dict) else None
            row: dict[str, Any] = {
                "path": f"venues.{name}.{path}",
                "label": f"{name} · {descriptor['label']}",
                "value": value,
                "status": str(descriptor.get("status") or "nt_native"),
                "section": descriptor["section"],
                "review_section": "account",
                "type": descriptor["type"],
            }
            if descriptor.get("help"):
                row["note"] = str(descriptor["help"])
            fields.append(row)
        native = venue["native_config"]
        for descriptor in schema["fields"]:
            path = str(descriptor["path"])
            value: Any = native
            for component in path.split("."):
                value = value.get(component) if isinstance(value, dict) else None
            status = str(descriptor.get("status") or "nt_native")
            reason = None
            if path == "fee_model.type" and value in {"unconfigured", "inherit"}:
                status = "unsupported"
                reason = "Nautilus 要求为每个 Venue 配置明确的 FeeModel"
            row: dict[str, Any] = {
                "path": f"venues.{name}.native_config.{path}",
                "label": f"{name} · {descriptor['label']}",
                "value": value,
                "status": status,
                "section": descriptor["section"],
                "review_section": "account" if descriptor["section"] == "account" else "execution",
                "type": descriptor["type"],
            }
            if descriptor.get("implementation_note"):
                row["note"] = str(descriptor["implementation_note"])
            if reason:
                row["reason"] = reason
                blockers.append({"path": row["path"], "reason": reason})
            fields.append(row)


def _append_execution_policy_fields(
    settings: dict[str, Any], fields: list[dict[str, Any]],
    blockers: list[dict[str, str]],
) -> None:
    """Project native timing, cost-basis and settlement policy branches.

    The capability descriptors are shared with the frontend.  DMTM remains
    frozen in RunSpec for review, but cannot be submitted until the official
    settlement event adapter and account posting path are connected.
    """
    from server.services.nautilus_bridge.native_configuration import native_configuration_schema

    schema = native_configuration_schema()
    coverage = {
        item["parameter"]: item
        for item in schema["execution_policy_coverage"]
    }

    timing = coverage["execution_timing"]
    fields.append({
        "path": timing["runspec_path"],
        "label": "成交时点",
        "value": settings.get("execution_timing"),
        "status": timing["status"],
        "section": "execution",
        "review_section": "execution",
        "type": "enum",
        "note": timing["note"],
    })

    policy = settings.get("instrument_execution_policy") or {}
    daily = policy.get("daily_settlement") or {}
    enabled = (
        daily.get("default") == "eligible_products"
        or any(value is True for value in (daily.get("scope_overrides") or {}).values())
        or any(value is True for value in (daily.get("instrument_overrides") or {}).values())
    )
    dmtm = coverage["daily_settlement"]
    dmtm_status = "unsupported" if enabled else "not_applicable"
    dmtm_note = dmtm["note"] if enabled else (
        "本次 RunSpec 已关闭 DMTM，不需要结算事件适配器。"
    )
    dmtm_row = {
        "path": dmtm["runspec_path"],
        "label": "逐日盯市（DMTM）",
        "value": daily,
        "status": dmtm_status,
        "section": "account",
        "review_section": "account",
        "type": "object",
        "note": dmtm_note,
    }
    fields.append(dmtm_row)
    if enabled:
        blockers.append({"path": dmtm["runspec_path"], "reason": dmtm_note})

    basis = policy.get("position_cost_basis") or {}
    for key in ("position_cost_basis", "position_cost_basis_by_instrument"):
        descriptor = coverage[key]
        fields.append({
            "path": descriptor["runspec_path"],
            "label": "持仓成本基准" if key == "position_cost_basis" else "持仓成本基准例外",
            "value": basis.get("default") if key == "position_cost_basis" else {
                "scope_overrides": basis.get("scope_overrides") or {},
                "instrument_overrides": basis.get("instrument_overrides") or {},
            },
            "status": descriptor["status"],
            "section": "account",
            "review_section": "account",
            "type": "enum" if key == "position_cost_basis" else "object",
            "note": descriptor["note"],
        })


def _positive_decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _complete_authoring_field_coverage(
    settings: dict[str, Any], fields: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    *, source_adapter_available: bool,
) -> None:
    """Make every submitted editor field visible in the frozen contract.

    The editor serializes only visible fields.  Any field not already handled
    by a mapper must therefore either be an explicit no-op for this exact
    configuration or become a submission blocker.  This prevents a newly
    added setting from silently disappearing between the editor and Nautilus.
    """
    covered = {
        token
        for item in fields
        for token in str(item.get("path") or "").split("/")
    }
    contract_owned = {
        "product_scope_refs", "venues", "strategy_venue_bindings",
        "account_model", "execution_model", "shared_market_data",
        "instrument_execution_policy", "start_utc", "end_utc",
        "data_source_ref", "source_version", "bar_end_timestamps",
    }
    for key, value in settings.items():
        if key in covered or key in contract_owned:
            continue
        status, note_or_reason = _authoring_setting_disposition(
            key, value, settings,
            source_adapter_available=source_adapter_available,
        )
        if status == "unsupported":
            fields.append({
                "path": key, "status": status,
                "reason": note_or_reason,
            })
            blockers.append({"path": key, "reason": note_or_reason})
        else:
            fields.append({
                "path": key, "status": status,
                **({"note": note_or_reason} if note_or_reason else {}),
            })


def _authoring_setting_disposition(
    key: str, value: Any, settings: dict[str, Any], *,
    source_adapter_available: bool | None = None,
) -> tuple[str, str]:
    if key.endswith("_custom_product_fields") and not value:
        return "not_applicable", "未配置自定义产品字段"
    if key == "factor_role_bindings" and not value:
        return "not_applicable", "没有配置角色化因子绑定"
    if key == "data_source_mode":
        if value == "list" and len(settings.get("data_source") or []) == 1:
            return "mapped", "数据源已唯一解析为服务端登记的 Nautilus Bar 适配器"
        return "unsupported", "自动或多源回退尚未冻结为确定的数据输入"
    if key == "freq_mode":
        available = (
            source_adapter_available if source_adapter_available is not None
            else _source_adapter(settings)[0] is not None
        )
        if value == "fixed" and available:
            return "mapped", "频率已解析为来源注册表中已验证的 Bar 适配器"
        return "unsupported", "当前没有可用于该频率选择的已验证 Nautilus 数据适配器"
    if key == "freq_fixed":
        available = (
            source_adapter_available if source_adapter_available is not None
            else _source_adapter(settings)[0] is not None
        )
        if available:
            return "mapped", "已由来源注册表解析为 Nautilus Bar 适配器"
        return "unsupported", "当前来源没有该频率的已验证 Nautilus Bar 适配器"
    if key in {"start_time", "end_time", "time_precision"}:
        if settings.get("time_precision", "exact") == "exact":
            return "mapped", "已与日期和时区一并冻结为 UTC 边界"
        return "unsupported", "交易日边界尚未由产品交易日历解析"
    if key == "timezone":
        return "mapped", "已按 IANA 时区转换并冻结为 UTC 边界"
    if key == "data_source":
        return "mapped", "已解析为确定的数据源成员"
    if key == "nautilus_venue":
        if not value:
            return "not_applicable", "OHLC 分配参数现由各 Nautilus Venue 配置"
        configured = [
            item.get("native_config", {}) for item in settings.get("venues", [])
            if isinstance(item, dict)
        ]
        weights = value.get("bar_volume_weights_bps") if isinstance(value, dict) else None
        remainder = value.get("bar_volume_remainder_to", "close") if isinstance(value, dict) else "close"
        if configured and all(
            item.get("bar_volume_weights_bps") == weights
            and item.get("bar_volume_remainder_to") == remainder
            for item in configured
        ):
            return "mapped", "旧字段已折叠为每个 Nautilus Venue 的 BarVolumeAllocation"
        return "unsupported", "全局 OHLC 分配与每个 Venue 的原生 BarVolumeAllocation 冲突；请改用 Venue 设置"
    if key == "engine":
        if str(value or "").strip().lower() in {"native", "nautilus_trader"}:
            return "mapped", "执行内核由 execution.backend=nautilus_trader 冻结"
        return "unsupported", "旧回测引擎选择不能用于 NautilusTrader RunSpec"
    if key in {
        "engine_mode", "accounting_mode", "daily_mark_to_market_enabled",
        "cost_basis_method", "instrument_execution_policy_overrides",
    }:
        return "mapped", "已折叠为版本化的逐品种执行政策"
    if key == "product_path_selection":
        return "mapped", "已折叠为冻结的 product_scope_refs"
    if key == "evaluation_split":
        return "not_applicable", "样本切分保留在 FactorTester RunSpec 分析合同，不是 Nautilus 撮合参数"
    if key == "strategy_book_mode":
        if value in {"per_strategy_one_ledger", "per_account"}:
            return "unsupported", "FactorTester 账户分账选项不对应 Nautilus 原生 Venue 账户；同 Venue 策略共用该场所账户"
        return "unsupported", "Nautilus 账户按 Venue 配置；不支持策略私有的独立现金账本"
    if key == "account_currency":
        currency = str(value or "").strip().upper()
        base_currency = str(settings.get("base_currency") or "").strip().upper()
        if currency and currency == base_currency:
            return "mapped", "与 Nautilus 账户 base_currency 相同"
        return "unsupported", "账户币种必须与冻结的 base_currency 一致；跨币种资金尚未接通"
    if key == "counterparty_profile":
        if value in (None, ""):
            return "not_applicable", "没有使用经纪商预设"
        return "unsupported", "经纪商预设尚未冻结为历史费用、保证金和执行规则"
    if key == "bar_open_visibility_delay":
        if str(value or "").strip().lower() == "1us":
            return "mapped", "由 Nautilus 的下一 Bar 开盘撮合事件取代旧时间戳偏移"
        return "unsupported", "Nautilus 原生开盘事件不使用旧 bar-open 人工时间偏移"
    if key == "bar_end_visibility_delay":
        if str(value or "").strip().lower() in {"0ns", "0", "0s"}:
            return "mapped", "行情字段在已完成 Bar 事件发布时可用"
        return "unsupported", "非零 Bar 结束可见延迟尚未接入 FactorExpr 发布时钟"
    if key == "transaction_fee_source":
        if _has_explicit_venue_fee_models(settings):
            return "not_applicable", "每个 Venue 已固定 Nautilus FeeModel；旧费用来源字段不再生效"
        if settings.get("fee_mode") == "zero":
            return "not_applicable", "零手续费模式不读取费率来源"
        return "unsupported", "费用来源尚未冻结为逐品种、逐有效时刻的 Nautilus FeeModel 输入"
    if key == "fixed_fee_rate":
        if _has_explicit_venue_fee_models(settings) and _zero(value):
            return "not_applicable", "手续费已由每个 Venue 的 Nautilus FeeModel 决定"
        if settings.get("fee_mode") != "fixed" and _zero(value):
            return "not_applicable", "固定费率模式未启用"
        return "unsupported", "旧固定费率尚未映射到 Nautilus FeeModel"
    if key in {"fee_per_contract", "fee_currency", "fee_schedule_ref"}:
        if settings.get("fee_mode") in {"per_contract", "historical_schedule"}:
            return "mapped", "旧草稿值已折叠为每个 Venue 的明确 Nautilus FeeModel"
        if _has_explicit_venue_fee_models(settings):
            return "not_applicable", "费用已按 Venue 固定；全局旧费用字段不再生效"
        if value in (None, ""):
            return "not_applicable", "没有使用此旧费用字段"
        return "unsupported", "此旧费用字段没有与所选 Nautilus FeeModel 对应"
    if key == "fee_custom_product_fields":
        if not value:
            return "not_applicable", "未配置自定义费用字段"
        return "unsupported", "费用覆盖必须先冻结为逐品种历史费率时间轴"
    if key == "slippage_bps":
        if settings.get("slippage_mode") == "none" and _zero(value):
            return "not_applicable", "未启用基点滑点"
        return "unsupported", "固定基点滑点尚未映射到 Nautilus FillModel"
    if key == "slippage_mode":
        if str(value or "none").strip().lower() == "none":
            return "not_applicable", "滑点由每个 Venue 的 Nautilus FillModel 决定"
        return "unsupported", "旧滑点模式没有一一对应的 Nautilus FillModel 参数"
    if key == "matching_model":
        if str(value or "auto").strip().lower() in {"auto", "next_bar_full_fill"}:
            return "not_applicable", "撮合由 Venue 的 Nautilus BookType、FillModel 和 Bar 撮合参数决定"
        return "unsupported", "旧撮合模式没有与 Nautilus Venue 参数等价的映射"
    if key == "liquidity_mode":
        if str(value or "infinite").strip().lower() == "infinite":
            return "not_applicable", "流动性限制由各 Venue 的 liquidity_consumption 与数据簿类型决定"
        return "unsupported", "旧流动性模式与 Nautilus 按 Bar 撮合腿或真实盘口消耗的语义不同"
    if key == "nt_capacity_policy":
        selected = str(value or "unconstrained").strip().lower()
        native = [item.get("native_config", {}) for item in settings.get("venues", []) if isinstance(item, dict)]
        if selected == "unconstrained":
            return "not_applicable", "容量策略已按 Venue 的 Nautilus 原生参数冻结"
        if selected == "bar_volume" and native and all(
            item.get("liquidity_consumption") is True
            and item.get("bar_execution") is True
            and item.get("book_type") == "L1_MBP" for item in native
        ):
            return "mapped", "旧草稿选项已折叠为每个 Venue 的 Bar-volume liquidity_consumption"
        if selected == "recorded_depth" and native and all(
            item.get("liquidity_consumption") is True
            and item.get("book_type") in {"L2_MBP", "L3_MBO"} for item in native
        ):
            return "mapped", "旧草稿选项已折叠为每个 Venue 的盘口流动性消耗"
        return "unsupported", "旧全局容量模式与按 Venue 冻结的 Nautilus 参数不一致"
    if key == "nt_price_protection_points":
        native = [item.get("native_config", {}) for item in settings.get("venues", []) if isinstance(item, dict)]
        if native and all(item.get("price_protection_points") == value for item in native):
            return "mapped", "已折叠为各 Venue 的 price_protection_points"
        if _zero(value):
            return "not_applicable", "未启用市价保护点数，使用各 Venue 的原生设置"
        return "unsupported", "全局保护点数与按 Venue 冻结的 Nautilus 参数不一致"
    if key == "participation_rate":
        if settings.get("liquidity_mode", "infinite") == "infinite":
            return "not_applicable", "不限制成交量时参与率不生效"
        return "unsupported", "旧整 Bar 参与率尚未映射为共享、确定性的 Nautilus FillModel 容量"
    if key == "volume_execution_price_basis":
        if settings.get("liquidity_mode", "infinite") == "infinite":
            return "not_applicable", "没有启用旧成交量容量模型"
        return "unsupported", "旧成交量容量价格基准未映射到 Nautilus 撮合事件"
    if key == "custom_product_fields":
        rows = value if isinstance(value, list) else []
        unsupported = [
            row for row in rows if isinstance(row, dict)
            and row.get("field") not in {"DailyMarkToMarketEnabled", "CostBasisMethod"}
        ]
        if not unsupported:
            return "mapped", "DMTM 与持仓成本规则已折叠到逐品种政策"
        return "unsupported", "自定义产品字段必须先冻结为 Nautilus Instrument/历史规则事件"
    if key in {"factor_mode", "signal_freq", "basepoint", "daily_basepoint",
               "warmup_mode", "warmup_window", "calendar_frequency",
               "end_session_skip", "end_session_gap"}:
        return "unsupported", "因子计算/交易日历字段尚未全部接入 Nautilus 事件驱动 FactorExpr 发布器"
    if key in {"strategy_intent_mode", "split_count", "group_index",
               "position_policy", "rebalance_trigger", "allocation_policy",
               "sizing_transform", "volatility_lookback", "volatility_warmup",
               "screen_rule", "screen_lower", "screen_upper", "threshold_mode",
               "entry_threshold", "exit_threshold", "quantile_entry",
               "quantile_exit", "side_mode", "term_carry_near_rank",
               "term_carry_far_rank", "term_carry_entry_threshold",
               "term_carry_exit_threshold", "term_carry_gross_weight",
               "factor_role_bindings", "category"}:
        return "unsupported", "策略模板参数尚未冻结为本次 Nautilus Strategy 的可执行参数"
    if key in {"margin_mode", "fixed_margin_ratio", "collateral_fraction",
               "margin_call_mode", "liquidation_target_buffer",
               "margin_custom_product_fields", "target_margin_utilization",
               "max_margin_utilization", "margin_utilization_tolerance"}:
        return "unsupported", "Nautilus 账户/保证金/强平配置尚未由历史交易规则编译并接入撮合账户"
    if key in {"force_close_before_expiry", "rollover_policy",
               "rollover_before_expiry"}:
        return "unsupported", "换月需要数据源提供的冻结主力切换表和可交易合约映射"
    if key in {"historical_field_policy", "trading_rule_custom_product_fields"}:
        return "unsupported", "必须冻结有版本的交易所历史规则时间轴，不能按最新快照或旧配置推断"
    if key in {"use_minor_units", "use_int_position", "quantity_rounding_policy"}:
        return "unsupported", "下单数量尚未按 Nautilus Instrument 的 size_increment 和 lot 规则冻结"
    if key in {"cash_reserve_ratio", "cash_reserve_major", "currency_conversion_fee_rate",
               "ledger_session_policy"}:
        return "unsupported", "旧资金池/账本配置不能隐式改写 Nautilus 子账户资金语义"
    if key == "equity_compute_live":
        return "not_applicable", "权益曲线由 Nautilus 账户事件和原生报告提供"
    if value in (None, "", [], {}):
        return "not_applicable", "此字段未设置"
    return "unsupported", "该 RunSpec 设置没有已验证的 Nautilus 原生映射或 FactorTester 适配器"


def _zero(value: object) -> bool:
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _has_explicit_venue_fee_models(settings: dict[str, Any]) -> bool:
    venues = settings.get("venues")
    if not isinstance(venues, list) or not venues:
        return False
    return all(
        isinstance(item, dict)
        and item.get("native_config", {}).get("fee_model", {}).get("type")
        not in {None, "unconfigured", "inherit"}
        for item in venues
    )


def _source_adapter(
    settings: dict[str, Any], *, registry: NautilusSourceRegistry | None = None,
) -> tuple[AdapterContract | None, str]:
    mode = str(settings.get("data_source_mode") or "auto").strip().lower()
    frequency_mode = str(settings.get("freq_mode") or "auto").strip().lower()
    frequency = str(settings.get("freq_fixed") or "").strip().upper()
    sources = settings.get("data_source")
    if mode != "list" or not isinstance(sources, list) or len(sources) != 1:
        return None, "请明确选择单一数据源；自动/多源回退尚未冻结为确定的 Nautilus 输入"
    if frequency_mode != "fixed":
        return None, "Nautilus RunSpec 要求明确固定数据频率"
    selected = str(sources[0] or "").strip()
    try:
        source_registry = registry or from_server_sources()
        return source_registry.adapter_for(
            source_key=selected, frequency=frequency,
            instrument_scope="physical_contract",
        ), ""
    except UnsupportedNautilusSource as exc:
        return None, str(exc)


def _utc_window(settings: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
    start_date = str(settings.get("start_date") or "").strip()
    end_date = str(settings.get("end_date") or "").strip()
    precision = str(settings.get("time_precision") or "exact").strip().lower()
    zone_name = str(settings.get("timezone") or "UTC").strip()
    if not start_date or not end_date:
        return None, "RunSpec 必须包含开始和结束日期"
    if precision != "exact":
        return None, "当前合同要求明确时刻；交易日边界需由交易日历适配器解析"
    try:
        zone = ZoneInfo(zone_name)
        start_day = date.fromisoformat(start_date)
        end_day = date.fromisoformat(end_date)
        start_clock = time.fromisoformat(str(settings.get("start_time") or "00:00"))
        end_clock = time.fromisoformat(str(settings.get("end_time") or "23:59"))
    except (ValueError, ZoneInfoNotFoundError):
        return None, "日期、时刻或时区无效，无法生成确定的 UTC 回测窗口"

    def localize(day: date, clock: time) -> datetime:
        local = datetime.combine(day, clock).replace(tzinfo=zone)
        roundtrip = local.astimezone(timezone.utc).astimezone(zone)
        if roundtrip.replace(tzinfo=None) != local.replace(tzinfo=None):
            raise ValueError("nonexistent local time")
        return local.astimezone(timezone.utc)

    try:
        start = localize(start_day, start_clock)
        end = localize(end_day, end_clock)
    except ValueError:
        return None, "时区在指定边界存在无效的本地时间"
    if start >= end:
        return None, "结束时间必须晚于开始时间"
    return {"start_utc": start.isoformat(), "end_utc": end.isoformat()}, ""


__all__ = ["freeze_execution_contract"]
