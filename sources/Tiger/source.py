"""Registration boundary for Tiger products, capabilities, and probes."""

from __future__ import annotations

from tools.data.availability.registry import register_availability_connector

from .data_source import TIGER, TIGER_OSE_L2
from .connector import TigerConnector


register_availability_connector("Tiger", TigerConnector)

__all__ = ["TIGER", "TIGER_OSE_L2"]
