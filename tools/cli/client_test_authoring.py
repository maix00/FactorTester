"""Test-module authoring schema HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class TestAuthoringClientMixin(ClientMixinBase):
    def manifest(self, application: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/test-authoring/modules/{application}"
        ))

    def tab_manifest(
        self, application: str, tab_key: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/test-authoring/modules/{application}/tabs/{tab_key}"
        ))

    def create_workspace(
        self,
        *,
        factor_families: list[dict[str, Any]] | None = None,
        factors: list[dict[str, Any]] | None = None,
        title: str = "Factor test",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/test-authoring/workspaces",
            {
                "title": title,
                "factor_families": factor_families or [],
                "factors": factors or [],
            },
        ))
        return dict(data.get("workspace") or {})

    def list_workspaces(self) -> list[dict[str, Any]]:
        data = self._expect_success(
            self.session.get("/api/test-authoring/workspaces")
        )
        return list(data.get("workspaces") or [])

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/test-authoring/workspaces/{workspace_id}"
        ))
        return dict(data.get("workspace") or {})

    def get_workspace_configuration(self, workspace_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration"
        ))
        return dict(data.get("configuration") or {})

    def create_configuration_snapshot(
        self,
        workspace_id: str,
        *,
        source_workspace_id: str,
        source_configuration_id: str,
        source_configuration_revision: int,
        name: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration-snapshots",
            {
                "source_workspace_id": source_workspace_id,
                "source_configuration_id": source_configuration_id,
                "source_configuration_revision": source_configuration_revision,
                "name": name,
            },
        ))
        return dict(data.get("snapshot") or {})

    def list_configuration_snapshots(
        self, workspace_id: str,
    ) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration-snapshots"
        ))
        return list(data.get("snapshots") or [])

    def save_configuration_template(
        self, workspace_id: str, *, name: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/templates",
            {"name": name},
        ))
        return dict(data.get("template") or {})

    def update_workspace_configuration(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.put(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration",
            {"expected_revision": expected_revision, "payload": payload},
        ))
        return dict(data.get("configuration") or {})

    def list_configuration_strategies(
        self, workspace_id: str, *, include_source: bool = False,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/strategies",
            query={"include_source": "1"} if include_source else {},
        ))

    def add_inline_strategy(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        name: str,
        source_code: str,
        target_strategy_id: str,
        entrypoint: str = "Strategy",
        requirements: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/strategies",
            {
                "expected_revision": expected_revision,
                "kind": "inline",
                "name": name,
                "source_code": source_code,
                "entrypoint": entrypoint,
                "target_strategy_id": target_strategy_id,
                "requirements": requirements or {},
            },
        ))

    def bind_library_strategy(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        strategy_ref: str,
        revision_ref: str,
        target_strategy_id: str,
        source_sha256: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/strategies",
            {
                "expected_revision": expected_revision,
                "kind": "library",
                "strategy_ref": strategy_ref,
                "revision_ref": revision_ref,
                "source_sha256": source_sha256,
                "target_strategy_id": target_strategy_id,
            },
        ))

    def update_inline_strategy(
        self, workspace_id: str, binding_id: str, *, expected_revision: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.patch(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/strategies/{binding_id}",
            {"expected_revision": expected_revision, **values},
        ))

    def remove_configuration_strategy(
        self, workspace_id: str, binding_id: str, *, expected_revision: int,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.delete(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/strategies/{binding_id}",
            query={"expected_revision": expected_revision},
        ))

    def load_configuration_template(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        configuration_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/test-authoring/workspaces/{workspace_id}/configuration/load-template",
            {
                "expected_revision": expected_revision,
                "configuration_id": configuration_id,
            },
        ))
        return dict(data.get("configuration") or {})

    def list_configuration_templates(self) -> list[dict[str, Any]]:
        data = self._expect_success(
            self.session.get("/api/test-authoring/configuration-templates")
        )
        return list(data.get("templates") or [])
