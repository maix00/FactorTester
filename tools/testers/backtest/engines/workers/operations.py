"""Registered operations exposed by isolated framework workers.

The bridge boundary is JSON, so Python callables are represented as registered
operation/policy names plus plain parameters.  This keeps framework workers
portable across subprocesses while still allowing new event-driven strategy
types to opt in without being hard-wired to "group backtest".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


HEALTH = "health"
RUN_TARGET_WEIGHTS = "run_target_weights"
RUN_STRATEGY_INTENTS = "run_strategy_intents"
RUN_GROUP_STRATEGY = "run_group_strategy"


@dataclass(frozen=True, slots=True)
class WorkerOperation:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "aliases": list(self.aliases),
        }


_OPERATIONS: dict[str, WorkerOperation] = {
    HEALTH: WorkerOperation(
        HEALTH,
        "健康检查",
        "返回框架版本、进程隔离和可执行 operation 清单。",
    ),
    RUN_TARGET_WEIGHTS: WorkerOperation(
        RUN_TARGET_WEIGHTS,
        "目标权重回放",
        "回放已经给定的 target-weight 时间序列，用于通用组合回测一致性测试。",
    ),
    RUN_STRATEGY_INTENTS: WorkerOperation(
        RUN_STRATEGY_INTENTS,
        "策略意图回放",
        "按已注册 strategy_kind/policy id 解释信号，生成交易意图并回放订单；分组、Long-Short 和后续技术规则都走这个入口。",
        aliases=(RUN_GROUP_STRATEGY,),
    ),
}

_ALIASES: dict[str, str] = {
    alias: operation.key
    for operation in _OPERATIONS.values()
    for alias in operation.aliases
}


def canonical_operation(operation: str) -> str:
    key = str(operation)
    return _ALIASES.get(key, key)


def operation_manifest() -> dict[str, dict[str, object]]:
    return {key: operation.to_dict() for key, operation in _OPERATIONS.items()}


def operation_keys_for_health() -> list[str]:
    return list(_OPERATIONS) + sorted(_ALIASES)


RunnerFactory = Callable[[], Callable]


def runner_name_for_operation(operation: str) -> str:
    key = canonical_operation(operation)
    if key == RUN_TARGET_WEIGHTS:
        return "run_target_weights"
    if key == RUN_STRATEGY_INTENTS:
        return "run_strategy_intents"
    raise ValueError(f"operation {operation!r} is not a runnable backtest operation")


def known_operations() -> Mapping[str, WorkerOperation]:
    return dict(_OPERATIONS)
