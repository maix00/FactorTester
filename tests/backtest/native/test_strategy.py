from __future__ import annotations

import re

from tools.testers.backtest.engines.native.strategy import Strategy


def test_strategy_name_has_alias_uuid_suffix():
    s = Strategy(alias="GroupA1")
    assert re.fullmatch(r"GroupA1:[0-9a-f]{32}", s.name)


def test_strategy_same_name_returns_same_instance():
    s1 = Strategy(alias="GroupA1")
    s2 = Strategy(name=s1.name)
    assert s1 is s2


def test_strategy_different_alias_not_equal():
    s1 = Strategy(alias="GroupA1")
    s2 = Strategy(alias="GroupA2")
    assert s1 != s2
    assert hash(s1) != hash(s2)
