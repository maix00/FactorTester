"""限价单/最小开仓下单量 历史调整事件模型。

数据来源：国信期货《各交易所各品种每笔下单数量限制》页面的备注列，
从文本中解析出的「每次最小开仓下单量调整为X手」等历史变更记录。

每个 AlterEvent 记录一条独立调整，含：
- 交易所、品种、合约范围
- 调整前后的限价单/最小开仓量
- 生效日期
- 原始备注文本
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime
from typing import ClassVar

from . import SOURCE_URL


# ---------------------------------------------------------------------------
# 交易所标识
# ---------------------------------------------------------------------------
class Exchange:
    SHFE = "SHFE"       # 上海期货交易所
    INE = "INE"         # 上海国际能源交易中心
    DCE = "DCE"         # 大连商品交易所
    CZCE = "CZCE"       # 郑州商品交易所
    GFEX = "GFEX"       # 广州期货交易所
    CFFEX = "CFFEX"     # 中国金融期货交易所

    _LABELS: ClassVar[dict[str, str]] = {
        "上海期货": SHFE,
        "上海国际能源": INE,
        "大连商品": DCE,
        "郑州商品": CZCE,
        "广州期货": GFEX,
        "中国金融期货": CFFEX,
        "上期所": SHFE,
        "能源中心": INE,
        "大商所": DCE,
        "郑商所": CZCE,
        "广期所": GFEX,
        "中金所": CFFEX,
    }

    @classmethod
    def from_label(cls, label: str) -> str | None:
        for key, val in cls._LABELS.items():
            if key in label:
                return val
        return None


# ---------------------------------------------------------------------------
# 正则：从备注文本中提取调整事件
# ---------------------------------------------------------------------------
# 匹配模式：
#   "自2026年3月9日当晚夜盘交易起，2606合约每次最小开仓下单量调整为8手"
#   "自2026年4月27日当晚夜盘交易时起，2607、2608及2609合约...调整为4手"
#   "2022年3月8日当晚夜盘交易起，每次最小开仓下单量调整为4手"
#   "2023年07月12日起，每次最小开仓下单量调整为1手"
#   "自2025年月12月26日交易起，每次最小开仓下单量调整为5手"

_MIN_OPEN_PATTERN = re.compile(
    r"(?:自\s*)?"
    r"(?P<year>\d{4})\s*年\s*(?P<month>\d{1,2})\s*(?:月\s*(?:(?P<day>\d{1,2})\s*日?)|月)"
    r".*?(?:起|交易时起)"
    r".*?(?:每次最小开仓下单(?:数量|量)调整为|交易指令每次最小开仓下单量调整为)"
    r"(?P<new_qty>\d+)\s*手",
    re.DOTALL,
)

# 同时支持「2022年5月起」（无日）、「2025年月12月26日」（多余月字）
_MIN_OPEN_PATTERN_FALLBACK = re.compile(
    r"(?:自\s*)?"
    r"(?P<year>\d{4})\s*年\s*"
    r"(?:(?P<month>\d{1,2})\s*月\s*(?:(?P<day>\d{1,2})\s*日?)?"
    r"|月\s*(?P<month2>\d{1,2})\s*月\s*(?P<day2>\d{1,2})\s*日?)"
    r".*?(?:起|交易时起)"
    r".*?(?:每次最小开仓下单(?:数量|量)调整为|交易指令每次最小开仓下单量调整为)"
    r"(?P<new_qty>\d+)\s*手",
    re.DOTALL,
)

# 提取合约代码（如 2605、2606、2607-2609）
_CONTRACT_CODE_PATTERN = re.compile(r"(?P<code>\d{4}(?:\s*[-至及,\s]+\s*\d{4})*)\s*合约")

# 提取"除XX外"的例外品种
_EXCLUSION_PATTERN = re.compile(r"除(?P<excluded>.+?)外")


@dataclass(frozen=True, slots=True)
class AlterEvent:
    """单条限价单/最小开仓下单量调整事件。

    字段说明：
    - exchange: 交易所代码（SHFE/INE/DCE/CZCE/GFEX/CFFEX）
    - product_label: 品种中文名（如「甲醇」「动力煤」）
    - contract_codes: 合约代码范围，如 ["2607","2608","2609"]；
      若为品种级别调整则为空列表
    - field: 调整的字段类型
        - "MinLimitOrderVolume"   最小下单量（最小开仓下单量）
        - "MaxLimitOrderVolume"   最大下单量（限价指令）
    - old_value: 调整前的值，手数（若未知则为 None）
    - new_value: 调整后的值，手数
    - effective_date: 生效日期
    - source_url: 数据来源 URL
    - raw_note: 原始备注文本
    """

    exchange: str
    product_label: str
    contract_codes: tuple[str, ...] = dataclass_field(default_factory=tuple)
    field: str = "MinLimitOrderVolume"
    old_value: float | None = None
    new_value: float = 1.0
    effective_date: date | None = None
    effective_timestamp: datetime | None = None
    source_url: str = ""
    source_date: str = ""
    product_code: str = ""
    product_codes: tuple[str, ...] = dataclass_field(default_factory=tuple)
    product_code_match_status: str = ""
    instrument_type: str = "future"
    raw_note: str = ""

    @property
    def is_product_level(self) -> bool:
        """是否为品种级别调整（非特定合约）。"""
        return len(self.contract_codes) == 0

    @property
    def contract_range(self) -> str:
        """合约范围的人类可读描述。"""
        if not self.contract_codes:
            return "全部合约"
        return "/".join(self.contract_codes)


def parse_alter_events_from_note(
    note: str,
    *,
    exchange: str = "",
    product_label: str = "",
    source_url: str = "",
) -> list[AlterEvent]:
    """从备注文本中解析出 AlterEvent 列表。

    目前支持「最小开仓下单量调整为X手」模式。
    若备注不含可识别的调整记录则返回空列表。
    """
    events: list[AlterEvent] = []
    for m in _MIN_OPEN_PATTERN.finditer(note):
        try:
            y, mo, d = int(m["year"]), int(m["month"]), int(m["day"])
            eff_date = date(y, mo, d)
        except ValueError:
            continue
        new_qty = int(m["new_qty"])

        # 尝试提取合约代码
        codes_match = _CONTRACT_CODE_PATTERN.search(note)
        codes: tuple[str, ...] = ()
        if codes_match:
            raw_codes = codes_match["code"]
            codes = tuple(
                c.strip()
                for c in re.split(r"[-至及,、\s]+", raw_codes)
                if c.strip()
            )

        events.append(
            AlterEvent(
                exchange=exchange,
                product_label=product_label,
                contract_codes=codes,
                field="MinLimitOrderVolume",
                new_value=float(new_qty),
                effective_date=eff_date,
                source_url=source_url,
                raw_note=note.strip(),
            )
        )
    return events


# ---------------------------------------------------------------------------
# 已知历史调整事件注册表（从国信期货页面手工提取）
# ---------------------------------------------------------------------------
# 每项为 dict，字段对应 AlterEvent 构造参数。
# 页面标注日期：2026-05-19

KNOWN_ALTER_EVENTS: list[dict] = [
    # ---- 上海期货交易所 ----
    # （该页面上期所暂无最小开仓下单量调整记录）

    # ---- 大连商品交易所 ----
    {
        "exchange": Exchange.DCE,
        "product_label": "苯乙烯",
        "contract_codes": ("2605", "2606"),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "乙二醇",
        "contract_codes": ("2605", "2606"),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "液化石油气",
        "contract_codes": ("2605", "2606"),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "线型低密度聚乙烯",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "聚氯乙烯",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "聚丙烯",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.DCE,
        "product_label": "纯苯",
        "contract_codes": ("2605", "2606"),
        "field": "MinLimitOrderVolume",
        "new_value": 4.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为4手",
    },

    # ---- 郑州商品交易所 ----
    {
        "exchange": Exchange.CZCE,
        "product_label": "红枣",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "old_value": 2.0,
        "new_value": 1.0,
        "effective_date": date(2023, 7, 12),
        "source_url": SOURCE_URL,
        "raw_note": "2023年07月12日起，每次最小开仓下单量调整为1手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "动力煤",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "old_value": 50.0,
        "new_value": 4.0,
        "effective_date": date(2022, 3, 8),
        "source_url": SOURCE_URL,
        "raw_note": "2022年3月8日当晚夜盘交易起，每次最小开仓下单量调整为4手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "普麦",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 10.0,
        "effective_date": date(2022, 5, 1),
        "source_url": SOURCE_URL,
        "raw_note": "2022年5月起，每次最小开仓下单量调整为10手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "强麦",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 10.0,
        "effective_date": date(2022, 5, 1),
        "source_url": SOURCE_URL,
        "raw_note": "2022年5月起，每次最小开仓下单量调整为10手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "早籼稻",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 10.0,
        "effective_date": date(2022, 5, 1),
        "source_url": SOURCE_URL,
        "raw_note": "2022年5月起，每次最小开仓下单量调整为10手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "粳稻",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 10.0,
        "effective_date": date(2022, 5, 1),
        "source_url": SOURCE_URL,
        "raw_note": "2022年5月起，每次最小开仓下单量调整为10手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "晚籼稻",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 10.0,
        "effective_date": date(2022, 5, 1),
        "source_url": SOURCE_URL,
        "raw_note": "2022年5月起，每次最小开仓下单量调整为10手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "甲醇",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日当晚夜盘交易起，2606合约每次最小开仓下单量调整为8手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "甲醇",
        "contract_codes": ("2607", "2608", "2609"),
        "field": "MinLimitOrderVolume",
        "new_value": 4.0,
        "effective_date": date(2026, 4, 27),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年4月27日当晚夜盘交易时起，2607、2608及2609合约的交易指令每次最小开仓下单量调整为4手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "对二甲苯",
        "contract_codes": ("2607", "2608", "2609"),
        "field": "MinLimitOrderVolume",
        "new_value": 2.0,
        "effective_date": date(2026, 4, 27),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年4月27日当晚夜盘交易时起，2607、2608及2609合约的交易指令每次最小开仓下单量调整为2手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "对二甲苯",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "PTA",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "短纤",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 8.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "瓶片",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 4.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为4手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "烧碱",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 4.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为4手",
    },
    {
        "exchange": Exchange.CZCE,
        "product_label": "丙烯",
        "contract_codes": ("2606",),
        "field": "MinLimitOrderVolume",
        "new_value": 4.0,
        "effective_date": date(2026, 3, 9),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年3月9日夜盘起，每次最小开仓下单数量调整为4手",
    },

    # ---- 广州期货交易所 ----
    {
        "exchange": Exchange.GFEX,
        "product_label": "碳酸锂",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 5.0,
        "effective_date": date(2025, 12, 26),
        "source_url": SOURCE_URL,
        "raw_note": "自2025年月12月26日交易起，每次最小开仓下单量调整为5手",
    },
    {
        "exchange": Exchange.GFEX,
        "product_label": "多晶硅",
        "contract_codes": (),
        "field": "MinLimitOrderVolume",
        "new_value": 5.0,
        "effective_date": date(2026, 4, 3),
        "source_url": SOURCE_URL,
        "raw_note": "自2026年4月3日交易起，每次最小开仓下单量调整为5手",
    },

    # ---- 中国金融期货交易所 ----
    # （暂无最小开仓下单量调整记录）
]


def iter_known_events() -> list[AlterEvent]:
    """返回 KNOWN_ALTER_EVENTS 中所有的 AlterEvent 实例。"""
    return [AlterEvent(**item) for item in KNOWN_ALTER_EVENTS]
