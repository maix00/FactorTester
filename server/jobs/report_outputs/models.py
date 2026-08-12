"""Small immutable value objects used by report builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GeneratedReport:
    name: str
    raw: bytes
    extension: str
    content_type: str
    receipt: dict[str, Any]
