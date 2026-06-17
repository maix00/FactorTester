"""
Shared time-range routes:
  GET  /api/default_time_range
  POST /set_time_range

set_time_range 直接构造 DataTime，全链路使用 DataTime。
"""
import uuid as _uuid
import pandas as pd
from flask import request, jsonify
import Settings
from tools.data.types import DataTime
from server.services.factor_registry import get_factor_family_instance
import server.services.runtime_state as runtime_state
from server.services.runtime_state import factor_testers_lock
from . import shared_bp
from server.services.api_response import api_ok, route_guard


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


@shared_bp.route('/set_time_range', methods=['POST'])
@route_guard
def set_time_range():
    """设置当前页面 tab 的时间范围，绑定到 page_uuid。

    前端首次调用时不传 page_uuid → 后端生成并返回；
    后续同一 tab 调用时传回已有的 page_uuid → 覆盖更新。
    与 page_uuid 关联的 FactorTester 也会同步更新时间。
    """
    data = request.get_json()
    factor_family_alias = data['factor_family_alias']
    get_factor_family_instance(factor_family_alias)  # validates alias
    page_uuid = data.get('page_uuid', '').strip() or str(_uuid.uuid4())
    start_date      = data['start_date']
    start_time      = data['start_time']
    end_date        = data['end_date']
    end_time        = data['end_time']
    is_trading_day  = data.get('is_trading_day', False)
    timezone        = data.get('timezone', 'UTC')

    if is_trading_day:
        start_dt = DataTime(ts=pd.Timestamp(start_date).tz_localize(timezone), precision='day')
        end_dt   = DataTime(ts=pd.Timestamp(end_date).tz_localize(timezone),   precision='day')
    else:
        start_dt = DataTime(ts=pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone))
        end_dt   = DataTime(ts=pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone))

    # 写入 page_uuid 对应的时间
    runtime_state.set_runtime_time(page_uuid, start_dt, end_dt)

    # 更新与当前 page_uuid 绑定的 tester
    from tools.factors.FactorTester import FactorTester
    tester_count = 0
    with factor_testers_lock:
        for tester in runtime_state.factor_testers:
            if isinstance(tester, FactorTester) and getattr(tester, '_page_uuid', None) == page_uuid:
                tester.update_time_range(start_dt, end_dt)
                tester_count += 1

    return api_ok({
        'show_next': start_date <= end_date,
        'change_factor_tester': tester_count > 0,
        'page_uuid': page_uuid,  # 前端存储，后续请求传回
    })
