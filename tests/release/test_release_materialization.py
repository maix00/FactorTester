from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.materialize import materialize_release
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)

from .test_client_wheel import _build_wheel as build_client_wheel
from .test_harness_wheel import _build_wheel as build_harness_wheel


def test_real_client_and_harness_wheels_materialize_together(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "release"
    artifacts = staging / "artifacts"
    client = build_client_wheel(tmp_path / "client-build")
    harness = build_harness_wheel(tmp_path / "harness-build")
    artifacts.mkdir(parents=True)
    installed = [
        (client, "python-wheel"),
        (harness, "harness-wheel"),
    ]
    receipts = []
    for source, kind in installed:
        shutil.copy2(source, artifacts / source.name)
        receipts.append({"filename": source.name, "kind": kind})

    result = materialize_release(staging, receipts)

    assert result["python"]["commands"] == [
        "factortester",
        "cli-anything-factortester-research",
    ]
    bin_root = staging / "runtime" / "python" / "bin"
    client_help = subprocess.check_output(
        [bin_root / "factortester", "--help"],
        text=True,
    )
    harness_help = subprocess.check_output(
        [bin_root / "cli-anything-factortester-research", "--help"],
        text=True,
    )
    assert "protocol" in client_help
    assert "graph" in harness_help
    assert "\n  cycle " not in harness_help

    client_root = tmp_path / "client-root"
    workspace_root = tmp_path / "workspace"
    package_root = workspace_root / "research/wheel-contract"
    package_root.mkdir(parents=True)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "wheel-contract",
        "title": "Installed wheel report contract",
        "status": "ready",
        "scope": {},
        "factor_family_versions": [],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:wheel",
        "run_ref": "",
        "graph_instance_ref": "work-package:wheel-contract",
        "graph_branch_ref": "report-branch:branch-one",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {
            "kind": "owned_research",
            "owner_ref": "maxa",
        },
    }]
    LocalProfileStore(client_root).save(profile)
    release_profile = tmp_path / "release-profile.json"
    release_profile.write_text(json.dumps({
        "release": {"install_root": str(client_root)},
    }), encoding="utf-8")
    scope = [
        "--profile", "maxa",
        "--work-package-id", "wheel-contract",
        "--branch-id", "branch-one",
        "--release-profile", str(release_profile),
        "--json",
    ]
    added = subprocess.run(
        [
            bin_root / "cli-anything-factortester-research",
            "report", "create", *scope,
        ],
        capture_output=True,
        text=True,
    )
    assert added.returncode == 0, added.stdout
    chapter = ensure_branch_report_chapter(
        workspace_root=workspace_root,
        work_package_id="wheel-contract",
        title="Installed wheel report contract",
        node_id="factor_semantics",
        branch_id="branch-one",
        branch_ref="report-branch:branch-one",
    )
    section_id = "finding-section"
    added = subprocess.run(
        [
            bin_root / "cli-anything-factortester-research",
            "report", "add", *scope,
            "--component-id", section_id,
            "--parent-id", chapter["chapter_sync"]["component_id"],
            "--kind", "section",
            "--title", "验收结果",
        ],
        capture_output=True,
        text=True,
    )
    assert added.returncode == 0, added.stdout
    added = subprocess.run(
        [
            bin_root / "cli-anything-factortester-research",
            "report", "add", *scope,
            "--component-id", "finding-one",
            "--parent-id", section_id,
            "--kind", "entry",
            "--body", "已验证安装后的研究报告命令可以渲染该结果",
        ],
        capture_output=True,
        text=True,
    )
    assert added.returncode == 0, added.stdout
    rendered = subprocess.check_output(
        [
            bin_root / "cli-anything-factortester-research",
            "report", "render", *scope,
        ],
        text=True,
    )
    payload = json.loads(rendered)
    report = Path(payload["output"])
    assert report.is_file()
    assert report == package_root / "branches/branch-one/REPORT.md"
    assert "已验证安装后的研究报告命令可以渲染该结果" in report.read_text()
