"""Thin signed-HTTP adapter to the owning Manager's existing Job authority."""
from __future__ import annotations

from dataclasses import fields
import base64
import hashlib
import json
import os
from pathlib import Path

from server.jobs.models import JobRecord, SchedulingEntitlement
from server.jobs.assurance import TerminalAssuranceSummary
from server.jobs.states import JobStatus
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey


def record_from_wire(raw):
    if raw is None:
        return None
    value = dict(raw)
    value["status"] = JobStatus(value["status"])
    value["entitlement"] = SchedulingEntitlement.from_dict(value.get("entitlement"))
    value["terminal_assurance"] = TerminalAssuranceSummary.from_dict(value.get("terminal_assurance"))
    return JobRecord(**value)


class RemoteJobRepository:
    """No local SQLite replica; all low-frequency mutations use the Manager."""
    def __init__(self, client: NodeControlClient, descriptor: dict):
        self.client, self.descriptor = client, descriptor
        self.attempts = {}

    def register(self):
        return self.client.signed_json("/api/federation/execution/register", self.descriptor)

    def _rpc(self, action, job_id, attempt=None, **args):
        attempt = attempt or self.attempts.get(job_id)
        if attempt is None:
            raise ValueError("attempt must be bound before remote Job access")
        return self.client.signed_json("/api/federation/execution/job", {
            "action": action, "job_id": job_id, "attempt": attempt, "args": args})

    def load(self, job_id, **_):
        return record_from_wire(self._rpc("load", job_id)["record"])

    def claim_attempt(self, job_id, attempt, *, worker_pid=None, worker_id=""):
        self.attempts[job_id] = attempt
        return record_from_wire(self._rpc("claim", job_id, attempt, worker_pid=worker_pid)["record"])

    def heartbeat_attempt(self, job_id, attempt, worker_id, **_):
        return self._rpc("heartbeat", job_id, attempt)["value"]

    def cancel_requested(self, job_id, attempt):
        return self._rpc("cancel", job_id, attempt)["value"]

    def record_progress(self, job_id, attempt, **kwargs):
        return self._rpc("progress", job_id, attempt, **kwargs)["value"]

    def transition(self, job_id, target, *, expected=None, **kwargs):
        return record_from_wire(self._rpc("terminal", job_id, target=JobStatus(target).value, **kwargs)["record"])

    def set_execution_plan(self, job_id, **kwargs):
        return record_from_wire(self._rpc("plan", job_id, **kwargs)["record"])

    def set_report_ref(self, job_id, report_ref):
        # terminal mutation already records its verified report reference.
        pass

    def record_artifact(self, **metadata):
        from server.jobs.artifacts import artifact_root
        path = (artifact_root() / metadata["relative_path"]).resolve(strict=True)
        if not path.is_relative_to(artifact_root()):
            raise ValueError("artifact escapes node output root")
        self._upload(metadata["job_id"], path, metadata["name"])

    def _upload(self, job_id, path, name):
        size = path.stat().st_size
        if size > 64*1024**2:
            raise ValueError("result file exceeds remote transfer budget")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024*1024):
                digest.update(block)
        with path.open("rb") as handle:
            offset = 0
            while True:
                block = handle.read(256*1024)
                result = self.client.signed_json("/api/federation/execution/result-file", {
                    "job_id": job_id, "attempt": self.attempts[job_id], "name": name,
                    "size": size, "offset": offset, "sha256": digest.hexdigest(),
                    "data": base64.b64encode(block).decode("ascii")})
                offset = result["offset"]
                if offset >= size:
                    break
                handle.seek(offset)

    def publish_report(self, *, job_id, reports_dir, **_):
        files = []
        for path in sorted(Path(reports_dir).iterdir()):
            if path.is_file() and not path.name.startswith("."):
                self._upload(job_id, path, path.name)
                files.append(path.name)
        value = self.client.signed_json("/api/federation/execution/report", {
            "job_id": job_id, "attempt": self.attempts[job_id], "files": files})
        return value.get("report_ref")

    def validate_local_binding(self, record):
        """Use the current local manifest, never a same-name global fallback."""
        from server.jobs.assurance import canonical_hash
        binding = record.job_spec.get("execution_binding") or {}
        descriptor_file = os.environ.get("TR_NODE_DESCRIPTOR_FILE")
        current = json.loads(Path(descriptor_file).read_text()) if descriptor_file else self.descriptor
        target = current["target"]
        if target != binding.get("target"):
            raise ValueError("worker deployment differs from frozen target")
        from traderesearch_data.execution import bind_bar_input, deployment_from_dict, offer_from_dict, requirement_from_dict
        offers = tuple(offer_from_dict(x) for x in current["offers"])
        for item in binding["inputs"]:
            bound = bind_bar_input(requirement_from_dict(item["requirement"]), deployment_from_dict(target),
                test_type=record.kind, offers=offers, selected_source_ref=item["source_ref"])
            if canonical_hash(bound.offer.installation) != canonical_hash(offer_from_dict(item["offer"]).installation):
                raise ValueError("local Bundle installation changed")


def remote_repository_from_env():
    endpoint = os.environ.get("TR_MANAGER_ENDPOINT", "").strip()
    if not endpoint:
        return None
    node_id = os.environ["TR_EXECUTION_NODE_ID"]
    key = NodeKey.load_or_create(os.environ["TR_NODE_KEY_FILE"], node_id=node_id)
    descriptor = json.loads(Path(os.environ["TR_NODE_DESCRIPTOR_FILE"]).read_text())
    client = NodeControlClient(endpoint, key=key)
    return RemoteJobRepository(client, descriptor)
