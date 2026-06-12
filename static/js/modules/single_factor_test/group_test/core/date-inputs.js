/**
 * core/date-inputs.js — 日期输入框 DOM 读写与验证
 *
 * 从 app.js 解耦提取。无外部依赖（仅依赖 window.DateUtils 和 DOM）。
 * 挂载到 GT.core.dateInputs 命名空间。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/date-inputs] bootstrap missing'); return; }
    GT.core = GT.core || {};
    if (GT.core.dateInputs) { console.warn('[GT core/date-inputs] already loaded'); return; }

    var dateInputs = {};

    // ---------- 显示日期修正提示 ----------
    dateInputs.showDateHint = function(input, message) {
        var container = input.closest('div');
        if (!container) return;
        var hint = container.querySelector('.date-hint');
        if (!hint) {
            hint = document.createElement('span');
            hint.className = 'date-hint';
            hint.style.cssText = 'font-size:12px;color:#28a745;margin-left:8px;font-weight:500;';
            container.appendChild(hint);
        }
        hint.textContent = message;
        setTimeout(function() { hint.remove(); }, 3000);
    };

    // ---------- 日期输入框验证（blur 时自动修正超出范围的日期） ----------
    dateInputs.bindDateValidation = function() {
        ['start', 'end'].forEach(function(prefix) {
            var yearEl  = document.getElementById('group_' + prefix + '_year');
            var monthEl = document.getElementById('group_' + prefix + '_month');
            var dayEl   = document.getElementById('group_' + prefix + '_day');
            if (!yearEl || !monthEl || !dayEl) return;

            [yearEl, monthEl, dayEl].forEach(function(el) {
                // input：只允许数字
                el.addEventListener('input', function() {
                    if (!/^\d*$/.test(this.value)) this.value = this.value.replace(/\D/g, '');
                });

                // blur：修正月份范围，再修正日期范围（同时间模块逻辑）
                el.addEventListener('blur', function() {
                    var y = parseInt(yearEl.value, 10);
                    var m = parseInt(monthEl.value, 10);
                    var d = parseInt(dayEl.value, 10);
                    var DU = window.DateUtils;
                    var p = function(n) { return DU ? DU.pad(n) : (n < 10 ? '0'+n : ''+n); };

                    // 修正年份
                    if (!isNaN(y)) {
                        if (y < 1900) { y = 1900; yearEl.value = '1900'; }
                        else if (y > 2100) { y = 2100; yearEl.value = '2100'; }
                    }

                    // 修正月份 1-12
                    if (!isNaN(m)) {
                        if (m < 1)  m = 1;
                        if (m > 12) m = 12;
                        monthEl.value = p(m);
                    }

                    // 修正日期 1-maxDay
                    if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                        var maxDay = DU ? DU.getMaxDay(y, m) : new Date(y, m, 0).getDate();
                        if (d < 1)      d = 1;
                        if (d > maxDay) d = maxDay;
                        dayEl.value = p(d);
                    }
                });
            });
        });
    };

    // ---------- 组合年月日为日期字符串（自动修正超出月末的日期） ----------
    dateInputs.buildValidDate = function(year, month, day) {
        var y = parseInt(year, 10);
        var m = parseInt(month, 10);
        var d = parseInt(day, 10);
        if (!y || !m || !d) return null;
        var maxDay = window.DateUtils ? window.DateUtils.getMaxDay(y, m) : new Date(y, m, 0).getDate();
        var clampedDay = Math.min(d, maxDay);
        return y + '-' + (m < 10 ? '0' + m : m) + '-' + (clampedDay < 10 ? '0' + clampedDay : clampedDay);
    };

    dateInputs.formatAdaptiveTime = function(timestamp, stepMs) {
        var d = new Date(timestamp);
        if (isNaN(d.getTime())) return String(timestamp);
        var y = d.getFullYear();
        var mo = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        var h = String(d.getHours()).padStart(2, '0');
        var mi = String(d.getMinutes()).padStart(2, '0');
        if (stepMs != null && stepMs < 86400000) {
            return y + '-' + mo + '-' + day + ' ' + h + ':' + mi;
        }
        return y + '-' + mo + '-' + day;
    };

    dateInputs.buildContinuousTimeAxis = function(rows, timestampGetter) {
        var timestamps = (rows || []).map(function(row) { return timestampGetter(row); });
        var n = timestamps.length;
        var stepMs = null;
        for (var i = 1; i < n; i++) {
            var d = timestamps[i] - timestamps[i - 1];
            if (d > 0 && (stepMs === null || d < stepMs)) {
                stepMs = d;
            }
        }
        var labels = timestamps.map(function(ts) { return dateInputs.formatAdaptiveTime(ts, stepMs); });
        var labelEvery = Math.max(1, Math.floor(n / 10));
        return {
            labels: labels,
            labelEvery: labelEvery,
            stepMs: stepMs,
            labelAt: function(value) {
                var idx = Math.round(value);
                return (idx >= 0 && idx < labels.length) ? labels[idx] : '';
            },
        };
    };

    // ---------- 读取分组时间范围输入（完整版：含时分和模式） ----------
    dateInputs.readGroupTimeRangeInput = function() {
        var sy = document.getElementById('group_start_year');
        var sm = document.getElementById('group_start_month');
        var sd = document.getElementById('group_start_day');
        var sh = document.getElementById('group_start_hour');
        var si = document.getElementById('group_start_minute');
        var ey = document.getElementById('group_end_year');
        var em = document.getElementById('group_end_month');
        var ed = document.getElementById('group_end_day');
        var eh = document.getElementById('group_end_hour');
        var ei = document.getElementById('group_end_minute');

        var hasStartDate = sy && sm && sd && sy.value && sm.value && sd.value;
        var hasEndDate = ey && em && ed && ey.value && em.value && ed.value;

        // 时分：仅在输入值存在时使用
        var startHour = (sh && sh.value) ? sh.value : null;
        var startMinute = (si && si.value) ? si.value : null;
        var endHour = (eh && eh.value) ? eh.value : null;
        var endMinute = (ei && ei.value) ? ei.value : null;

        // 时间精度
        var precEl = document.querySelector('input[name="group_time_precision"]:checked');
        var precision = precEl ? precEl.value : 'exact';

        // 时区（仅 exact 精度时有效）
        var tzEl = document.getElementById('group_tz');
        var tz = (precision === 'exact' && tzEl) ? tzEl.value : null;

        return {
            startDate: hasStartDate ? dateInputs.buildValidDate(sy.value, sm.value, sd.value) : null,
            endDate: hasEndDate ? dateInputs.buildValidDate(ey.value, em.value, ed.value) : null,
            startHour: startHour,
            startMinute: startMinute,
            endHour: endHour,
            endMinute: endMinute,
            precision: precision,
            tz: tz,
            // 派生：完整时间字符串 (YYYY-MM-DD HH:MM)
            startDt: hasStartDate ? dateInputs.buildValidDate(sy.value, sm.value, sd.value) + (startHour ? ' ' + startHour + ':' + (startMinute || '00') : '') : null,
            endDt: hasEndDate ? dateInputs.buildValidDate(ey.value, em.value, ed.value) + (endHour ? ' ' + endHour + ':' + (endMinute || '00') : '') : null,
        };
    };

    // ---------- 读取旧版时间范围（仅年月日，向后兼容） ----------
    dateInputs.readGroupDateOnlyInput = function() {
        var tr = dateInputs.readGroupTimeRangeInput();
        return { startDate: tr.startDate, endDate: tr.endDate };
    };

    // ---------- 解析分组运行时间范围（含新模式字段） ----------
    dateInputs.resolveGroupRunTimeRange = function(savedStartDate, savedEndDate) {
        var explicit = dateInputs.readGroupTimeRangeInput();
        var startDate = explicit.startDate || savedStartDate || null;
        var endDate = explicit.endDate || savedEndDate || null;
        return {
            startDate: startDate,
            endDate: endDate,
            startHour: explicit.startHour,
            startMinute: explicit.startMinute,
            endHour: explicit.endHour,
            endMinute: explicit.endMinute,
            timeMode: explicit.timeMode,
            startDt: explicit.startDt,
            endDt: explicit.endDt,
            explicitStartDate: explicit.startDate,
            explicitEndDate: explicit.endDate,
            precision: explicit.precision,
        };
    };

    // ---------- 绑定时间精度切换：时分自动禁用/启用 ----------
    dateInputs.bindTimePrecisionSwitch = function() {
        var radios = document.querySelectorAll('input[name="group_time_precision"]');
        if (!radios.length) return;

        function setHourMinuteDisabled(disabled) {
            ['group_start_hour', 'group_start_minute', 'group_end_hour', 'group_end_minute'].forEach(function(id) {
                var el = document.getElementById(id);
                if (el) {
                    el.disabled = disabled;
                    el.style.background = disabled ? '#ccc' : '#eee';
                }
            });
        }

        function onPrecisionChange() {
            var prec = document.querySelector('input[name="group_time_precision"]:checked');
            if (!prec) return;
            var val = prec.value;
            // exact → 手动时分可用，时区显示；day → 时分禁用，时区隐藏
            var isExact = (val === 'exact');
            setHourMinuteDisabled(!isExact);
            var tzWrap = document.getElementById('group_tz_wrap');
            if (tzWrap) {
                tzWrap.style.display = isExact ? '' : 'none';
            }
        }

        radios.forEach(function(r) {
            r.addEventListener('change', onPrecisionChange);
        });

        // 初始状态
        onPrecisionChange();
    };

    // ---------- 解析运行时间范围（含 submission 日期 fallback） ----------
    // savedStartDate/savedEndDate: 分组对象保存的日期
    // fallbackTesterId: 当以上都没有时，从 window.submissions 按 testerId 查找日期
    dateInputs.resolveGroupRunTimeRangeWithFallback = function(savedStartDate, savedEndDate, fallbackTesterId) {
        var resolved = dateInputs.resolveGroupRunTimeRange(savedStartDate, savedEndDate);
        if (resolved.startDate && resolved.endDate) return resolved;
        // Fallback: 从全局 submissions 列表中按 testerId 查找
        if (fallbackTesterId && window.submissions) {
            var sub = window.submissions.find(function(s) { return String(s.id) === String(fallbackTesterId); });
            if (sub) {
                if (!resolved.startDate) resolved.startDate = sub.start_date || null;
                if (!resolved.endDate) resolved.endDate = sub.end_date || null;
            }
        }
        return resolved;
    };

    GT.core.dateInputs = dateInputs;
})();
