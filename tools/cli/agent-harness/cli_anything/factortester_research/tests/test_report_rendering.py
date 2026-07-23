"""Deterministic, cold-path research report acceptance tests."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import unquote, urlparse

from click.testing import CliRunner
import pytest

from cli_anything.factortester_research.factortester_research_cli import cli
from cli_anything.factortester_research.core.reporting import (
    MarkdownReportTarget,
    canonical_report_snapshot,
    render_branch_report,
)
from cli_anything.factortester_research.core.reporting import generation, writer
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.local_profile_contracts import _research_artifact


def _snapshot() -> dict:
    return {
        "schema_version": 1,
        "workspace_id": "workspace-maxa",
        "work_package_id": "sgccs-review",
        "branch_id": "branch-sgccs",
        "title": "SgCCS bounded research report",
        "status": "blocked",
        "product_group": "china_futures",
        "current_node": "capability_gap",
        "graph_ref": "factor-research@5:sha256:graph",
        "methodology_hash": "1" * 64,
        "decision_contract_hash": "2" * 64,
        "trial_plan_hash": "3" * 64,
        "factor_family_versions": ["MaxA:SgCCS@7"],
        "sections": [{
            "section_id": "current-state",
            "checkpoint_ref": "trace:checkpoint-current-state",
            "branch_ref": "graph-branch:instance-sgccs:branch-sgccs",
            "title": "Current evidence state",
            "body": "The latest bounded decision remains blocked.",
            "links": [{
                "link_id": "trial-plan-design",
                "kind": "trial_plan",
                "target_ref": "trial-plan:sgccs:1",
            }, {
                "link_id": "obligation-bootstrap",
                "kind": "obligation",
                "target_ref": "obligation:bootstrap-sharpe",
            }],
            "evidence_refs": ["evidence:job-attempt-1"],
            "asset_refs": ["asset:equity-curve", "asset:unavailable"],
        }],
        "evidence_refs": ["evidence:job-attempt-1"],
        "assets": [{
            "asset_ref": "asset:equity-curve",
            "content_hash": "4" * 64,
            "media_type": "image/png",
            "filename": f"{'4' * 64}.png",
            "caption": "Reviewed equity curve",
            "alt_text": "Equity curve over the declared sample",
            "provenance_refs": ["evidence:job-attempt-1"],
            "availability": "available",
        }, {
            "asset_ref": "asset:unavailable",
            "content_hash": "5" * 64,
            "media_type": "application/json",
            "filename": f"{'5' * 64}.json",
            "caption": "Restricted detail",
            "alt_text": "",
            "provenance_refs": ["evidence:restricted"],
            "availability": "unauthorized",
        }],
        "gaps": [{
            "gap_ref": "capability:performance.bootstrap-sharpe",
            "reason": "No approved implementation is available.",
        }],
    }


def test_markdown_is_byte_stable_and_contains_only_bounded_refs() -> None:
    snapshot = canonical_report_snapshot(_snapshot())
    target = MarkdownReportTarget()

    first = target.render(snapshot)
    second = target.render(deepcopy(snapshot))

    assert first == second
    text = first.decode()
    assert snapshot["source_hash"] not in text
    assert "evidence:job-attempt-1" not in text
    assert "MaxA:SgCCS@7" in text
    assert (
        "![Equity curve over the declared sample]"
        f"(../../assets/{'4' * 64}.png)"
    ) in text
    assert "`asset:unavailable` — unauthorized" in text
    assert "performance.bootstrap-sharpe" in text


def test_incremental_render_does_not_rewrite_unchanged_report(
    tmp_path,
) -> None:
    snapshot = _snapshot()

    first = render_branch_report(snapshot, workspace_root=tmp_path)
    stat_before = first["path"].stat()
    index_stat_before = first["index_path"].stat()
    aggregate_stat_before = first["work_package_report_path"].stat()
    second = render_branch_report(snapshot, workspace_root=tmp_path)
    stat_after = second["path"].stat()

    assert first["changed"] is True
    assert second["changed"] is False
    assert first["content_hash"] == second["content_hash"]
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns
    assert stat_before.st_ino == stat_after.st_ino
    assert second["index_path"].stat() == index_stat_before
    assert second["work_package_report_path"].stat() == aggregate_stat_before
    package_root = tmp_path / "research" / "sgccs-review"
    assert first["path"] == (
        package_root / "branches" / "branch-sgccs" / "REPORT.md"
    )
    assert (package_root / "INDEX.json").is_file()
    assert (package_root / "REPORT.md").is_file()
    assert (package_root / "assets").is_dir()
    assert first["artifact_refs"] == {
        "index": "artifact:research/sgccs-review/INDEX.json",
        "work_package_report": "artifact:research/sgccs-review/REPORT.md",
        "branch_report": (
            "artifact:research/sgccs-review/branches/branch-sgccs/REPORT.md"
        ),
        "assets": "artifact:research/sgccs-review/assets/",
    }


def test_branch_change_updates_only_that_branch_and_package_aggregates(
    tmp_path,
) -> None:
    first_branch = _snapshot()
    second_branch = deepcopy(first_branch)
    second_branch.update({
        "branch_id": "branch-trend",
        "title": "Trend hypothesis",
    })
    second_branch["sections"][0]["branch_ref"] = (
        "graph-branch:instance-trend:branch-trend"
    )
    first = render_branch_report(first_branch, workspace_root=tmp_path)
    second = render_branch_report(second_branch, workspace_root=tmp_path)
    stable_branch_stat = first["path"].stat()
    changed_branch_stat = second["path"].stat()
    index_stat = second["index_path"].stat()
    aggregate_stat = second["work_package_report_path"].stat()

    second_branch["sections"][0]["body"] = "New bounded evidence state."
    updated = render_branch_report(second_branch, workspace_root=tmp_path)

    assert updated["branch_changed"] is True
    assert updated["index_changed"] is True
    assert updated["work_package_report_changed"] is True
    assert first["path"].stat().st_ino == stable_branch_stat.st_ino
    assert updated["path"].stat().st_ino != changed_branch_stat.st_ino
    assert updated["index_path"].stat().st_ino != index_stat.st_ino
    assert (
        updated["work_package_report_path"].stat().st_ino
        != aggregate_stat.st_ino
    )


def test_index_projects_sections_for_the_current_swift_reader(tmp_path) -> None:
    result = render_branch_report(_snapshot(), workspace_root=tmp_path)

    index = json.loads(result["index_path"].read_text(encoding="utf-8"))
    assert index["sections"] == [{
        "section_ref": "report-section:branch-sgccs:current-state",
        "section_id": "current-state",
        "checkpoint_ref": "trace:checkpoint-current-state",
        "branch_ref": "graph-branch:instance-sgccs:branch-sgccs",
        "title": "Current evidence state",
        "summary": "The latest bounded decision remains blocked.",
        "created_at": 0.0,
        "links": [{
            "link_id": "trial-plan-design",
            "kind": "trial_plan",
            "target_ref": "trial-plan:sgccs:1",
            "section_ref": "report-section:branch-sgccs:current-state",
        }, {
            "link_id": "obligation-bootstrap",
            "kind": "obligation",
            "target_ref": "obligation:bootstrap-sharpe",
            "section_ref": "report-section:branch-sgccs:current-state",
        }, {
            "link_id": "branch-sgccs:current-state:evidence:0",
            "kind": "evidence",
            "target_ref": "evidence:job-attempt-1",
            "section_ref": "report-section:branch-sgccs:current-state",
        }, {
            "link_id": "branch-sgccs:current-state:asset:0",
            "kind": "report_section",
            "target_ref": "asset:equity-curve",
            "section_ref": "report-section:branch-sgccs:current-state",
        }, {
            "link_id": "branch-sgccs:current-state:asset:1",
            "kind": "report_section",
            "target_ref": "asset:unavailable",
            "section_ref": "report-section:branch-sgccs:current-state",
        }],
    }]


def test_checkpoint_section_navigation_retains_latest_bounded_window(
    tmp_path,
) -> None:
    for index in range(writer.index.MAX_INDEX_SECTIONS + 2):
        snapshot = _snapshot()
        snapshot["sections"][0].update({
            "section_id": f"checkpoint-{index:04d}",
            "created_at": float(index),
        })
        result = render_branch_report(snapshot, workspace_root=tmp_path)

    value = json.loads(result["index_path"].read_text(encoding="utf-8"))
    assert len(value["sections"]) == writer.index.MAX_INDEX_SECTIONS
    assert value["omitted_section_count"] == 2
    assert value["sections"][0]["created_at"] == 2.0
    assert value["sections"][-1]["created_at"] == float(
        writer.index.MAX_INDEX_SECTIONS + 1
    )


def test_same_branch_id_is_isolated_by_work_package(tmp_path) -> None:
    first_snapshot = _snapshot()
    second_snapshot = deepcopy(first_snapshot)
    second_snapshot["work_package_id"] = "trend-review"

    first = render_branch_report(first_snapshot, workspace_root=tmp_path)
    second = render_branch_report(second_snapshot, workspace_root=tmp_path)

    assert first["path"] != second["path"]
    assert first["path"].is_file()
    assert second["path"].is_file()
    assert first["artifact_refs"]["branch_report"] == (
        "artifact:research/sgccs-review/branches/branch-sgccs/REPORT.md"
    )
    assert second["artifact_refs"]["branch_report"] == (
        "artifact:research/trend-review/branches/branch-sgccs/REPORT.md"
    )


def test_artifact_refs_survive_moving_the_workspace_root(tmp_path) -> None:
    first_root = tmp_path / "first"
    moved_root = tmp_path / "moved"
    first = render_branch_report(_snapshot(), workspace_root=first_root)
    first_root.rename(moved_root)
    second = render_branch_report(_snapshot(), workspace_root=moved_root)

    assert second["changed"] is False
    assert second["artifact_refs"] == first["artifact_refs"]
    index = json.loads(second["index_path"].read_text(encoding="utf-8"))
    assert str(first_root) not in json.dumps(index)
    assert str(moved_root) not in json.dumps(index)


def test_concurrent_branches_merge_under_one_work_package_lock(
    tmp_path,
    monkeypatch,
) -> None:
    first = _snapshot()
    second = deepcopy(first)
    second.update({"branch_id": "branch-trend", "title": "Trend"})
    second["sections"][0]["branch_ref"] = (
        "graph-branch:instance-trend:branch-trend"
    )
    original_load = writer.index.load_index
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    def observed_load(*args, **kwargs):
        with state_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.03)
        try:
            return original_load(*args, **kwargs)
        finally:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(writer.index, "load_index", observed_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda value: render_branch_report(value, workspace_root=tmp_path),
            [first, second],
        ))

    index = json.loads(results[0]["index_path"].read_text())
    assert state["maximum"] == 1
    assert [item["branch_id"] for item in index["branches"]] == [
        "branch-sgccs", "branch-trend",
    ]


@pytest.mark.parametrize("level", ["top", "branch", "section", "link"])
def test_existing_index_rejects_unknown_fields_at_every_level(
    tmp_path,
    level,
) -> None:
    first = render_branch_report(_snapshot(), workspace_root=tmp_path)
    index = json.loads(first["index_path"].read_text())
    target = {
        "top": index,
        "branch": index["branches"][0],
        "section": index["sections"][0],
        "link": index["sections"][0]["links"][0],
    }[level]
    target["unexpected"] = True
    first["index_path"].write_text(json.dumps(index))

    with pytest.raises(ValueError, match="fields are invalid"):
        render_branch_report(_snapshot(), workspace_root=tmp_path)


def test_existing_index_is_size_and_count_bounded_before_merge(tmp_path) -> None:
    first = render_branch_report(_snapshot(), workspace_root=tmp_path)
    first["index_path"].write_bytes(
        b"x" * (writer.index.MAX_INDEX_BYTES + 1)
    )

    with pytest.raises(ValueError, match="exceeds .* bytes"):
        render_branch_report(_snapshot(), workspace_root=tmp_path)

    first = render_branch_report(_snapshot(), workspace_root=tmp_path / "other")
    index = json.loads(first["index_path"].read_text())
    index["sections"] = index["sections"] * (
        writer.index.MAX_INDEX_SECTIONS + 1
    )
    first["index_path"].write_text(json.dumps(index))
    with pytest.raises(ValueError, match="bounded array"):
        render_branch_report(_snapshot(), workspace_root=tmp_path / "other")


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("evidence", "file:///private/result.json"),
        ("evidence", "artifact:/Users/max/private.json"),
        ("evidence", "artifact:C:/Users/max/private.json"),
        ("evidence", "artifact://Users/max/private.json"),
        ("asset", "/private/curve.png"),
        ("asset", r"C:\\research\\curve.png"),
    ],
)
def test_snapshot_rejects_local_paths_in_references(field, unsafe) -> None:
    snapshot = _snapshot()
    if field == "evidence":
        snapshot["sections"][0]["evidence_refs"] = [unsafe]
    else:
        snapshot["sections"][0]["asset_refs"] = [unsafe]

    with pytest.raises(ValueError, match="stable reference"):
        canonical_report_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("title", "Result at /Users/maxdeux/private/result.json"),
        ("body", "Read /home/researcher/private/result.json"),
        ("body", r"Read C:\\Users\\researcher\\private\\result.json"),
        ("body", "Read ~/private/result.json"),
    ],
)
def test_snapshot_rejects_local_paths_in_projected_text(
    field,
    unsafe,
) -> None:
    snapshot = _snapshot()
    if field == "title":
        snapshot["title"] = unsafe
    else:
        snapshot["sections"][0]["body"] = unsafe

    with pytest.raises(ValueError, match="bounded text"):
        canonical_report_snapshot(snapshot)


@pytest.mark.parametrize(
    "unsafe",
    [
        "../../private/evidence.json",
        "./evidence.json",
        "~/evidence.json",
        r"private\\evidence.json",
        "private/evidence.json",
    ],
)
def test_snapshot_rejects_relative_device_paths_as_references(
    unsafe,
) -> None:
    snapshot = _snapshot()
    snapshot["sections"][0]["evidence_refs"] = [unsafe]

    with pytest.raises(ValueError, match="stable reference"):
        canonical_report_snapshot(snapshot)


@pytest.mark.parametrize("field", ["target_ref", "evidence_ref", "asset_ref"])
def test_existing_index_rejects_local_paths_in_references(
    tmp_path,
    field,
) -> None:
    first = render_branch_report(_snapshot(), workspace_root=tmp_path)
    index = json.loads(first["index_path"].read_text())
    if field == "target_ref":
        index["sections"][0]["links"][0][field] = "file:///tmp/result"
    elif field == "evidence_ref":
        index["branches"][0]["evidence_refs"] = ["/tmp/result"]
    else:
        index["branches"][0]["asset_refs"] = [r"C:\\result.png"]
    first["index_path"].write_text(json.dumps(index))

    with pytest.raises(ValueError, match="stable reference"):
        render_branch_report(_snapshot(), workspace_root=tmp_path)


@pytest.mark.parametrize(
    ("location", "unsafe", "message"),
    [
        ("title", "Result at /Users/maxdeux/private", "bounded text"),
        ("summary", "Read ~/private/result.json", "bounded text"),
        ("target_ref", "../../private/evidence.json", "stable reference"),
    ],
)
def test_existing_index_rejects_paths_in_all_projected_fields(
    tmp_path,
    location,
    unsafe,
    message,
) -> None:
    first = render_branch_report(_snapshot(), workspace_root=tmp_path)
    index = json.loads(first["index_path"].read_text())
    if location == "title":
        index["branches"][0]["title"] = unsafe
    elif location == "summary":
        index["sections"][0]["summary"] = unsafe
    else:
        index["sections"][0]["links"][0]["target_ref"] = unsafe
    first["index_path"].write_text(json.dumps(index))

    with pytest.raises(ValueError, match=message):
        render_branch_report(_snapshot(), workspace_root=tmp_path)


def test_failed_atomic_replace_preserves_previous_complete_report(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    first = render_branch_report(snapshot, workspace_root=tmp_path)
    previous = first["path"].read_bytes()
    snapshot["sections"][0]["body"] = "Changed bounded state."
    monkeypatch.setattr(
        generation.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected failure")),
    )

    with pytest.raises(OSError, match="injected failure"):
        render_branch_report(snapshot, workspace_root=tmp_path)

    assert first["path"].read_bytes() == previous


@pytest.mark.parametrize(
    "failed_target",
    ["branch", "work_package_report", "index"],
)
def test_failed_generation_publish_restores_all_three_old_files(
    tmp_path,
    monkeypatch,
    failed_target,
) -> None:
    snapshot = _snapshot()
    first = render_branch_report(snapshot, workspace_root=tmp_path)
    targets = {
        "branch": first["path"],
        "work_package_report": first["work_package_report_path"],
        "index": first["index_path"],
    }
    previous = {name: path.read_bytes() for name, path in targets.items()}
    snapshot["sections"][0]["body"] = "Changed bounded state."
    real_replace = generation.os.replace

    def fail_selected_replace(source, destination):
        if Path(destination) == targets[failed_target]:
            raise OSError(f"injected {failed_target} failure")
        return real_replace(source, destination)

    monkeypatch.setattr(generation.os, "replace", fail_selected_replace)

    with pytest.raises(OSError, match=f"injected {failed_target} failure"):
        render_branch_report(snapshot, workspace_root=tmp_path)

    assert {
        name: path.read_bytes() for name, path in targets.items()
    } == previous
    index = json.loads(previous["index"])
    assert index["branches"][0]["content_hash"] == hashlib.sha256(
        previous["branch"]
    ).hexdigest()
    assert index["branches"][0]["source_hash"] == canonical_report_snapshot(
        _snapshot()
    )["source_hash"]


@pytest.mark.parametrize(
    "prohibited",
    [
        {"factor_source": "secret implementation"},
        {"nested": {"raw_stdout": "unbounded"}},
        {"expression_tree": {"operator": "private"}},
        {"credentials": {"token": "secret"}},
    ],
)
def test_snapshot_rejects_prohibited_source_and_heavy_payloads(
    prohibited,
) -> None:
    snapshot = _snapshot()
    snapshot["sections"][0].update(prohibited)

    with pytest.raises(ValueError, match="prohibited report field"):
        canonical_report_snapshot(snapshot)


def test_renderer_interface_does_not_require_pdf_or_chart_dependency() -> None:
    target = MarkdownReportTarget()

    assert target.media_type == "text/markdown"
    assert target.extension == ".md"
    assert not hasattr(target, "database")
    assert not hasattr(target, "client")


def test_report_cli_renders_snapshot_without_server_access(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()))
    workspace_root = tmp_path / "workspace"

    result = CliRunner().invoke(cli, [
        "report",
        "render",
        "--snapshot-file",
        str(snapshot_path),
        "--workspace-root",
        str(workspace_root),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["changed"] is True
    assert payload["path"].endswith(
        "research/sgccs-review/branches/branch-sgccs/REPORT.md"
    )
    assert payload["artifact_refs"]["index"] == (
        "artifact:research/sgccs-review/INDEX.json"
    )
    descriptor = payload["local_artifact_descriptor"]
    assert _research_artifact(descriptor) == descriptor
    assert descriptor["artifact_ref"] == (
        payload["artifact_refs"]["branch_report"]
    )
    assert descriptor["local_ref"].startswith("file://")
    assert descriptor["index_ref"].startswith("file://")
    assert str(workspace_root) not in json.dumps(payload["artifact_refs"])
    index_url = urlparse(descriptor["index_ref"])
    index = json.loads(Path(unquote(index_url.path)).read_text())
    assert set(index["sections"][0]) == {
        "section_ref", "section_id", "checkpoint_ref", "branch_ref",
        "title", "summary", "links", "created_at",
    }
    assert set(index["sections"][0]["links"][0]) == {
        "link_id", "kind", "target_ref", "section_ref",
    }
    store = LocalProfileStore(tmp_path / "client-support")
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8000",
        workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "sgccs-review",
        "title": "SgCCS review",
        "status": "ready",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@7"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:maxa",
        "run_ref": "run:1",
        "graph_instance_ref": "instance:1",
        "graph_branch_ref": "branch:sgccs",
        "checkpoint_ref": "checkpoint:1",
        "evidence_refs": ["evidence:job-attempt-1"],
        "timeline_refs": descriptor["section_refs"][:1],
        "artifacts": [descriptor],
        "provenance": {"kind": "owned_research", "owner_ref": "maxa"},
    }]

    saved = store.save(profile)

    assert saved["research_records"][0]["artifacts"] == [descriptor]
