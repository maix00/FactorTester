import sqlite3

from server.services.research_step.result_reporting.presentations import (
    result_presentations,
)
from server.services.research_step.result_reporting.projection import (
    build_result_report_projection,
)
from server.services.research_step.result_reporting import service


def _action():
    return {
        "action_id": "action:ic",
        "obligation_refs": ["obligation:predictive-validity"],
        "output_evidence_refs": ["evidence:" + "a" * 64],
    }


def _row():
    return {
        "index": 1,
        "run_id": "run-1",
        "job_id": "job-1",
        "kind": "ic",
        "status": "succeeded",
        "trial_role": "candidate",
        "run_spec_hash": "b" * 64,
        "run_spec_alias_zh": "截面 IC · 日盘",
        "result_summary": {
            "ic_stats": {
                "columns": ["index", "SgCPS"],
                "rows": [
                    {"index": "mean", "SgCPS": 0.031},
                    {"index": "IR", "SgCPS": 0.42},
                    {"index": "t_stat", "SgCPS": 2.1},
                ],
            },
            "full_result_bytes": 999999,
        },
    }


def test_projection_keeps_typed_links_and_bounded_scalar_results():
    value = build_result_report_projection(
        action=_action(),
        plan_hash="c" * 64,
        rows=[_row()],
        receipt=None,
    )

    items = value["local_report_items"]
    links = [
        link for item in items for link in item["links"]
    ]
    assert {(item["kind"], item["target_ref"]) for item in links} >= {
        ("run_spec", "runspec:" + "b" * 64),
        ("run", "run:run-1"),
        ("job", "job:job-1"),
        ("evidence", "evidence:" + "a" * 64),
        ("trial_plan", "trial-plan:sha256:" + "c" * 64),
    }
    rows = items[0]["content"]["rows"]
    assert ["IC 均值 · SgCPS", "0.031"] == rows[0]["cells"][-2:]
    assert rows[0]["cells"][:4] == [
        "截面 IC 检验", "候选方案", "已成功", "日盘",
    ]
    assert "action:" not in items[0]["title_zh"]
    assert all("full_result_bytes" not in str(row) for row in rows)
    assert "不可恢复" in items[1]["content"]["rows"][0]["text"]
    assert items[0]["section_role"] == "trial_result"
    assert items[1]["section_role"] == "trial_audit"


def test_projection_does_not_repeat_prefixed_action_subject():
    value = build_result_report_projection(
        action={
            **_action(),
            "action_id": "action:in-sample-ic",
        },
        plan_hash="c" * 64,
        rows=[_row()],
        receipt=None,
    )

    assert value["action_id"] == "action:in-sample-ic"
    assert [
        item["subject_ref"] for item in value["local_report_items"]
    ] == ["action:in-sample-ic", "audit:in-sample-ic"]
    assert all(
        "action:action:" not in item["subject_ref"]
        for item in value["local_report_items"]
    )


def test_projection_reports_authoritative_obligation_delta():
    receipt = {
        "proposal": {
            "recommended_action": "advance_trial_stage",
            "obligation_delta": [{
                "obligation_id": "predictive-validity",
                "from_state": "open",
                "to_state": "bounded",
                "criterion_ref": (
                    "criterion:2024-day-night-cross-sectional-ic-reviewed"
                ),
            }],
        },
        "decision": {"disposition": "accepted"},
    }

    value = build_result_report_projection(
        action=_action(),
        plan_hash="c" * 64,
        rows=[_row()],
        receipt=receipt,
        presentations={
            "obligations": {
                "obligation:predictive-validity": {
                    "alias_zh": "样本内截面 IC 是否提供可复现的预测信息？",
                },
            },
            "evidence": {
                "evidence:" + "a" * 64: {
                    "alias_zh": "日盘截面 IC 结果",
                    "summary_zh": "IC 均值 0.031；t 统计量 2.1",
                },
            },
        },
    )

    rows = value["local_report_items"][1]["content"]["rows"]
    assert rows[0]["text"] == "审计结论：已接受；后续路径：进入下一试验阶段。"
    assert "样本内截面 IC 是否提供可复现的预测信息？" in rows[1]["text"]
    assert "待处理 → 已限定" in rows[1]["text"]
    assert "2024 年日盘与夜盘截面 IC 结果已审阅" in rows[1]["text"]
    assert rows[1]["link_ids"] == ["obligation-1"]
    links = value["local_report_items"][1]["links"]
    assert value["local_report_items"][1]["section_role"] == "obligation_changes"
    assert next(
        item for item in links if item["kind"] == "evidence"
    )["label"] == "日盘截面 IC 结果"
    assert next(
        item for item in links if item["kind"] == "obligation"
    )["label"] == "样本内截面 IC 是否提供可复现的预测信息？"


