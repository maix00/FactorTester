/**
 * core/local-settings/dates.js — registers GroupTest dates as local settings.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT || !GT.localSettings || !GT.core || !GT.core.dates) {
        console.warn('[GT local-settings/dates] dependencies missing');
        return;
    }

    var dates = GT.core.dates;

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
            if (m) m.value = parts[1];
            if (d) d.value = parts[2];
        }
        setDate('start', data.startDate);
        setDate('end', data.endDate);
    }

    function summarize(data) {
        data = data || {};
        if (!data.startDate && !data.endDate) return null;
        return '分组日期: ' + (data.startDate || '未设置') + ' → ' + (data.endDate || '未设置');
    }

    function validateRunPayload(fields) {
        if (!fields.startDate || !fields.endDate) return ['请设置时间范围'];
        if (fields.startDate > fields.endDate) return ['起始日期不能晚于终止日期'];
        return [];
    }

    function getStructureKeyParts(fields) {
        return [fields.startDate || '', fields.endDate || ''];
    }

    GT.localSettings.register({
        key: 'dates',
        order: 10,
        collect: collect,
        apply: apply,
        runFields: ['startDate', 'endDate'],
        runPayload: [
            { field: 'startDate', key: 'start_date' },
            { field: 'endDate', key: 'end_date' },
        ],
        validateRunPayload: validateRunPayload,
        getStructureKeyParts: getStructureKeyParts,
        summarize: summarize,
    });
})();
