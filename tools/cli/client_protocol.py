"""Remote protocol discovery client."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ProtocolClientMixin(ClientMixinBase):
    def protocol_manifest(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/protocol-manifest")
        )
