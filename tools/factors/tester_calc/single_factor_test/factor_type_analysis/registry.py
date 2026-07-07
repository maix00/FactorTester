"""
ReferenceFactorRegistry — 参照因子注册中心。

定义预置的因子类别（趋势跟踪、波动率、动量、持仓量、量价关系），
每个类别有一个或多个代表性参照因子及其配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FactorCategory(str, Enum):
    """因子类别枚举。"""
    TREND = "trend"            # 趋势跟踪
    MOMENTUM = "momentum"      # 动量
    VOLATILITY = "volatility"  # 波动率
    LOW_VOLATILITY = "low_volatility"  # 低波/防御
    VALUE = "value"            # 价值/期限结构估值
    CARRY = "carry"            # carry/展期收益
    QUALITY = "quality"        # 质量
    SIZE = "size"              # 规模
    YIELD = "yield"            # 收益率
    GROWTH = "growth"          # 成长
    LIQUIDITY = "liquidity"    # 流动性
    POSITION = "position"      # 持仓量
    PRICE_VOLUME = "price_volume"  # 量价关系
    CUSTOM = "custom"          # 自定义

    @property
    def label_cn(self) -> str:
        labels = {
            "trend": "趋势跟踪",
            "momentum": "动量",
            "volatility": "波动率",
            "low_volatility": "低波/防御",
            "value": "价值",
            "carry": "Carry",
            "quality": "质量",
            "size": "规模",
            "yield": "收益率",
            "growth": "成长",
            "liquidity": "流动性",
            "position": "持仓量",
            "price_volume": "量价关系",
            "custom": "自定义",
        }
        return labels[self.value]


@dataclass(frozen=True, slots=True)
class ReferenceFactorDef:
    """参照因子定义。"""
    key: str
    name: str
    category: FactorCategory
    factor_alias: str
    factor_family_alias: str = ""
    reference_source: str = "public_factor"
    asset_classes: tuple[str, ...] = ("futures",)
    enabled_by_default: bool = True
    requires_data: tuple[str, ...] = ("price_volume",)
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "category": self.category.value,
            "category_label": self.category.label_cn,
            "factor_alias": self.factor_alias,
            "factor_family_alias": self.factor_family_alias,
            "reference_source": self.reference_source,
            "asset_classes": list(self.asset_classes),
            "enabled_by_default": self.enabled_by_default,
            "requires_data": list(self.requires_data),
            "help_text": self.help_text,
        }


@dataclass(slots=True)
class ReferenceFactorRegistry:
    """
    参照因子注册中心。
    
    用法:
        registry = ReferenceFactorRegistry()
        registry.register(ReferenceFactorDef(
            key="trend_mm", name="MmTrend",
            category=FactorCategory.TREND,
            factor_alias="MmTrend"
        ))
        registry.register(ReferenceFactorDef(...))
    """

    _defs: dict[str, ReferenceFactorDef] = field(default_factory=dict)

    def register(self, ref_def: ReferenceFactorDef) -> None:
        if ref_def.key in self._defs:
            raise ValueError(f"duplicate reference factor key: {ref_def.key}")
        self._defs[ref_def.key] = ref_def

    def get(self, key: str) -> ReferenceFactorDef:
        return self._defs[key]

    def list(self) -> list[ReferenceFactorDef]:
        return list(self._defs.values())

    def by_category(self, category: FactorCategory) -> list[ReferenceFactorDef]:
        return [d for d in self._defs.values() if d.category == category]

    def categories(self) -> list[FactorCategory]:
        seen: set[FactorCategory] = set()
        result: list[FactorCategory] = []
        for d in self._defs.values():
            if d.category not in seen:
                seen.add(d.category)
                result.append(d.category)
        return result

    def manifest(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self.list()]

    def count(self) -> int:
        return len(self._defs)


# ========================
#  默认注册的参照因子
# ========================

_DEFAULT_REFERENCE_FACTORS = [
    # --- 趋势跟踪类 ---
    ReferenceFactorDef(
        key="trend_mm_trend", name="MmTrend",
        category=FactorCategory.TREND,
        factor_alias="MmTrend",
        factor_family_alias="MmTrend",
        help_text="趋势跟踪基准—多空趋势判断",
    ),
    ReferenceFactorDef(
        key="trend_mm_mabreak", name="MmMABreak",
        category=FactorCategory.TREND,
        factor_alias="MmMABreak",
        factor_family_alias="MmMABreak",
        help_text="趋势跟踪基准—均线突破",
    ),
    # --- 动量类 ---
    ReferenceFactorDef(
        key="mom_mm_ret", name="MmRet",
        category=FactorCategory.MOMENTUM,
        factor_alias="MmRet",
        factor_family_alias="MmRet",
        help_text="动量基准—N日收益率",
    ),
    ReferenceFactorDef(
        key="mom_mm_rsi", name="MmRSI",
        category=FactorCategory.MOMENTUM,
        factor_alias="MmRSI",
        factor_family_alias="MmRSI",
        help_text="动量基准—RSI指标",
    ),
    # --- 波动率类 ---
    ReferenceFactorDef(
        key="vol_vl_atr", name="VlATR",
        category=FactorCategory.VOLATILITY,
        factor_alias="VlATR",
        factor_family_alias="VlATR",
        help_text="波动率基准—ATR",
    ),
    ReferenceFactorDef(
        key="vol_vl_gk", name="VlGK",
        category=FactorCategory.VOLATILITY,
        factor_alias="VlGK",
        factor_family_alias="VlGK",
        help_text="波动率基准—GK波动率",
    ),
    ReferenceFactorDef(
        key="low_vol_inverse_realized", name="LowVolInv",
        category=FactorCategory.LOW_VOLATILITY,
        factor_alias="LowVolInv",
        factor_family_alias="LowVolInv",
        help_text="低波/防御基准—实现波动率的反向暴露",
        enabled_by_default=False,
    ),
    # --- 价值 / Carry 类（期货里通常由期限结构或基差代理） ---
    ReferenceFactorDef(
        key="value_ts_spread", name="TsSpreadValue",
        category=FactorCategory.VALUE,
        factor_alias="TsSpreadValue",
        factor_family_alias="TsSpreadValue",
        help_text="价值基准—期限结构价差/相对便宜度；需要期限结构数据",
        enabled_by_default=False,
        requires_data=("term_structure",),
    ),
    ReferenceFactorDef(
        key="carry_roll_yield", name="RollYieldCarry",
        category=FactorCategory.CARRY,
        factor_alias="RollYieldCarry",
        factor_family_alias="RollYieldCarry",
        help_text="Carry基准—展期收益/期限结构斜率；需要期限结构数据",
        enabled_by_default=False,
        requires_data=("term_structure",),
    ),
    # --- 持仓量类 ---
    ReferenceFactorDef(
        key="pos_oi_chg_rat", name="OiChgRat",
        category=FactorCategory.POSITION,
        factor_alias="OiChgRat",
        factor_family_alias="OiChgRat",
        help_text="持仓量基准—持仓变化率",
    ),
    ReferenceFactorDef(
        key="pos_oi_net_build", name="OiNetBuild",
        category=FactorCategory.POSITION,
        factor_alias="OiNetBuild",
        factor_family_alias="OiNetBuild",
        help_text="持仓量基准—净持仓变化",
    ),
    # --- 量价关系类 ---
    ReferenceFactorDef(
        key="pv_vp_amihud", name="VpAmihud",
        category=FactorCategory.PRICE_VOLUME,
        factor_alias="VpAmihud",
        factor_family_alias="VpAmihud",
        help_text="量价基准—Amihud非流动性",
    ),
    ReferenceFactorDef(
        key="pv_vp_vol_price_corr", name="VpVolPriceCorr",
        category=FactorCategory.PRICE_VOLUME,
        factor_alias="VpVolPriceCorr",
        factor_family_alias="VpVolPriceCorr",
        help_text="量价基准—量价相关性",
    ),
    ReferenceFactorDef(
        key="liq_amihud_inverse", name="LiquidityInv",
        category=FactorCategory.LIQUIDITY,
        factor_alias="LiquidityInv",
        factor_family_alias="LiquidityInv",
        help_text="流动性基准—交易冲击/非流动性的反向暴露",
        enabled_by_default=False,
    ),
    # --- 股票/截面风格，保留注册但默认不对期货运行 ---
    ReferenceFactorDef(
        key="quality_profitability", name="QualityProfitability",
        category=FactorCategory.QUALITY,
        factor_alias="QualityProfitability",
        asset_classes=("equity",),
        enabled_by_default=False,
        requires_data=("fundamental",),
        help_text="股票质量基准—盈利能力/稳健性，期货默认不启用",
    ),
    ReferenceFactorDef(
        key="size_market_cap", name="SizeMarketCap",
        category=FactorCategory.SIZE,
        factor_alias="SizeMarketCap",
        asset_classes=("equity",),
        enabled_by_default=False,
        requires_data=("fundamental",),
        help_text="股票规模基准—市值，期货默认不启用",
    ),
    ReferenceFactorDef(
        key="yield_dividend", name="DividendYield",
        category=FactorCategory.YIELD,
        factor_alias="DividendYield",
        asset_classes=("equity",),
        enabled_by_default=False,
        requires_data=("fundamental",),
        help_text="股票收益率基准—股息率，期货默认不启用",
    ),
    ReferenceFactorDef(
        key="growth_fundamental", name="GrowthFundamental",
        category=FactorCategory.GROWTH,
        factor_alias="GrowthFundamental",
        asset_classes=("equity",),
        enabled_by_default=False,
        requires_data=("fundamental",),
        help_text="股票成长基准—基本面成长，期货默认不启用",
    ),
]


def create_default_registry() -> ReferenceFactorRegistry:
    """创建并返回含默认参照因子的注册中心。"""
    registry = ReferenceFactorRegistry()
    for ref_def in _DEFAULT_REFERENCE_FACTORS:
        registry.register(ref_def)
    return registry


# 模块级单例（方便直接 import）
default_registry = create_default_registry()
