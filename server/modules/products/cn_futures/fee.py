"""
CN Futures specific endpoints.
  POST /get_fee_table
  POST /save_fee_modifications
  POST /get_fee_modifications

FeeModification lives in tools/products/transactions/fees.py (tool-layer domain model).
"""
import traceback
from flask import request, jsonify
from server.services.api_response import api_fail, api_ok
from tools.products.transactions.fees import (
    clean_modifications,
    sort_modifications,
    FeeModificationStore,
)
from . import cn_futures_bp

# ── Fee modifications persistent storage ────────────────────────────────────

_fee_store = FeeModificationStore()


@cn_futures_bp.route('/save_fee_modifications', methods=['POST'])
def save_fee_modifications():
    """Save fee modifications for a submission."""
    body = request.get_json(silent=True) or {}
    sub_id = str(body.get('submission_id') or '').strip()
    if not sub_id:
        return api_fail('缺少 submission_id')
    mods = body.get('modifications')
    if not isinstance(mods, list):
        mods = []

    cleaned = sort_modifications(clean_modifications(mods))
    _fee_store.save(sub_id, cleaned)
    return api_ok({'modifications': cleaned, 'count': len(cleaned)})


@cn_futures_bp.route('/get_fee_modifications', methods=['POST'])
def get_fee_modifications():
    """Retrieve fee modifications for a submission."""
    body = request.get_json(silent=True) or {}
    sub_id = str(body.get('submission_id') or '').strip()
    if not sub_id:
        return api_fail('缺少 submission_id')
    mods = _fee_store.load(sub_id)
    return api_ok({'modifications': mods, 'count': len(mods)})


# ── Fee table ──────────────────────────────────────────────────────────────

@cn_futures_bp.route('/get_fee_table', methods=['POST'])
def get_fee_table():
    from sources.LocalCNFutures.FeeData import get_table_for_display, fetch_and_save
    body = request.get_json(silent=True) or {}
    try:
        if body.get('force_refresh', False):
            fetch_and_save(force=True)
        rows = get_table_for_display()
        source_date = None
        if rows:
            source_date = rows[0].get('date')
        return jsonify({
            'success': True,
            'rows': rows,
            'fee_source': 'current_snapshot',
            'fee_source_date': source_date,
            'fee_notice': '历史回测使用当前可得费率推测历史费率；若存在历史费率快照，则按快照日期向前填充。',
        })
    except Exception as e:
        traceback.print_exc()
        return api_fail(str(e), status_code=500)
