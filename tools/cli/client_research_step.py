"""Research Step HTTP methods for :class:`FactorTesterClient`."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchStepClientMixin(ClientMixinBase):
    def inspect_research_step(
        self, instance_id: str, branch_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/research-step"
        ))
        return dict(data.get("research_step") or {})

    def prepare_research_step(
        self,
        instance_id: str,
        branch_id: str,
        *,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/research-step/prepare",
            {"request": request},
        ))
        return dict(data.get("contract") or {})