def test_evidence_chip_label_stays_bounded_with_long_factor_alias():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    presentation = result_presentations(
        connection,
        instance_id="instance-1",
        branch_id="branch-1",
        rows=[{
            **_row(),
            "evidence_ref": "evidence:" + "a" * 64,
            "run_spec_alias_zh": (
                "截面 IC · 夜盘 · " + "超长因子参数说明" * 100
            ),
        }],
        receipt=None,
    )["evidence"]["evidence:" + "a" * 64]

    assert presentation["alias_zh"] == "夜盘 · 截面 IC 结果"
    assert len(presentation["alias_zh"].encode("utf-8")) <= 160
    assert "IC 均值 0.031" in presentation["summary_zh"]
    assert "t 统计量 2.1" in presentation["summary_zh"]


def test_projection_keeps_bounded_backtest_group_metrics():
    row = _row()
    row.update({
        "kind": "backtest",
        "result_summary": {
            "metrics": {
                "long-short": {
                    "Sharpe": 1.21,
                    "Max Drawdown": -0.083,
                    "ignored_vector": [1, 2],
                },
            },
            "groups": [{
                "key": "long-short",
                "annualized_return": 0.18,
                "equity_curve_points_persisted": False,
            }],
        },
    })

    value = build_result_report_projection(
        action=_action(), plan_hash="c" * 64, rows=[row], receipt=None,
    )

    table = value["local_report_items"][0]["content"]
    labels = {item["cells"][-2]: item["cells"][-1] for item in table["rows"]}
    assert labels["多空组合 · 夏普比率"] == "1.21"
    assert labels["多空组合 · 最大回撤"] == "-0.083"
    assert labels["多空组合 · 年化收益率"] == "0.18"
    assert "ignored_vector" not in labels


def test_retry_attempts_are_filtered_by_admitted_evidence_ref(monkeypatch):
    rows = []
    for job_id, run_id, run_hash in (
        ("job-old", "run-old", "1" * 64),
        ("job-admitted", "run-new", "2" * 64),
    ):
        rows.append({
            "job_id": job_id, "run_id": run_id, "kind": "ic",
            "run_kind": "ic", "status": "succeeded",
            "run_spec_hash": run_hash,
            "run_spec_json": (
                '{"run_spec_version":3,"configuration_revision":1,'
                '"analyses":["ic"],"configuration":{}}'
            ),
            "trial_role": "candidate", "trial_stage": "validation",
            "decision_contract_hash": "3" * 64,
            "methodology_hash": "4" * 64,
            "run_trial_plan_hash": "5" * 64,
            "result_summary_json": '{"mean_ic":0.02}',
        })

    monkeypatch.setattr(
        service.JobRepository, "record_from_row",
        lambda self, row: type("Job", (), {"job_id": row["job_id"]})(),
    )
    hashes = {"job-old": "a" * 64, "job-admitted": "b" * 64}
    monkeypatch.setattr(
        service, "project_job_attempt_evidence",
        lambda job, **kwargs: {"envelope_hash": hashes[job.job_id]},
    )

    result = service._admitted_rows(
        rows, artifacts=[],
        evidence_refs={"evidence:" + "b" * 64},
    )

    assert [item["job_id"] for item in result] == ["job-admitted"]
