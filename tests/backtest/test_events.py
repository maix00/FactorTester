"""EventQueue + BacktestEvent 测试 — 排序、push/pop/peek"""

from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest.event_queue import EventQueue
from tools.backtest.events import BacktestEvent, EventCategory


# ============================================================
# BacktestEvent 排序测试
# ============================================================

def test_backtest_event_sort_order_by_timestamp():
    """同 category/priority/seq 时按 timestamp 排序"""
    e1 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-02"),
        category=EventCategory.MARKET_DATA,
    )
    e2 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
    )
    # e2 时间更早，应排在前面
    assert e2 < e1


def test_backtest_event_sort_order_by_category():
    """同 timestamp 时按 category 排序"""
    e1 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.PNL,          # 90
    )
    e2 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,  # 10
    )
    assert e2 < e1  # MARKET_DATA=10 < PNL=90


def test_backtest_event_sort_order_by_priority():
    """同 timestamp + category 时按 priority 排序"""
    e1 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
        priority=5,
    )
    e2 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
        priority=1,
    )
    assert e2 < e1  # priority=1 < priority=5


def test_backtest_event_sort_order_by_seq():
    """同 timestamp + category + priority 时按 seq 排序"""
    e1 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
        seq=2,
    )
    e2 = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
        seq=1,
    )
    assert e2 < e1  # seq=1 < seq=2


# ============================================================
# EventCategory IntEnum 测试
# ============================================================

def test_event_category_values():
    """验证 10 类事件的值范围"""
    assert EventCategory.MARKET_DATA == 10
    assert EventCategory.FACTOR == 20
    assert EventCategory.SIGNAL == 30
    assert EventCategory.ORDER == 40
    assert EventCategory.FEE == 50
    assert EventCategory.MARGIN == 60
    assert EventCategory.LIQUIDITY == 70
    assert EventCategory.FILL == 80
    assert EventCategory.PNL == 90
    assert EventCategory.REPORT == 100


def test_event_category_order():
    """验证类别按数值从小到大排列"""
    cats = list(EventCategory)
    assert cats == sorted(cats)


# ============================================================
# EventQueue 测试
# ============================================================

def test_event_queue_push_pop_order():
    """push 无序事件，pop 按排序键正确出队"""
    q = EventQueue()
    ts = pd.Timestamp("2024-01-01")

    # 逆序 push
    q.push(BacktestEvent(ts, EventCategory.REPORT, seq=1))
    q.push(BacktestEvent(ts, EventCategory.PNL, seq=2))
    q.push(BacktestEvent(ts, EventCategory.MARKET_DATA, seq=3))

    # pop 应返回 category 最小的
    e1 = q.pop()
    assert e1.category == EventCategory.MARKET_DATA
    e2 = q.pop()
    assert e2.category == EventCategory.PNL
    e3 = q.pop()
    assert e3.category == EventCategory.REPORT


def test_event_queue_empty_pop_raises():
    """空队列 pop 抛 IndexError"""
    q = EventQueue()
    with pytest.raises(IndexError, match="empty EventQueue"):
        q.pop()


def test_event_queue_peek():
    """peek 返回最小元素但不移除"""
    q = EventQueue()
    ts = pd.Timestamp("2024-01-01")
    q.push(BacktestEvent(ts, EventCategory.PNL, seq=1))
    q.push(BacktestEvent(ts, EventCategory.MARKET_DATA, seq=2))

    top = q.peek()
    assert top is not None
    assert top.category == EventCategory.MARKET_DATA
    assert len(q) == 2  # peeking doesn't remove


def test_event_queue_peek_empty():
    """空队列 peek 返回 None"""
    q = EventQueue()
    assert q.peek() is None


def test_event_queue_len():
    q = EventQueue()
    ts = pd.Timestamp("2024-01-01")
    assert len(q) == 0
    q.push(BacktestEvent(ts, EventCategory.MARKET_DATA))
    assert len(q) == 1
    q.push(BacktestEvent(ts, EventCategory.PNL))
    assert len(q) == 2
    q.pop()
    assert len(q) == 1


def test_event_queue_bool():
    q = EventQueue()
    assert not bool(q)
    q.push(BacktestEvent(pd.Timestamp("2024-01-01"), EventCategory.MARKET_DATA))
    assert bool(q)


def test_event_queue_multi_timestamp():
    """多时间戳事件正确按时间排序"""
    q = EventQueue()
    t1 = pd.Timestamp("2024-01-01")
    t2 = pd.Timestamp("2024-01-02")
    t3 = pd.Timestamp("2024-01-03")

    # 乱序 push
    q.push(BacktestEvent(t2, EventCategory.MARKET_DATA))
    q.push(BacktestEvent(t1, EventCategory.MARKET_DATA))
    q.push(BacktestEvent(t3, EventCategory.MARKET_DATA))

    assert q.pop().timestamp == t1
    assert q.pop().timestamp == t2
    assert q.pop().timestamp == t3


def test_event_payload_not_in_sort():
    """payload 不参与排序"""
    e = BacktestEvent(
        timestamp=pd.Timestamp("2024-01-01"),
        category=EventCategory.MARKET_DATA,
        payload={"key": "value", "t_idx": 5},
    )
    assert e.payload["t_idx"] == 5
    assert e.payload["key"] == "value"
