/**
 * core/local-settings/calendar-freq.js — shared group calendar frequency setting.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT || !GT.localSettings) {
        console.warn('[GT local-settings/calendar-freq] dependencies missing');
        return;
    }

    var ALLOWED = ['1min', '5min', '1day'];

    function getAutoInput() {
        return document.getElementById('group_calendar_freq_auto');
    }

    function getManualWrap() {
        return document.getElementById('group_calendar_freq_manual_wrap');
    }

    function getCheckedManualInput() {
        return document.querySelector('input[name="group_calendar_freq"]:checked');
    }

    function normalizeManual(value) {
        value = value == null ? '' : String(value).trim();
        return ALLOWED.indexOf(value) >= 0 ? value : null;
    }

    function syncManualVisibility() {
        var autoInput = getAutoInput();
        var wrap = getManualWrap();
        if (!wrap) return;
        wrap.style.display = autoInput && autoInput.checked ? 'none' : '';
    }

    function collect() {
        var autoInput = getAutoInput();
        var manualInput = getCheckedManualInput();
        return {
            autoGroupCalendarFreq: !(autoInput && autoInput.checked === false),
            groupCalendarFreq: normalizeManual(manualInput && manualInput.value),
        };
    }

    function apply(data) {
        data = data || {};
        var autoInput = getAutoInput();
        var autoValue = data.autoGroupCalendarFreq !== false;
        if (autoInput) autoInput.checked = autoValue;

        var manualValue = normalizeManual(data.groupCalendarFreq) || ALLOWED[0];
        var manualInput = document.querySelector('input[name="group_calendar_freq"][value="' + manualValue + '"]');
        if (manualInput) manualInput.checked = true;

        syncManualVisibility();
    }

    function validateRunPayload(fields) {
        if (fields.autoGroupCalendarFreq === false && !normalizeManual(fields.groupCalendarFreq)) {
            return ['请选择合法的公共时间轴频率'];
        }
        return [];
    }

    function summarize(data) {
        data = data || {};
        if (data.autoGroupCalendarFreq !== false) return '公共时间轴频率: 自动判断';
        var value = normalizeManual(data.groupCalendarFreq);
        return value ? ('公共时间轴频率: ' + value) : null;
    }

    function getStructureKeyParts(fields) {
        return [
            fields.autoGroupCalendarFreq === false ? 'manual' : 'auto',
            fields.autoGroupCalendarFreq === false ? (normalizeManual(fields.groupCalendarFreq) || '') : '',
        ];
    }

    function bind() {
        var autoInput = getAutoInput();
        if (autoInput && !autoInput.dataset.gtBound) {
            autoInput.addEventListener('change', syncManualVisibility);
            autoInput.dataset.gtBound = '1';
        }
        syncManualVisibility();
    }

    GT.localSettings.register({
        key: 'calendarFreq',
        order: 30,
        tabLabel: '时间轴频率',
        collect: collect,
        apply: apply,
        runFields: ['autoGroupCalendarFreq', 'groupCalendarFreq'],
        runPayload: [
            { field: 'autoGroupCalendarFreq', key: 'auto_group_calendar_freq' },
            { field: 'groupCalendarFreq', key: 'group_calendar_freq' },
        ],
        validateRunPayload: validateRunPayload,
        getStructureKeyParts: getStructureKeyParts,
        summarize: summarize,
        bind: bind,
    });

    bind();
})();
