(() => {
  function open(state, url) {
    if (typeof state.context.raw !== "function") return new EventSource(url);
    const abortController = new AbortController();
    const decoder = new TextDecoder();
    let reader = null;
    let buffer = "";
    let closed = false;
    const source = {
      onopen: null,
      onmessage: null,
      onerror: null,
      close() {
        if (closed) return;
        closed = true;
        abortController.abort();
        void reader?.cancel().catch(() => {});
      },
    };
    const dispatch = frame => {
      let identifier = "";
      const data = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith("id:")) identifier = line.slice(3).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) source.onmessage?.({
        lastEventId: identifier,
        data: data.join("\n"),
      });
    };
    void state.context.raw(url, {
      headers: {Accept: "text/event-stream"},
      signal: abortController.signal,
    }).then(async response => {
      if (closed) return;
      if (!response.body) throw new Error("Profile Agent event stream is empty");
      reader = response.body.getReader();
      source.onopen?.();
      while (!closed) {
        const value = await reader.read();
        if (value.done) break;
        buffer += decoder.decode(value.value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        frames.forEach(dispatch);
      }
      if (!closed) source.onerror?.(new Error("Profile Agent event stream ended"));
    }).catch(error => {
      if (!closed && error?.name !== "AbortError") source.onerror?.(error);
    });
    return source;
  }

  window.FTProfileAgentEventSource = Object.freeze({open});
})();
