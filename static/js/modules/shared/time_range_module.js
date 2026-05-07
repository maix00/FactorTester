/**
 * 时间范围模块独立脚本
 * 功能：独立年/月/日/时/分输入、时区输入、交易日/期货日盘/夜盘选项、进位/退位逻辑
 * 通过 API /api/default_time_range 获取默认值
 * 共用 date_utils.js 中的 pad / getMaxDay / carryOver / adjustTime 函数
 */

(function() {
    // 等待 DateUtils 加载完成
    function waitForDateUtils(callback) {
        if (window.DateUtils) {
            callback();
        } else {
            setTimeout(function() { waitForDateUtils(callback); }, 50);
        }
    }

    // DOM 元素引用
    var startYear = document.getElementById('start_year');
    var startMonth = document.getElementById('start_month');
    var startDay = document.getElementById('start_day');
    var startHour = document.getElementById('start_hour');
    var startMinute = document.getElementById('start_minute');
    var endYear = document.getElementById('end_year');
    var endMonth = document.getElementById('end_month');
    var endDay = document.getElementById('end_day');
    var endHour = document.getElementById('end_hour');
    var endMinute = document.getElementById('end_minute');
    var isTradingDayCheck = document.getElementById('is_trading_day');
    var isCnFuturesDayCheck = document.getElementById('is_cn_futures_day');
    var isCnFuturesNightCheck = document.getElementById('is_cn_futures_night');
    var timezoneInput = document.getElementById('timezone_input');
    var confirmBtn = document.getElementById('confirm_time_btn');
    var statusSpan = document.getElementById('confirm_time_status');
    var currentSettingsSpan = document.getElementById('current_settings');

    // 全局配置（将从 API 加载）
    var default_day_start_time = '09:30';
    var default_day_end_time = '15:00';
    var default_cn_futures_day_start = '09:00';
    var default_cn_futures_day_end = '15:00';
    var default_cn_futures_night_start = '21:00';
    var default_cn_futures_night_end = '15:00';
    var factorFamilyAlias = '';

    // ---------- 辅助函数（直接使用 DateUtils） ----------
    function pad(n) { return window.DateUtils.pad(n); }
    function getMaxDay(year, month) { return window.DateUtils.getMaxDay(year, month); }

    function setTimeInputsDisabled(disabled) {
        [startHour, startMinute, endHour, endMinute].forEach(function(el) {
            if (el) {
                el.disabled = disabled;
                el.style.background = disabled ? '#ccc' : '#eee';
            }
        });
    }

    // 进位/退位逻辑（直接使用 DateUtils）
    function carryOver(thisId, thisMin, thisMax, lastId, prefix) {
        window.DateUtils.carryOver(thisId, thisMin, thisMax, lastId, prefix);
    }

    function adjustTime(id, prefix) {
        window.DateUtils.adjustTime(id, prefix);
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
            page_uuid: window._pageUuid || '',  // 已有则传回，首次为空后端生成
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
                // 存储后端返回的 page_uuid，后续请求传回
                if (res.page_uuid) {
                    window._pageUuid = res.page_uuid;
                }
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
                // 自动退出抽屉
                var drawer = document.getElementById('time-range-drawer');
                if (drawer) drawer.classList.remove('open');
                var badge = document.getElementById('user-badge');
                if (badge) badge.style.display = '';
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
                // 通知其他模块默认时间已就绪
                document.dispatchEvent(new CustomEvent('timeRangeDefaultLoaded'));
            })
            .catch(err => {
                console.error('加载默认时间设置失败:', err);
                statusSpan.innerText = '加载默认设置失败';
                statusSpan.style.color = '#d40000';
            });
    }

    // ---------- 初始化 ----------
    function init() {
        loadDefaultSettings().then(function() {
            bindInputEvents();
            isTradingDayCheck.addEventListener('change', toggleTradingDay);
            isCnFuturesDayCheck.addEventListener('change', toggleCnFutures);
            isCnFuturesNightCheck.addEventListener('change', toggleCnFutures);
            confirmBtn.addEventListener('click', confirmTimeRange);
            toggleTradingDay(); // 确保交易日状态正确
        });
    }

    // 确保 DateUtils 已加载后再初始化
    waitForDateUtils(init);

    // ── 时间模板管理 ─────────────────────────────────────────────────────────
    var $tSel  = document.getElementById('time-tpl-select');
    var $tLbl  = document.getElementById('time-tpl-name-label');
    var $tInp  = document.getElementById('time-tpl-name-input');
    var $tStat = document.getElementById('time-tpl-status');

    if (!$tSel) return;

    function tTplStatus(msg, ok) {
        $tStat.textContent = msg;
        $tStat.style.color = ok ? '#28a745' : '#d40000';
        setTimeout(function() { if ($tStat.textContent === msg) $tStat.textContent = ''; }, 2500);
    }

    function collectCurrentTimeData() {
        return {
            start_date:        startYear.value + '-' + pad(startMonth.value) + '-' + pad(startDay.value),
            start_time:        pad(startHour.value) + ':' + pad(startMinute.value),
            end_date:          endYear.value + '-' + pad(endMonth.value) + '-' + pad(endDay.value),
            end_time:          pad(endHour.value) + ':' + pad(endMinute.value),
            timezone:          timezoneInput.value,
            is_trading_day:    isTradingDayCheck.checked,
            is_cn_futures_day: isCnFuturesDayCheck.checked,
            is_cn_futures_night: isCnFuturesNightCheck.checked
        };
    }

    function applyTimeData(td) {
        if (!td) return;
        var sd = (td.start_date || '').split('-');
        var ed = (td.end_date   || '').split('-');
        var st = (td.start_time || '').split(':');
        var et = (td.end_time   || '').split(':');
        if (sd.length === 3) { startYear.value = sd[0]; startMonth.value = +sd[1]; startDay.value = +sd[2]; }
        if (ed.length === 3) { endYear.value   = ed[0]; endMonth.value   = +ed[1]; endDay.value   = +ed[2]; }
        if (st.length === 2) { startHour.value = st[0]; startMinute.value = st[1]; }
        if (et.length === 2) { endHour.value   = et[0]; endMinute.value   = et[1]; }
        if (td.timezone != null) timezoneInput.value = td.timezone;
        if (td.is_trading_day    != null) isTradingDayCheck.checked    = td.is_trading_day;
        if (td.is_cn_futures_day != null) isCnFuturesDayCheck.checked  = td.is_cn_futures_day;
        if (td.is_cn_futures_night != null) isCnFuturesNightCheck.checked = td.is_cn_futures_night;
        updateCurrentSettings();
    }

    function populateTimeTplSelect() {
        var prev = $tSel.value;
        fetch('/api/time_templates')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                while ($tSel.options.length > 1) $tSel.remove(1);
                if (data.success && data.templates) {
                    data.templates.forEach(function(t) {
                        var opt = document.createElement('option');
                        opt.value = t.id; opt.textContent = t.name;
                        $tSel.appendChild(opt);
                    });
                }
                if (prev) $tSel.value = prev;
                updateTimeTplNameDisplay();
            });
    }

    function updateTimeTplNameDisplay() {
        var id = $tSel.value;
        if (id) { $tLbl.textContent = $tSel.options[$tSel.selectedIndex].text; $tLbl.style.display = ''; }
        else    { $tLbl.style.display = 'none'; }
    }

    $tSel.addEventListener('change', function() {
        $tInp.style.display = 'none'; updateTimeTplNameDisplay();
    });

    $tLbl.addEventListener('dblclick', function() {
        var id = $tSel.value; if (!id) return;
        $tInp.value = $tLbl.textContent;
        $tInp.style.display = ''; $tInp.focus();
        $tLbl.style.display = 'none';
    });

    function commitTimeTplRename(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== 'Escape') return;
        if (e.key === 'Escape') { $tInp.style.display = 'none'; $tLbl.style.display = ''; return; }
        var id = $tSel.value; if (!id) { $tInp.style.display = 'none'; return; }
        var newName = $tInp.value.trim();
        if (!newName) { $tInp.style.display = 'none'; $tLbl.style.display = ''; return; }
        fetch('/api/time_templates/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: newName })
        }).then(function(r) { return r.json(); }).then(function(data) {
            $tInp.style.display = 'none';
            if (data.success) {
                tTplStatus('✓ 重命名成功', true);
                populateTimeTplSelect();
                setTimeout(function() { $tSel.value = id; updateTimeTplNameDisplay(); }, 300);
            } else {
                $tLbl.style.display = ''; tTplStatus('重命名失败: ' + data.error, false);
            }
        });
    }
    $tInp.addEventListener('keydown', commitTimeTplRename);
    $tInp.addEventListener('blur',    commitTimeTplRename);

    document.getElementById('time-tpl-load-btn').addEventListener('click', function() {
        var id = $tSel.value;
        if (!id) { tTplStatus('请先选择一个模板', false); return; }
        fetch('/api/time_templates/' + id)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) { tTplStatus('加载失败: ' + data.error, false); return; }
                applyTimeData(data.template.time_data);
                confirmBtn.disabled = false;
                confirmBtn.click();
                tTplStatus('✓ 模板已加载', true);
            });
    });

    document.getElementById('time-tpl-save-btn').addEventListener('click', function() {
        var td = collectCurrentTimeData();
        var name = prompt('请输入模板名称：');
        if (!name || !name.trim()) return;
        fetch('/api/time_templates', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name.trim(), time_data: td })
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.success) {
                tTplStatus('✓ 模板已保存', true);
                populateTimeTplSelect();
                setTimeout(function() { $tSel.value = data.id; updateTimeTplNameDisplay(); }, 300);
            } else { tTplStatus('保存失败: ' + data.error, false); }
        });
    });

    document.getElementById('time-tpl-update-btn').addEventListener('click', function() {
        var id = $tSel.value;
        if (!id) { tTplStatus('请先选择一个模板', false); return; }
        var td = collectCurrentTimeData();
        fetch('/api/time_templates/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ time_data: td })
        }).then(function(r) { return r.json(); }).then(function(data) {
            tTplStatus(data.success ? '✓ 模板已更新' : '更新失败: ' + data.error, data.success);
        });
    });

    document.getElementById('time-tpl-delete-btn').addEventListener('click', function() {
        var id = $tSel.value;
        if (!id) { tTplStatus('请先选择一个模板', false); return; }
        var name = $tSel.options[$tSel.selectedIndex].text;
        if (!confirm('确定删除模板「' + name + '」？')) return;
        fetch('/api/time_templates/' + id, { method: 'DELETE' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) { tTplStatus('✓ 模板已删除', true); populateTimeTplSelect(); }
                else { tTplStatus('删除失败: ' + data.error, false); }
            });
    });

    populateTimeTplSelect();
    // ── 时间模板管理 END ──────────────────────────────────────────────────────

})();