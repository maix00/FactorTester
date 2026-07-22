from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from tools.cli.release.materialize import materialize_release

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
    assert "cycle" in harness_help

    snapshot = {
        "schema_version": 1,
        "workspace_id": "workspace-maxa",
        "work_package_id": "wheel-contract",
        "branch_id": "branch-one",
        "title": "Installed wheel report contract",
        "status": "active",
        "product_group": "china_futures",
        "current_node": "factor_semantics",
        "graph_ref": "factor-research@5:sha256:graph",
        "methodology_hash": "1" * 64,
        "decision_contract_hash": "2" * 64,
        "trial_plan_hash": "",
        "factor_family_versions": ["MaxA:SgCCS@7"],
        "sections": [{
            "section_id": "checkpoint-one",
            "title": "Checkpoint one",
            "body": "The installed harness rendered this checkpoint.",
            "created_at": 1.0,
            "checkpoint_ref": "trace:checkpoint-one",
            "branch_ref": "graph-branch:instance-one:branch-one",
            "links": [],
            "evidence_refs": [],
            "asset_refs": [],
        }],
        "evidence_refs": [],
        "assets": [],
        "gaps": [],
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    report_root = tmp_path / "reports"
    rendered = subprocess.check_output(
        [
            bin_root / "cli-anything-factortester-research",
            "report", "render",
            "--snapshot-file", snapshot_path,
            "--workspace-root", report_root,
            "--json",
        ],
        text=True,
    )
    payload = json.loads(rendered)
    assert Path(payload["path"]).is_file()
    assert payload["artifact_refs"]["branch_report"] == (
        "artifact:research/wheel-contract/branches/branch-one/REPORT.md"
    )
