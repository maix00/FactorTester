"""Registration boundary for Tiger products, cache providers, and probes."""

from __future__ import annotations

from tools.data.availability.registry import register_availability_connector

from .connector import TigerConnector
from .data_source import TIGER, TIGER_OSE_DAY1, TIGER_OSE_MIN1


register_availability_connector("Tiger", TigerConnector)

__all__ = ["TIGER", "TIGER_OSE_DAY1", "TIGER_OSE_MIN1"]
