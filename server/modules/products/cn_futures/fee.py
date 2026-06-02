"""
CN Futures specific endpoints.
  POST /get_fee_table
"""
import traceback
from flask import request, jsonify
from server.services.api_response import api_fail
from . import cn_futures_bp


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
