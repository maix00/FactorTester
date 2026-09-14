"""High-level FactorTester HTTP API client."""

from __future__ import annotations

from typing import Any

from .client_admin import AdminClientMixin
from .client_agent_flow import AgentFlowClientMixin
from .client_agent_profile import AgentProfileClientMixin
from .client_factor_library import FactorLibraryClientMixin
from .client_jobs import JobsClientMixin
from .client_navigation import NavigationClientMixin
from .client_order_audit import OrderAuditClientMixin
from .client_product_library import ProductLibraryClientMixin
from .client_strategy_library import StrategyLibraryClientMixin
from .client_protocol import ProtocolClientMixin
from .client_research import ResearchClientMixin
from .client_research_evidence import ResearchEvidenceClientMixin
from .client_research_graph import ResearchGraphClientMixin
from .client_research_step import ResearchStepClientMixin
from .client_runs import RunsClientMixin
from .client_test_authoring import TestAuthoringClientMixin
from .http import HttpSession


class FactorTesterClient(
    AdminClientMixin,
    ProtocolClientMixin,
    ResearchGraphClientMixin,
    ResearchEvidenceClientMixin,
    AgentFlowClientMixin,
    AgentProfileClientMixin,
    OrderAuditClientMixin,
    ResearchClientMixin,
    RunsClientMixin,
    JobsClientMixin,
    TestAuthoringClientMixin,
    NavigationClientMixin,
    ProductLibraryClientMixin,
    FactorLibraryClientMixin,
    StrategyLibraryClientMixin,
    ResearchStepClientMixin,
):
    """Stable public client composed from domain-specific HTTP adapters."""

    def __init__(self, session: HttpSession) -> None:
        self.session = session

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/auth/login",
            {"username": username, "password": password},
        ))

    def current_principal(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/api/session"))

    def sync_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Synchronize a source-free local Profile projection to its Manager."""
        return self._expect_success(self.session.post(
            "/api/client/profiles/sync",
            {"profile": profile},
        ))

    def logout(self) -> dict[str, Any]:
        try:
            return self._expect_success(self.session.post("/auth/logout", {}))
        finally:
            self.session.clear_cookies()

    def _expect_success(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("success") is False:
            raise RuntimeError(str(data.get("error") or data))
        return data
