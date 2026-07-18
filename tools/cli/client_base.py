"""Typed contract shared by FactorTester HTTP client mixins."""

from __future__ import annotations

from typing import Any

from .http import HttpSession


class ClientMixinBase:
    """Declare the transport surface supplied by ``FactorTesterClient``."""

    session: HttpSession

    def _expect_success(self, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
