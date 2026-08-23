(() => {
  function number(value) {
    if (value == null || value === "" || typeof value === "boolean") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function timestamp(value, index = 0) {
    if (typeof value === "number" && Number.isFinite(value)) {
      if (Math.abs(value) > 20_000_000_000) return value;
      if (Math.abs(value) > 1_000_000_000) return value * 1000;
      return index;
    }
    const text = String(value || "").trim();
    const parsed = /^\d{4}-\d{2}-\d{2}$/.test(text)
      ? new Date(`${text}T00:00:00`).getTime()
      : Date.parse(text);
    return Number.isFinite(parsed) ? parsed : index;
  }

  function userTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
    } catch (_error) {
      return undefined;
    }
  }

  function timeOptions() {
    return {timezone: userTimezone()};
  }

  function observed(items) {
    const values = new Set();
    (Array.isArray(items) ? items : []).forEach(item => {
      (Array.isArray(item?.timestamps) ? item.timestamps : []).forEach((value, index) => {
        const parsed = timestamp(value, index);
        if (Number.isFinite(parsed)) values.add(parsed);
      });
    });
    return [...values].sort((left, right) => left - right);
  }

  function aligned(item, timeline, field = "values", scale = 1) {
    const times = Array.isArray(item?.timestamps) ? item.timestamps : [];
    const values = Array.isArray(item?.[field]) ? item[field] : [];
    const byTime = new Map();
    for (let index = 0; index < Math.min(times.length, values.length); index += 1) {
      const x = timestamp(times[index], index);
      const y = number(values[index]);
      if (Number.isFinite(x) && y != null) byTime.set(x, y * scale);
    }
    return timeline.map(x => [x, byTime.has(x) ? byTime.get(x) : null]);
  }

  function nearest(timeline, value) {
    if (!timeline.length || !Number.isFinite(Number(value))) return null;
    let best = timeline[0];
    let distance = Math.abs(best - Number(value));
    for (let index = 1; index < timeline.length; index += 1) {
      const candidate = timeline[index];
      const candidateDistance = Math.abs(candidate - Number(value));
      if (candidateDistance < distance) {
        best = candidate;
        distance = candidateDistance;
      }
    }
    return best;
  }

  window.FTChartTimeline = Object.freeze({
    aligned, nearest, number, observed, timeOptions, timestamp, userTimezone,
  });
})();
