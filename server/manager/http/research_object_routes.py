"""Manager-owned Evidence, TrialPlan, Run and RunSpec object routes."""

from __future__ import annotations

import re
from copy import deepcopy
from urllib.parse import parse_qs, unquote

from server.jobs.repository import JobRepository
from server.manager.http.responses import json_response
from server.services import (
    direct_trial_plan_registry,
    research_configurations,
    research_runs,
    research_workspaces,
)
from server.services.direct_trial_plans import create_binding
from server.services.research_evidence_catalog import (
    attach_tag,
    capture_job_source,
    create_evidence,
    create_tag,
    detach_tag,
    finalize_lifecycle_transition,
    list_facets,
    list_source_fragments,
    list_tags,
    prepare_lifecycle_transition,
    propose_tag,
    put_source_capture,
    put_source_fragment,
    retire_tag,
    search_evidence,
    update_tag,
)
from server.services.research_evidence_registry import (
    admit_evidence,
    admit_evidence_for_graph,
    get_evidence,
)


class ResearchObjectRoutesMixin:
    """Keep durable research objects independent from execution services."""

    def _research_owner(self) -> str | None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return None
        return str(session["username"])

    def _research_object_error(self, exc: Exception, *, missing: bool = False) -> None:
        if isinstance(exc, PermissionError):
            status = 403
        else:
            status = 404 if missing or isinstance(exc, KeyError) else 409
        json_response(self, {"success": False, "error": str(exc)}, status)

    def _research_object_body(self, maximum: int) -> dict:
        value = self._json_body(maximum)
        if not isinstance(value, dict):
            raise TypeError("request body must be an object")
        return value

    def _get_research_object_routes(self, parsed) -> bool:
        if parsed.path.startswith("/api/research-evidence/"):
            return self._get_evidence_route(parsed)
        direct = re.fullmatch(r"/api/trial-plans/direct/([^/]+)", parsed.path)
        run_spec = re.fullmatch(r"/api/run-specs/([^/]+)", parsed.path)
        run = re.fullmatch(r"/api/runs/([^/]+)", parsed.path)
        if not (direct or run_spec or run):
            return False
        owner = self._research_owner()
        if owner is None:
            return True
        try:
            if direct:
                value = direct_trial_plan_registry.load(
                    owner=owner,
                    trial_plan_hash=unquote(direct.group(1)),
                )
                if value is None:
                    raise KeyError("TrialPlan not found")
                payload = {"trial_plan": value}
            elif run_spec:
                value = research_runs.load_run_spec(
                    run_spec_hash=unquote(run_spec.group(1)),
                    owner=owner,
                )
                if value is None:
                    raise KeyError("RunSpec not found")
                payload = {"run_spec": value}
            else:
                run_id = unquote(run.group(1))
                value = research_runs.load_run(run_id=run_id, owner=owner)
                if value is None:
                    raise KeyError("run not found")
                jobs = JobRepository().list(owner=owner, run_id=run_id, limit=200)
                payload = {"run": value, "jobs": [job.summary() for job in jobs]}
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_object_error(exc, missing=isinstance(exc, KeyError))
            return True
        json_response(self, {"success": True, **payload})
        return True

    def _get_evidence_route(self, parsed) -> bool:
        owner = self._research_owner()
        if owner is None:
            return True
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            fragment = re.fullmatch(
                r"/api/research-evidence/sources/(.+)/fragments",
                parsed.path,
            )
            detail = re.fullmatch(r"/api/research-evidence/(.+)", parsed.path)
            if fragment:
                payload = {
                    "fragments": list_source_fragments(
                        owner=owner,
                        source_ref=unquote(fragment.group(1)),
                    )
                }
            elif parsed.path == "/api/research-evidence/facets":
                payload = {"facets": list_facets(owner=owner)}
            elif parsed.path == "/api/research-evidence/tags":
                payload = {
                    "tags": list_tags(
                        owner=owner,
                        include_retired=query.get("include_retired") == ["1"],
                    )
                }
            elif parsed.path == "/api/research-evidence/search":
                start = str(query.get("time_start", [""])[0])
                end = str(query.get("time_end", [""])[0])
                if bool(start) != bool(end):
                    raise ValueError(
                        "time_start and time_end must be provided together"
                    )
                payload = {
                    "result": search_evidence(
                        owner=owner,
                        product_refs=query.get("product_ref", []),
                        factor_refs=query.get("factor_ref", []),
                        sample_refs=query.get("sample_ref", []),
                        time_window={"start": start, "end": end} if start else None,
                        evidence_kinds=query.get("evidence_kind", []),
                        source_kinds=query.get("source_kind", []),
                        tag_refs=query.get("tag_ref", []),
                        text=str(query.get("text", [""])[0]),
                        limit=int(query.get("limit", ["20"])[0] or 20),
                        include_excluded=query.get("include_excluded") == ["1"],
                    )
                }
            elif detail:
                evidence_ref = unquote(detail.group(1))
                research_id = str(query.get("research_id", [""])[0] or "")
                report_id = str(query.get("report_id", [""])[0] or "")
                access = None
                evidence_owner = owner
                if research_id or report_id:
                    catalog = getattr(self.state, "research_catalog", None)
                    if catalog is None:
                        raise RuntimeError("Research catalog is unavailable")
                    access = catalog.resolve_evidence_access(
                        evidence_ref=evidence_ref,
                        viewer=owner,
                        research_id=research_id,
                        report_id=report_id,
                    )
                    if not access["can_view"]:
                        raise PermissionError("research Evidence access is not authorized")
                    evidence_owner = catalog.evidence_owner_ref(evidence_ref)
                payload = {"evidence": get_evidence(
                    owner=evidence_owner,
                    evidence_ref=evidence_ref,
                )}
                if access is not None:
                    payload["access"] = access
            else:
                raise KeyError("research Evidence route not found")
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_object_error(exc, missing=isinstance(exc, KeyError))
            return True
        json_response(self, {"success": True, **payload})
        return True

    def _post_research_object_routes(self, parsed) -> bool:
        if parsed.path == "/api/trial-plans/direct":
            return self._post_direct_trial_plan()
        clone = re.fullmatch(r"/api/runs/([^/]+)/clone-workspace", parsed.path)
        if clone:
            return self._clone_run_workspace(unquote(clone.group(1)))
        if not parsed.path.startswith("/api/research-evidence"):
            return False
        return self._post_evidence_route(parsed)

    def _post_direct_trial_plan(self) -> bool:
        owner = self._research_owner()
        if owner is None:
            return True
        try:
            data = self._research_object_body(4 * 1024 * 1024)
            binding = create_binding(
                trial_plan=data.get("trial_plan"),
                run_spec_hash=str(data.get("run_spec_hash") or ""),
                trial_role=str(data.get("trial_role") or ""),
                comparison_id=str(data.get("comparison_id") or ""),
            )
            direct_trial_plan_registry.save(owner=owner, binding=binding)
        except (KeyError, TypeError, ValueError) as exc:
            self._research_object_error(exc)
            return True
        json_response(self, {"success": True, "trial_binding": binding})
        return True

    def _clone_run_workspace(self, run_id: str) -> bool:
        owner = self._research_owner()
        if owner is None:
            return True
        try:
            run = research_runs.load_run(run_id=run_id, owner=owner)
            if run is None:
                raise KeyError("run not found")
            configuration = run["run_spec"].get("configuration")
            if not isinstance(configuration, dict):
                raise TypeError("run has no restorable configuration")
            if (
                int(configuration.get("schema_version") or 0)
                != research_configurations.SCHEMA_VERSION
            ):
                raise ValueError("historical RunSpec configuration is incompatible")
            data = self._research_object_body(256 * 1024)
            title = str(data.get("title") or f"Restored run {run_id[:8]}").strip()
            workspace = research_workspaces.create_workspace(
                owner=owner,
                title=title,
                payload=deepcopy(configuration),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._research_object_error(exc, missing=isinstance(exc, KeyError))
            return True
        json_response(
            self,
            {
                "success": True,
                "workspace": workspace,
                "source_run_id": run_id,
                "source_run_spec_hash": run["run_spec_hash"],
            },
            201,
        )
        return True

    def _post_evidence_route(self, parsed) -> bool:
        owner = self._research_owner()
        if owner is None:
            return True
        if parsed.path == "/api/research-evidence":
            json_response(
                self,
                {"success": False, "error": "source-wide Evidence writes are retired"},
                410,
            )
            return True
        try:
            data = self._research_object_body(4 * 1024 * 1024)
            payload, status = self._evidence_write(owner, parsed.path, data)
        except (KeyError, TypeError, ValueError) as exc:
            self._research_object_error(exc)
            return True
        json_response(self, {"success": True, **payload}, status)
        return True

    def _evidence_write(self, owner: str, path: str, data: dict):
        fragment = re.fullmatch(r"/api/research-evidence/sources/(.+)/fragments", path)
        retire = re.fullmatch(r"/api/research-evidence/tags/(.+)/retire", path)
        attach = re.fullmatch(r"/api/research-evidence/(.+)/tags", path)
        prepare = re.fullmatch(r"/api/research-evidence/(.+)/lifecycle/prepare", path)
        finalize = re.fullmatch(r"/api/research-evidence/lifecycle/(.+)/finalize", path)
        graph_admit = re.fullmatch(
            r"/api/research-evidence/(.+)/graph-admissions", path
        )
        admit = re.fullmatch(r"/api/research-evidence/(.+)/admissions", path)
        if path == "/api/research-evidence/sources":
            value = put_source_capture(
                owner=owner,
                source_kind=data.get("source_kind"),
                identity=data.get("identity"),
                content_hash=data.get("content_hash"),
                audit=data.get("audit") or {},
                captured_at=data.get("captured_at"),
            )
            return {"source": value}, 201
        if path == "/api/research-evidence/sources/job":
            return {
                "source": capture_job_source(
                    owner=owner, job_id=str(data.get("job_id") or "")
                )
            }, 201
        if fragment:
            value = put_source_fragment(
                owner=owner,
                source_ref=unquote(fragment.group(1)),
                selector=data.get("selector"),
                fragment_hash=data.get("fragment_hash"),
                title_zh=data.get("title_zh"),
                summary_zh=data.get("summary_zh"),
                preview=data.get("preview") or {},
                created_at=data.get("created_at"),
            )
            return {"fragment": value}, 201
        if path == "/api/research-evidence/compositions":
            value = create_evidence(
                owner=owner,
                evidence_kind=data.get("evidence_kind"),
                fragment_refs=data.get("fragment_refs"),
                title_zh=data.get("title_zh"),
                description_zh=data.get("description_zh"),
                claim_summary=data.get("claim_summary"),
                applicability=data.get("applicability") or {},
                identity_refs=data.get("identity_refs") or {},
                limitations=data.get("limitations") or [],
                conflicts=data.get("conflicts") or [],
            )
            return {"evidence": value}, 201
        if path == "/api/research-evidence/tags/proposals":
            value = propose_tag(
                owner=owner,
                title_zh=data.get("title_zh"),
                description_zh=data.get("description_zh"),
                created_by_profile_ref=data.get("created_by_profile_ref"),
                distinct_reason=str(data.get("distinct_reason") or ""),
            )
            return {"proposal": value}, 201
        if path == "/api/research-evidence/tags":
            return {
                "tag": create_tag(
                    owner=owner, proposal_token=str(data.get("proposal_token") or "")
                )
            }, 201
        if retire:
            return {
                "tag": retire_tag(owner=owner, tag_ref=unquote(retire.group(1)))
            }, 200
        if prepare:
            value = prepare_lifecycle_transition(
                owner=owner,
                evidence_ref=unquote(prepare.group(1)),
                action=str(data.get("action") or ""),
                reason_zh=data.get("reason_zh"),
                profile_ref=str(data.get("profile_ref") or ""),
                agent_id=str(data.get("agent_id") or ""),
                instance_id=str(data.get("instance_id") or ""),
                branch_id=str(data.get("branch_id") or ""),
                parent_id=str(data.get("parent_id") or ""),
            )
            return {"transition": value}, 201
        if finalize:
            return {
                "lifecycle": finalize_lifecycle_transition(
                    owner=owner,
                    transition_ref=unquote(finalize.group(1)),
                    report_receipt=data.get("report_receipt"),
                )
            }, 200
        if graph_admit:
            value = admit_evidence_for_graph(
                owner=owner,
                evidence_ref=unquote(graph_admit.group(1)),
                instance_id=str(data.get("instance_id") or ""),
                branch_id=str(data.get("branch_id") or ""),
                qualification=str(data.get("qualification") or ""),
                note=str(data.get("note") or ""),
            )
            return {"admission": value}, 201
        if admit:
            value = admit_evidence(
                owner=owner,
                evidence_ref=unquote(admit.group(1)),
                environment_ref=str(data.get("environment_ref") or ""),
                subject_ref=str(data.get("subject_ref") or ""),
                qualification=str(data.get("qualification") or ""),
                note=str(data.get("note") or ""),
            )
            return {"admission": value}, 201
        if attach:
            value = attach_tag(
                owner=owner,
                evidence_ref=unquote(attach.group(1)),
                tag_ref=str(data.get("tag_ref") or ""),
            )
            return {"attachment": value}, 201
        raise KeyError("research Evidence route not found")

    def _patch_research_object_routes(self, parsed) -> bool:
        match = re.fullmatch(r"/api/research-evidence/tags/(.+)", parsed.path)
        if not match:
            return False
        owner = self._research_owner()
        if owner is None:
            return True
        try:
            data = self._research_object_body(256 * 1024)
            value = update_tag(
                owner=owner,
                tag_ref=unquote(match.group(1)),
                title_zh=data.get("title_zh"),
                description_zh=data.get("description_zh"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._research_object_error(exc)
            return True
        json_response(self, {"success": True, "tag": value})
        return True

    def _delete_research_object_routes(self, parsed) -> bool:
        match = re.fullmatch(r"/api/research-evidence/(.+)/tags/(.+)", parsed.path)
        if not match:
            return False
        owner = self._research_owner()
        if owner is None:
            return True
        try:
            value = detach_tag(
                owner=owner,
                evidence_ref=unquote(match.group(1)),
                tag_ref=unquote(match.group(2)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._research_object_error(exc)
            return True
        json_response(self, {"success": True, "attachment": value})
        return True


__all__ = ["ResearchObjectRoutesMixin"]
