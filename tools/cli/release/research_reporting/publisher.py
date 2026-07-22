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
from .journal import build_fragment, content_hash
from .writer import render_branch_report


MAX_CARRIER_BYTES = 64 * 1024
MAX_NARRATIVE_BYTES = 64 * 1024
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
    "open_obligations", "closure", "report_lineage",
    "latest_transition",
}
_TRANSITION_FIELDS = {
    "step_ref", "edge_ref", "from_node", "to_node", "created_at",
    "evidence_refs", "trial_plan_refs", "obligation_refs", "claim_refs",
    "job_refs", "run_refs", "obligation_changes", "claim_changes",
    "delta_refs",
}
_TRANSITION_OPTIONAL_FIELDS = {"delta_refs"}
_CLAIM_FIELDS = {"claim_ref", "claim_type", "evidence_state"}
_OBLIGATION_FIELDS = {
    "obligation_ref", "status", "materiality", "question_summary",
}
_OBLIGATION_CHANGE_FIELDS = {"obligation_id", "from_state", "to_state"}
_CLAIM_CHANGE_FIELDS = {"claim_id", "from_state", "to_state"}
_NARRATIVE_FIELDS = {"schema_version", "language", "title", "sections"}
_NARRATIVE_SECTION_FIELDS_V1 = {"section_id", "title", "body", "links"}
_NARRATIVE_SECTION_FIELDS_V2 = {"section_id", "title", "blocks", "links"}
_NARRATIVE_SECTION_FIELDS_V2_WITH_BODY = {
    "section_id", "title", "body", "blocks", "links",
}
_NARRATIVE_LINK_FIELDS = {"link_id", "kind", "target_ref"}
_NARRATIVE_LINK_FIELDS_WITH_LABEL = {
    "link_id", "kind", "target_ref", "label",
}
_CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LINK_KINDS = {
    "checkpoint", "trial_plan", "obligation", "claim", "evidence",
    "job", "run", "delta", "profile_handoff", "report_section",
}
_RESULT_NODES = {
    "job_evidence_ready", "statistical_robustness", "result_audit",
    "ic", "factor_evaluation", "backtest", "robustness",
}
_RESULT_KINDS = {"ic", "factor_evaluation", "backtest", "robustness"}
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
    narrative: dict[str, Any],
) -> dict[str, Any]:
    """Materialize one checkpoint and update its existing local record."""
    value = _canonical_carrier(carrier)
    narrative_value = _canonical_narrative(narrative, value)
    carrier_hash = content_hash(value)
    narrative_hash = content_hash(narrative_value)
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
    ):
        raise ValueError("branch_ref must identify a physical Graph branch")
    branch_instance_id = _safe_id(
        branch_parts[1], "branch_instance_id"
    )
    branch_id = _safe_id(branch_parts[2], "branch_id")
    if value["checkpoint_ref"] != value["latest_transition"]["step_ref"]:
        raise ValueError("checkpoint_ref must equal latest transition step_ref")

    if agent["scope"] != {
        "instance_id": branch_instance_id,
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
    snapshot = _report_snapshot(
        value,
        narrative=narrative_value,
        workspace_id=workspace_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        factor_family_versions=record["factor_family_versions"],
        scope_identity=scope_identity,
    )
    fragment = build_fragment(
        checkpoint_ref=value["checkpoint_ref"],
        created_at=value["latest_transition"]["created_at"],
        carrier_hash=carrier_hash,
        narrative_hash=narrative_hash,
        sections=snapshot["sections"],
        evidence_refs=snapshot["evidence_refs"],
        gaps=snapshot["gaps"],
        lineage=value["report_lineage"],
        graph_ref=value["graph_ref"],
        branch_ref=value["branch_ref"],
        edge_ref=value["latest_transition"]["edge_ref"],
    )
    journal_replaced_branch_id = (
        _journal_source_branch_id(
            value["report_lineage"], branch_id=branch_id,
        )
        if _is_graph_continuation(value["latest_transition"])
        else None
    )
    report = render_branch_report(
        snapshot,
        workspace_root=Path(profile["workspace_root"]),
        journal_fragment=fragment,
        journal_replaced_branch_id=journal_replaced_branch_id,
    )
    if (
        previous_checkpoint == value["checkpoint_ref"]
        and not report["journal_fragment_changed"]
    ):
        existing_artifact = _existing_branch_artifact(
            record,
            work_package_id=work_package_id,
            branch_id=branch_id,
            checkpoint_ref=value["checkpoint_ref"],
        )
        if existing_artifact is not None:
            return {
                "changed": bool(report["changed"]),
                "report_changed": bool(report["changed"]),
                "profile_changed": False,
                "checkpoint_ref": value["checkpoint_ref"],
                "artifact": existing_artifact,
                "carrier_hash": carrier_hash,
                "narrative_hash": narrative_hash,
                "section_hash": fragment["section_hash"],
            }
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
        "carrier_hash": carrier_hash,
        "narrative_hash": narrative_hash,
        "section_hash": fragment["section_hash"],
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
    if value["schema_version"] != 2:
        raise ValueError("checkpoint carrier schema_version must be 2")
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
    lineage = value["report_lineage"]
    if not isinstance(lineage, dict) or set(lineage) not in ({
        "status", "predecessor_checkpoint_ref",
    }, {
        "status", "predecessor_checkpoint_ref", "source_branch_ref",
    }):
        raise ValueError("report_lineage fields are invalid")
    lineage_status = lineage["status"]
    predecessor = lineage["predecessor_checkpoint_ref"]
    if lineage_status == "history_incomplete":
        raise ValueError(
            "research history is incomplete; restart from a trusted root"
        )
    if lineage_status == "root":
        if predecessor != "":
            raise ValueError("root report lineage cannot have a predecessor")
    elif lineage_status == "linked":
        _reference(predecessor, "report_lineage.predecessor_checkpoint_ref")
        if not predecessor.startswith("trace:"):
            raise ValueError("report lineage predecessor must be a trace ref")
        if "source_branch_ref" in lineage:
            _reference(lineage["source_branch_ref"], "report_lineage.source_branch_ref")
            if not lineage["source_branch_ref"].startswith("graph-branch:"):
                raise ValueError(
                    "report lineage source must be a graph branch ref"
                )
    else:
        raise ValueError("report_lineage status is invalid")
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
    if not isinstance(transition, dict):
        raise ValueError("latest_transition fields are invalid")
    transition_fields = set(transition)
    if not (
        transition_fields == _TRANSITION_FIELDS
        or transition_fields == _TRANSITION_FIELDS - _TRANSITION_OPTIONAL_FIELDS
    ):
        raise ValueError("latest_transition fields are invalid")
    transition.setdefault("delta_refs", [])
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
        "job_refs", "run_refs", "delta_refs",
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
    carrier: dict[str, Any], *, narrative: dict[str, Any],
    workspace_id: str, work_package_id: str,
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
    sections = []
    for section in narrative["sections"]:
        links = list(section["links"])
        links.append({
            "link_id": f"checkpoint-{checkpoint_key}",
            "kind": "checkpoint",
            "target_ref": carrier["checkpoint_ref"],
        })
        projected = {
            "section_id": f"{checkpoint_key}-{section['section_id']}",
            "title": section["title"],
            "evidence_refs": [
                item["target_ref"] for item in links
                if item["kind"] == "evidence"
            ],
            "asset_refs": [],
            "links": links,
            "created_at": transition["created_at"],
        }
        if narrative["schema_version"] == 2:
            # A v2 section may combine a short connective narrative with
            # structured blocks.  Preserve that prose instead of silently
            # dropping it while projecting the carrier into the journal.
            projected["body"] = section.get("body", "")
            projected["blocks"] = deepcopy(section["blocks"])
        else:
            projected["body"] = section["body"]
        sections.append(projected)
    return {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "work_package_id": work_package_id,
        "branch_id": branch_id,
        "title": narrative["title"],
        "status": carrier["status"],
        "product_group": carrier["product_group"],
        "current_node": carrier["current_node"],
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
                "受 checkpoint 载荷上限约束，有 "
                f"{carrier['omitted_evidence_count']} 条证据引用未随本次载荷提供。"
            ),
        }] if carrier["omitted_evidence_count"] else []),
    }


