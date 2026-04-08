/**
 * 时间范围模块独立脚本
 * 功能：独立年/月/日/时/分输入、时区输入、交易日/期货日盘/夜盘选项、进位/退位逻辑
 * 通过 API /api/default_time_range 获取默认值
 */

(function() {
    // DOM 元素引用
    const startYear = document.getElementById('start_year');
    const startMonth = document.getElementById('start_month');
    const startDay = document.getElementById('start_day');
    const startHour = document.getElementById('start_hour');
    const startMinute = document.getElementById('start_minute');
    const endYear = document.getElementById('end_year');
    const endMonth = document.getElementById('end_month');
    const endDay = document.getElementById('end_day');
    const endHour = document.getElementById('end_hour');
    const endMinute = document.getElementById('end_minute');
    const isTradingDayCheck = document.getElementById('is_trading_day');
    const isCnFuturesDayCheck = document.getElementById('is_cn_futures_day');
    const isCnFuturesNightCheck = document.getElementById('is_cn_futures_night');
    const timezoneInput = document.getElementById('timezone_input');
    const confirmBtn = document.getElementById('confirm_time_btn');
    const statusSpan = document.getElementById('confirm_time_status');
    const currentSettingsSpan = document.getElementById('current_settings');

    // 全局配置（将从 API 加载）
    let default_day_start_time = '09:30';
    let default_day_end_time = '15:00';
    let default_cn_futures_day_start = '09:00';
    let default_cn_futures_day_end = '15:00';
    let default_cn_futures_night_start = '21:00';
    let default_cn_futures_night_end = '15:00';
    let factorFamilyAlias = '';

    // ---------- 辅助函数 ----------
    function pad(n) {
        n = parseInt(n);
        return n < 10 ? '0' + n : n.toString();
    }

    function getMaxDay(year, month) {
        year = parseInt(year);
        month = parseInt(month);
        if (isNaN(year) || isNaN(month) || month < 1 || month > 12) return 31;
        return new Date(year, month, 0).getDate();
    }

    function setTimeInputsDisabled(disabled) {
        [startHour, startMinute, endHour, endMinute].forEach(el => {
            if (el) {
                el.disabled = disabled;
                el.style.background = disabled ? '#ccc' : '#eee';
            }
        });
    }

    // 进位/退位逻辑（与原版相同）
    function carryOver(thisId, thisMin, thisMax, lastId, prefix) {
        const thisElem = document.getElementById(thisId);
        const lastElem = document.getElementById(lastId);
        if (!thisElem || !lastElem) return;
        let thisNum = parseInt(thisElem.value);
        let lastNum = parseInt(lastElem.value);

        if (isNaN(thisNum)) {
            thisElem.value = pad(thisMin);
            return;
        }
        if (isNaN(lastNum)) {
            lastElem.value = pad(thisMin);
            if (thisNum < thisMin) thisElem.value = pad(thisMin);
            else if (thisNum > thisMax) thisElem.value = pad(thisMax);
            else thisElem.value = pad(thisNum);
            return;
        }
        if (thisNum === thisMin - 1) {
            lastElem.value = pad(lastNum - 1);
            if (thisId.endsWith('day')) {
                thisElem.value = pad(1);
                adjustTime(lastId, prefix);
                const newMonth = parseInt(document.getElementById(prefix + '_month').value);
                const newYear = parseInt(document.getElementById(prefix + '_year').value);
                const maxDay = getMaxDay(newYear, newMonth);
                thisElem.value = pad(maxDay);
            } else {
                thisElem.value = pad(thisMax);
            }
            adjustTime(lastId, prefix);
            lastElem.value = pad(parseInt(lastElem.value));
            return;
        }
        if (thisNum === thisMax + 1) {
            lastElem.value = pad(lastNum + 1);
            thisElem.value = pad(thisMin);
            adjustTime(lastId, prefix);
            return;
        }
        if (thisNum > thisMax + 1) {
            thisElem.value = pad(thisMax);
            return;
        }
        if (thisNum < thisMin - 1) {
            thisElem.value = pad(thisMin);
            return;
        }
        thisElem.value = pad(thisNum);
    }

    function adjustTime(id, prefix) {
        const minuteId = prefix + '_minute';
        const hourId = prefix + '_hour';
        const dayId = prefix + '_day';
        const yearId = prefix + '_year';
        const monthId = prefix + '_month';

        const minuteElem = document.getElementById(minuteId);
        if (!minuteElem) return;
        let minuteVal = parseInt(minuteElem.value);
        if (isNaN(minuteVal) || minuteVal > 59 || minuteVal < 0) {
            carryOver(minuteId, 0, 59, hourId, prefix);
            return;
        } else {
            minuteElem.value = pad(minuteVal);
        }

        const hourElem = document.getElementById(hourId);
        if (!hourElem) return;
        let hourVal = parseInt(hourElem.value);
        if (isNaN(hourVal) || hourVal > 23 || hourVal < 0) {
            carryOver(hourId, 0, 23, dayId, prefix);
            return;
        } else {
            hourElem.value = pad(hourVal);
        }

        const dayElem = document.getElementById(dayId);
        const yearElem = document.getElementById(yearId);
        const monthElem = document.getElementById(monthId);
        if (!dayElem || !yearElem || !monthElem) return;
        let year = parseInt(yearElem.value);
        let month = parseInt(monthElem.value);
        let dayVal = parseInt(dayElem.value);
        let maxDay = getMaxDay(year, month);

        if (id.endsWith('month') && dayVal > maxDay) {
            dayElem.value = pad(maxDay);
        }

        if (isNaN(dayVal) || dayVal > maxDay || dayVal < 1) {
            carryOver(dayId, 1, maxDay, monthId, prefix);
            return;
        } else {
            dayElem.value = pad(dayVal);
        }

        if (isNaN(month) || month > 12 || month < 1) {
            carryOver(monthId, 1, 12, yearId, prefix);
            return;
        } else {
            monthElem.value = pad(month);
        }

        if (isNaN(year) || year < 1900 || year > 2100) {
            if (year < 1900) yearElem.value = '1900';
            else yearElem.value = '2100';
            return;
        } else {
            yearElem.value = pad(year);
        }
    }

    // 更新时间显示和按钮状态
    function updateCurrentSettings() {
        if (!startYear || !endYear) return;
        const sy = startYear.value, sm = pad(startMonth.value), sd = pad(startDay.value);
        const sh = pad(startHour.value), smin = pad(startMinute.value);
        const ey = endYear.value, em = pad(endMonth.value), ed = pad(endDay.value);
        const eh = pad(endHour.value), emin = pad(endMinute.value);
        const isTradingDay = isTradingDayCheck.checked;

        currentSettingsSpan.innerText = `起始时间: ${sy}-${sm}-${sd} ${sh}:${smin}, 终末时间: ${ey}-${em}-${ed} ${eh}:${emin}${isTradingDay ? ' (交易日)' : ''}`;

        // 验证起始时间 <= 终末时间
        const startDt = new Date(`${sy}-${sm}-${sd}T${sh}:${smin}:00`);
        const endDt = new Date(`${ey}-${em}-${ed}T${eh}:${emin}:00`);
        const isValid = !isNaN(startDt) && !isNaN(endDt) && startDt <= endDt;

        if (isValid) {
            confirmBtn.disabled = false;
            confirmBtn.style.background = '#0078d4';
            confirmBtn.style.cursor = 'pointer';
            statusSpan.innerText = '点击确定按钮更新因子计算的时间范围';
            statusSpan.style.color = '#888';
        } else {
            confirmBtn.disabled = true;
            confirmBtn.style.background = '#ccc';
            confirmBtn.style.cursor = 'not-allowed';
            statusSpan.innerText = '⚠️ 起始时间必须 ≤ 终末时间';
            statusSpan.style.color = '#d40000';
        }
    }

    // ---------- 交易日/期货切换 ----------
    function toggleTradingDay() {
        const isTradingDay = isTradingDayCheck.checked;
        if (isTradingDay) {
            isCnFuturesDayCheck.checked = false;
            isCnFuturesNightCheck.checked = false;
            startHour.value = "00";
            startMinute.value = "00";
            endHour.value = "00";
            endMinute.value = "00";
            setTimeInputsDisabled(true);
        } else {
            const [sh, sm] = default_day_start_time.split(':');
            const [eh, em] = default_day_end_time.split(':');
            startHour.value = pad(sh);
            startMinute.value = pad(sm);
            endHour.value = pad(eh);
            endMinute.value = pad(em);
            setTimeInputsDisabled(false);
        }
        updateCurrentSettings();
    }

    function toggleCnFutures(event) {
        const target = event.target;
        if (target === isCnFuturesDayCheck && isCnFuturesDayCheck.checked) isCnFuturesNightCheck.checked = false;
        else if (target === isCnFuturesNightCheck && isCnFuturesNightCheck.checked) isCnFuturesDayCheck.checked = false;
        if (isCnFuturesDayCheck.checked || isCnFuturesNightCheck.checked) isTradingDayCheck.checked = false;

        if (isCnFuturesDayCheck.checked) {
            const [sh, sm] = default_cn_futures_day_start.split(':');
            const [eh, em] = default_cn_futures_day_end.split(':');
            startHour.value = pad(sh);
            startMinute.value = pad(sm);
            endHour.value = pad(eh);
            endMinute.value = pad(em);
            setTimeInputsDisabled(true);
        } else if (isCnFuturesNightCheck.checked) {
            const [sh, sm] = default_cn_futures_night_start.split(':');
            const [eh, em] = default_cn_futures_night_end.split(':');
            startHour.value = pad(sh);
            startMinute.value = pad(sm);
            endHour.value = pad(eh);
            endMinute.value = pad(em);
            setTimeInputsDisabled(true);
        } else {
            const [sh, sm] = default_day_start_time.split(':');
            const [eh, em] = default_day_end_time.split(':');
            startHour.value = pad(sh);
            startMinute.value = pad(sm);
            endHour.value = pad(eh);
            endMinute.value = pad(em);
            setTimeInputsDisabled(false);
        }
        updateCurrentSettings();
    }

    // ---------- 提交时间范围 ----------
    function confirmTimeRange() {
        const data = {
            factor_family_alias: factorFamilyAlias,
            start_date: `${startYear.value}-${pad(startMonth.value)}-${pad(startDay.value)}`,
            start_time: `${pad(startHour.value)}:${pad(startMinute.value)}`,
            end_date: `${endYear.value}-${pad(endMonth.value)}-${pad(endDay.value)}`,
            end_time: `${pad(endHour.value)}:${pad(endMinute.value)}`,
            is_trading_day: isTradingDayCheck.checked,
            is_cn_futures_day: isCnFuturesDayCheck.checked,
            is_cn_futures_night: isCnFuturesNightCheck.checked,
            timezone: timezoneInput.value
        };

        statusSpan.innerText = '保存中...';
        statusSpan.style.color = '#0078d4';

        fetch('/set_time_range', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                let msg = '✓ 已保存';
                if (res.start_calc_param_val) {
                    msg += '，因子起始计算时间更新为: ' + res.start_calc_param_val;
                } else {
                    msg += '，时间范围已更新';
                }
                if (res.change_factor_tester) {
                    msg += '，正在更新因子测试中...';
                }
                statusSpan.innerText = msg;
                statusSpan.style.color = '#28a745';
                setTimeout(() => {
                    if (statusSpan.innerText === msg) statusSpan.innerText = '';
                }, 3000);
            } else {
                statusSpan.innerText = '保存失败: ' + (res.error || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        })
        .catch(err => {
            statusSpan.innerText = '网络错误: ' + err.message;
            statusSpan.style.color = '#d40000';
        });
    }

    // 绑定输入框的 blur/input 事件
    // 在 bindInputEvents 函数中，区分 input 和 blur 的处理
    function bindInputEvents() {
        const ids = ['start_year','start_month','start_day','start_hour','start_minute',
                    'end_year','end_month','end_day','end_hour','end_minute'];
        ids.forEach(id => {
            const elem = document.getElementById(id);
            if (!elem) return;
            const prefix = id.startsWith('start') ? 'start' : 'end';
            
            // input 事件：只做基本限制（例如小时不超过23，分钟不超过59，年份不超过当前长度限制）
            elem.addEventListener('input', function(e) {
                let val = this.value;
                // 限制只能输入数字（如果输入框类型是 text 或 number 已经限制，但为了安全）
                if (val && !/^\d*$/.test(val)) {
                    this.value = val.replace(/\D/g, '');
                    return;
                }
                // 针对年份：允许任意长度，不做范围修正
                if (id.endsWith('year')) {
                    // 不限制，只让用户输入
                    return;
                }
                // 针对月份、日、小时、分钟：做临时边界限制（防止超出范围但允许中间值）
                let max = {month:12, day:31, hour:23, minute:59}[id.split('_')[1]];
                if (max && val.length > 0) {
                    let num = parseInt(val);
                    if (!isNaN(num) && num > max) {
                        this.value = max;
                    }
                }
            });
            
            // blur 事件：做完整的进位/退位和范围修正
            elem.addEventListener('blur', function() {
                adjustTime(id, prefix);
                updateCurrentSettings();
            });
        });
    }

    // 加载默认设置（从 API）
    function loadDefaultSettings() {
        return fetch('/api/default_time_range')
            .then(res => res.json())
            .then(data => {
                // 解析起始时间
                const startDate = data.start_date.split('-');
                const [startHourStr, startMinuteStr] = data.start_time.split(':');
                const endDate = data.end_date.split('-');
                const [endHourStr, endMinuteStr] = data.end_time.split(':');
                
                startYear.value = startDate[0];
                startMonth.value = pad(startDate[1]);
                startDay.value = pad(startDate[2]);
                startHour.value = pad(startHourStr);
                startMinute.value = pad(startMinuteStr);
                
                endYear.value = endDate[0];
                endMonth.value = pad(endDate[1]);
                endDay.value = pad(endDate[2]);
                endHour.value = pad(endHourStr);
                endMinute.value = pad(endMinuteStr);
                
                timezoneInput.value = data.timezone || 'Asia/Shanghai';
                
                // 保存默认时间配置（用于重置）
                default_day_start_time = data.start_time;
                default_day_end_time = data.end_time;
                default_cn_futures_day_start = data.cn_futures_day_start || '09:00';
                default_cn_futures_day_end = data.cn_futures_day_end || '15:00';
                default_cn_futures_night_start = data.cn_futures_night_start || '21:00';
                default_cn_futures_night_end = data.cn_futures_night_end || '15:00';
                
                // 获取因子家族别名（从页面元素 data-factor-alias 获取）
                const sectionElem = document.querySelector('.section[data-factor-alias]');
                if (sectionElem) factorFamilyAlias = sectionElem.getAttribute('data-factor-alias');
                
                // 初始化复选框状态（默认都未勾选）
                isTradingDayCheck.checked = false;
                isCnFuturesDayCheck.checked = false;
                isCnFuturesNightCheck.checked = false;
                setTimeInputsDisabled(false);
                
                // 更新显示
                updateCurrentSettings();
            })
            .catch(err => {
                console.error('加载默认时间设置失败:', err);
                statusSpan.innerText = '加载默认设置失败';
                statusSpan.style.color = '#d40000';
            });
    }

    // 初始化
    function init() {
        loadDefaultSettings().then(() => {
            bindInputEvents();
            isTradingDayCheck.addEventListener('change', toggleTradingDay);
            isCnFuturesDayCheck.addEventListener('change', toggleCnFutures);
            isCnFuturesNightCheck.addEventListener('change', toggleCnFutures);
            confirmBtn.addEventListener('click', confirmTimeRange);
            toggleTradingDay(); // 确保交易日状态正确
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();