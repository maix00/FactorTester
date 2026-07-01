"""
Shared time-range routes:
  GET  /api/default_time_range
"""
import pandas as pd
from flask import jsonify
import settings as Settings
from . import shared_bp


@shared_bp.route('/api/default_time_range')
def get_default_time_range():
    start = Settings.default_test_start_date
    end   = Settings.default_test_end_date
    start_str = start.strftime('%Y-%m-%d') if isinstance(start, pd.Timestamp) else start
    end_str   = end.strftime('%Y-%m-%d')   if isinstance(end,   pd.Timestamp) else end
    if hasattr(Settings, 'timezone'):
        timezone = getattr(Settings, 'timezone')
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
