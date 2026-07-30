from pathlib import Path

import click
import pytest

from tools.cli.commands.research_graph_continuation_report import (
    shadow_continuation_source,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile


def _profile(client_root: Path, *, provenance: dict) -> None:
    value = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=client_root / "workspace",
    )
    value["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {"instance_id": "source", "branch_id": "source-branch"},
        "status": "ready",
        "next_action": "Continue",
    }]
    value["research_records"] = [{
        "record_id": "target",
        "title": "Shadow",
        "status": "pending",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["factor-family:stable"],
        "agent_id": "research-maxa",
        "created_at": 1,
        "updated_at": 1,
        "workspace_ref": "workspace:one",
        "run_ref": "",
        "graph_instance_ref": "work-package:target",
        "graph_branch_ref": "graph-branch:target:target-branch",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": provenance,
    }]
    LocalProfileStore(client_root).save(value)


def test_shadow_report_retry_resolves_explicit_source_identity(
    tmp_path: Path,
) -> None:
    _profile(tmp_path, provenance={
        "kind": "shadow_graph_continuation",
        "source_work_package_id": "source-package",
        "source_graph_branch_ref": "graph-branch:source:source-branch",
    })

    assert shadow_continuation_source(
        client_root=tmp_path,
        profile_id="maxa",
        agent_id="research-maxa",
        target_instance_id="target",
        target_branch_id="target-branch",
    ) == {
        "target_work_package_id": "target",
        "source_work_package_id": "source-package",
        "source_instance_id": "source",
        "source_branch_id": "source-branch",
    }


def test_shadow_report_retry_rejects_non_shadow_record(
    tmp_path: Path,
) -> None:
    _profile(tmp_path, provenance={"kind": "owned_research"})

    with pytest.raises(click.ClickException, match="only accepts a shadow"):
        shadow_continuation_source(
            client_root=tmp_path,
            profile_id="maxa",
            agent_id="research-maxa",
            target_instance_id="target",
            target_branch_id="target-branch",
        )
