"""Thin OIDC HTTP adapter to the owning Manager's existing Job authority."""
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
from server.identity.service_access import ServiceHTTPClient, configured_client


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
    def __init__(self, client: ServiceHTTPClient, descriptor: dict):
        self.client, self.descriptor = client, descriptor
        self.attempts = {}
        self.input_manifests = {}

    def register(self):
        return self.client.post_json("/api/federation/execution/register", {key: value for key, value in self.descriptor.items() if key in {"target", "service_port", "offers", "runtime_adapters", "market_endpoint"}})

    def _rpc(self, action, job_id, attempt=None, **args):
        attempt = attempt or self.attempts.get(job_id)
        if attempt is None:
            raise ValueError("attempt must be bound before remote Job access")
        return self.client.post_json("/api/federation/execution/job", {
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
        if isinstance(kwargs.get("result_summary"), dict):
            kwargs["result_summary"] = {key: value for key, value in kwargs["result_summary"].items() if key != "reports_dir"}
        return record_from_wire(self._rpc("terminal", job_id, target=JobStatus(target).value, **kwargs)["record"])

    def set_execution_plan(self, job_id, **kwargs):
        catalogs = self.descriptor.get("catalog_inputs")
        if catalogs:
            record = self.load(job_id)
            required = {item["product_ref"] for item in record.job_spec["run_spec"]["data_requirements"]}
            if not required.issubset(catalogs):
                raise ValueError("node-local catalog installation lacks requested products")
            kwargs["plan"]["catalog_inputs"] = {key: catalogs[key] for key in sorted(required)}
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
                result = self.client.post_json("/api/federation/execution/result-file", {
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
        value = self.client.post_json("/api/federation/execution/report", {
            "job_id": job_id, "attempt": self.attempts[job_id], "files": files})
        return value.get("report_ref")

    def list_artifacts(self, *, job_id, owner):
        return self.input_manifests.get(job_id, [])

    def source_context(self, record):
        from contextlib import contextmanager
        @contextmanager
        def scope():
            from server.jobs.artifacts import artifact_root
            from server.jobs.input_artifacts import load_retained_factor_sources
            from server.services.factor_registry import transient_factor_source_scope
            metadata = self._rpc("input_manifest", record.job_id)["files"]
            if sum(item["size_bytes"] for item in metadata) > 128*1024**2:
                raise ValueError("retained Job inputs exceed node transfer budget")
            folder = artifact_root() / record.job_id / f"inputs-{record.attempt}"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                local = []
                for item in metadata:
                    digest = item["content_hash"]
                    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                        raise ValueError("invalid retained input hash")
                    path = folder / digest
                    actual = hashlib.sha256()
                    with path.open("wb") as handle:
                        offset = 0
                        while offset < item["size_bytes"]:
                            block = base64.b64decode(self._rpc("input_block", record.job_id, name=item["name"], offset=offset)["data"], validate=True)
                            if not block or len(block) > min(256*1024, item["size_bytes"]-offset):
                                raise ValueError("invalid retained input block")
                            handle.write(block); actual.update(block); offset += len(block)
                    if actual.hexdigest() != digest:
                        path.unlink(); raise ValueError("retained input hash mismatch")
                    local.append({**item, "relative_path": path.relative_to(artifact_root()).as_posix()})
                self.input_manifests[record.job_id] = local
                policy = record.job_spec.get("run_spec", {}).get("factor_source_policy", {})
                entries = load_retained_factor_sources(self, job_id=record.job_id, owner=record.owner,
                                                       manifest=policy.get("files", []))
                overrides = {item["factor_id"]: item["source_code"] for item in entries if not item.get("canonical_family_ref")}
                portable = {item["canonical_family_ref"]: item for item in entries if item.get("canonical_family_ref")}
                with transient_factor_source_scope(owner=record.owner, overrides=overrides, portable_overrides=portable):
                    yield
            finally:
                # Retained bytes remain authoritative on Manager; node copies
                # are per-attempt staging, not another synchronized library.
                import shutil
                self.input_manifests.pop(record.job_id, None)
                shutil.rmtree(folder)
        return scope()

    def validate_local_binding(self, record):
        """Use the current local manifest, never a same-name global fallback."""
        from server.jobs.assurance import canonical_hash
        binding = record.job_spec.get("execution_binding") or {}
        descriptor_file = os.environ.get("TR_NODE_DESCRIPTOR_FILE")
        current = load_node_descriptor(Path(descriptor_file), manager_id=self.descriptor["target"]["manager_id"]) if descriptor_file else self.descriptor
        target = current["target"]
        if target != binding.get("target"):
            raise ValueError("worker deployment differs from frozen target")
        from traderesearch_data.execution import bind_bar_input, deployment_from_dict, offer_from_dict, requirement_from_dict
        offers = tuple(offer_from_dict(x) for x in current["offers"])
        from sources.registry import installed_bundles
        from traderesearch_data.bundles import bundle_content_fingerprint
        installed = {bundle.bundle_id: bundle for bundle in installed_bundles()}
        from server.services.nautilus_bridge.source_registry import from_server_sources
        registry = from_server_sources()
        for item in binding["inputs"]:
            runtime = current.get("runtime_adapters", {}).get(item["source_ref"], {})
            adapter = registry.adapter_for(source_key=runtime.get("member_key"),
                frequency=runtime.get("frequency"), instrument_scope=runtime.get("instrument_scope"))
            if runtime != {key: getattr(adapter, key) for key in runtime}:
                raise ValueError("registered runtime adapter differs from installed source")
            if runtime != item.get("runtime_adapter"):
                raise ValueError("runtime adapter changed since planning")
            settings = record.job_spec["run_spec"]["configuration"]["analyses"][record.kind]["execution"]["nautilus_contract"]["settings"]
            if any((venue.get("native_config") or {}).get("book_type", venue.get("book_type", "L1_MBP")) not in adapter.supported_book_types for venue in settings.get("venues", [])):
                raise ValueError("Venue book type is not supported by installed source adapter")
            frozen = offer_from_dict(item["offer"]).installation
            bundle = installed.get(frozen.bundle_id)
            if (bundle is None or bundle.version != frozen.bundle_version
                    or bundle_content_fingerprint(bundle) != frozen.bundle_fingerprint):
                raise ValueError("local installed Bundle code differs from frozen installation")
            bound = bind_bar_input(requirement_from_dict(item["requirement"]), deployment_from_dict(target),
                test_type=record.kind, offers=offers, selected_source_ref=item["source_ref"])
            if canonical_hash(bound.offer.installation) != canonical_hash(offer_from_dict(item["offer"]).installation):
                raise ValueError("local Bundle installation changed")


def load_node_descriptor(path, *, manager_id=""):
    value = json.loads(Path(path).read_text())
    registrations = value.get("registrations") if isinstance(value, dict) else None
    if registrations is None:
        return value
    matches = [item for item in registrations if item["target"]["manager_id"] == manager_id]
    if len(matches) != 1:
        raise ValueError("select exactly one Manager registration with TR_MANAGER_ID")
    return matches[0]


def remote_repository_from_env():
    endpoint = os.environ.get("TR_MANAGER_ENDPOINT", "").strip()
    if not endpoint:
        return None
    node_id = os.environ["TR_EXECUTION_NODE_ID"]
    descriptor = load_node_descriptor(Path(os.environ["TR_NODE_DESCRIPTOR_FILE"]), manager_id=os.environ.get("TR_MANAGER_ID", ""))
    client = ServiceHTTPClient(endpoint, oidc=configured_client(), response_limit=16*1024**2)
    if descriptor["target"]["node_id"] != node_id:
        raise ValueError("node identity differs from its selected descriptor")
    return RemoteJobRepository(client, descriptor)
