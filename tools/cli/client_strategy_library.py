"""HTTP client methods for the persistent Strategy library."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from .client_base import ClientMixinBase


def _ref(value: str) -> str:
    return quote(str(value or "").strip(), safe="")


class StrategyLibraryClientMixin(ClientMixinBase):
    def list_strategy_library(
        self, *, scope: str = "mine", page: int = 1, limit: int = 20,
        query: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/strategy-library/strategies",
            query={"scope": scope, "page": page, "limit": limit, "query": query},
        ))

    def get_strategy(self, strategy_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}"
        ))

    def create_strategy(
        self, *, name: str, source_code: str, entrypoint: str = "Strategy",
        description: str = "", visibility: str = "private",
        requirements: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/strategy-library/strategies",
            {
                "name": name,
                "description": description,
                "visibility": visibility,
                "entrypoint": entrypoint,
                "source_code": source_code,
                "requirements": requirements or {},
            },
        ))

    def create_strategy_from_file(
        self, *, name: str, source_file: str | Path,
        entrypoint: str = "Strategy", description: str = "",
        visibility: str = "private",
    ) -> dict[str, Any]:
        source = Path(source_file).read_text(encoding="utf-8")
        return self.create_strategy(
            name=name, source_code=source, entrypoint=entrypoint,
            description=description, visibility=visibility,
        )

    def update_strategy(
        self, strategy_ref: str, values: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.patch(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}", values,
        ))

    def delete_strategy(self, strategy_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.delete(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}"
        ))

    def list_strategy_revisions(self, strategy_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}/revisions"
        ))

    def get_strategy_revision(
        self, strategy_ref: str, revision_ref: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}/revisions/{_ref(revision_ref)}"
        ))

    def list_strategy_shares(self, strategy_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}/shares"
        ))

    def grant_strategy_share(self, strategy_ref: str, principal_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}/shares",
            {"principal_ref": principal_ref},
        ))

    def revoke_strategy_share(self, strategy_ref: str, principal_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.delete(
            f"/api/strategy-library/strategies/{_ref(strategy_ref)}/shares/{_ref(principal_ref)}"
        ))
