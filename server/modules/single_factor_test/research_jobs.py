"""HTTP interface for research contexts, configurations, templates, and runs."""

from __future__ import annotations

import os
import re
import uuid
from copy import deepcopy

from flask import jsonify, request, session

import settings as Settings
from server.jobs.artifacts import default_user_quota_bytes
from server.jobs.entitlements import entitlement_for_owner
from server.jobs.input_artifacts import (
    retain_factor_sources,
    retain_run_dependencies,
    retain_strategy_sources,
    retain_strategy_specs,
    strategy_spec_input_bytes,
)
from server.jobs.ipc import DaemonUnavailable, JobDaemonClient
from server.jobs.models import JobRecord
from server.jobs.ports import detect_port
from server.jobs.report_outputs import (
    default_output_requests,
    output_capabilities,
    output_requests_for_analysis,
    result_retention_mode_for,
    validate_output_requests,
)
from server.jobs.repository import JobRepository
from server.jobs.run_input_dependencies import (
    dependency_input_bytes,
)
from server.jobs.run_input_dependencies import (
    source_free_manifest as dependency_manifest,
)
from server.jobs.run_input_dependencies import (
    validate_entries as validate_run_input_dependencies,
)
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp
from server.services import (
    external_factor_artifacts,
    factor_revisions,
    factor_subject_descriptors,
    research_configuration_snapshots,
    research_configurations,
    research_runs,
    research_workspaces,
)
from server.services.factor_registry import transient_factor_source_scope
from server.services.federated_factor_sources import (
    freeze_sources as freeze_federated_factor_sources,
)
from server.services.federated_factor_sources import (
    source_free_context as source_free_federated_context,
)
from server.services.federated_factor_sources import (
    source_free_manifest as federated_source_manifest,
)
from server.services.federated_factor_sources import (
    source_transfer_manifest as federated_source_transfer_manifest,
)
from server.services.frozen_product_scope import freeze_product_scope
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from server.services.research_report_presentations import (
    run_spec_presentation,
)
from server.services.research_run_context import (
    MANAGER_RUN_CONTEXT_KEY,
    create_manager_run_context,
    load_manager_run_context,
)
from server.services.research_run_context import (
    RunRequestError as _RunRequestError,
)
from server.services.session_runtime import require_user
from server.services.strategy_plans import normalize_strategy_plan
from server.services.transient_factor_sources import (
    cleanup_scope,
    create_scope,
    validate_entries,
)
from server.services.transient_strategy_sources import (
    cleanup_scope as cleanup_strategy_scope,
)
from server.services.transient_strategy_sources import (
    create_scope as create_strategy_scope,
)
from server.services.transient_strategy_sources import (
    validate_entries as validate_strategy_entries,
)
from tools.factors.formula_identity import require_frozen_factor
from tools.testers.backtest.engines.native.performance_profile import (
    normalize_performance_profile,
)
from tools.testers.backtest.modules.margin_budget_impl.observability import (
    normalize_margin_execution_profile,
)
from tools.testers.settings.runtime_intent import (
    normalize_backtest_runtime_setting_intent,
)

SUPPORTED_ANALYSES = {"backtest", "ic", "factor_evaluation", "factor_type_analysis"}
_TASK_NAME_LIMIT = 160
_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VISITOR_MAX_JOBS = 20
_VISITOR_STORAGE_QUOTA_BYTES = 256 * 1024 * 1024


def _normalise_task_name(value: object) -> str:
    """Keep a task label short and separate from the immutable RunSpec hash."""
    return " ".join(str(value or "").split())[:_TASK_NAME_LIMIT]


