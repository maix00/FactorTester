from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderStore:
    pending_orders: dict[Any, Any] = field(default_factory=dict)
