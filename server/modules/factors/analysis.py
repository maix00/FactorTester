"""
Factor analysis-run routes:
  POST /api/factor_evaluation/evaluate
  POST /api/factor_type_analysis/analyze
"""
from __future__ import annotations

import traceback

from flask import request, jsonify

from . import factors_bp
from ._common import request_page_uuid
from server.modules.single_factor_test.evaluation import FactorEvaluation
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.server_facade import (
    FactorTypeAnalysisRun,
)


@factors_bp.route('/api/factor_evaluation/evaluate', methods=['POST'])
def factor_evaluation_evaluate():
    """Evaluate one factor for products selected directly from the product tree."""
    data = request.get_json() or {}
    page_uuid, error = request_page_uuid(data)
    if error is not None:
        return error

    try:
        evaluation = FactorEvaluation.from_request(data, page_uuid=page_uuid)
        return jsonify(evaluation.run())
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


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
        run = FactorTypeAnalysisRun.from_request(data, page_uuid=page_uuid)
        return jsonify(run.run())
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500
