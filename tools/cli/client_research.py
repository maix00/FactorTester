"""Research catalog, profile, trial, and external-factor client methods."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .client_base import ClientMixinBase


class ResearchClientMixin(ClientMixinBase):
    @staticmethod
    def _research_url(research_id: str, suffix: str = "") -> str:
        target = quote(str(research_id or "").strip(), safe="")
        return f"/api/research/{target}{suffix}"

    def list_researches(
        self, *, include_archived: bool = False, scope: str = "all",
    ) -> dict[str, Any]:
        """List the durable Research objects visible to the current user."""
        query = {"scope": str(scope or "all").strip() or "all"}
        if include_archived:
            query["include_archived"] = "1"
        return self._expect_success(self.session.get(
            "/api/research",
            query=query,
        ))

    def create_research(
        self,
        *,
        title: str,
        description: str = "",
        visibility: str = "private",
        authorized_users: list[str] | None = None,
        profile_ref: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/research",
            {
                "title": title,
                "description": description,
                "visibility": visibility,
                "authorized_users": authorized_users or [],
                "profile_ref": profile_ref,
            },
        ))

    def get_research(self, research_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(self._research_url(research_id)))

    def update_research(
        self, research_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.patch(
            self._research_url(research_id), payload,
        ))

    def add_research_member(
        self, research_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            self._research_url(research_id, "/members"), payload,
        ))
        return dict(data.get("member") or {})

    def create_research_workspace(
        self, research_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            self._research_url(research_id, "/workspaces"), payload,
        ))
        return dict(data.get("workspace") or {})

    def register_research_report(
        self, research_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            self._research_url(research_id, "/reports"), payload,
        ))
        return dict(data.get("report") or {})

    def link_research_evidence(
        self, research_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            self._research_url(research_id, "/evidence"), payload,
        ))
        return dict(data.get("evidence_link") or {})

    def migrate_research_reports(
        self, records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/research/migrations/reports", {"records": records},
        ))

    def list_research_reports(
        self, *, scope: str = "all", include_archived: bool = False,
    ) -> dict[str, Any]:
        """Read Research > Reports from the canonical Research catalog."""
        selected = str(scope or "all").strip() or "all"
        if selected not in {"all", "mine", "shared", "subordinates"}:
            raise ValueError("research report scope is invalid")
        query = {"scope": selected}
        if include_archived:
            query["include_archived"] = "1"
        return self._expect_success(self.session.get(
            "/api/research/reports", query=query,
        ))

    def research_report_catalog(self, *, scope: str) -> dict[str, Any]:
        """Backward-compatible method name using the canonical API."""
        return self.list_research_reports(scope=scope)

    def profile_directory(
        self,
        *,
        scope: str = "mine",
        query: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Read the bounded Research > Profiles directory projection."""
        return self._expect_success(self.session.get(
            "/api/client/profile-directory",
            query={
                "scope": scope,
                "query": query,
                "page": page,
                "page_size": page_size,
            },
        ))

    def create_direct_trial_plan(
        self,
        *,
        trial_plan: dict[str, Any],
        run_spec_hash: str,
        trial_role: str,
        comparison_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/trial-plans/direct",
            {
                "trial_plan": trial_plan,
                "run_spec_hash": run_spec_hash,
                "trial_role": trial_role,
                "comparison_id": comparison_id,
            },
        ))
        return dict(data.get("trial_binding") or {})

    def get_direct_trial_plan(self, trial_plan_ref: str) -> dict[str, Any]:
        digest = str(trial_plan_ref).removeprefix("trial-plan:sha256:")
        data = self._expect_success(
            self.session.get(f"/api/trial-plans/direct/{digest}")
        )
        return dict(data.get("trial_plan") or {})

    def validate_external_factor_artifact(
        self,
        manifest_path: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/external-factor-artifacts/validate",
            {"manifest_path": manifest_path},
        ))
        return dict(data.get("artifact") or {})
