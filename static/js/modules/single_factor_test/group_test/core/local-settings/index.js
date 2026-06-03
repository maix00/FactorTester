/**
 * core/local-settings/index.js — GroupTest local setting registry.
 *
 * Local settings are UI state owned by GroupTest but outside the group graph
 * datamodel. They are saved as one global-template snapshot entry so future
 * modules can register additional local state without touching templates again.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/local-settings] bootstrap missing'); return; }
    if (GT.localSettings) { console.warn('[GT core/local-settings] already loaded'); return; }

    var _entries = [];
    var _byKey = {};

    function _deepCopy(obj) {
        if (obj === undefined || obj === null) return obj;
        try { return JSON.parse(JSON.stringify(obj)); }
        catch (e) { return obj; }
    }

    function register(spec) {
        if (!spec || !spec.key || typeof spec.collect !== 'function' || typeof spec.apply !== 'function') {
            console.warn('[GT local-settings] invalid registration', spec);
            return;
        }
        if (_byKey[spec.key]) {
            for (var i = _entries.length - 1; i >= 0; i--) {
                if (_entries[i].key === spec.key) _entries.splice(i, 1);
            }
        }
        spec.order = typeof spec.order === 'number' ? spec.order : 100;
        spec.runFields = Array.isArray(spec.runFields) ? spec.runFields.slice() : [];
        spec.runPayload = Array.isArray(spec.runPayload) ? spec.runPayload.slice() : [];
        _entries.push(spec);
        _byKey[spec.key] = spec;
        _entries.sort(function(a, b) { return a.order - b.order; });
    }

    function collect() {
        var out = {};
        for (var i = 0; i < _entries.length; i++) {
            var entry = _entries[i];
            try {
                var value = entry.collect();
                if (value !== undefined && value !== null) out[entry.key] = _deepCopy(value);
            } catch (e) {
                console.warn('[GT local-settings] collect failed for ' + entry.key, e);
            }
        }
        return out;
    }

    function getRunFields() {
        var fields = {};
        for (var i = 0; i < _entries.length; i++) {
            var entry = _entries[i];
            if (!entry.runFields.length) continue;
            try {
                var value = typeof entry.getRunFields === 'function' ? entry.getRunFields() : entry.collect();
                entry.runFields.forEach(function(key) {
                    if (!Object.prototype.hasOwnProperty.call(value || {}, key)) return;
                    fields[key] = _deepCopy(value[key]);
                });
            } catch (e) {
                console.warn('[GT local-settings] getRunFields failed for ' + entry.key, e);
            }
        }
        return fields;
    }

    function getRunField(key, fallback) {
        var fields = getRunFields();
        return Object.prototype.hasOwnProperty.call(fields, key) ? fields[key] : fallback;
    }

    function prepareRun() {
        var fields = getRunFields();
        var payload = {};
        var errors = [];
        var structureKeyParts = [];

        for (var i = 0; i < _entries.length; i++) {
            var entry = _entries[i];
            try {
                for (var pi = 0; pi < entry.runPayload.length; pi++) {
                    var mapping = entry.runPayload[pi];
                    if (!mapping || !mapping.field || !mapping.key) continue;
                    if (!Object.prototype.hasOwnProperty.call(fields, mapping.field)) continue;
                    payload[mapping.key] = _deepCopy(fields[mapping.field]);
                }
                if (typeof entry.validateRunPayload === 'function') {
                    var entryErrors = entry.validateRunPayload(fields, payload);
                    if (Array.isArray(entryErrors)) errors = errors.concat(entryErrors);
                    else if (entryErrors) errors.push(String(entryErrors));
                }
                if (typeof entry.getStructureKeyParts === 'function') {
                    var parts = entry.getStructureKeyParts(fields, payload);
                    if (Array.isArray(parts)) structureKeyParts = structureKeyParts.concat(parts.map(function(p) { return String(p || ''); }));
                }
            } catch (e) {
                errors.push(entry.key + ': ' + (e && e.message || e));
            }
        }

        return { fields: fields, payload: payload, errors: errors, structureKeyParts: structureKeyParts };
    }

    function apply(snapshot) {
        snapshot = snapshot || {};
        var errors = [];
        for (var i = 0; i < _entries.length; i++) {
            var entry = _entries[i];
            if (!Object.prototype.hasOwnProperty.call(snapshot, entry.key)) continue;
            try { entry.apply(_deepCopy(snapshot[entry.key])); }
            catch (e) { errors.push(entry.key + ': ' + (e && e.message || e)); }
        }
        return { applied: _entries.length, errors: errors };
    }

    function summarize(snapshot) {
        snapshot = snapshot || {};
        var lines = [];
        for (var i = 0; i < _entries.length; i++) {
            var entry = _entries[i];
            if (!Object.prototype.hasOwnProperty.call(snapshot, entry.key)) continue;
            if (typeof entry.summarize !== 'function') continue;
            try {
                var value = entry.summarize(snapshot[entry.key]);
                if (Array.isArray(value)) lines = lines.concat(value);
                else if (value || value === 0) lines.push(String(value));
            } catch (e) {
                console.warn('[GT local-settings] summarize failed for ' + entry.key, e);
            }
        }
        return lines.length ? lines : null;
    }

    GT.localSettings = {
        key: 'local_settings',
        order: 50,
        label: '分组本地设置',
        icon: '🧭',
        register: register,
        collect: collect,
        apply: apply,
        summarize: summarize,
        getRunFields: getRunFields,
        getRunField: getRunField,
        prepareRun: prepareRun,
        _entries: _entries,
    };
})();
