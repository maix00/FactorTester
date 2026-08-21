"""Generic supplemental JobAttempt interface."""

from .registry import SupplementalAdapter, adapter, register
from .requests import SupplementalRequest, request_supplemental

__all__ = [
    "SupplementalAdapter", "SupplementalRequest", "adapter", "register",
    "request_supplemental",
]
