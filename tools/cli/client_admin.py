"""Administrative server projections shared by CLI and native transports."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class AdminClientMixin(ClientMixinBase):
    def list_server_instances(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/admin/server-instances")
        )

    def run_server_instance_action(
        self,
        instance_id: str,
        action: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/api/admin/server-instances/{instance_id}/actions",
            {"action": action},
        ))

    def list_global_jobs(
        self,
        *,
        limit: int = 20,
        cursor: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/admin/jobs",
            query={"limit": limit, "cursor": cursor or None},
        ))
