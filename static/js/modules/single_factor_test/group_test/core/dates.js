/**
 * core/dates.js — 分组测试日期工具函数
 *
 * 从 app.js 解耦提取。无外部依赖（仅依赖 window.DateUtils 和 DOM）。
 * 挂载到 GT.core.dates 命名空间。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/dates] bootstrap missing'); return; }
    GT.core = GT.core || {};
    if (GT.core.dates) { console.warn('[GT core/dates] already loaded'); return; }

    var dates = {};

    // ---------- 显示日期修正提示 ----------
    dates.showDateHint = function(input, message) {
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
    dates.bindDateValidation = function() {
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
    dates.buildValidDate = function(year, month, day) {
        var y = parseInt(year, 10);
        var m = parseInt(month, 10);
        var d = parseInt(day, 10);
        if (!y || !m || !d) return null;
        var maxDay = window.DateUtils ? window.DateUtils.getMaxDay(y, m) : new Date(y, m, 0).getDate();
        var clampedDay = Math.min(d, maxDay);
        return y + '-' + (m < 10 ? '0' + m : m) + '-' + (clampedDay < 10 ? '0' + clampedDay : clampedDay);
    };

    dates.formatAdaptiveTime = function(timestamp, stepMs) {
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

    dates.buildContinuousTimeAxis = function(rows, timestampGetter) {
        var timestamps = (rows || []).map(function(row) { return timestampGetter(row); });
        var n = timestamps.length;
        var stepMs = null;
        for (var i = 1; i < n; i++) {
            var d = timestamps[i] - timestamps[i - 1];
            if (d > 0 && (stepMs === null || d < stepMs)) {
                stepMs = d;
            }
        }
        var labels = timestamps.map(function(ts) { return dates.formatAdaptiveTime(ts, stepMs); });
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

    // ---------- 读取分组时间范围输入 ----------
    dates.readGroupTimeRangeInput = function() {
        var sy = document.getElementById('group_start_year') ? document.getElementById('group_start_year').value : null;
        var sm = document.getElementById('group_start_month') ? document.getElementById('group_start_month').value : null;
        var sd = document.getElementById('group_start_day') ? document.getElementById('group_start_day').value : null;
        var ey = document.getElementById('group_end_year') ? document.getElementById('group_end_year').value : null;
        var em = document.getElementById('group_end_month') ? document.getElementById('group_end_month').value : null;
        var ed = document.getElementById('group_end_day') ? document.getElementById('group_end_day').value : null;
        return {
            startDate: (sy && sm && sd) ? dates.buildValidDate(sy, sm, sd) : null,
            endDate: (ey && em && ed) ? dates.buildValidDate(ey, em, ed) : null,
        };
    };

    // ---------- 持久化时间范围到 group settings ----------
    dates.persistGroupTimeRangeToDatamodel = function(startDate, endDate) {
        if (!GT.groupSettings.groups || (!startDate && !endDate)) return;
        var allGroups = GT.groupSettings.groups.getAll() || [];
        allGroups.forEach(function(group) {
            try {
                var patch = {};
                if (startDate) patch.startDate = startDate;
                if (endDate) patch.endDate = endDate;
                GT.groupSettings.groups.update(group.id, patch);
            } catch (e) { /* skip invalid/stale group */ }
        });
    };

    // ---------- 解析分组运行时间范围 ----------
    dates.resolveGroupRunTimeRange = function(savedStartDate, savedEndDate) {
        var explicit = dates.readGroupTimeRangeInput();
        var startDate = explicit.startDate || savedStartDate || null;
        var endDate = explicit.endDate || savedEndDate || null;
        return {
            startDate: startDate,
            endDate: endDate,
            explicitStartDate: explicit.startDate,
            explicitEndDate: explicit.endDate,
        };
    };

    // ---------- 绑定"使用当前时间范围"按钮 ----------
    dates.bindUseTimeRange = function() {
        var btn = document.getElementById('use_time_range_btn');
        if (!btn) return;
        btn.addEventListener('click', function() {
            var startYear = document.getElementById('start_year') ? document.getElementById('start_year').value : null;
            var startMonth = document.getElementById('start_month') ? document.getElementById('start_month').value : null;
            var startDay = document.getElementById('start_day') ? document.getElementById('start_day').value : null;
            var endYear = document.getElementById('end_year') ? document.getElementById('end_year').value : null;
            var endMonth = document.getElementById('end_month') ? document.getElementById('end_month').value : null;
            var endDay = document.getElementById('end_day') ? document.getElementById('end_day').value : null;
            
            var startDate = null, endDate = null;
            if (startYear && startMonth && startDay) {
                startDate = dates.buildValidDate(startYear, startMonth, startDay);
                if (startDate) {
                    var parts = startDate.split('-');
                    document.getElementById('group_start_year').value = parts[0];
                    document.getElementById('group_start_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_start_day').value = parseInt(parts[2], 10);
                }
            }
            if (endYear && endMonth && endDay) {
                endDate = dates.buildValidDate(endYear, endMonth, endDay);
                if (endDate) {
                    var parts = endDate.split('-');
                    document.getElementById('group_end_year').value = parts[0];
                    document.getElementById('group_end_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_end_day').value = parseInt(parts[2], 10);
                }
            }

            if (GT.groupSettings.groups && (startDate || endDate)) {
                var allBase = GT.groupSettings.groups.getAll();
                allBase.forEach(function(bg) {
                    try {
                        var patch = {};
                        if (startDate) patch.startDate = startDate;
                        if (endDate) patch.endDate = endDate;
                        GT.groupSettings.groups.update(bg.id, patch);
                    } catch (e) { /* skip */ }
                });
            }
        });
    };

    // ---------- 从时间模块同步时间到分组测试时间输入框 ----------
    dates.syncFromTimeModule = function() {
        var IDs = [
            ['start_year','group_start_year'], ['start_month','group_start_month'], ['start_day','group_start_day'],
            ['end_year','group_end_year'], ['end_month','group_end_month'], ['end_day','group_end_day']
        ];
        IDs.forEach(function(pair) {
            var src = document.getElementById(pair[0]);
            var dst = document.getElementById(pair[1]);
            if (src && dst && src.value) dst.value = src.value;
        });

        var sy = document.getElementById('group_start_year');
        var sm = document.getElementById('group_start_month');
        var sd = document.getElementById('group_start_day');
        var ey = document.getElementById('group_end_year');
        var em = document.getElementById('group_end_month');
        var ed = document.getElementById('group_end_day');
        var startDate = (sy && sm && sd) ? dates.buildValidDate(sy.value, sm.value, sd.value) : null;
        var endDate = (ey && em && ed) ? dates.buildValidDate(ey.value, em.value, ed.value) : null;

        if (GT.groupSettings.groups && (startDate || endDate)) {
            var allBase = GT.groupSettings.groups.getAll();
            allBase.forEach(function(bg) {
                try {
                    var patch = {};
                    if (startDate) patch.startDate = startDate;
                    if (endDate) patch.endDate = endDate;
                    GT.groupSettings.groups.update(bg.id, patch);
                } catch (e) {
                    // Silently skip if update fails (e.g. validation)
                }
            });
        }
    };

    // ---------- 绑定时间同步监听器 ----------
    dates.bindTimeSyncListeners = function() {
        ['start_year','start_month','start_day','end_year','end_month','end_day'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('change', dates.syncFromTimeModule);
        });
    };

    // ---------- 解析运行时间范围（含 submission 日期 fallback） ----------
    // savedStartDate/savedEndDate: 分组对象保存的日期
    // fallbackTesterId: 当以上都没有时，从 window.submissions 按 testerId 查找日期
    dates.resolveGroupRunTimeRangeWithFallback = function(savedStartDate, savedEndDate, fallbackTesterId) {
        var resolved = dates.resolveGroupRunTimeRange(savedStartDate, savedEndDate);
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

    GT.core.dates = dates;
})();
