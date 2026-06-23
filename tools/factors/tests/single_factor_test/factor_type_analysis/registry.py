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
    POSITION = "position"      # 持仓量
    PRICE_VOLUME = "price_volume"  # 量价关系
    CUSTOM = "custom"          # 自定义

    @property
    def label_cn(self) -> str:
        labels = {
            "trend": "趋势跟踪",
            "momentum": "动量",
            "volatility": "波动率",
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
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "category": self.category.value,
            "category_label": self.category.label_cn,
            "factor_alias": self.factor_alias,
            "factor_family_alias": self.factor_family_alias,
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
        help_text="趋势跟踪基准—多空趋势判断",
    ),
    ReferenceFactorDef(
        key="trend_mm_mabreak", name="MmMABreak",
        category=FactorCategory.TREND,
        factor_alias="MmMABreak",
        help_text="趋势跟踪基准—均线突破",
    ),
    # --- 动量类 ---
    ReferenceFactorDef(
        key="mom_mm_ret", name="MmRet",
        category=FactorCategory.MOMENTUM,
        factor_alias="MmRet",
        help_text="动量基准—N日收益率",
    ),
    ReferenceFactorDef(
        key="mom_mm_rsi", name="MmRSI",
        category=FactorCategory.MOMENTUM,
        factor_alias="MmRSI",
        help_text="动量基准—RSI指标",
    ),
    # --- 波动率类 ---
    ReferenceFactorDef(
        key="vol_vl_atr", name="VlATR",
        category=FactorCategory.VOLATILITY,
        factor_alias="VlATR",
        help_text="波动率基准—ATR",
    ),
    ReferenceFactorDef(
        key="vol_vl_gk", name="VlGK",
        category=FactorCategory.VOLATILITY,
        factor_alias="VlGK",
        help_text="波动率基准—GK波动率",
    ),
    # --- 持仓量类 ---
    ReferenceFactorDef(
        key="pos_oi_chg_rat", name="OiChgRat",
        category=FactorCategory.POSITION,
        factor_alias="OiChgRat",
        help_text="持仓量基准—持仓变化率",
    ),
    ReferenceFactorDef(
        key="pos_oi_net_build", name="OiNetBuild",
        category=FactorCategory.POSITION,
        factor_alias="OiNetBuild",
        help_text="持仓量基准—净持仓变化",
    ),
    # --- 量价关系类 ---
    ReferenceFactorDef(
        key="pv_vp_amihud", name="VpAmihud",
        category=FactorCategory.PRICE_VOLUME,
        factor_alias="VpAmihud",
        help_text="量价基准—Amihud非流动性",
    ),
    ReferenceFactorDef(
        key="pv_vp_vol_price_corr", name="VpVolPriceCorr",
        category=FactorCategory.PRICE_VOLUME,
        factor_alias="VpVolPriceCorr",
        help_text="量价基准—量价相关性",
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
