"""
Factor analysis-run routes:
  POST /api/factor_evaluation/evaluate
  POST /api/factor_type_analysis/analyze
"""
from __future__ import annotations

import traceback
import uuid

from flask import request, jsonify

from . import factors_bp
from ._common import request_page_uuid
from server.services import test_jobs
from server.services.session_runtime import current_user
from server.modules.single_factor_test.evaluation import FactorEvaluation
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.server_facade import (
    FactorTypeAnalysisRun,
)


def _run_factor_evaluation(data: dict, *, page_uuid: str) -> dict:
    evaluation = FactorEvaluation.from_request(data, page_uuid=page_uuid)
    return evaluation.run()


def _run_factor_type_analysis(data: dict, *, page_uuid: str) -> dict:
    run = FactorTypeAnalysisRun.from_request(data, page_uuid=page_uuid)
    return run.run()


def _result_error_response(exc: Exception):
    if isinstance(exc, LookupError):
        return jsonify({"success": False, "error": str(exc)}), 404
    if isinstance(exc, ValueError):
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


def _submit_analysis_job(kind: str, data: dict, runner) -> test_jobs.TestJob:
    page_uuid, error = request_page_uuid(data)
    if error is not None:
        status_code = error[1] if isinstance(error, tuple) and len(error) > 1 else 400
        body = error[0].get_json() if isinstance(error, tuple) and hasattr(error[0], "get_json") else {}
        raise ValueError(body.get("error") or f"invalid page_uuid ({status_code})")
    assert page_uuid is not None

    run_token = str(data.get("run_token") or f"{kind}-{uuid.uuid4().hex}")
    job = test_jobs.create_job(
        kind=kind,
        run_token=run_token,
        page_uuid=page_uuid,
        owner=current_user(),
        payload=data,
    )

    def _target(sink: test_jobs.TestJobSink) -> None:
        try:
            if sink.job.cancel_event.is_set():
                sink.emit_error(f"{kind} job cancelled before start", cancelled=True)
                return
            sink.emit_start(total=1, groups=1, phase="compute")
            result = runner(data, page_uuid=page_uuid)
            if sink.job.cancel_event.is_set():
                sink.emit_error(f"{kind} job cancelled", cancelled=True)
                return
            sink.emit_progress(1, 1, "compute")
            sink.emit_result(result)
        except Exception as exc:
            sink.emit_error(str(exc), traceback=traceback.format_exc())

    test_jobs.submit(job, _target)
    return job


def start_factor_evaluation_job(data: dict) -> test_jobs.TestJob:
    return _submit_analysis_job("factor_evaluation", data, _run_factor_evaluation)


def start_factor_type_analysis_job(data: dict) -> test_jobs.TestJob:
    return _submit_analysis_job("factor_type_analysis", data, _run_factor_type_analysis)


@factors_bp.route('/api/factor_evaluation/evaluate', methods=['POST'])
def factor_evaluation_evaluate():
    """Evaluate one factor for products selected directly from the product tree."""
    data = request.get_json() or {}
    page_uuid, error = request_page_uuid(data)
    if error is not None:
        return error

    try:
        return jsonify(_run_factor_evaluation(data, page_uuid=page_uuid))
    except Exception as exc:
        return _result_error_response(exc)


@factors_bp.route('/api/factor_type_analysis/analyze', methods=['POST'])
def factor_type_analysis_analyze():
    """
    因子类型分析 API。

    接收因子 + 产品 + 时间设置，返回：
      - 与各参照因子的相关性
      - 与各因子类别的聚合相关性
      - 最佳匹配类别
      - 品种间相关性矩阵
    """
    data = request.get_json() or {}
    page_uuid, error = request_page_uuid(data)
    if error is not None:
        return error

    try:
        return jsonify(_run_factor_type_analysis(data, page_uuid=page_uuid))
    except Exception as exc:
        return _result_error_response(exc)
