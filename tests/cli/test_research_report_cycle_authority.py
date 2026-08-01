from __future__ import annotations

from types import SimpleNamespace

from tools.cli.release.research_obligations import (
    initialize_ledger,
    write_ledger,
)
from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.references.cycle_authority import (
    validate_cycle_reference,
)


class _RemoteMustNotRun:
    def get_research_cycle_object(self, *_args, **_kwargs):
        raise AssertionError("local obligation authority called remote server")


def test_obligation_reference_uses_branch_ledger_authority(tmp_path):
    ledger = initialize_ledger(
        branch_ref="graph-branch:instance:branch",
        graph_ref="factor-research@v10",
        current_node="data_contract",
        context_ref="context:one",
        checkpoint_ref="trace:one",
        obligations=[{
            "obligation_id": "data-contract",
            "title_zh": "数据契约",
            "status": "bounded",
            "epistemic_question": "数据是否满足研究需要",
            "requirement_refs": ["data.source_availability"],
            "scope": {},
            "claim_scopes": [],
        }],
    )
    write_ledger(tmp_path, "branch", ledger)
    scope = SimpleNamespace(
        package_root=tmp_path,
        branch_id="branch",
        branch_ref="graph-branch:instance:branch",
    )

    value = validate_cycle_reference(
        reference=DeclaredReportReference(
            kind="obligation",
            target_ref="obligation:data-contract",
            label="数据契约",
            url_start=0,
        ),
        scope=scope,
        client=_RemoteMustNotRun(),
    )

    assert value["obligation_id"] == "data-contract"
    assert value["title_zh"] == "数据契约"
    assert value["requirement_refs"] == ["data.source_availability"]
