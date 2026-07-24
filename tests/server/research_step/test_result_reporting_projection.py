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


def test_projection_reports_authoritative_obligation_delta():
    receipt = {
        "proposal": {
            "recommended_action": "advance_trial_stage",
            "obligation_delta": [{
                "obligation_id": "predictive-validity",
                "from_state": "open",
                "to_state": "bounded",
                "criterion_ref": "criterion:ic-support",
            }],
        },
        "decision": {"disposition": "accepted"},
    }

    value = build_result_report_projection(
        action=_action(),
        plan_hash="c" * 64,
        rows=[_row()],
        receipt=receipt,
    )

    rows = value["local_report_items"][1]["content"]["rows"]
    assert "accepted" in rows[0]["text"]
    assert "open → bounded" in rows[1]["text"]
    assert rows[1]["link_ids"] == ["obligation-1"]


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
                '{"run_spec_version":2,"configuration_revision":1,'
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
