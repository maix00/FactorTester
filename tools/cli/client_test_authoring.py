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
