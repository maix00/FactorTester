"""
Shared time-range routes:
  GET  /api/default_time_range
  POST /set_time_range
set_time_range 直接构造 DataTime，全链路使用 DataTime。
"""
import pandas as pd
from flask import request, jsonify
import Settings
from tools.data.types import DataTime
from server.services.factor_registry import get_factor_family_instance
import server.services.page_runtime as page_runtime
from server.services.session_runtime import current_user
from . import shared_bp
from server.services.api_response import api_fail, api_ok, route_guard


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

    page_uuid 由页面打开时生成并随后续请求传回；
    这里不再负责生成 page_uuid，只负责更新其运行时状态。
    """
    data = request.get_json()
    factor_family_alias = data['factor_family_alias']
    page_uuid = str(data.get('page_uuid', '')).strip()
    if not page_uuid:
        return api_fail('缺少 page_uuid，请先打开页面并生成页面上下文', 400)
    get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)  # validates alias & warms page cache
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
    page_runtime.set_runtime_time(page_uuid, start_dt, end_dt)
    page_runtime.register_page(page_uuid, owner=current_user(), factor_family_alias=factor_family_alias)

    # 更新与当前 page_uuid 绑定的 tester
    from tools.factors.FactorTester import FactorTester
    tester_count = 0
    for tester in page_runtime.iter_factor_testers(page_uuid):
        if isinstance(tester, FactorTester):
            tester.update_time_range(start_dt, end_dt)
            tester_count += 1

    return api_ok({
        'show_next': start_date <= end_date,
        'change_factor_tester': tester_count > 0,
        'page_uuid': page_uuid,  # 前端存储，后续请求传回
    })
