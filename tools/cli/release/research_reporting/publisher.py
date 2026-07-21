"""Pure-local publisher for bounded Active Graph checkpoint carriers."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import ntpath
from pathlib import Path
import posixpath
import re
from typing import Any
from urllib.parse import urlsplit

from ..local_profile import LocalProfileStore
from .writer import render_branch_report


MAX_CARRIER_BYTES = 64 * 1024
MAX_ITEMS = 16
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\\\s]{1,511}$")
_SCOPE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_LOCAL_PATH = re.compile(
    r'''(?:^|[\s"'`(\[=:])(?:~[/\\]|[A-Za-z]:[/\\]|/(?!/))'''
)
_CARRIER_FIELDS = {
    "schema_version", "workspace_ref", "work_package_ref", "branch_ref",
    "graph_ref", "checkpoint_ref", "research_cycle_ref", "title",
    "product_group", "current_node", "status", "decision_contract_hash",
    "methodology_hash", "trial_plan_hash", "evidence_refs",
    "omitted_evidence_count", "job_refs", "run_refs", "claims",
    "open_obligations", "closure",
    "latest_transition",
}
_TRANSITION_FIELDS = {
    "step_ref", "edge_ref", "from_node", "to_node", "created_at",
    "evidence_refs", "trial_plan_refs", "obligation_refs", "claim_refs",
    "job_refs", "run_refs", "obligation_changes", "claim_changes",
}
_CLAIM_FIELDS = {"claim_ref", "claim_type", "evidence_state"}
_OBLIGATION_FIELDS = {
    "obligation_ref", "status", "materiality", "question_summary",
}
_OBLIGATION_CHANGE_FIELDS = {"obligation_id", "from_state", "to_state"}
_CLAIM_CHANGE_FIELDS = {"claim_id", "from_state", "to_state"}
_PROHIBITED_KEYS = {
    "api_key", "credential", "credentials", "expression_tree",
    "factor_source", "formula", "password", "raw_stderr", "raw_stdout",
    "secret", "source_code", "token",
}


def publish_research_checkpoint(
    *,
    client_root: Path,
    profile_id: str,
    agent_id: str,
    carrier: dict[str, Any],
) -> dict[str, Any]:
    """Materialize one checkpoint and update its existing local record."""
    value = _canonical_carrier(carrier)
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    agent = _find_agent(profile, agent_id)
    if agent["role"] != "research":
        raise ValueError("checkpoint publisher requires a research Agent")

    workspace_id = _ref_id(value["workspace_ref"], "workspace")
    work_package_id = _ref_id(value["work_package_ref"], "work-package")
    branch_parts = value["branch_ref"].split(":")
    if (
        len(branch_parts) != 3
        or branch_parts[0] != "graph-branch"
        or branch_parts[1] != work_package_id
    ):
        raise ValueError("branch_ref does not belong to the Work Package")
    branch_id = _safe_id(branch_parts[2], "branch_id")
    if value["checkpoint_ref"] != value["latest_transition"]["step_ref"]:
        raise ValueError("checkpoint_ref must equal latest transition step_ref")

    if agent["scope"] != {
        "instance_id": work_package_id,
        "branch_id": branch_id,
    }:
        raise ValueError("research Agent scope does not match checkpoint branch")
    record = _find_record(
        profile,
        work_package_ref=value["work_package_ref"],
        branch_ref=value["branch_ref"],
        agent_id=agent_id,
    )
    if not record["scope"] or not record["factor_family_versions"]:
        raise ValueError("research record lacks scope or factor-family identity")
    scope_identity = _scope_identity(record["scope"])
    if record["workspace_ref"] != value["workspace_ref"]:
        raise ValueError("checkpoint workspace does not match research record")
    if record["graph_instance_ref"] != value["work_package_ref"]:
        raise ValueError("checkpoint Work Package does not match research record")
    if record["graph_branch_ref"] != value["branch_ref"]:
        raise ValueError("checkpoint branch does not match research record")
    if not any(
        item["workspace_id"] == workspace_id
        and item["server_workspace_ref"] == value["workspace_ref"]
        for item in profile["workspaces"]
    ):
        raise ValueError("checkpoint workspace is not registered in the profile")
    previous_checkpoint = str(record["checkpoint_ref"] or "")
    previous_timestamp = float(record["updated_at"] or 0)
    incoming_timestamp = value["latest_transition"]["created_at"]
    if previous_checkpoint:
        if incoming_timestamp < previous_timestamp:
            raise ValueError("checkpoint is older than the local research record")
        if incoming_timestamp == previous_timestamp and (
            value["checkpoint_ref"] != previous_checkpoint
        ):
            raise ValueError("checkpoint timestamp conflicts with local record")
        if value["checkpoint_ref"] == previous_checkpoint and (
            incoming_timestamp != previous_timestamp
        ):
            raise ValueError("checkpoint identity has a conflicting timestamp")
        if value["checkpoint_ref"] == previous_checkpoint:
            existing_artifact = _existing_branch_artifact(
                record,
                work_package_id=work_package_id,
                branch_id=branch_id,
                checkpoint_ref=value["checkpoint_ref"],
            )
            if existing_artifact is not None:
                return {
                    "changed": False,
                    "report_changed": False,
                    "profile_changed": False,
                    "checkpoint_ref": value["checkpoint_ref"],
                    "artifact": existing_artifact,
                }

    snapshot = _report_snapshot(
        value,
        workspace_id=workspace_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        factor_family_versions=record["factor_family_versions"],
        scope_identity=scope_identity,
    )
    report = render_branch_report(
        snapshot,
        workspace_root=Path(profile["workspace_root"]),
    )
    descriptor = deepcopy(report["local_artifact_descriptor"])
    descriptor["section_refs"] = [
        item for item in descriptor["section_refs"]
        if item["section_ref"].startswith(
            f"report-section:{branch_id}:"
        )
    ]
    updated = deepcopy(record)
    updated.update({
        "title": value["title"],
        "status": "ready",
        "updated_at": value["latest_transition"]["created_at"],
        "checkpoint_ref": value["checkpoint_ref"],
        "run_ref": (
            value["run_refs"][0] if value["run_refs"] else record["run_ref"]
        ),
        "evidence_refs": snapshot["evidence_refs"],
        "timeline_refs": descriptor["section_refs"],
    })
    updated["artifacts"] = [
        item for item in record["artifacts"]
        if item["artifact_ref"] != descriptor["artifact_ref"]
    ] + [descriptor]
    saved = store.upsert_research_record(profile_id, updated)
    profile_changed = saved != profile
    return {
        "changed": bool(report["changed"] or profile_changed),
        "report_changed": bool(report["changed"]),
        "profile_changed": profile_changed,
        "checkpoint_ref": value["checkpoint_ref"],
        "artifact": descriptor,
    }


def _canonical_carrier(carrier: Any) -> dict[str, Any]:
    if not isinstance(carrier, dict) or set(carrier) != _CARRIER_FIELDS:
        raise ValueError("checkpoint carrier fields are invalid")
    _reject_prohibited(carrier)
    encoded = json.dumps(
        carrier, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_CARRIER_BYTES:
        raise ValueError(f"checkpoint carrier exceeds {MAX_CARRIER_BYTES} bytes")
    value = deepcopy(carrier)
    if value["schema_version"] != 1:
        raise ValueError("checkpoint carrier schema_version must be 1")
    for field in (
        "workspace_ref", "work_package_ref", "branch_ref", "checkpoint_ref",
        "research_cycle_ref",
    ):
        _reference(value[field], field)
    for field in ("title", "product_group", "current_node", "status", "graph_ref"):
        _text(value[field], field)
    for field in (
        "decision_contract_hash", "methodology_hash",
    ):
        if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
            raise ValueError(f"{field} must be lowercase sha256")
    trial_plan_hash = value["trial_plan_hash"]
    if (
        not isinstance(trial_plan_hash, str)
        or (trial_plan_hash and not _SHA256.fullmatch(trial_plan_hash))
    ):
        raise ValueError("trial_plan_hash must be empty or lowercase sha256")
    cycle_prefix = "research-cycle:sha256:"
    if (
        not value["research_cycle_ref"].startswith(cycle_prefix)
        or not _SHA256.fullmatch(value["research_cycle_ref"][len(cycle_prefix):])
    ):
        raise ValueError("research_cycle_ref must identify a complete projection")
    omitted_count = value["omitted_evidence_count"]
    if (
        type(omitted_count) is not int
        or omitted_count < 0
        or omitted_count > 2_147_483_647
    ):
        raise ValueError("omitted_evidence_count must be a non-negative integer")
    for field in ("evidence_refs", "job_refs", "run_refs"):
        value[field] = _references(value[field], field)
    value["claims"] = _objects(value["claims"], _CLAIM_FIELDS, "claims")
    for item in value["claims"]:
        _reference(item["claim_ref"], "claim_ref")
        _text(item["claim_type"], "claim_type")
        _text(item["evidence_state"], "evidence_state")
    value["open_obligations"] = _objects(
        value["open_obligations"], _OBLIGATION_FIELDS, "open_obligations",
    )
    for item in value["open_obligations"]:
        _reference(item["obligation_ref"], "obligation_ref")
        for field in ("status", "materiality", "question_summary"):
            _text(item[field], field, maximum=1000)
    if value["closure"] is not None:
        closure = value["closure"]
        if not isinstance(closure, dict) or set(closure) != {
            "proposal_ref", "disposition",
        }:
            raise ValueError("closure fields are invalid")
        _reference(closure["proposal_ref"], "closure.proposal_ref")
        _text(closure["disposition"], "closure.disposition")
    transition = value["latest_transition"]
    if not isinstance(transition, dict) or set(transition) != _TRANSITION_FIELDS:
        raise ValueError("latest_transition fields are invalid")
    for field in ("step_ref", "edge_ref"):
        _reference(transition[field], field)
    for field in ("from_node", "to_node"):
        _text(transition[field], field)
    timestamp = transition["created_at"]
    if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
        raise ValueError("latest_transition.created_at must be finite")
    transition["created_at"] = float(timestamp)
    for field in (
        "evidence_refs", "trial_plan_refs", "obligation_refs", "claim_refs",
        "job_refs", "run_refs",
    ):
        transition[field] = _references(transition[field], field)
    for field, item_fields, identifier_field in (
        ("obligation_changes", _OBLIGATION_CHANGE_FIELDS, "obligation_id"),
        ("claim_changes", _CLAIM_CHANGE_FIELDS, "claim_id"),
    ):
        transition[field] = _objects(
            transition[field], item_fields, field,
        )
        for item in transition[field]:
            _safe_id(item[identifier_field], identifier_field)
            _text(item["from_state"], "from_state")
            _text(item["to_state"], "to_state")
    return value


def _report_snapshot(
    carrier: dict[str, Any], *, workspace_id: str, work_package_id: str,
    branch_id: str, factor_family_versions: list[str],
    scope_identity: dict[str, Any],
) -> dict[str, Any]:
    transition = carrier["latest_transition"]
    checkpoint_refs = _unique([
        scope_identity["scope_ref"],
        carrier["research_cycle_ref"], carrier["checkpoint_ref"],
        *carrier["evidence_refs"], *carrier["job_refs"], *carrier["run_refs"],
        *transition["evidence_refs"], *transition["job_refs"],
        *transition["run_refs"],
    ])
    checkpoint_key = hashlib.sha256(
        carrier["checkpoint_ref"].encode("utf-8")
    ).hexdigest()[:16]
    state_links = _links([
        ("evidence", carrier["checkpoint_ref"]),
        ("evidence", carrier["research_cycle_ref"]),
        ("evidence", transition["edge_ref"]),
        *(("trial_plan", ref) for ref in transition["trial_plan_refs"]),
        *(("evidence", item["claim_ref"]) for item in carrier["claims"]),
        *(("obligation", item["obligation_ref"])
          for item in carrier["open_obligations"]),
        *(("obligation", ref) for ref in transition["obligation_refs"]),
        *(("evidence", ref) for ref in transition["claim_refs"]),
    ], "state")
    claims = carrier["claims"]
    obligations = carrier["open_obligations"]
    body = [
        f"Product group: {carrier['product_group']}",
        f"Current node: {carrier['current_node']}",
        f"Transition: {transition['from_node']} -> {transition['to_node']}",
        "Scope fields: "
        + ", ".join(f"`{item}`" for item in scope_identity["fields"]),
        f"Canonical scope hash: `{scope_identity['scope_hash']}`",
    ]
    if claims:
        body.extend([
            "Claims:",
            *(f"- {item['claim_type']}: {item['evidence_state']}"
              for item in claims),
        ])
    if obligations:
        body.extend([
            "Open obligations:",
            *(f"- {item['question_summary']} [{item['materiality']}]"
              for item in obligations),
        ])
    if transition["obligation_changes"]:
        body.extend([
            "Obligation changes:",
            *(
                f"- {item['obligation_id']}: "
                f"{item.get('from_state', '')} -> {item.get('to_state', '')}"
                for item in transition["obligation_changes"]
            ),
        ])
    if transition["claim_changes"]:
        body.extend([
            "Claim evidence changes:",
            *(
                f"- {item['claim_id']}: "
                f"{item.get('from_state', '')} -> {item.get('to_state', '')}"
                for item in transition["claim_changes"]
            ),
        ])
    if carrier["closure"] is not None:
        body.append(
            "Closure: "
            + json.dumps(
                carrier["closure"], ensure_ascii=False, sort_keys=True,
            )
        )
    sections = [{
        "section_id": f"checkpoint-{checkpoint_key}",
        "title": f"Checkpoint {carrier['checkpoint_ref']}",
        "body": "\n\n".join(body),
        "evidence_refs": checkpoint_refs,
        "asset_refs": [],
        "links": state_links,
        "created_at": transition["created_at"],
    }]
    return {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "work_package_id": work_package_id,
        "branch_id": branch_id,
        "title": carrier["title"],
        "status": carrier["status"],
        "graph_ref": carrier["graph_ref"],
        "methodology_hash": carrier["methodology_hash"],
        "decision_contract_hash": carrier["decision_contract_hash"],
        "trial_plan_hash": carrier["trial_plan_hash"],
        "factor_family_versions": list(factor_family_versions),
        "evidence_refs": checkpoint_refs,
        "sections": sections,
        "assets": [],
        "gaps": ([{
            "gap_ref": "report-gap:omitted-evidence",
            "reason": (
                f"{carrier['omitted_evidence_count']} evidence reference(s) "
                "were omitted from this bounded checkpoint carrier."
            ),
        }] if carrier["omitted_evidence_count"] else []),
    }


def _find_agent(profile: dict[str, Any], agent_id: str) -> dict[str, Any]:
    for item in profile["agents"]:
        if item["agent_id"] == agent_id:
            return item
    raise ValueError(f"local Agent not found: {agent_id}")


def _find_record(
    profile: dict[str, Any],
    *,
    work_package_ref: str,
    branch_ref: str,
    agent_id: str,
) -> dict[str, Any]:
    matches = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == work_package_ref
        and item["graph_branch_ref"] == branch_ref
        and item["agent_id"] == agent_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "checkpoint requires exactly one matching local research record"
        )
    return matches[0]


def _existing_branch_artifact(
    record: dict[str, Any],
    *,
    work_package_id: str,
    branch_id: str,
    checkpoint_ref: str,
) -> dict[str, Any] | None:
    if not any(
        item.get("target_ref") == checkpoint_ref
        for item in record["timeline_refs"]
    ):
        return None
    expected_ref = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT.md"
    )
    matches = [
        item for item in record["artifacts"]
        if item.get("artifact_ref") == expected_ref
    ]
    return deepcopy(matches[0]) if len(matches) == 1 else None


def _objects(value: Any, fields: set[str], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"{label} must be a bounded array")
    if any(not isinstance(item, dict) or set(item) != fields for item in value):
        raise ValueError(f"{label} item fields are invalid")
    return value


def _references(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"{field} must be a bounded reference array")
    for item in value:
        _reference(item, field)
    return list(value)


def _reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ValueError(f"{field} must be a stable reference")
    parsed = urlsplit(value)
    network_reference = parsed.scheme.lower() in {"http", "https"}
    logical_absolute_path = (
        not parsed.netloc
        and (
            parsed.path.startswith(("/", "~"))
            or ntpath.isabs(parsed.path)
            or bool(ntpath.splitdrive(parsed.path)[0])
        )
    )
    if (
        parsed.scheme.lower() == "file"
        or (bool(parsed.netloc) and not network_reference)
        or (network_reference and not parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or logical_absolute_path
        or posixpath.isabs(value)
        or ntpath.isabs(value)
        or "\\" in value
        or re.search(r"(?:^|/)\.\.?($|/)", parsed.path)
    ):
        raise ValueError(f"{field} must be a stable reference")
    return value


def _ref_id(value: str, scheme: str) -> str:
    prefix = scheme + ":"
    if not value.startswith(prefix):
        raise ValueError(f"reference must use {scheme}: scheme")
    return _safe_id(value[len(prefix):], scheme)


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _text(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError(f"{field} must be bounded text")
    return value


def _scope_identity(scope: Any) -> dict[str, Any]:
    """Return a non-reversible audit identity for one bounded local scope."""
    canonical = _canonical_scope_value(scope, depth=0)
    if not isinstance(canonical, dict) or not canonical:
        raise ValueError("research scope must be a non-empty object")
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > 8 * 1024:
        raise ValueError("research scope exceeds 8192 bytes")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "fields": sorted(canonical),
        "scope_hash": digest,
        "scope_ref": f"scope:sha256:{digest}",
    }


def _canonical_scope_value(value: Any, *, depth: int) -> Any:
    if depth > 4:
        raise ValueError("research scope nesting is too deep")
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValueError("research scope object is too large")
        result = {}
        for key in sorted(value):
            if not isinstance(key, str) or not _SCOPE_KEY.fullmatch(key):
                raise ValueError("research scope key is invalid")
            if key.lower() in _PROHIBITED_KEYS:
                raise ValueError(f"prohibited research scope field: {key}")
            result[key] = _canonical_scope_value(value[key], depth=depth + 1)
        return result
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("research scope array is too large")
        return [
            _canonical_scope_value(item, depth=depth + 1) for item in value
        ]
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("research scope number must be finite")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 256 or _LOCAL_PATH.search(value):
            raise ValueError("research scope text is unsafe or too large")
        return value
    raise ValueError("research scope value type is unsupported")


def _reject_prohibited(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in _PROHIBITED_KEYS:
                raise ValueError(f"prohibited checkpoint field: {key}")
            _reject_prohibited(nested)
    elif isinstance(value, list):
        for item in value:
            _reject_prohibited(item)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))[:64]


def _links(values: list[tuple[str, str]], prefix: str) -> list[dict[str, str]]:
    return [
        {"link_id": f"{prefix}-{index}", "kind": kind, "target_ref": ref}
        for index, (kind, ref) in enumerate(values[:50])
    ]
