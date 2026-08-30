from __future__ import annotations

import json

import pytest

from cli_anything.factortester_research.core.entry_preparation import (
    build_entry_assessment_skeleton,
    compact_factor_facts,
    validate_entry_assessment_document,
)
from tools.cli.release.research_reporting.authoring.inline_links import (
    validate_typed_target,
)
from tools.cli import research_graph_entry_assessment as entry_assessment


def _describe() -> dict:
    return {
        "factor": {
            "id": "SgCPS",
            "name": "SgCPS",
            "source": "custom",
            "owner_username": "18717974771",
            "source_access": True,
            "chinese_name": "中心价格强度",
            "description": "Signal Centered Price Strength",
            "params": [
                {
                    "alias": "P",
                    "type": "FactorParam",
                    "default_value": "CA",
                    "options": [{"value": "CA"}] * 100,
                },
                {
                    "alias": "N",
                    "type": "WindowParam",
                    "default_value": "20d",
                    "options": [],
                },
            ],
        },
        "tree_repr": (
            "div\n"
            "├─ sub\n"
            "│  ├─ mul\n"
            "│  │  ├─ Const[2]\n"
            "│  │  └─ ParamRef[P]\n"
            "│  └─ ColumnRef[HIGH_ADJUSTED]\n"
            "└─ ColumnRef[LOW_ADJUSTED]"
        ),
        "column_refs": ["HA", "LA"],
        "operator_keys": ["rolling_max", "rolling_min"],
        "source_checks": {"ok": True},
        "source_code": "must not survive",
        "debug_graph": {
            "root_id": 8,
            "next_id": 9,
            "nodes": [
                {
                    "id": 1, "key": "Constant", "cat": "leaf", "label": "",
                    "inputs": [], "params": {"value": "2"}, "x": 0, "y": 0,
                },
                {
                    "id": 2, "key": "DataColumnParam", "cat": "leaf",
                    "label": "P", "inputs": [],
                    "params": {
                        "alias": "P", "type": "FactorParam",
                        "default_value": "CA",
                    },
                    "x": 0, "y": 0,
                },
                {
                    "id": 3, "key": "*", "cat": "arithBinary", "label": "*",
                    "inputs": [1, 2], "params": {}, "x": 0, "y": 0,
                },
                {
                    "id": 4, "key": "DataColumnParam", "cat": "leaf",
                    "label": "HA", "inputs": [],
                    "params": {
                        "alias": "HA", "type": "DataColumnParam",
                        "default_value": "HA",
                    },
                    "x": 0, "y": 0,
                },
                {
                    "id": 5, "key": "-", "cat": "arithBinary", "label": "-",
                    "inputs": [3, 4], "params": {}, "x": 0, "y": 0,
                },
                {
                    "id": 6, "key": "DataColumnParam", "cat": "leaf",
                    "label": "LA", "inputs": [],
                    "params": {
                        "alias": "LA", "type": "DataColumnParam",
                        "default_value": "LA",
                    },
                    "x": 0, "y": 0,
                },
                {
                    "id": 7, "key": "/", "cat": "arithBinary", "label": "/",
                    "inputs": [5, 6], "params": {}, "x": 0, "y": 0,
                },
                {
                    "id": 8, "key": "Return", "cat": "output",
                    "label": "return", "inputs": [7], "params": {},
                    "x": 0, "y": 0,
                },
            ],
        },
    }


