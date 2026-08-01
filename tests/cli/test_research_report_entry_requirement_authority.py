from __future__ import annotations

from types import SimpleNamespace

from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.references.entry_requirements import (
    validate_entry_requirement_reference,
)


class _Client:
    def get_current_graph_requirement(
        self, _instance_id, _branch_id, requirement_id,
    ):
        return {
            "graph_ref": "factor-research@v10",
            "node_id": "data_contract",
            "requirement_sources": ["node", "edge"],
            "requirement": {
                "requirement_id": requirement_id,
                "title_zh": "数据来源覆盖",
                "gate_policy": {"minimum_qualification": "limited"},
            },
        }


class _HistoricalClient:
    def get_current_graph_requirement(self, *_args):
        raise RuntimeError("requirement is not active at the current node")

    def get_research_graph_node_info(self, *_args):
        return {"graph_ref": "factor-research@v10"}

    def list_research_graph_versions(self, graph_id):
        assert graph_id == "factor-research"
        return [{
            "version": 10,
            "requirement_catalog": {"requirements": [{
                "requirement_id": "hypothesis_validity.mechanism_chain",
                "title_zh": "机制作用链",
                "gate_policy": {"accepted_states": ["bounded"]},
            }]},
        }]


def test_requirement_authority_accepts_structured_list_metadata():
    value = validate_entry_requirement_reference(
        reference=DeclaredReportReference(
            kind="entry_requirement",
            target_ref="requirement:data.source_availability",
            label="数据来源覆盖",
        ),
        scope=SimpleNamespace(
            branch_ref="graph-branch:instance:branch",
        ),
        client=_Client(),
    )

    assert value["requirement_sources"] == ["node", "edge"]
    assert value["gate_policy"] == {
        "minimum_qualification": "limited",
    }


def test_historical_requirement_uses_immutable_graph_catalog():
    value = validate_entry_requirement_reference(
        reference=DeclaredReportReference(
            kind="entry_requirement",
            target_ref="requirement:hypothesis_validity.mechanism_chain",
            label="机制作用链",
        ),
        scope=SimpleNamespace(
            branch_ref="graph-branch:instance:branch",
        ),
        client=_HistoricalClient(),
        allow_historical=True,
    )

    assert value["authority_scope"] == "historical_graph_catalog"
    assert value["title_zh"] == "机制作用链"
    assert value["gate_policy"] == {"accepted_states": ["bounded"]}
