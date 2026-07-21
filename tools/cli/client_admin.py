"""Administrative server projections shared by CLI and native transports."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class AdminClientMixin(ClientMixinBase):
    def list_server_instances(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/admin/api/server-instances")
        )

    def run_server_instance_action(
        self,
        instance_id: str,
        action: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/admin/api/server-instances/{instance_id}/actions",
            {"action": action},
        ))

    def list_global_jobs(
        self,
        *,
        limit: int = 20,
        cursor: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/admin/api/jobs",
            query={"limit": limit, "cursor": cursor or None},
        ))
