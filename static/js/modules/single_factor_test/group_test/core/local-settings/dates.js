/**
 * core/local-settings/dates.js — registers GroupTest dates as local settings.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT || !GT.localSettings || !GT.core || !GT.core.dateInputs) {
        console.warn('[GT local-settings/dates] dependencies missing');
        return;
    }

    var dates = GT.core.dateInputs;

    function collect() {
        return dates.readGroupTimeRangeInput();
    }

    function apply(data) {
        data = data || {};
        function setDate(prefix, value) {
            if (!value) return;
            var parts = String(value).split('-');
            if (parts.length !== 3) return;
            var y = document.getElementById('group_' + prefix + '_year');
            var m = document.getElementById('group_' + prefix + '_month');
            var d = document.getElementById('group_' + prefix + '_day');
            if (y) y.value = parts[0];
            if (m) m.value = parseInt(parts[1], 10);
            if (d) d.value = parseInt(parts[2], 10);
        }
        setDate('start', data.startDate);
        setDate('end', data.endDate);

        // 恢复时分
        if (data.startHour) {
            var sh = document.getElementById('group_start_hour');
            if (sh) sh.value = data.startHour;
        }
        if (data.startMinute) {
            var si = document.getElementById('group_start_minute');
            if (si) si.value = data.startMinute;
        }
        if (data.endHour) {
            var eh = document.getElementById('group_end_hour');
            if (eh) eh.value = data.endHour;
        }
        if (data.endMinute) {
            var ei = document.getElementById('group_end_minute');
            if (ei) ei.value = data.endMinute;
        }

        // 恢复时间精度
        if (data.precision) {
            var precEl = document.getElementById('group_precision_' + data.precision);
            if (precEl) precEl.checked = true;
        }

        // 恢复时区
        if (data.tz) {
            var tzEl = document.getElementById('group_tz');
            if (tzEl) tzEl.value = data.tz;
        }
    }

    function summarize(data) {
        data = data || {};
        if (!data.startDate && !data.endDate) return null;
        var start = data.startDate || '未设置';
        var end = data.endDate || '未设置';
        if (data.startHour) start += ' ' + data.startHour + ':' + (data.startMinute || '00');
        if (data.endHour) end += ' ' + data.endHour + ':' + (data.endMinute || '00');
        var modeLabel = {day:'天级', exact:'精确'}[data.precision] || '';
        var tzSuffix = data.tz ? ' [' + data.tz + ']' : '';
        return '时间: ' + start + ' → ' + end + (modeLabel ? ' [' + modeLabel + tzSuffix + ']' : '');
    }

    function validateRunPayload(fields) {
        if (!fields.startDate || !fields.endDate) return ['请设置时间范围'];
        if (fields.startDate > fields.endDate) return ['起始日期不能晚于终止日期'];
        return [];
    }

    function getStructureKeyParts(fields) {
        return [fields.startDate || '', fields.endDate || '', fields.precision || 'exact', fields.tz || '',
                fields.startHour || '', fields.startMinute || '',
                fields.endHour || '', fields.endMinute || ''];
    }

    GT.localSettings.register({
        key: 'dates',
        order: 10,
        tabLabel: '时间',
        collect: collect,
        apply: apply,
        runFields: ['startDate', 'endDate', 'startHour', 'startMinute', 'endHour', 'endMinute', 'precision', 'tz'],
        runPayload: [
            { field: 'startDate', key: 'start_date' },
            { field: 'endDate', key: 'end_date' },
            { field: 'startHour', key: 'start_hour' },
            { field: 'startMinute', key: 'start_minute' },
            { field: 'endHour', key: 'end_hour' },
            { field: 'endMinute', key: 'end_minute' },
            { field: 'precision', key: 'precision' },
            { field: 'tz', key: 'tz' },
        ],
        validateRunPayload: validateRunPayload,
        getStructureKeyParts: getStructureKeyParts,
        summarize: summarize,
    });
})();