def _next_packet() -> dict:
    return {
        "graph": "factor-research@v9",
        "context_ref": "sha256:" + "1" * 64,
        "branch": {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
        "node": {"node_id": "factor_semantics", "kind": "validation"},
        "entry_requirements": [
            {
                "requirement_id": "factor_semantics.expression_identity",
                "title_zh": "原公式、LaTeX、算子树、参数、ColumnRef 和版本是什么",
                "gate_policy": "plan_before_exit",
                "mapped_obligation_refs": ["obligation:existing-1"],
                "mapped_statuses": ["open"],
                "detail_ref": (
                    "graph-requirement:"
                    "factor_semantics.expression_identity"
                ),
            },
            {
                "requirement_id": "factor_semantics.timing_and_causality",
                "title_zh": "输入何时可知，是否含未来信息",
                "gate_policy": "plan_before_exit",
                "mapped_obligation_refs": [],
                "mapped_statuses": [],
                "detail_ref": (
                    "graph-requirement:"
                    "factor_semantics.timing_and_causality"
                ),
            },
        ],
        "current_obligations": [
            {
                "obligation_id": "existing-1",
                "status": "open",
                "materiality": "decision_blocking",
                "question_summary": "既有表达式身份义务",
                "detail_ref": (
                    "research-cycle-object:obligation:existing-1"
                ),
            },
        ],
        "candidate_edges": [],
    }


def _detail(requirement_id: str) -> dict:
    return {
        "graph_ref": "factor-research@v9",
        "node_id": "factor_semantics",
        "requirement": {
            "requirement_id": requirement_id,
            "revision": 1,
            "gate_policy": "plan_before_exit",
            "question_zh": "请逐项判断。",
            "evidence_expected_zh": ["当前事实", "Agent 的逐项回答"],
            "not_sufficient_zh": ["不能只凭单次回测"],
            "industry_principle_zh": "从表达式和市场事实提出可证伪机制。",
            "industry_basis_refs": ["S-FIRST-PRINCIPLES"],
        },
        "mapped_obligations": (
            [{
                "obligation_id": "existing-1",
                "status": "open",
                "question_summary": "既有表达式身份义务",
                "detail_ref": (
                    "research-cycle-object:obligation:existing-1"
                ),
            }]
            if requirement_id.endswith("expression_identity")
            else []
        ),
        "report_requirements": [{
            "report_requirement_id": f"report.requirement.{requirement_id}",
            "method_ref": "explain_formula",
            "title_zh": "逐项报告",
            "requirement_ref": requirement_id,
            "subject_selector": {"kind": "verification_obligation"},
        }],
    }


def test_factor_facts_are_compact_source_free_and_have_latex() -> None:
    facts = compact_factor_facts(_describe(), factor_ref="SgCPS")

    assert facts["factor"]["name"] == "SgCPS"
    assert facts["factor"]["params"] == [
        {"alias": "P", "type": "FactorParam", "default_value": "CA"},
        {"alias": "N", "type": "WindowParam", "default_value": "20d"},
    ]
    assert facts["column_refs"] == ["HA", "LA"]
    assert facts["latex"] == r"\frac{2 \cdot P - \mathrm{HA}}{\mathrm{LA}}"
    assert facts["expression_ref"].startswith("factor-expression:sha256:")
    encoded = json.dumps(facts, ensure_ascii=False)
    assert "must not survive" not in encoded
    assert '"options"' not in encoded
    assert '"x"' not in encoded


def test_factor_latex_renders_operator_names_without_escaped_backslash() -> None:
    describe = _describe()
    describe["debug_graph"] = {
        "root_id": 4,
        "nodes": [
            {
                "id": 1, "key": "DataColumnParam", "cat": "leaf",
                "label": "HA", "inputs": [],
                "params": {
                    "alias": "HA", "type": "DataColumnParam",
                    "default_value": "HA",
                },
            },
            {
                "id": 2, "key": "DataColumnParam", "cat": "leaf",
                "label": "N", "inputs": [],
                "params": {
                    "alias": "N", "type": "WindowParam",
                    "default_value": "20d",
                },
            },
            {
                "id": 3, "key": "rolling_max", "cat": "ts",
                "label": "H", "inputs": [1, 2], "params": {},
            },
            {
                "id": 4, "key": "Return", "cat": "output",
                "label": "return", "inputs": [3], "params": {},
            },
        ],
    }

    latex = compact_factor_facts(describe, factor_ref="SgCPS")["latex"]

    assert latex == r"\operatorname{rolling\_max}\left(\mathrm{HA},N\right)"
    assert r"\backslash" not in latex


def test_skeleton_only_loads_explicit_requirements() -> None:
    requirement_id = "factor_semantics.expression_identity"
    skeleton = build_entry_assessment_skeleton(
        next_packet=_next_packet(),
        requirement_details={requirement_id: _detail(requirement_id)},
        factor_facts=compact_factor_facts(_describe(), factor_ref="SgCPS"),
        selected_requirement_ids=[requirement_id],
    )

    assert len(skeleton["assessments"]) == 1
    item = skeleton["assessments"][0]
    assert item["requirement_id"] == requirement_id
    assert skeleton["editing_contract"]["coverage_decisions"] == [
        "create_new", "map_existing", "no_material_issue",
    ]
    assert item["existing_obligations"][0]["obligation_ref"] == (
        "obligation:existing-1"
    )
    assert item["report"]["report_requirement_id"] == (
        f"report.requirement.{requirement_id}"
    )


def test_skeleton_rejects_requirement_outside_current_node() -> None:
    with pytest.raises(ValueError, match="not active"):
        build_entry_assessment_skeleton(
            next_packet=_next_packet(),
            requirement_details={"data.foo": _detail("data.foo")},
            factor_facts=compact_factor_facts(
                _describe(), factor_ref="SgCPS",
            ),
            selected_requirement_ids=["data.foo"],
        )


def _completed_document(decision: str) -> dict:
    requirement_id = "factor_semantics.expression_identity"
    value = build_entry_assessment_skeleton(
        next_packet=_next_packet(),
        requirement_details={requirement_id: _detail(requirement_id)},
        factor_facts=compact_factor_facts(_describe(), factor_ref="SgCPS"),
        selected_requirement_ids=[requirement_id],
    )
    assessment = value["assessments"][0]
    assessment["applicability"] = {
        "status": "applicable",
        "reason_zh": "当前研究直接依赖该表达式身份与版本。",
        "fact_refs": [value["factor_facts"]["expression_ref"]],
    }
    assessment["coverage"]["decision"] = decision
    assessment["coverage"]["obligation_refs"] = (
        ["obligation:existing-1"]
        if decision in {"create_new", "map_existing"}
        else []
    )
    assessment["resolution"] = {
        "route": "existing_evidence",
        "reuse_status": "exact",
        "validation_refs": [value["factor_facts"]["expression_ref"]],
    }
    assessment["entry_effect"] = {
        "status": "pass",
        "limitation_refs": [],
    }
    assessment["first_resolution_action"] = {
        "kind": "cli_evidence",
        "action_ref": "cli:factor-library.describe:SgCPS",
        "trial_ref": "",
        "description_zh": "复用当前表达式事实包完成身份核对。",
    }
    assessment["report"]["content_zh"] = [
        "表达式身份已按当前版本、参数、算子树和固定数据列逐项核对。",
        "既有义务与当前要求的关系及首个处置动作已明确记录。",
    ]
    return value


@pytest.mark.parametrize(
    "decision", ["create_new", "map_existing", "no_material_issue"],
)
def test_validation_supports_all_coverage_decisions(decision: str) -> None:
    document = _completed_document(decision)
    if decision == "no_material_issue":
        assessment = document["assessments"][0]
        assessment["coverage"]["obligation_refs"] = []

    result = validate_entry_assessment_document(document)

    assert result["valid"] is True
    assert result["entry_requirement_assessments"][0]["coverage"][
        "decision"
    ] == decision
    assert result["report_submission"]["items"][0][
        "report_requirement_id"
    ].startswith("report.requirement.")
    assert result["local_report_items"][0]["content_zh"][0].startswith(
        "表达式身份"
    )
    assert result["local_report_items"][0]["title_zh"] == (
        document["assessments"][0]["title_zh"]
    )


def test_report_projection_requires_inline_code_in_canonical_prose() -> None:
    document = _completed_document("map_existing")
    document["assessments"][0]["report"]["content_zh"] = [
        "$F 决定调度，$Rev 只声明方向；$100 仍是普通金额。",
    ]

    with pytest.raises(
        ValueError,
        match=r"must wrap FactorTester meta parameter \$F",
    ):
        validate_entry_assessment_document(document)


def test_report_projection_preserves_explicit_inline_code_and_amounts() -> None:
    document = _completed_document("map_existing")
    document["assessments"][0]["report"]["content_zh"] = [
        "`$F` 决定调度，`$Rev` 只声明方向；$100 仍是普通金额。",
    ]

    result = validate_entry_assessment_document(document)
    rows = result["local_report_items"][0]["content_zh"]
    assert rows == [
        "`$F` 决定调度，`$Rev` 只声明方向；$100 仍是普通金额。"
    ]


def test_report_projection_types_references_from_stable_prefixes() -> None:
    document = _completed_document("no_material_issue")
    assessment = document["assessments"][0]
    assessment["applicability"]["fact_refs"] = [
        "report:capability-resolution",
        "trace:" + "a" * 32,
        "evidence:screen-binding",
    ]
    assessment["resolution"]["validation_refs"] = list(
        assessment["applicability"]["fact_refs"]
    )

    result = validate_entry_assessment_document(document)
    links = result["local_report_items"][0]["links"]

    assert [
        (item["kind"], item["target_ref"]) for item in links
    ][:3] == [
        ("graph_reference", "report:capability-resolution"),
        ("graph_reference", "trace:" + "a" * 32),
        ("evidence", "evidence:screen-binding"),
    ]
    for item in links:
        validate_typed_target(
            kind=item["kind"],
            target_ref=item["target_ref"],
            field="entry projection",
        )


def test_validation_requires_a_trial_ref_for_trial_candidate() -> None:
    document = _completed_document("map_existing")
    action = document["assessments"][0]["first_resolution_action"]
    action.update({
        "kind": "trial_candidate",
        "action_ref": "",
        "trial_ref": "",
    })

    with pytest.raises(ValueError, match="trial_ref"):
        validate_entry_assessment_document(document)


def test_validation_reports_unedited_fields_by_requirement() -> None:
    requirement_id = "factor_semantics.expression_identity"
    document = build_entry_assessment_skeleton(
        next_packet=_next_packet(),
        requirement_details={requirement_id: _detail(requirement_id)},
        factor_facts=compact_factor_facts(_describe(), factor_ref="SgCPS"),
        selected_requirement_ids=[requirement_id],
    )

    with pytest.raises(
        ValueError,
        match=r"factor_semantics\.expression_identity\.applicability",
    ):
        validate_entry_assessment_document(document)


class _Result:
    def __init__(self, payload: dict) -> None:
        self.returncode = 0
        self.stdout = json.dumps(payload, ensure_ascii=False)
        self.stderr = ""
        self.argv = ["factortester"]


def test_node_advance_support_prepares_current_details_and_factor_describe(
    monkeypatch, tmp_path,
) -> None:
    requirement_id = "factor_semantics.expression_identity"
    calls: list[list[str]] = []

    def run(args: list[str], *, timeout: int):
        calls.append(args)
        if args[:3] == ["research", "graphs", "requirement-detail"]:
            return _Result(_detail(args[-1]))
        if args[:2] == ["factor-library", "describe"]:
            return _Result(_describe())
        raise AssertionError(args)

    monkeypatch.setattr(entry_assessment, "run_factortester", run)
    output = tmp_path / "entry.json"
    document = entry_assessment.prepare_entry_assessment(
        next_packet=_next_packet(),
        factor_family="SgCPS",
        factor_source="auto",
        output=output,
    )

    assert output.exists()
    assert len(calls) == 3
    assert calls[-1] == [
        "factor-library", "describe", "SgCPS",
        "--source", "auto", "--debug-graph", "--json",
    ]
    assert document["selected_requirement_ids"] == [
        requirement_id,
        "factor_semantics.timing_and_causality",
    ]


def test_node_advance_support_validates_editable_document() -> None:
    payload = entry_assessment.normalize_entry_assessment(
        _completed_document("map_existing")
    )

    assert payload["valid"] is True
    assert "entry_requirement_assessments" in payload
    assert "report_submission" in payload
