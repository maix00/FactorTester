"""
Shared time-range routes:
  GET  /api/default_time_range
  POST /set_time_range
"""
import pandas as pd
from flask import request, jsonify
import Settings
from server.shared import get_factor_family_instance, _factor_testers_lock
import server.shared as shared
from . import shared_bp


@shared_bp.route('/api/default_time_range')
def get_default_time_range():
    start = Settings.default_test_start_date
    end   = Settings.default_test_end_date
    start_str = start.strftime('%Y-%m-%d') if isinstance(start, pd.Timestamp) else start
    end_str   = end.strftime('%Y-%m-%d')   if isinstance(end,   pd.Timestamp) else end
    if hasattr(Settings, 'timezone'):
        timezone = Settings.timezone
    elif isinstance(start, pd.Timestamp) and start.tz is not None:
        timezone = str(start.tz)
    else:
        timezone = 'Asia/Shanghai'
    return jsonify({
        'start_date': start_str,
        'start_time': Settings.default_day_start_time,
        'end_date':   end_str,
        'end_time':   Settings.default_day_end_time,
        'timezone':   timezone,
        'cn_futures_day_start':   getattr(Settings, 'default_cn_futures_day_start',   '09:00'),
        'cn_futures_day_end':     getattr(Settings, 'default_cn_futures_day_end',     '15:00'),
        'cn_futures_night_start': getattr(Settings, 'default_cn_futures_night_start', '21:00'),
        'cn_futures_night_end':   getattr(Settings, 'default_cn_futures_night_end',   '15:00'),
    })


@shared_bp.route('/set_time_range', methods=['POST'])
def set_time_range():
    data = request.get_json()
    try:
        factor_family_alias = data['factor_family_alias']
        get_factor_family_instance(factor_family_alias)  # validates alias
        start_date      = data['start_date']
        start_time      = data['start_time']
        end_date        = data['end_date']
        end_time        = data['end_time']
        is_trading_day  = data.get('is_trading_day', False)
        timezone        = data.get('timezone', 'UTC')

        shared.start_calc_point = (
            pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
            if not is_trading_day else pd.Timestamp(start_date).date()
        )
        shared.start_point = (
            pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
            if not is_trading_day else pd.Timestamp(start_date).tz_localize(timezone)
        )
        shared.end_point = (
            pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
            if not is_trading_day else pd.Timestamp(end_date).tz_localize(timezone)
        )

        with _factor_testers_lock:
            _testers_snapshot = list(shared.factor_testers)
        if _testers_snapshot:
            from tools.factors.FactorTester import FactorTester
            for tester in _testers_snapshot:
                assert isinstance(tester, FactorTester)
                tester.update_time_range((shared.start_point, shared.end_point))

        return jsonify({
            'success': True,
            'show_next': start_date <= end_date,
            'change_factor_tester': bool(_testers_snapshot),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