def _journal_source_branch_id(
    lineage: dict[str, Any], *, branch_id: str,
) -> str | None:
    """Return the physical source branch named by a lineage edge.

    This identity is used only to retire the old current entry in the logical
    Work Package index.  Physical fragments remain under their source branch.
    """
    source = lineage.get("source_branch_ref")
    if not source:
        return None
    parts = str(source).split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
    ):
        raise ValueError("report lineage source branch is invalid")
    _safe_id(parts[1], "report_lineage.source_instance_id")
    source_branch_id = _safe_id(parts[2], "report_lineage.source_branch_id")
    if source_branch_id == branch_id:
        raise ValueError("report lineage source branch cannot equal target")
    return source_branch_id


def _is_graph_continuation(transition: dict[str, Any]) -> bool:
    """Distinguish a Graph-version continuation from a real research fork."""
    return transition.get("edge_ref") == "graph-edge:__graph_continuation__"


def _canonical_narrative(
    narrative: Any,
    carrier: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(narrative, dict) or set(narrative) != _NARRATIVE_FIELDS:
        raise ValueError("local narrative fields are invalid")
    encoded = json.dumps(
        narrative, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_NARRATIVE_BYTES:
        raise ValueError(
            f"local narrative exceeds {MAX_NARRATIVE_BYTES} bytes"
        )
    schema_version = narrative["schema_version"]
    if schema_version not in {1, 2} or narrative["language"] != "zh-Hans":
        raise ValueError("local narrative language must be zh-Hans")
    title = _zh_text(narrative["title"], "narrative.title", maximum=256)
    sections = narrative["sections"]
    if not isinstance(sections, list) or not sections or len(sections) > 8:
        raise ValueError("local narrative sections must be a bounded array")
    allowed_refs = _carrier_reference_allowlist(carrier)
    result = []
    seen_ids = set()
    declared_target_refs: set[str] = set()
    for item in sections:
        fields = set(item) if isinstance(item, dict) else set()
        if schema_version == 2:
            expected_fields = (
                _NARRATIVE_SECTION_FIELDS_V2,
                _NARRATIVE_SECTION_FIELDS_V2_WITH_BODY,
            )
        else:
            expected_fields = (_NARRATIVE_SECTION_FIELDS_V1,)
        if fields not in expected_fields:
            raise ValueError("local narrative section fields are invalid")
        section_id = _safe_id(item["section_id"], "narrative.section_id")
        if section_id in seen_ids:
            raise ValueError("local narrative section_id must be unique")
        seen_ids.add(section_id)
        links = item["links"]
        if not isinstance(links, list) or len(links) > MAX_ITEMS:
            raise ValueError("local narrative links must be a bounded array")
        projected_links = []
        link_ids = set()
        for link in links:
            if not isinstance(link, dict) or frozenset(link) not in {
                frozenset(_NARRATIVE_LINK_FIELDS),
                frozenset(_NARRATIVE_LINK_FIELDS_WITH_LABEL),
            }:
                raise ValueError("local narrative link fields are invalid")
            if link["kind"] not in _LINK_KINDS:
                raise ValueError("local narrative link kind is invalid")
            link_id = _safe_id(link["link_id"], "narrative.link_id")
            if link_id in link_ids:
                raise ValueError("narrative.link_id must be unique")
            link_ids.add(link_id)
            _reference(link["target_ref"], "narrative.target_ref")
            if link["target_ref"] not in allowed_refs:
                raise ValueError(
                    "narrative links must belong to the same checkpoint carrier"
                )
            declared_target_refs.add(link["target_ref"])
            projected = dict(link)
            if "label" in projected:
                projected["label"] = _zh_text(
                    projected["label"], "narrative.link.label", maximum=160,
                )
            projected_links.append(projected)
        section = {
            "section_id": section_id,
            "title": _zh_text(item["title"], "narrative.section.title"),
            "links": projected_links,
        }
        if schema_version == 2:
            if "body" in item:
                section["body"] = _zh_body(item["body"])
            section["blocks"] = _canonical_narrative_blocks(
                item["blocks"], declared_link_ids=link_ids,
            )
        else:
            section["body"] = _zh_body(item["body"])
        result.append(section)
    missing = _required_narrative_targets(carrier) - declared_target_refs
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            "narrative must link every checkpoint object: " + missing_text
        )
    if schema_version == 2:
        _validate_result_table_bindings(carrier, result)
    return {
        "schema_version": schema_version,
        "language": "zh-Hans",
        "title": title,
        "sections": result,
    }


def _validate_result_table_bindings(
    carrier: dict[str, Any], sections: list[dict[str, Any]]
) -> None:
    """Require result refs to be reachable from a structured result table.

    The local publisher deliberately does not fetch Job artifacts.  At result
    nodes, the Agent therefore has to place the already-verified values into a
    v2 table block and bind each row to the corresponding stable chip ref.
    Ordinary prose checkpoints and legacy v1 narratives remain unchanged.
    """
    transition = carrier["latest_transition"]
    if not _is_result_checkpoint(carrier, transition):
        return
    result_targets = set(carrier["job_refs"] + carrier["run_refs"])
    result_targets.update(
        ref for ref in (
            carrier["evidence_refs"] + transition["evidence_refs"]
        ) if ref.startswith("evidence:")
    )
    if not result_targets:
        return

    links_by_id = {
        link["link_id"]: link
        for section in sections
        for link in section["links"]
    }
    table_link_ids = {
        link_id
        for section in sections
        for block in section.get("blocks", [])
        if block["kind"] == "table"
        for row in block["rows"]
        for link_id in row["link_ids"]
    }
    missing = sorted(
        target for target in result_targets
        if not any(
            link_id in table_link_ids
            and links_by_id.get(link_id, {}).get("target_ref") == target
            for link_id in links_by_id
        )
    )
    if missing:
        raise ValueError(
            "result table must bind every Job/run/result evidence ref: "
            + ", ".join(missing)
        )


def _is_result_checkpoint(
    carrier: dict[str, Any], transition: dict[str, Any]
) -> bool:
    nodes = {carrier["current_node"], transition["to_node"]}
    if nodes & _RESULT_NODES:
        return True
    edge_ref = transition["edge_ref"]
    return any(
        edge_ref.endswith(f"__{node}") for node in _RESULT_NODES
    )


def _canonical_narrative_blocks(
    value: Any,
    *,
    declared_link_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("narrative blocks must be a bounded array")
    blocks = []
    used_link_ids: set[str] = set()
    for block in value:
        if not isinstance(block, dict):
            raise ValueError("narrative block must be an object")
        kind = block.get("kind")
        if kind == "math" and set(block) == {
            "kind", "latex", "fallback", "link_ids",
        }:
            refs = block["link_ids"]
            if not isinstance(refs, list) or not refs or len(refs) > MAX_ITEMS:
                raise ValueError("narrative math link_ids are invalid")
            for link_id in refs:
                _safe_id(link_id, "narrative.math.link_id")
                if link_id not in declared_link_ids:
                    raise ValueError(
                        "math chip must reference a declared section link"
                    )
                used_link_ids.add(link_id)
            blocks.append({
                "kind": kind,
                "latex": _text(block["latex"], "narrative.math.latex", 2000),
                "fallback": _zh_body(block["fallback"]),
                "link_ids": list(refs),
            })
            continue
        if kind == "paragraph" and set(block) in (
            {"kind", "text"}, {"kind", "text", "link_ids"}
        ):
            projected = {"kind": kind, "text": _zh_body(block["text"])}
            if "link_ids" in block:
                refs = block["link_ids"]
                if (
                    not isinstance(refs, list) or not refs
                    or len(refs) > MAX_ITEMS
                ):
                    raise ValueError("narrative paragraph link_ids are invalid")
                for link_id in refs:
                    _safe_id(link_id, "narrative.paragraph.link_id")
                    if link_id not in declared_link_ids:
                        raise ValueError(
                            "paragraph chip must reference a declared section link"
                        )
                    used_link_ids.add(link_id)
                projected["link_ids"] = list(refs)
            blocks.append(projected)
            continue
        if kind == "list" and set(block) == {"kind", "rows"}:
            rows = _canonical_narrative_rows(
                block["rows"],
                declared_link_ids=declared_link_ids,
                used_link_ids=used_link_ids,
                table_columns=None,
            )
            blocks.append({"kind": kind, "rows": rows})
            continue
        if kind == "table" and set(block) in (
            {"kind", "columns", "rows"},
            {"kind", "columns", "rows", "result_kind"},
        ):
            columns = block["columns"]
            if (
                not isinstance(columns, list)
                or not 1 <= len(columns) <= 12
            ):
                raise ValueError("narrative table columns are invalid")
            canonical_columns = [
                _zh_text(item, "narrative.table.column", maximum=128)
                for item in columns
            ]
            rows = _canonical_narrative_rows(
                block["rows"],
                declared_link_ids=declared_link_ids,
                used_link_ids=used_link_ids,
                table_columns=len(canonical_columns),
            )
            projected = {
                "kind": kind,
                "columns": canonical_columns,
                "rows": rows,
            }
            if "result_kind" in block:
                result_kind = block["result_kind"]
                if result_kind not in _RESULT_KINDS:
                    raise ValueError("narrative table result_kind is invalid")
                projected["result_kind"] = result_kind
            blocks.append(projected)
            continue
        raise ValueError("narrative block fields are invalid")
    if used_link_ids != declared_link_ids:
        raise ValueError(
            "every declared section link must be bound to one list or table row"
        )
    return blocks


def _canonical_narrative_rows(
    value: Any,
    *,
    declared_link_ids: set[str],
    used_link_ids: set[str],
    table_columns: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise ValueError("narrative block rows must be a bounded array")
    rows = []
    for item in value:
        expected = (
            {"cells", "link_ids"}
            if table_columns is not None
            else {"text", "link_ids"}
        )
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("narrative row fields are invalid")
        link_ids = item["link_ids"]
        if (
            not isinstance(link_ids, list)
            or not link_ids
            or len(link_ids) > MAX_ITEMS
        ):
            raise ValueError("narrative row link_ids are invalid")
        for link_id in link_ids:
            _safe_id(link_id, "narrative.row.link_id")
            if link_id not in declared_link_ids:
                raise ValueError("row chip must reference a declared section link")
            used_link_ids.add(link_id)
        if table_columns is None:
            rows.append({
                "text": _zh_body(item["text"]),
                "link_ids": list(link_ids),
            })
            continue
        cells = item["cells"]
        if not isinstance(cells, list) or len(cells) != table_columns:
            raise ValueError("narrative table row width is invalid")
        rows.append({
            "cells": [
                _text(cell, "narrative.table.cell", maximum=512)
                for cell in cells
            ],
            "link_ids": list(link_ids),
        })
    return rows


def _carrier_reference_allowlist(carrier: dict[str, Any]) -> set[str]:
    transition = carrier["latest_transition"]
    values = {
        carrier["checkpoint_ref"], carrier["research_cycle_ref"],
        transition["step_ref"], transition["edge_ref"],
        *carrier["evidence_refs"], *carrier["job_refs"], *carrier["run_refs"],
        *transition["evidence_refs"], *transition["trial_plan_refs"],
        *transition["obligation_refs"], *transition["claim_refs"],
        *transition["job_refs"], *transition["run_refs"],
        *transition["delta_refs"],
        *(item["claim_ref"] for item in carrier["claims"]),
        *(item["obligation_ref"] for item in carrier["open_obligations"]),
    }
    values.update(
        f"obligation:{item['obligation_id']}"
        for item in transition["obligation_changes"]
    )
    values.update(
        f"claim:{item['claim_id']}" for item in transition["claim_changes"]
    )
    return values


def _required_narrative_targets(carrier: dict[str, Any]) -> set[str]:
    """Return checkpoint objects that must remain inspectable from prose.

    Scope and graph identity are already rendered as report metadata.  The
    research objects below are the claims, obligations, plans and executions
    whose evidence must be reachable from the narrative itself.
    """
    transition = carrier["latest_transition"]
    required = set(
        carrier["evidence_refs"]
        + carrier["job_refs"]
        + carrier["run_refs"]
        + transition["evidence_refs"]
        + transition["trial_plan_refs"]
        + transition["obligation_refs"]
        + transition["claim_refs"]
        + transition["job_refs"]
        + transition["run_refs"]
        + transition["delta_refs"]
        + [item["claim_ref"] for item in carrier["claims"]]
        + [item["obligation_ref"] for item in carrier["open_obligations"]]
        + [
            f"obligation:{item['obligation_id']}"
            for item in transition["obligation_changes"]
        ]
        + [
            f"claim:{item['claim_id']}"
            for item in transition["claim_changes"]
        ]
    )
    return required


def _zh_text(value: Any, field: str, maximum: int = 512) -> str:
    text = _text(value, field, maximum=maximum)
    if not _CHINESE.search(text):
        raise ValueError(f"{field} must contain Simplified Chinese prose")
    return text


def _zh_body(value: Any) -> str:
    text = _text(value, "narrative.section.body", maximum=4000)
    in_code = False
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not line or in_code:
            continue
        if not _CHINESE.search(line):
            raise ValueError(
                "narrative.section.body lines must contain Chinese prose"
            )
    return text


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
