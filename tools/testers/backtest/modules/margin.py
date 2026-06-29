"""Margin module — fields folded into TradingRuleModule in step 5 (see plan).
Skeleton only; old on_<phase>/setting_definitions body removed in the
issue-114 rewrite."""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule


class MarginModule(ExecutableModule):
    key: ClassVar[str] = "margin"
    label: ClassVar[str] = "保证金"
