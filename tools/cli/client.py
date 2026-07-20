"""High-level FactorTester HTTP API client."""

from __future__ import annotations

from typing import Any

from .client_agent_flow import AgentFlowClientMixin
from .client_factor_library import FactorLibraryClientMixin
from .client_protocol import ProtocolClientMixin
from .client_research import ResearchClientMixin
from .client_research_graph import ResearchGraphClientMixin
from .http import HttpSession


class FactorTesterClient(
    ProtocolClientMixin,
    ResearchGraphClientMixin,
    AgentFlowClientMixin,
    ResearchClientMixin,
    FactorLibraryClientMixin,
):
    """Stable public client composed from domain-specific HTTP adapters."""

    def __init__(self, session: HttpSession) -> None:
        self.session = session

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/login",
            {"username": username, "password": password},
        ))

    def set_keep_login(self, enabled: bool) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/api/keep_login", {
                "keep_login": bool(enabled),
            })
        )

    def logout(self) -> dict[str, Any]:
        try:
            return self._expect_success(self.session.post("/logout", {}))
        finally:
            self.session.clear_cookies()

    def _expect_success(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("success") is False:
            raise RuntimeError(str(data.get("error") or data))
        return data
