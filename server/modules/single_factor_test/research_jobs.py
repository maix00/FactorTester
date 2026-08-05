"""HTTP interface for research contexts, configurations, templates, and runs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
import uuid

from flask import jsonify, request
import settings as Settings

from server.modules.single_factor_test import sft_bp
from server.services import (
    external_factor_artifacts,
    factor_revisions,
    factor_subject_descriptors,
    research_configurations,
    research_configuration_snapshots,
    research_runs,
    research_workspaces,
)
from server.jobs.ipc import DaemonUnavailable, JobDaemonClient
from server.jobs.artifacts import default_user_quota_bytes
from server.jobs.report_outputs import (
    default_output_requests,
    output_capabilities,
    output_requests_for_analysis,
    validate_output_requests,
)
from server.jobs.entitlements import entitlement_for_owner
from server.jobs.models import JobRecord
from server.jobs.ports import detect_port
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.session_runtime import require_user
from server.services.factor_registry import transient_factor_source_scope
from server.services.transient_factor_sources import (
    cleanup_scope,
    create_scope,
    validate_entries,
)
from server.services.transient_strategy_sources import (
    cleanup_scope as cleanup_strategy_scope,
    create_scope as create_strategy_scope,
    validate_entries as validate_strategy_entries,
)
from server.services.strategy_plans import normalize_strategy_plan
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from server.services.research_report_presentations import (
    run_spec_presentation,
)
from tools.testers.backtest.engines.native.performance_profile import (
    normalize_performance_profile,
)
from tools.testers.backtest.modules.margin_budget_impl.observability import (
    normalize_margin_execution_profile,
)


SUPPORTED_ANALYSES = {"backtest", "ic", "factor_evaluation", "factor_type_analysis"}


class _RunRequestError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


def _prepare_research_run_request(data: dict, *, owner: str) -> dict:
    workspace_id = str(data.get("workspace_id") or "").strip()
    analyses = data.get("analyses")
    if not isinstance(analyses, list) or not analyses:
        raise _RunRequestError("analyses must be a non-empty list")
    analyses = [str(item).strip() for item in analyses]
    unsupported = sorted(set(analyses) - SUPPORTED_ANALYSES)
    if unsupported:
        raise _RunRequestError(f"unsupported analyses: {unsupported}")
    retention_mode = str(data.get("retention_mode") or "summary").strip()
    if retention_mode not in {"summary", "full"}:
        raise _RunRequestError("unsupported retention_mode")
    step_mode = bool(data.get("step_mode"))
    try:
        performance_profile = normalize_performance_profile(
            data.get("performance_profile")
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    try:
        margin_execution_profile = normalize_margin_execution_profile(
            data.get("margin_execution_profile")
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    try:
        factor_subjects = (
            factor_subject_descriptors.validate_factor_subject_descriptors(
                data.get("factor_subject_descriptors")
            )
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    try:
        output_requests = validate_output_requests(
            data.get("output_requests"), analyses,
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    if not output_requests:
        output_requests = default_output_requests(analyses)
    if step_mode and analyses != ["backtest"]:
        raise _RunRequestError(
            "step mode requires exactly one backtest analysis"
        )
    try:
        transient_sources = validate_entries(data.get("transient_factor_sources"))
    except ValueError as exc:
        raise _RunRequestError(str(exc), details={"code": "invalid_transient_factor_sources"}) from exc
    try:
        transient_strategy_sources = validate_strategy_entries(
            data.get("transient_strategy_sources")
        )
    except ValueError as exc:
        raise _RunRequestError(
            str(exc), details={"code": "invalid_transient_strategy_sources"}
        ) from exc
    strategy_specs = data.get("strategy_specs") or []
    uploaded_strategy_paths = {
        str(item.get("path") or "") for item in transient_strategy_sources
    }
    try:
        strategy_plan = normalize_strategy_plan(
            strategy_specs, uploaded_paths=uploaded_strategy_paths,
        )
    except ValueError as exc:
        code = (
            "strategy_source_unavailable"
            if "source is not uploaded" in str(exc)
            else "invalid_strategy_plan"
        )
        raise _RunRequestError(str(exc), details={"code": code}) from exc
    if transient_strategy_sources and not strategy_plan:
        raise _RunRequestError(
            "transient strategy sources require a matching strategy_specs entry",
            details={"code": "orphan_transient_strategy_sources"},
        )
    source_overrides = {
        str(item["factor_id"]): str(item["source_code"])
        for item in transient_sources
    }
    snapshot_id = str(data.get("configuration_snapshot_id") or "").strip()
    snapshot_revision = data.get("configuration_snapshot_revision")
    if snapshot_id:
        try:
            configuration = research_configuration_snapshots.load_snapshot(
                owner=owner,
                workspace_id=workspace_id,
                snapshot_id=snapshot_id,
                expected_revision=int(snapshot_revision),
            )
        except TypeError as exc:
            raise _RunRequestError(
                "configuration_snapshot_revision is required"
            ) from exc
        except KeyError as exc:
            raise _RunRequestError(str(exc), status_code=404) from exc
        except ValueError as exc:
            raise _RunRequestError(str(exc), status_code=409) from exc
        configuration = {
            "configuration_id": configuration["snapshot_id"],
            "revision": configuration["snapshot_revision"],
            "payload": configuration["payload"],
            "fingerprint": configuration["fingerprint"],
            "snapshot": configuration,
        }
    else:
        if snapshot_revision is not None:
            raise _RunRequestError(
                "configuration_snapshot_id is required"
            )
        try:
            configuration_revision = int(
                data.get("configuration_revision")
            )
        except (TypeError, ValueError) as exc:
            raise _RunRequestError(
                "configuration_revision is required"
            ) from exc
        configuration = research_configurations.load_workspace_configuration(
            workspace_id=workspace_id,
            owner=owner,
        )
        if configuration is None:
            raise _RunRequestError(
                "workspace configuration not found",
                status_code=404,
            )
        if configuration["revision"] != configuration_revision:
            raise _RunRequestError(
                "configuration revision changed",
                status_code=409,
                details={"current_revision": configuration["revision"]},
            )
    missing = [
        kind for kind in analyses
        if not isinstance(
            configuration["payload"]["analyses"].get(kind),
            dict,
        )
    ]
    if missing:
        raise _RunRequestError(
            f"configuration missing analyses: {missing}"
        )
    try:
        with transient_factor_source_scope(
            owner=owner,
            overrides=source_overrides,
        ):
            frozen_configuration = _freeze_product_selections(
                configuration,
                owner=owner,
                analyses=analyses,
            )
            frozen_configuration = _freeze_external_factor_artifacts(
                frozen_configuration
            )
            frozen_configuration = factor_revisions.freeze_factor_revisions(
                frozen_configuration,
                owner=owner,
            )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    except ImportError as exc:
        raise _RunRequestError(
            "因子源码不在服务器 canonical 因子库；请在本次 Run 中显式上传 Profile 源码，"
            "或先执行持久化授权同步",
            details={"code": "factor_source_unavailable", "detail": str(exc)},
        ) from exc
    run_spec = {
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "workspace_id": workspace_id,
        "configuration_id": configuration["configuration_id"],
        "configuration_revision": configuration["revision"],
        "configuration_fingerprint": configuration["fingerprint"],
        "analyses": analyses,
        "retention_mode": retention_mode,
        "step_mode": step_mode,
        "output_requests": output_requests,
        "configuration": deepcopy(frozen_configuration["payload"]),
    }
    if factor_subjects:
        empty_alias_hash = hashlib.sha256(b"").hexdigest()
        alias_hashes = {
            str(item.get("factor_alias_hash") or "")
            for item in (
                run_spec["configuration"]["shared"].get(
                    "factor_revision_manifests"
                ) or []
            )
            if isinstance(item, dict)
        }
        alias_hashes.discard("")
        alias_hashes.discard(empty_alias_hash)
        try:
            factor_subject_descriptors.assert_factor_sets_match_run(
                factor_subjects,
                factor_alias_hashes=alias_hashes,
            )
        except ValueError as exc:
            raise _RunRequestError(str(exc)) from exc
        run_spec["factor_subject_descriptors"] = (
            factor_subject_descriptors.compact_factor_subject_descriptors(
                factor_subjects
            )
        )
        factor_refs = factor_subject_descriptors.factor_refs_by_alias(
            factor_subjects
        )
        run_shared_factors = (
            run_spec.get("configuration", {}).get("shared", {}).get("factors")
        )
        execution_shared_factors = (
            frozen_configuration.get("payload", {})
            .get("shared", {})
            .get("factors")
        )
        if not isinstance(run_shared_factors, list) or not isinstance(
            execution_shared_factors, list
        ):
            raise _RunRequestError(
                "factor-set subjects require canonical RunSpec factors"
            )
        missing_refs: list[str] = []
        for factor in run_shared_factors:
            if not isinstance(factor, dict):
                continue
            alias = str(factor.get("alias") or "").strip()
            target_ref = factor_refs.get(alias)
            if not target_ref:
                missing_refs.append(alias or "<empty>")
                continue
            # Keep the exact submitted member reference in the immutable
            # configuration.  No N/$F parsing or family-level substitution is
            # allowed here.
            factor["factor_ref"] = target_ref
        execution_by_alias = {
            str(item.get("alias") or "").strip(): item
            for item in execution_shared_factors
            if isinstance(item, dict) and str(item.get("alias") or "").strip()
        }
        for alias, target_ref in factor_refs.items():
            item = execution_by_alias.get(alias)
            if item is not None:
                item["factor_ref"] = target_ref
        if missing_refs:
            raise _RunRequestError(
                "factor-set subjects do not bind every RunSpec factor: "
                + ", ".join(sorted(missing_refs))
            )
        run_spec["factor_refs"] = dict(sorted(factor_refs.items()))
    if strategy_plan:
        run_spec["strategy_specs"] = deepcopy(strategy_plan)
        run_spec["strategy_plan"] = deepcopy(strategy_plan)
    run_spec["strategy_source_policy"] = (
        {
            "mode": "transient_run_source",
            "files": [
                {key: value for key, value in item.items() if key != "source_code"}
                for item in transient_strategy_sources
            ],
        }
        if transient_strategy_sources
        else {"mode": "metadata_only"}
    )
    if transient_sources:
        run_spec["factor_source_policy"] = {
            "mode": "transient_run_source",
            "files": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "source_code"
                }
                for item in transient_sources
            ],
        }
    else:
        run_spec["factor_source_policy"] = {"mode": "metadata_only"}
    trial_binding = data.get("trial_binding")
    if isinstance(trial_binding, dict):
        research_binding = {
            key: str(trial_binding.get(key) or "")
            for key in (
                "profile_ref", "acting_profile_ref", "work_package_ref",
                "instance_id", "branch_id",
            )
            if trial_binding.get(key)
        }
        if research_binding.get("instance_id") and not research_binding.get("work_package_ref"):
            research_binding["work_package_ref"] = (
                "work-package:" + research_binding["instance_id"]
            )
        if research_binding:
            run_spec["research_binding"] = research_binding
    snapshot = configuration.get("snapshot")
    if isinstance(snapshot, dict):
        run_spec["configuration_snapshot"] = {
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_revision": snapshot["snapshot_revision"],
            "fingerprint": snapshot["fingerprint"],
            "source_provenance": deepcopy(
                snapshot["source_provenance"]
            ),
        }
    return {
        "workspace_id": workspace_id,
        "configuration": configuration,
        "frozen_configuration": frozen_configuration,
        "analyses": analyses,
        "retention_mode": retention_mode,
        "step_mode": step_mode,
        "performance_profile": performance_profile,
        "margin_execution_profile": margin_execution_profile,
        "output_requests": output_requests,
        "run_spec": run_spec,
        "transient_sources": transient_sources,
        "transient_strategy_sources": transient_strategy_sources,
        "strategy_specs": strategy_plan,
        "strategy_plan": strategy_plan,
    }


def _run_request_error_response(exc: _RunRequestError):
    return jsonify({
        "success": False,
        "error": str(exc),
        **exc.details,
    }), exc.status_code


def _selection_id(group: dict) -> str:
    raw = group.get("product_path_selection")
    if isinstance(raw, dict):
        return str(
            raw.get("product_path_selection_id")
            or raw.get("selection_id")
            or raw.get("id")
            or ""
        )
    return str(group.get("product_path_selection_id") or group.get("testerId") or "")


def _freeze_product_selections(configuration: dict, *, owner: str, analyses: list[str]) -> dict:
    frozen = deepcopy(configuration)
    if "backtest" not in analyses:
        return frozen
    backtest = frozen["payload"]["analyses"].get("backtest")
    if not isinstance(backtest, dict):
        return frozen
    selections = deepcopy(backtest.get("product_selections") or {})
    if isinstance(selections, list):
        selections = {
            str(item.get("product_path_selection_id") or item.get("selection_id") or item.get("id") or ""): item
            for item in selections if isinstance(item, dict)
        }
    if not isinstance(selections, dict):
        selections = {}
    from server.modules.products.product_group_store import load_product_groups

    product_groups = {
        str(item.get("id") or ""): item
        for item in load_product_groups(owner) if isinstance(item, dict)
    }
    unresolved: set[str] = set()
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        selection_id = _selection_id(group)
        if not selection_id:
            continue
        raw = selections.get(selection_id)
        if not isinstance(raw, dict):
            group_selection = group.get("product_path_selection")
            raw = deepcopy(group_selection) if isinstance(group_selection, dict) else {}
        paths = raw.get("selected_paths") or raw.get("paths")
        if not isinstance(paths, list) or not paths:
            product_group = product_groups.get(selection_id)
            if product_group is None:
                unresolved.add(selection_id)
                continue
            paths = deepcopy(product_group.get("paths") or [])
            raw.update({
                "label": str(product_group.get("name") or selection_id),
                "product_group": str(product_group.get("name") or selection_id),
                "product_group_template_id": selection_id,
            })
        raw["product_path_selection_id"] = selection_id
        raw["selected_paths"] = deepcopy(paths)
        selections[selection_id] = raw
    if unresolved:
        raise ValueError(
            "configuration references product selections unavailable to owner: "
            + ", ".join(sorted(unresolved))
        )
    backtest["product_selections"] = selections
    return frozen


def _freeze_external_factor_artifacts(configuration: dict) -> dict:
    frozen = deepcopy(configuration)
    shared = frozen["payload"]["shared"]
    artifacts = external_factor_artifacts.freeze_configured_artifacts(shared)
    if artifacts:
        shared["external_factor_artifacts"] = artifacts
    return frozen


def _deployment_id() -> str:
    return str(os.environ.get("GTHT_DEPLOYMENT_ID") or "factortester-local")


def _submission_context() -> dict[str, str]:
    user_agent = str(request.headers.get("User-Agent") or "").strip()
    marker = str(request.headers.get("X-FactorTester-Client") or "").strip()
    value = f"{marker} {user_agent}".lower()
    if "cli" in value:
        channel = "cli"
    elif "swift" in value or "ftclient" in value:
        channel = "swift"
    elif "web" in value or "mozilla" in value:
        channel = "web"
    else:
        channel = "http"
    return {
        "channel": channel,
        "client": marker or user_agent.split("/", 1)[0] or "unknown",
        "user_agent": user_agent[:200],
        "trigger": "manual",
        "api_route": str(request.path or ""),
    }


def _daemon_client() -> JobDaemonClient:
    socket_path = os.environ.get(
        "GTHT_JOB_DAEMON_SOCKET",
        str(Settings.CACHE_DIR / "runtime" / f"research-jobs-{_deployment_id()}.sock"),
    )
    return JobDaemonClient(socket_path)


def _submit_kind(kind: str, payload: dict, *, run_spec_hash: str):
    process_runners = {
        "backtest": "server.modules.single_factor_test.process_runners:run_group",
        "ic": "server.modules.single_factor_test.process_runners:run_ic",
        "factor_evaluation": "server.modules.single_factor_test.process_runners:run_factor_evaluation",
        "factor_type_analysis": "server.modules.single_factor_test.process_runners:run_factor_type_analysis",
    }
    runner = process_runners.get(kind)
    if runner is None:
        raise ValueError(f"unsupported research job kind: {kind}")
    repository = JobRepository()
    payload.setdefault("submission_context", _submission_context())
    job = repository.create(JobRecord(
        job_id=uuid.uuid4().hex,
        kind=kind,
        run_id=str(payload["run_id"]),
        workspace_id=str(payload["workspace_id"]),
        owner=str(payload["_owner"]),
        status=JobStatus.SUBMITTED,
        retry_of=str(payload.pop("_retry_of", "") or ""),
        attempt=max(1, int(payload.pop("_attempt", 1) or 1)),
        step_mode=bool(payload.get("step_mode")),
        retention_mode=str(payload.get("retention_mode") or "summary"),
        deployment_id=_deployment_id(),
        service_port=detect_port(request.environ),
        source_revision=str(os.environ.get("GTHT_SOURCE_REVISION") or ""),
        runner_path=runner,
        job_spec=deepcopy(payload),
        run_spec_hash=run_spec_hash,
        entitlement=entitlement_for_owner(str(payload["_owner"])),
    ))
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return job


def _execution_payload(configuration: dict, kind: str) -> dict:
    payload = configuration["payload"]
    analysis = payload["analyses"].get(kind)
    if not isinstance(analysis, dict):
        raise ValueError(f"configuration has no {kind} analysis payload")
    shared = deepcopy(payload["shared"])
    execution = {**shared, **deepcopy(analysis)}
    families = shared.get("factor_families")
    if isinstance(families, list) and len(families) == 1 and isinstance(families[0], dict):
        execution.setdefault("factor_family_alias", str(families[0].get("alias") or ""))
    execution["research_configuration"] = {
        "configuration_id": configuration["configuration_id"],
        "revision": configuration["revision"],
        "fingerprint": configuration["fingerprint"],
    }
    return execution


@sft_bp.post("/api/workspaces")
def create_research_workspace():
    data = request.get_json(silent=True) or {}
    factor_families = data.get("factor_families") or []
    factors = data.get("factors") or []
    if not isinstance(factor_families, list) or not all(isinstance(item, dict) for item in factor_families):
        return jsonify({"success": False, "error": "factor_families must be an array of objects"}), 400
    if not isinstance(factors, list) or not all(isinstance(item, dict) for item in factors):
        return jsonify({"success": False, "error": "factors must be an array of objects"}), 400
    workspace = research_workspaces.create_workspace(
        owner=require_user(),
        title=str(data.get("title") or "Factor research").strip(),
        factor_families=factor_families,
        factors=factors,
    )
    return jsonify({"success": True, "workspace": workspace}), 201


@sft_bp.get("/api/jobs/artifact-capabilities")
def get_job_artifact_capabilities():
    """Declare outputs that can be requested before or after a Job."""
    return jsonify({
        "success": True,
        "schema_version": 1,
        "outputs": output_capabilities(),
    })


@sft_bp.get("/api/workspaces")
def list_research_workspaces():
    return jsonify({
        "success": True,
        "workspaces": research_workspaces.list_workspaces(owner=require_user()),
    })


@sft_bp.get("/api/workspaces/<workspace_id>")
def get_research_workspace(workspace_id: str):
    workspace = research_workspaces.load_workspace(
        workspace_id=workspace_id, owner=require_user(),
    )
    if workspace is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, "workspace": workspace})


@sft_bp.get("/api/workspaces/<workspace_id>/configuration")
def get_workspace_configuration(workspace_id: str):
    value = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id, owner=require_user(),
    )
    if value is None:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    return jsonify({"success": True, "configuration": value})


@sft_bp.post("/api/external-factor-artifacts/validate")
def validate_external_factor_artifact():
    require_user()
    data = request.get_json(silent=True) or {}
    manifest_path = str(data.get("manifest_path") or "").strip()
    if not manifest_path:
        return jsonify({"success": False, "error": "manifest_path is required"}), 400
    try:
        artifact = external_factor_artifacts.validate_and_freeze(manifest_path)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "artifact": artifact})


@sft_bp.put("/api/workspaces/<workspace_id>/configuration")
def update_workspace_configuration(workspace_id: str):
    data = request.get_json(silent=True) or {}
    try:
        expected_revision = int(data.get("expected_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "expected_revision is required"}), 400
    try:
        value = research_configurations.update_workspace_configuration(
            workspace_id=workspace_id,
            owner=require_user(),
            expected_revision=expected_revision,
            payload=data.get("payload"),
        )
    except research_configurations.ConfigurationRevisionConflict as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "current_revision": exc.current_revision,
        }), 409
    except KeyError:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "configuration": value})


@sft_bp.get("/api/configuration-templates")
def list_configuration_templates():
    return jsonify({
        "success": True,
        "templates": research_configurations.list_templates(owner=require_user()),
    })


@sft_bp.post("/api/workspaces/<workspace_id>/configuration/templates")
def save_configuration_template(workspace_id: str):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "template name is required"}), 400
    try:
        template = research_configurations.save_template(
            workspace_id=workspace_id, owner=require_user(), name=name,
        )
    except KeyError:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    return jsonify({"success": True, "template": template}), 201


@sft_bp.post("/api/workspaces/<workspace_id>/configuration/load-template")
def load_configuration_template(workspace_id: str):
    data = request.get_json(silent=True) or {}
    configuration_id = str(data.get("configuration_id") or "").strip()
    try:
        expected_revision = int(data.get("expected_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "expected_revision is required"}), 400
    try:
        value = research_configurations.load_template_into_workspace(
            configuration_id=configuration_id,
            workspace_id=workspace_id,
            owner=require_user(),
            expected_revision=expected_revision,
        )
    except research_configurations.ConfigurationRevisionConflict as exc:
        return jsonify({
            "success": False, "error": str(exc), "current_revision": exc.current_revision,
        }), 409
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "configuration": value})


@sft_bp.put("/api/configuration-templates/<configuration_id>")
def overwrite_configuration_template(configuration_id: str):
    workspace_id = str((request.get_json(silent=True) or {}).get("workspace_id") or "").strip()
    if not workspace_id:
        return jsonify({"success": False, "error": "workspace_id is required"}), 400
    try:
        value = research_configurations.overwrite_template_from_workspace(
            configuration_id=configuration_id,
            workspace_id=workspace_id,
            owner=require_user(),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "template": value})


@sft_bp.delete("/api/configuration-templates/<configuration_id>")
def delete_configuration_template(configuration_id: str):
    if not research_configurations.delete_template(
        configuration_id=configuration_id, owner=require_user(),
    ):
        return jsonify({"success": False, "error": "template not found"}), 404
    return jsonify({"success": True, "configuration_id": configuration_id})


@sft_bp.post("/api/runs")
def submit_research_run():
    data = request.get_json(silent=True) or {}
    owner = require_user()
    repository = JobRepository()
    quota = repository.storage_quota(
        owner=owner, default_bytes=default_user_quota_bytes()
    )
    usage = repository.storage_usage(owner=owner)
    if usage > quota:
        return jsonify({
            "success": False,
            "error": "retained result quota exceeded; delete full results before submitting",
            "code": "storage_quota_exceeded",
            "usage_bytes": usage,
            "quota_bytes": quota,
        }), 507
    try:
        prepared = _prepare_research_run_request(data, owner=owner)
    except _RunRequestError as exc:
        return _run_request_error_response(exc)
    workspace_id = prepared["workspace_id"]
    configuration = prepared["configuration"]
    frozen_configuration = prepared["frozen_configuration"]
    analyses = prepared["analyses"]
    retention_mode = prepared["retention_mode"]
    step_mode = prepared["step_mode"]
    performance_profile = prepared["performance_profile"]
    margin_execution_profile = prepared["margin_execution_profile"]
    run_spec = prepared["run_spec"]
    transient_sources = prepared.get("transient_sources") or []
    transient_scope = create_scope(owner=owner, entries=transient_sources)
    transient_strategy_scope = create_strategy_scope(
        owner=owner,
        entries=prepared.get("transient_strategy_sources") or [],
    )
    try:
        run = research_runs.create_run(
            owner=owner,
            workspace_id=workspace_id,
            configuration_id=configuration["configuration_id"],
            configuration_revision=configuration["revision"],
            run_spec=run_spec,
            trial_binding=data.get("trial_binding"),
            report_binding=data.get("report_binding"),
        )
    except ValueError as exc:
        cleanup_scope(str(transient_scope.get("scope_id") or ""))
        cleanup_strategy_scope(str(transient_strategy_scope.get("scope_id") or ""))
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        cleanup_scope(str(transient_scope.get("scope_id") or ""))
        cleanup_strategy_scope(str(transient_strategy_scope.get("scope_id") or ""))
        raise
    jobs = []
    try:
        for kind in analyses:
            payload = {
                **_execution_payload(frozen_configuration, kind),
                "run_id": run["run_id"],
                "run_token": f"{run['run_id']}:{kind}",
                "workspace_id": workspace_id,
                "configuration_id": configuration["configuration_id"],
                "configuration_revision": configuration["revision"],
                "_owner": owner,
                "retention_mode": retention_mode,
                "step_mode": step_mode,
                "output_requests": output_requests_for_analysis(
                    prepared["output_requests"], kind,
                ),
                "run_spec": run_spec,
                "factor_refs": dict(run_spec.get("factor_refs") or {}),
                "strategy_specs": list(prepared.get("strategy_specs") or []),
                "strategy_plan": list(prepared.get("strategy_plan") or []),
                "transient_factor_source_scope_id": str(
                    transient_scope.get("scope_id") or ""
                ),
                "transient_strategy_source_scope_id": str(
                    transient_strategy_scope.get("scope_id") or ""
                ),
            }
            if kind == "backtest" and performance_profile is not None:
                payload["performance_profile"] = deepcopy(
                    performance_profile
                )
            if kind == "backtest" and margin_execution_profile is not None:
                payload["margin_execution_profile"] = deepcopy(
                    margin_execution_profile
                )
            job = _submit_kind(
                kind,
                payload,
                run_spec_hash=str(run["run_spec_hash"]),
            )
            jobs.append(job.summary())
    except Exception:
        # A submission failure before the first Job is durable must not leave
        # a source bundle behind.  Once a Job exists, its terminal lifecycle
        # owns cleanup because that Job may already be running.
        if not JobRepository().has_run_attempts(
            owner=owner,
            run_id=str(run["run_id"]),
        ):
            cleanup_scope(str(transient_scope.get("scope_id") or ""))
            cleanup_strategy_scope(str(transient_strategy_scope.get("scope_id") or ""))
        raise
    try:
        presentation_sample_identity = derive_sample_identity(run_spec)
    except ValueError:
        presentation_sample_identity = None
    presentation = run_spec_presentation(
        run_spec,
        run_spec_hash=str(run["run_spec_hash"]),
        run_id=str(run["run_id"]),
        sample_identity=presentation_sample_identity,
    )
    return jsonify({
        "success": True,
        "run_id": run["run_id"],
        "run": {**run, "report_presentation": presentation},
        "jobs": jobs,
        "report_projection": {
            "schema_version": 1,
            "links": [{
                "kind": "run",
                "target_ref": f"run:{run['run_id']}",
                "label": presentation["alias_zh"],
            }],
            "run_spec": presentation,
        },
    }), 202


@sft_bp.post("/api/runs/preview")
def preview_research_run():
    """Derive the exact frozen RunSpec identity without creating state."""
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        prepared = _prepare_research_run_request(data, owner=owner)
    except _RunRequestError as exc:
        return _run_request_error_response(exc)
    run_spec = prepared["run_spec"]
    configuration = prepared["configuration"]
    try:
        sample_identity = derive_sample_identity(run_spec)
    except ValueError as exc:
        sample_identity = {
            "authority": "unavailable",
            "error": str(exc),
        }
    presentation = run_spec_presentation(
        run_spec,
        run_spec_hash=research_runs.hash_run_spec(run_spec),
        sample_identity=sample_identity,
    )
    return jsonify({
        "success": True,
        "run_spec_hash": research_runs.hash_run_spec(run_spec),
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "configuration_id": configuration["configuration_id"],
        "configuration_revision": configuration["revision"],
        "configuration_fingerprint": configuration["fingerprint"],
        "configuration_snapshot": deepcopy(
            run_spec.get("configuration_snapshot")
        ),
        "analyses": prepared["analyses"],
        "retention_mode": prepared["retention_mode"],
        "step_mode": prepared["step_mode"],
        "performance_profile": deepcopy(
            prepared["performance_profile"]
        ),
        "margin_execution_profile": deepcopy(
            prepared["margin_execution_profile"]
        ),
        "output_requests": list(prepared["output_requests"]),
        "strategy_specs": deepcopy(prepared.get("strategy_specs") or []),
        "strategy_plan": deepcopy(prepared.get("strategy_plan") or []),
        "strategy_source_policy": deepcopy(
            run_spec.get("strategy_source_policy") or {}
        ),
        "factor_source_policy": deepcopy(
            run_spec.get("factor_source_policy") or {}
        ),
        "sample_identity": sample_identity,
        "factor_revision_manifests": deepcopy(
            run_spec["configuration"]["shared"].get(
                "factor_revision_manifests"
            ) or []
        ),
        "factor_subject_descriptors": deepcopy(
            run_spec.get("factor_subject_descriptors") or []
        ),
        "report_projection": {
            "schema_version": 1,
            "links": [{
                "kind": "run_spec",
                "target_ref": presentation["target_ref"],
                "label": presentation["alias_zh"],
            }],
            "run_spec": presentation,
        },
    })


@sft_bp.get("/api/runs/<run_id>")
def get_research_run(run_id: str):
    owner = require_user()
    run = research_runs.load_run(run_id=run_id, owner=owner)
    if run is None:
        return jsonify({"success": False, "error": "run not found"}), 404
    jobs = JobRepository().list(owner=owner, run_id=run_id, limit=200)
    return jsonify({"success": True, "run": run, "jobs": [job.summary() for job in jobs]})


@sft_bp.get("/api/run-specs/<run_spec_hash>")
def get_research_run_spec(run_spec_hash: str):
    try:
        run_spec = research_runs.load_run_spec(
            run_spec_hash=run_spec_hash,
            owner=require_user(),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if run_spec is None:
        return jsonify({"success": False, "error": "RunSpec not found"}), 404
    return jsonify({"success": True, "run_spec": run_spec})


@sft_bp.post("/api/runs/<run_id>/clone-workspace")
def clone_research_run_workspace(run_id: str):
    owner = require_user()
    run = research_runs.load_run(run_id=run_id, owner=owner)
    if run is None:
        return jsonify({"success": False, "error": "run not found"}), 404
    payload = run["run_spec"].get("configuration")
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "run has no restorable configuration"}), 409
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or f"Restored run {run_id[:8]}").strip()
    workspace = research_workspaces.create_workspace(
        owner=owner, title=title, payload=deepcopy(payload),
    )
    return jsonify({
        "success": True,
        "workspace": workspace,
        "source_run_id": run_id,
        "source_run_spec_hash": run["run_spec_hash"],
    }), 201
