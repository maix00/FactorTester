"""Research catalog, profile, trial, and external-factor client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchClientMixin(ClientMixinBase):
    def research_report_catalog(self, *, scope: str) -> dict[str, Any]:
        """Read one Web-equivalent research-report visibility scope."""
        selected = str(scope or "mine").strip()
        if selected == "mine":
            return self._expect_success(
                self.session.get("/api/research-publications/settings")
            )
        if selected not in {"shared", "subordinates"}:
            raise ValueError("research report scope is invalid")
        return self._expect_success(self.session.get(
            "/api/public-research", query={"scope": selected},
        ))

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
