"""
CN Futures specific endpoints.
  POST /get_fee_table
"""
import os, sys, traceback
from flask import request, jsonify
from server.services.api_response import api_fail
from . import cn_futures_bp


@cn_futures_bp.route('/get_fee_table', methods=['POST'])
def get_fee_table():
    _src = os.path.join(os.getcwd(), 'sources')
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from sources.FeeData import get_table_for_display, fetch_and_save
    body = request.get_json(silent=True) or {}
    try:
        if body.get('force_refresh', False):
            fetch_and_save(force=True)
        rows = get_table_for_display()
        return jsonify({'success': True, 'rows': rows})
    except Exception as e:
        traceback.print_exc()
        return api_fail(str(e), status_code=500)
