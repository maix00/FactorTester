"""事件类型定义 — BacktestEvent, EventCategory

DES (离散事件仿真)：所有事件登记到 FEL (Future Event List)，按
(timestamp, category, priority, seq) 四元组排序。
"""

from dataclasses import dataclass, field
from enum import IntEnum

import pandas as pd


class EventCategory(IntEnum):
    """事件类别 — 值越小越先执行。

    同一时间戳下，引擎按 category 从小到大处理所有事件。
    用户可覆盖默认顺序。
    """
    MARKET_DATA   = 10   # 行情数据到达（向量化预计算结果的逐期切片）
    FACTOR        = 20   # 路径依赖因子求值
    SIGNAL        = 30   # 信号生成（membership → 买卖意图）
    ORDER         = 40   # 订单拆解（trade_intent → 手数/方向）
    FEE           = 50   # 费用核算
    MARGIN        = 60   # 保证金占用
    LIQUIDITY     = 70   # 流动性约束
    FILL          = 80   # 成交确认
    PNL           = 90   # 盯市盈亏
    REPORT        = 100  # 报告/日志


@dataclass(order=True)
class BacktestEvent:
    """FEL 中的单个事件。

    排序键（order=True 按字段顺序）：
    (timestamp, category, priority, seq)

    其中 seq 是全局递增的序列号，保证同优先级 FIFO。
    """
    timestamp: pd.Timestamp
    category: EventCategory
    priority: int = 0
    seq: int = 0

    # --- 以下字段不参与排序 ---
    event_type: str = field(default="", compare=False)
    payload: dict = field(default_factory=dict, compare=False)
