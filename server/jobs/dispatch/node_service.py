"""Authenticated execution-node operations over existing Job/target repositories.

Transport authenticates each request with the existing enrolled node key. This
module never accepts a caller-selected principal or another Manager's Job DB.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import re
import time
from typing import Any

from server.jobs.assurance import canonical_hash
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus, TERMINAL_STATUSES
from traderesearch_data.execution import (
    bind_bar_input, deployment_from_dict, offer_from_dict, requirement_from_dict,
)

_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def target_route(target: dict) -> str:
    """Stable broker namespace includes owning Manager and node, not IP/port."""
    parsed = deployment_from_dict(target)
    return "node-" + canonical_hash(asdict(parsed))


def record_to_wire(record: JobRecord | None) -> dict | None:
    return asdict(record) if record else None


class ExecutionNodeService:
    def __init__(self, repository, *, manager_id: str):
        self.repository = repository
        self.manager_id = manager_id

    def register(self, node_id: str, payload: dict) -> dict:
        target = deployment_from_dict(payload["target"])
        if target.node_id != node_id or target.manager_id != self.manager_id:
            raise PermissionError("node/Manager identity mismatch")
        raw_offers = payload.get("offers")
        if not isinstance(raw_offers, list) or len(raw_offers) > 2048:
            raise ValueError("bounded installation inventory is required")
        offers = tuple(offer_from_dict(item) for item in raw_offers)
        for offer in offers:
            if (offer.installation.node_id != node_id
                    or offer.installation.authority != self.manager_id):
                raise PermissionError("installation belongs to another node/Manager")
        refs = [item.source_ref + ":" + item.product_ref + ":" + item.bar_spec for item in offers]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate installed source/product/Bar offer")
        port = payload.get("service_port")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("service_port is invalid")
        runtime = payload.get("runtime_adapters", {})
        if not isinstance(runtime, dict) or set(runtime) - {offer.source_ref for offer in offers}:
            raise ValueError("runtime adapters reference unknown installations")
        # No plugin entrypoints, paths or credentials are accepted as Manager metadata.
        allowed = {"member_key", "adapter_id", "frequency", "instrument_scope", "clock_policy"}
        if any(not isinstance(item, dict) or set(item) != allowed
               or any(not isinstance(v, str) or not v for v in item.values())
               for item in runtime.values()):
            raise ValueError("invalid source adapter metadata")
        route = target_route(asdict(target))
        self.repository.heartbeat_worker_target(
            route, port, node_id, ttl_seconds=60,
            capabilities={"execution_target": asdict(target), "offers": [asdict(x) for x in offers],
                          "runtime_adapters": runtime},
        )
        return {"route_id": route, "service_port": port}

    def directory(self) -> list[dict]:
        return [row for row in self.repository.list_worker_targets()
                if (row.get("capabilities", {}).get("execution_target") or {}).get("manager_id")
                == self.manager_id]

    def bind(self, *, target: dict, requirements: list[dict], selections: dict,
             test_type: str) -> dict:
        parsed_target = deployment_from_dict(target)
        if parsed_target.manager_id != self.manager_id:
            raise ValueError("submit this target to its owning Manager")
        rows = [row for row in self.directory() if row["deployment_id"] == target_route(target)
                and row["online"]]
        if len(rows) != 1:
            raise ValueError("selected execution deployment is offline or ambiguous")
        capabilities = rows[0]["capabilities"]
        offers = tuple(offer_from_dict(item) for item in capabilities["offers"])
        if not requirements or len(requirements) > 2048:
            raise ValueError("bounded data requirements are required")
        bindings = []
        for raw in requirements:
            requirement = requirement_from_dict(raw)
            source = selections.get(requirement.requirement_ref, selections.get(requirement.product_ref, ""))
            bound = bind_bar_input(requirement, parsed_target, test_type=test_type,
                                   offers=offers, selected_source_ref=source)
            adapter = capabilities["runtime_adapters"].get(bound.offer.source_ref)
            if adapter is None:
                raise ValueError("selected source has no executable adapter")
            bindings.append({**asdict(bound), "source_ref": source, "runtime_adapter": adapter})
        if len({b["requirement"]["product_ref"] for b in bindings}) != len(bindings):
            raise ValueError("duplicate product requirements")
        # Current runner has one source staging request. Reject mixed adapters
        # rather than selecting the first source and executing the wrong tape.
        if len({canonical_hash(b["runtime_adapter"]) for b in bindings}) != 1:
            raise ValueError("this service requires a common Bar adapter for this run")
        return {"target": asdict(parsed_target), "route_id": rows[0]["deployment_id"],
                "service_port": rows[0]["service_port"], "test_type": test_type,
                "inputs": bindings}

    def _record(self, node_id: str, payload: dict) -> JobRecord:
        record = self.repository.require(str(payload["job_id"]))
        if record.attempt != payload.get("attempt"):
            raise PermissionError("stale JobAttempt")
        binding = record.job_spec.get("execution_binding") or {}
        target = binding.get("target") or {}
        if target.get("node_id") != node_id or target.get("manager_id") != self.manager_id:
            raise PermissionError("Job is assigned to another node/Manager")
        if (binding.get("route_id") != record.deployment_id
                or binding.get("service_port") != record.service_port):
            raise PermissionError("Job route differs from frozen execution binding")
        return record

    def operation(self, node_id: str, payload: dict) -> dict:
        record = self._record(node_id, payload)
        action = payload.get("action")
        args = payload.get("args") or {}
        if action == "load":
            return {"record": record_to_wire(record)}
        if action == "claim":
            # Revalidate live deployment/source before claiming or loading data.
            binding = record.job_spec["execution_binding"]
            rebound = self.bind(target=binding["target"],
                                requirements=[item["requirement"] for item in binding["inputs"]],
                                selections={requirement_from_dict(item["requirement"]).requirement_ref:
                                            item["source_ref"] for item in binding["inputs"]},
                                test_type=record.kind)
            for frozen, current in zip(binding["inputs"], rebound["inputs"], strict=True):
                if (frozen["offer"]["installation"] != current["offer"]["installation"]
                        or frozen["runtime_adapter"] != current["runtime_adapter"]):
                    raise ValueError("source installation changed; replan required")
            claimed = self.repository.claim_attempt(record.job_id, record.attempt,
                worker_id=node_id, worker_pid=args.get("worker_pid"))
            return {"record": record_to_wire(claimed)}
        if action == "plan":
            plan = args["plan"]
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            plan["execution_binding"] = record.job_spec["execution_binding"]
            updated = self.repository.set_execution_plan(record.job_id, plan=plan,
                notices=args.get("notices", []), requires_confirmation=bool(args.get("requires_confirmation")))
            return {"record": record_to_wire(updated)}
        if action == "cancel":
            return {"value": self.repository.cancel_requested(record.job_id, record.attempt)}
        if action == "heartbeat":
            return {"value": self.repository.heartbeat_attempt(record.job_id, record.attempt, node_id)}
        if action == "progress":
            return {"value": self.repository.record_progress(record.job_id, record.attempt, **args)}
        if action == "terminal":
            status = JobStatus(args.pop("target"))
            if status not in TERMINAL_STATUSES:
                raise ValueError("only terminal state can be reported")
            allowed = {"result_summary", "error", "cancel_reason"}
            if set(args) - allowed:
                raise ValueError("invalid terminal fields")
            if record.status in TERMINAL_STATUSES:
                if record.status != status or record.result_summary != args.get("result_summary"):
                    raise ValueError("conflicting terminal report")
                return {"record": record_to_wire(record)}
            if record.status is not JobStatus.RUNNING and not (record.status is JobStatus.PLANNING and status is JobStatus.FAILED):
                raise ValueError("Job is not running or planning")
            if self.repository.cancel_requested(record.job_id, record.attempt):
                status = JobStatus.CANCELLED
            updated = self.repository.transition(record.job_id, status,
                expected=record.status, **args)
            report_ref = (updated.result_summary or {}).get("report_ref")
            if report_ref:
                self.repository.set_report_ref(record.job_id, str(report_ref))
            return {"record": record_to_wire(updated)}
        raise ValueError("unsupported node Job operation")

    def report_file(self, node_id: str, payload: dict) -> dict:
        """Bounded Job-result upload; no arbitrary paths or database access."""
        import base64
        import fcntl
        from pathlib import Path
        from server.jobs.artifacts import artifact_root, default_user_quota_bytes
        record = self._record(node_id, payload)
        if record.status is not JobStatus.RUNNING:
            raise ValueError("results require an active JobAttempt")
        if not _SAFE.fullmatch(record.job_id):
            raise ValueError("unsafe Job identity")
        name = payload["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError("invalid result file name")
        size, offset = payload["size"], payload["offset"]
        digest = payload["sha256"]
        if (type(size) is not int or type(offset) is not int or not 0 <= offset <= size <= 64*1024**2
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("invalid result size/hash")
        block = base64.b64decode(payload["data"], validate=True)
        if len(block) > 256*1024 or offset + len(block) > size:
            raise ValueError("result block exceeds budget")
        folder = artifact_root() / record.job_id / f"node-results-{record.attempt}"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ".upload.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            files = tuple(p for p in folder.iterdir() if p.name != ".upload.lock")
            used = sum(p.stat().st_size for p in files)
            quota = self.repository.storage_quota(owner=record.owner, default_bytes=default_user_quota_bytes())
            if (len(files) > 32 or used + len(block) > min(quota, 128*1024**2)
                    or self.repository.storage_usage(owner=record.owner) + used + len(block) > quota):
                raise ValueError("Job result storage budget exceeded")
            path = folder / name
            existing = path.stat().st_size if path.exists() else 0
            if existing != offset:
                if existing >= offset + len(block):
                    with path.open("rb") as current:
                        current.seek(offset)
                        if current.read(len(block)) == block:
                            return {"offset": existing}
                raise ValueError("result upload offset changed")
            with path.open("ab") as handle:
                handle.write(block)
            if path.stat().st_size == size:
                actual = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(1024*1024):
                        actual.update(chunk)
                if actual.hexdigest() != digest:
                    path.unlink()
                    raise ValueError("result hash mismatch")
                # Register only fully verified bytes in the existing artifact authority.
                self.repository.record_artifact(job_id=record.job_id, name=name,
                    relative_path=path.relative_to(artifact_root()).as_posix(),
                    content_type="text/html" if name.endswith(".html") else "application/octet-stream",
                    content_hash=digest, size_bytes=size, retention_mode="retained")
            return {"offset": offset + len(block)}

    def publish_report(self, node_id: str, payload: dict) -> dict:
        from server.jobs.artifacts import artifact_root
        from server.jobs.storage.couchdb_reports import publish_job_report
        record = self._record(node_id, payload)
        if record.status is not JobStatus.RUNNING:
            raise ValueError("report requires an active JobAttempt")
        folder = artifact_root() / record.job_id / f"node-results-{record.attempt}"
        names = payload.get("files")
        if not isinstance(names, list) or not names or len(names) > 32:
            raise ValueError("bounded verified report files required")
        registered = self.repository.list_artifacts(job_id=record.job_id, owner=record.owner)
        expected = {item["name"] for item in registered if item.get("state") == "active"}
        if not set(names).issubset(expected):
            raise ValueError("report contains unverified files")
        ref = publish_job_report(job_id=record.job_id, attempt=record.attempt,
                                 owner=record.owner, reports_dir=str(folder),
                                 metadata={"node_id": node_id, "engine": "nautilus_trader"})
        return {"report_ref": ref}