def _normalise_acting_profile_ref(value: object) -> str:
    """Normalize the optional Profile identity stored on a JobAttempt."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("profile:"):
        raw = raw.split(":", 1)[1].strip()
    if not _PROFILE_ID_PATTERN.fullmatch(raw):
        raise _RunRequestError(
            "acting_profile_ref must be a valid Profile ID",
            details={"code": "invalid_acting_profile_ref"},
        )
    return f"profile:{raw}"


def _normalise_custom_strategy_scope(data: dict) -> dict:
    """Normalize nested custom-strategy fields before they enter a RunSpec."""
    raw = data.get("custom_strategy_scope")
    scope = raw if isinstance(raw, dict) else {}
    overrides = data.get("custom_strategy_overrides", scope.get("overrides", {}))
    if not isinstance(overrides, dict):
        raise _RunRequestError("custom_strategy_overrides must be an object")
    mounted = data.get("custom_strategy_mounted_tabs", scope.get("mounted_tabs", []))
    if not isinstance(mounted, list):
        raise _RunRequestError("custom_strategy_mounted_tabs must be an array")
    product_mask = data.get(
        "custom_strategy_product_mask", scope.get("product_mask", []),
    )
    if not isinstance(product_mask, list):
        raise _RunRequestError("custom_strategy_product_mask must be an array")
    return {
        "overrides": deepcopy(overrides),
        "mounted_tabs": list(dict.fromkeys(str(item) for item in mounted if str(item))),
        "product_mask": list(dict.fromkeys(
            str(item).strip() for item in product_mask if str(item).strip()
        )),
    }


def _prepare_local_research_run_request(data: dict, *, owner: str) -> dict:
    task_name = _normalise_task_name(
        data.get("task_name") if "task_name" in data else data.get("name")
    )
    acting_profile_ref = _normalise_acting_profile_ref(
        data.get("acting_profile_ref")
    )
    acting_profile_name = _normalise_task_name(data.get("acting_profile_name"))
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
    output_requests_supplied = (
        "output_requests" in data and data.get("output_requests") is not None
    )
    try:
        output_requests = validate_output_requests(
            data.get("output_requests"), analyses,
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    if not output_requests_supplied:
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
    custom_strategy_scope = _normalise_custom_strategy_scope(data)
    try:
        run_input_dependencies = validate_run_input_dependencies(
            data.get("run_input_dependencies"), analyses=analyses,
        )
    except ValueError as exc:
        raise _RunRequestError(
            str(exc), details={"code": "invalid_run_input_dependencies"}
        ) from exc
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
            frozen_configuration = freeze_product_scope(
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
    runtime_setting_changes: list[dict] = []
    if "backtest" in analyses:
        try:
            normalized_payload, runtime_setting_changes = (
                normalize_backtest_runtime_setting_intent(
                    frozen_configuration.get("payload") or {},
                )
            )
        except ValueError as exc:
            raise _RunRequestError(str(exc)) from exc
        frozen_configuration = {
            **frozen_configuration,
            "payload": normalized_payload,
        }
    run_spec = {
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "workspace_id": workspace_id,
        "configuration_id": configuration["configuration_id"],
        "configuration_revision": configuration["revision"],
        "configuration_fingerprint": configuration["fingerprint"],
        "analyses": analyses,
        "retention_mode": retention_mode,
        "output_requests": output_requests,
        "configuration": deepcopy(frozen_configuration["payload"]),
    }
    if "backtest" in analyses:
        run_spec["runtime_setting_normalization"] = {
            "schema_version": 1,
            "changes": deepcopy(runtime_setting_changes),
        }
    ic_payload = run_spec["configuration"].get("analyses", {}).get("ic", {})
    if "ic" in analyses and ic_payload.get("schema_version") == 2:
        from tools.testers.ic_test.configuration.grouped import (
            compile_ic_grouped_configuration,
        )
        frequencies = {}
        for item in run_spec["configuration"].get("shared", {}).get("factors", []):
            try:
                frozen_factor = require_frozen_factor(item)
            except (TypeError, ValueError):
                continue
            frequency = str(
                item.get("frequency")
                or item.get("freq")
                or ""
            ).strip()
            if not frequency:
                alias = frozen_factor["alias"]
                match = re.search(r"(?:^|\|)\$F:([^|]+)", alias)
                frequency = match.group(1).strip() if match else ""
            if frequency:
                frequencies[frozen_factor["ref"]] = frequency
        run_spec["typed_ic"] = compile_ic_grouped_configuration(
            ic_payload, factor_frequencies=frequencies,
        )
    # ``step_mode`` is a backtest-only run field.  Do not put a synthetic
    # false value into IC/evaluation RunSpecs: the registry is the closed
    # contract for which submitted fields become executable RunSpec fields.
    if "backtest" in analyses:
        run_spec["step_mode"] = step_mode
    if factor_subjects:
        frozen_factor_refs = {
            require_frozen_factor(item)["ref"]
            for item in run_spec["configuration"]["shared"].get("factors") or []
        }
        try:
            factor_subject_descriptors.assert_factor_sets_match_run(
                factor_subjects,
                factor_refs=frozen_factor_refs,
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
            try:
                frozen_factor = require_frozen_factor(factor)
            except (TypeError, ValueError):
                missing_refs.append("<invalid frozen factor>")
                continue
            if factor_refs.get(frozen_factor["alias"]) != frozen_factor["ref"]:
                missing_refs.append(frozen_factor["alias"])
        execution_refs = {}
        for factor in execution_shared_factors:
            try:
                frozen_factor = require_frozen_factor(factor)
            except (TypeError, ValueError):
                continue
            execution_refs[frozen_factor["alias"]] = frozen_factor["ref"]
        if execution_refs != factor_refs:
            missing_refs.append("<execution factor set mismatch>")
        if missing_refs:
            raise _RunRequestError(
                "factor-set subjects do not bind every RunSpec factor: "
                + ", ".join(sorted(missing_refs))
            )
    if strategy_plan:
        run_spec["strategy_specs"] = deepcopy(strategy_plan)
        run_spec["strategy_plan"] = deepcopy(strategy_plan)
    run_spec["custom_strategy_scope"] = deepcopy(custom_strategy_scope)
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
    run_spec["run_input_dependency_policy"] = (
        {
            "mode": "retained_job_input",
            "files": dependency_manifest(run_input_dependencies),
        }
        if run_input_dependencies
        else {"mode": "metadata_only", "files": []}
    )
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
        "task_name": task_name,
        "acting_profile_ref": acting_profile_ref,
        "acting_profile_name": acting_profile_name,
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
        "custom_strategy_scope": custom_strategy_scope,
        "run_input_dependencies": run_input_dependencies,
    }


def prepare_manager_run_context(
    data: dict,
    *,
    owner: str,
    source_free: bool = False,
    storage_server_id: str = "",
    source_collector=None,
) -> dict:
    """Freeze origin-owned authoring state before selecting an executor."""
    local_request = deepcopy(data)
    local_request.pop(MANAGER_RUN_CONTEXT_KEY, None)
    prepared = _prepare_local_research_run_request(local_request, owner=owner)
    portable_sources = freeze_federated_factor_sources(
        prepared, owner=owner,
    )
    prepared["portable_factor_sources"] = portable_sources
    all_sources = [
        *(prepared.get("transient_sources") or []),
        *portable_sources,
    ]
    prepared["run_spec"]["factor_source_policy"] = (
        {
            "mode": "transient_run_source",
            "transport": "manager_frozen",
            "files": federated_source_manifest(
                all_sources,
                owner=owner,
                storage_server_id=storage_server_id,
            ),
        }
        if all_sources else {"mode": "metadata_only"}
    )
    if callable(source_collector):
        source_collector(
            federated_source_transfer_manifest(
                all_sources,
                owner=owner,
                storage_server_id=storage_server_id,
            )
        )
    context = create_manager_run_context(prepared, owner=owner)
    return (
        source_free_federated_context(
            context,
            owner=owner,
            storage_server_id=storage_server_id,
        )
        if source_free else context
    )


def _prepare_research_run_request(data: dict, *, owner: str) -> dict:
    context = data.get(MANAGER_RUN_CONTEXT_KEY)
    if context is not None:
        return load_manager_run_context(context, owner=owner)
    return _prepare_local_research_run_request(data, owner=owner)


def _run_request_error_response(exc: _RunRequestError):
    return jsonify({
        "success": False,
        "error": str(exc),
        **exc.details,
    }), exc.status_code


def _capability_plans(prepared: dict, *, owner: str) -> list[dict[str, object]]:
    """Build the same source-aware plans used by the durable job planner.

    This endpoint is intentionally read-only.  It lets a federated Manager
    ask each candidate service whether the frozen products, frequencies and
    requested data sources are executable before creating a Job there.
    """
    from server.modules.single_factor_test.planning import build_execution_plan

    source_overrides = {
        str(item.get("factor_id") or ""): str(item.get("source_code") or "")
        for item in prepared.get("transient_sources") or []
        if isinstance(item, dict) and item.get("factor_id")
    }
    portable_overrides = {
        str(item.get("canonical_family_ref") or ""): item
        for item in prepared.get("portable_factor_sources") or []
        if isinstance(item, dict) and item.get("canonical_family_ref")
    }
    plans: list[dict[str, object]] = []
    with transient_factor_source_scope(
        owner=owner,
        overrides=source_overrides,
        portable_overrides=portable_overrides,
    ):
        for kind in prepared["analyses"]:
            output_requests = output_requests_for_analysis(
                prepared["output_requests"], kind,
            )
            payload = {
                **_execution_payload(prepared["frozen_configuration"], kind),
                "_owner": owner,
                "run_spec": prepared["run_spec"],
                "run_spec_hash": research_runs.hash_run_spec(
                    prepared["run_spec"],
                ),
                "workspace_id": prepared["workspace_id"],
                "output_requests": output_requests,
                "strategy_specs": list(prepared.get("strategy_specs") or []),
                "strategy_plan": list(prepared.get("strategy_plan") or []),
                "custom_strategy_scope": deepcopy(
                    prepared.get("custom_strategy_scope") or {}
                ),
            }
            plan = build_execution_plan(kind, payload)
            plans.append(plan)
    return plans


def _capability_requirements(
    plans: list[dict[str, object]],
) -> list[dict[str, str]]:
    requirements: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for plan in plans:
        resolved = plan.get("resolved") if isinstance(plan, dict) else None
        if not isinstance(resolved, dict):
            continue
        rows = resolved.get("data_requirements")
        if not isinstance(rows, list) or not rows:
            rows = [
                {"product": product}
                for product in resolved.get("products") or ()
            ]
        for item in rows:
            if not isinstance(item, dict):
                continue
            product = str(
                item.get("product") or item.get("product_name") or ""
            ).strip()
            if not product:
                continue
            row = {
                "product": product,
                "frequency": str(
                    item.get("frequency") or item.get("freq") or ""
                ).strip(),
                "data_source": str(
                    item.get("data_source") or item.get("source") or ""
                ).strip(),
            }
            key = (row["product"], row["frequency"], row["data_source"])
            if key not in seen:
                seen.add(key)
                requirements.append(row)
    return requirements


def _execution_plans_or_error(prepared: dict, *, owner: str):
    """Build the one execution-plan contract shared by preview and submit."""
    try:
        return _capability_plans(prepared, owner=owner), None
    except (AssertionError, ValueError) as exc:
        return None, (jsonify({
            "success": False,
            "error": str(exc),
            "code": "data_capability_unavailable",
            "requirements": [],
        }), 422)
    except (ImportError, KeyError, TypeError, RuntimeError) as exc:
        return None, (jsonify({
            "success": False,
            "error": "data capability preflight is unavailable",
            "code": "data_capability_preflight_unavailable",
            "details": str(exc),
        }), 503)


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


def _submit_kind(
    kind: str,
    payload: dict,
    *,
    run_spec_hash: str,
    transient_factor_sources: list[dict] | None = None,
    transient_strategy_sources: list[dict] | None = None,
    strategy_specs: list[dict] | None = None,
    run_input_dependencies: list[dict] | None = None,
):
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
        retention_mode=str(
            payload.get("result_retention_mode")
            or payload.get("retention_mode")
            or "summary"
        ),
        deployment_id=_deployment_id(),
        service_port=detect_port(request.environ),
        source_revision=str(os.environ.get("GTHT_SOURCE_REVISION") or ""),
        runner_path=runner,
        job_spec=deepcopy(payload),
        run_spec_hash=run_spec_hash,
        entitlement=entitlement_for_owner(str(payload["_owner"])),
    ))
    try:
        retain_factor_sources(
            repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=transient_factor_sources or [],
        )
        retain_strategy_sources(
            repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=transient_strategy_sources or [],
        )
        retain_strategy_specs(
            repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=strategy_specs or [],
        )
        retain_run_dependencies(
            repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=run_input_dependencies or [],
        )
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    except Exception as exc:
        repository.transition(
            job.job_id,
            JobStatus.FAILED,
            expected=JobStatus.SUBMITTED,
            error={
                "code": "job_input_retention_failed",
                "message": str(exc),
            },
        )
        raise
    return job


def _execution_payload(configuration: dict, kind: str) -> dict:
    payload = configuration["payload"]
    analysis = payload["analyses"].get(kind)
    if not isinstance(analysis, dict):
        raise ValueError(f"configuration has no {kind} analysis payload")
    shared = deepcopy(payload["shared"])
    execution = {**shared, **deepcopy(analysis)}
    # The frozen configuration keeps registered fields exactly once in
    # ``execution.settings``. Runners still receive their established flat input
    # contract, so materialize that view only at the execution boundary; it
    # never re-enters the RunSpec or configuration snapshot.
    execution_contract = execution.get("execution")
    settings = (
        execution_contract.get("settings")
        if isinstance(execution_contract, dict)
        else None
    )
    if not isinstance(settings, dict):
        raise ValueError("RunSpec v4 requires analysis.execution.settings")
    execution = {**execution, **deepcopy(settings)}
    execution["research_configuration"] = {
        "configuration_id": configuration["configuration_id"],
        "revision": configuration["revision"],
        "fingerprint": configuration["fingerprint"],
    }
    return execution


@sft_bp.post("/api/test-authoring/workspaces")
def create_research_workspace():
    data = request.get_json(silent=True) or {}
    factors = data.get("factors") or []
    if not isinstance(factors, list) or not all(isinstance(item, dict) for item in factors):
        return jsonify({"success": False, "error": "factors must be an array of objects"}), 400
    workspace = research_workspaces.create_workspace(
        owner=require_user(),
        title=str(data.get("title") or "Factor test").strip(),
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


@sft_bp.get("/api/test-authoring/workspaces")
def list_research_workspaces():
    return jsonify({
        "success": True,
        "workspaces": research_workspaces.list_workspaces(owner=require_user()),
    })


@sft_bp.get("/api/test-authoring/workspaces/<workspace_id>")
def get_research_workspace(workspace_id: str):
    workspace = research_workspaces.load_workspace(
        workspace_id=workspace_id, owner=require_user(),
    )
    if workspace is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, "workspace": workspace})


@sft_bp.delete("/api/test-authoring/workspaces/<workspace_id>")
def delete_research_workspace(workspace_id: str):
    value = research_workspaces.delete_draft_workspace(
        workspace_id=workspace_id, owner=require_user(),
    )
    if value is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, **value})


@sft_bp.get("/api/test-authoring/workspaces/<workspace_id>/configuration")
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


@sft_bp.put("/api/test-authoring/workspaces/<workspace_id>/configuration")
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


@sft_bp.get("/api/test-authoring/configuration-templates")
def list_configuration_templates():
    return jsonify({
        "success": True,
        "templates": research_configurations.list_templates(owner=require_user()),
    })


@sft_bp.post("/api/test-authoring/workspaces/<workspace_id>/configuration/templates")
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


@sft_bp.post("/api/test-authoring/workspaces/<workspace_id>/configuration/load-template")
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


@sft_bp.put("/api/test-authoring/configuration-templates/<configuration_id>")
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


@sft_bp.delete("/api/test-authoring/configuration-templates/<configuration_id>")
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
    visitor_gateway = bool(session.get("manager_gateway_visitor_id"))
    if visitor_gateway and repository.count_with_metadata(owner=owner) >= _VISITOR_MAX_JOBS:
        return jsonify({
            "success": False,
            "error": "访客模式最多保留 20 个测试任务",
            "code": "visitor_job_limit_exceeded",
            "limit": _VISITOR_MAX_JOBS,
        }), 429
    default_quota = (
        _VISITOR_STORAGE_QUOTA_BYTES
        if visitor_gateway else default_user_quota_bytes()
    )
    quota = repository.storage_quota(
        owner=owner, default_bytes=default_quota,
    )
    if visitor_gateway:
        quota = min(quota, _VISITOR_STORAGE_QUOTA_BYTES)
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
    _plans, planning_error = _execution_plans_or_error(prepared, owner=owner)
    if planning_error is not None:
        return planning_error
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
    portable_sources = prepared.get("portable_factor_sources") or []
    retained_factor_sources = [*transient_sources, *portable_sources]
    factor_input_bytes = sum(
        int(item.get("source_bytes") or 0) for item in retained_factor_sources
    )
    strategy_source_bytes = sum(
        len(str(item.get("source_code") or "").encode("utf-8"))
        for item in prepared.get("transient_strategy_sources") or []
    )
    strategy_specs = list(prepared.get("strategy_specs") or [])
    retained_input_bytes = factor_input_bytes * len(analyses)
    if "backtest" in analyses:
        retained_input_bytes += strategy_source_bytes
        retained_input_bytes += strategy_spec_input_bytes(strategy_specs)
    retained_input_bytes += sum(
        dependency_input_bytes(
            prepared.get("run_input_dependencies") or [], analysis=kind,
        )
        for kind in analyses
    )
    if usage + retained_input_bytes > quota:
        return jsonify({
            "success": False,
            "error": "retained input quota exceeded; delete Job artifacts before submitting",
            "code": "storage_quota_exceeded",
            "usage_bytes": usage,
            "requested_input_bytes": retained_input_bytes,
            "quota_bytes": quota,
        }), 507
    transient_scope = create_scope(
        owner=owner,
        entries=transient_sources,
        portable_entries=portable_sources,
    )
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
            output_requests = output_requests_for_analysis(
                prepared["output_requests"], kind,
            )
            payload = {
                **_execution_payload(frozen_configuration, kind),
                "run_id": run["run_id"],
                "run_token": f"{run['run_id']}:{kind}",
                "workspace_id": workspace_id,
                "configuration_id": configuration["configuration_id"],
                "configuration_revision": configuration["revision"],
                "_owner": owner,
                "task_name": prepared["task_name"],
                "acting_profile_ref": prepared["acting_profile_ref"],
                "acting_profile_name": prepared["acting_profile_name"],
                "retention_mode": retention_mode,
                "result_retention_mode": result_retention_mode_for(
                    output_requests,
                    requested=retention_mode,
                ),
                "step_mode": step_mode,
                "output_requests": output_requests,
                "run_spec": run_spec,
                "execution_plan": deepcopy(next(
                    (plan for plan in (_plans or ()) if plan.get("kind") == kind),
                    {},
                )),
                "strategy_specs": list(prepared.get("strategy_specs") or []),
                "strategy_plan": list(prepared.get("strategy_plan") or []),
                "custom_strategy_scope": deepcopy(
                    prepared.get("custom_strategy_scope") or {}
                ),
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
                transient_factor_sources=retained_factor_sources,
                transient_strategy_sources=(
                    prepared.get("transient_strategy_sources") or []
                    if kind == "backtest" else []
                ),
                strategy_specs=(strategy_specs if kind == "backtest" else []),
                run_input_dependencies=[
                    item
                    for item in prepared.get("run_input_dependencies") or []
                    if kind in (item.get("analyses") or ())
                ],
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
    _plans, planning_error = _execution_plans_or_error(prepared, owner=owner)
    if planning_error is not None:
        return planning_error
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
        "task_name": prepared["task_name"],
        "acting_profile_ref": prepared["acting_profile_ref"],
        "acting_profile_name": prepared["acting_profile_name"],
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
        "custom_strategy_scope": deepcopy(
            prepared.get("custom_strategy_scope") or {}
        ),
        "strategy_source_policy": deepcopy(
            run_spec.get("strategy_source_policy") or {}
        ),
        "factor_source_policy": deepcopy(
            run_spec.get("factor_source_policy") or {}
        ),
        "sample_identity": sample_identity,
        "frozen_factors": deepcopy(
            run_spec["configuration"]["shared"].get("factors") or []
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


@sft_bp.post("/api/runs/capability-preview")
def preview_research_run_capabilities():
    """Validate a run against this service's product/data capabilities.

    The endpoint deliberately creates no Run, Job, input bundle, or quota
    reservation.  A Manager calls it on each candidate service port before
    forwarding the real ``POST /api/runs`` request.
    """
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        prepared = _prepare_research_run_request(data, owner=owner)
    except _RunRequestError as exc:
        return _run_request_error_response(exc)
    plans, planning_error = _execution_plans_or_error(prepared, owner=owner)
    if planning_error is not None:
        return planning_error
    requirements = _capability_requirements(plans)
    return jsonify({
        "success": True,
        "capability": True,
        "data_requirements": requirements,
        "plans": [
            {
                "kind": plan.get("kind"),
                "resolved": plan.get("resolved"),
                "resolved_hash": plan.get("resolved_hash"),
                "notices": plan.get("notices") or [],
            }
            for plan in plans
        ],
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
    if int(payload.get("schema_version") or 0) != research_configurations.SCHEMA_VERSION:
        return jsonify({
            "success": False,
            "error": (
                "historical RunSpec configuration is incompatible and cannot be "
                "restored; create a new editable configuration"
            ),
        }), 409
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
