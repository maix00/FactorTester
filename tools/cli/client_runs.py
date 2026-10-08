"""Run and immutable RunSpec HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class RunsClientMixin(ClientMixinBase):
    def submit_run(
        self,
        workspace_id: str,
        configuration_revision: int | None,
        *,
        analyses: list[str],
        retention_mode: str = "summary",
        step_mode: bool = False,
        performance_profile: dict[str, Any] | None = None,
        margin_execution_profile: dict[str, Any] | None = None,
        output_requests: list[str] | None = None,
        sample_use: dict[str, Any] | None = None,
        report_binding: dict[str, Any] | None = None,
        transient_factor_sources: list[dict[str, Any]] | None = None,
        strategy_specs: list[dict[str, Any]] | None = None,
        transient_strategy_sources: list[dict[str, Any]] | None = None,
        run_input_dependencies: list[dict[str, Any]] | None = None,
        factor_subject_descriptors: list[dict[str, Any]] | None = None,
        configuration_snapshot_id: str = "",
        configuration_snapshot_revision: int | None = None,
    ) -> dict[str, Any]:
        payload = self._run_request_payload(
            workspace_id,
            configuration_revision,
            analyses=analyses,
            retention_mode=retention_mode,
            step_mode=step_mode,
            performance_profile=performance_profile,
            margin_execution_profile=margin_execution_profile,
            output_requests=output_requests,
            transient_factor_sources=transient_factor_sources,
            strategy_specs=strategy_specs,
            transient_strategy_sources=transient_strategy_sources,
            run_input_dependencies=run_input_dependencies,
            factor_subject_descriptors=factor_subject_descriptors,
            configuration_snapshot_id=configuration_snapshot_id,
            configuration_snapshot_revision=configuration_snapshot_revision,
        )
        if sample_use is not None:
            payload["sample_use"] = sample_use
        if report_binding is not None:
            payload["report_binding"] = report_binding
        return self._expect_success(self.session.post("/api/runs", payload))

    @staticmethod
    def _run_request_payload(
        workspace_id: str,
        configuration_revision: int | None,
        *,
        analyses: list[str],
        retention_mode: str,
        step_mode: bool,
        performance_profile: dict[str, Any] | None,
        margin_execution_profile: dict[str, Any] | None,
        output_requests: list[str] | None,
        transient_factor_sources: list[dict[str, Any]] | None,
        strategy_specs: list[dict[str, Any]] | None,
        transient_strategy_sources: list[dict[str, Any]] | None,
        run_input_dependencies: list[dict[str, Any]] | None,
        factor_subject_descriptors: list[dict[str, Any]] | None,
        configuration_snapshot_id: str,
        configuration_snapshot_revision: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "analyses": analyses,
            "retention_mode": retention_mode,
            "step_mode": bool(step_mode),
        }
        if output_requests:
            payload["output_requests"] = list(output_requests)
        if performance_profile is not None:
            payload["performance_profile"] = dict(performance_profile)
        if margin_execution_profile is not None:
            payload["margin_execution_profile"] = dict(margin_execution_profile)
        if configuration_snapshot_id:
            payload["configuration_snapshot_id"] = configuration_snapshot_id
            payload["configuration_snapshot_revision"] = (
                configuration_snapshot_revision
            )
        else:
            payload["configuration_revision"] = configuration_revision
        if transient_factor_sources:
            payload["transient_factor_sources"] = list(transient_factor_sources)
        if strategy_specs:
            payload["strategy_specs"] = list(strategy_specs)
        if transient_strategy_sources:
            payload["transient_strategy_sources"] = list(transient_strategy_sources)
        if run_input_dependencies:
            payload["run_input_dependencies"] = list(run_input_dependencies)
        if factor_subject_descriptors:
            payload["factor_subject_descriptors"] = list(
                factor_subject_descriptors
            )
        return payload

    def preview_run(
        self,
        workspace_id: str,
        configuration_revision: int | None,
        *,
        analyses: list[str],
        retention_mode: str = "summary",
        step_mode: bool = False,
        performance_profile: dict[str, Any] | None = None,
        margin_execution_profile: dict[str, Any] | None = None,
        output_requests: list[str] | None = None,
        transient_factor_sources: list[dict[str, Any]] | None = None,
        strategy_specs: list[dict[str, Any]] | None = None,
        transient_strategy_sources: list[dict[str, Any]] | None = None,
        run_input_dependencies: list[dict[str, Any]] | None = None,
        factor_subject_descriptors: list[dict[str, Any]] | None = None,
        configuration_snapshot_id: str = "",
        configuration_snapshot_revision: int | None = None,
    ) -> dict[str, Any]:
        """Derive the exact frozen RunSpec identity without creating a run."""
        payload = self._run_request_payload(
            workspace_id,
            configuration_revision,
            analyses=analyses,
            retention_mode=retention_mode,
            step_mode=step_mode,
            performance_profile=performance_profile,
            margin_execution_profile=margin_execution_profile,
            output_requests=output_requests,
            transient_factor_sources=transient_factor_sources,
            strategy_specs=strategy_specs,
            transient_strategy_sources=transient_strategy_sources,
            run_input_dependencies=run_input_dependencies,
            factor_subject_descriptors=factor_subject_descriptors,
            configuration_snapshot_id=configuration_snapshot_id,
            configuration_snapshot_revision=configuration_snapshot_revision,
        )
        return self._expect_success(
            self.session.post("/api/runs/preview", payload)
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/runs/{run_id}"))
        return dict(data.get("run") or {})

    def get_run_spec(self, run_spec_hash: str) -> dict[str, Any]:
        digest = str(run_spec_hash).removeprefix("sha256:")
        data = self._expect_success(
            self.session.get(f"/api/run-specs/{digest}")
        )
        return dict(data.get("run_spec") or {})

    def clone_run_workspace(
        self,
        run_id: str,
        *,
        title: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/runs/{run_id}/clone-workspace",
            {"title": title},
        ))
        return dict(data.get("workspace") or {})
