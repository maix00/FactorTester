(() => {
  // Xpert is a local presentation client. Manager remains the only conversation
  // authority; the iframe receives no provider credentials or remote API access.
  const sessions = new Map();
  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status, headers: {"Content-Type": "application/json"},
  });
  function content(item) {
    if (item.type === "workflow") return (item.workflow?.tasks || []).map(task =>
      [task.title, typeof task.content === "string" ? task.content : ""].filter(Boolean).join("\n")
    ).join("\n\n");
    return (item.content || []).map(part => part.text || "").join("");
  }
  function message(item) {
    return {id: item.id, role: item.type === "user_message" ? "human" : "ai",
      type: item.type === "user_message" ? "human" : "ai", content: content(item),
      createdAt: item.created_at};
  }
  function conversation(thread) {
    return {id: thread.id, threadId: thread.id, title: thread.title,
      createdAt: thread.created_at, updatedAt: thread.created_at, status: "idle"};
  }
  function create(adapter, options = {}) {
    let disposed = false;
    const active = new Set();
    const pages = new Map();
    const runs = new Map();
    const liveItems = new Map();
    async function call(type, params = {}, signal) {
      if (disposed) throw new Error("会话界面已关闭");
      const response = await adapter.fetch(adapter.endpoint, {
        method: "POST", body: JSON.stringify({type, params}), signal,
      });
      if (!response.ok) {
        const error = new Error((await response.json()).error || `HTTP ${response.status}`);
        error.status = response.status; throw error;
      }
      return response;
    }
    const data = async (type, params) => (await call(type, params)).json();
    async function history(id, offset = 0, limit = 50) {
      let page = pages.get(id);
      if (!page || offset === 0) {
        const thread = await data("threads.get_by_id", {thread_id: id});
        page = {items: thread.items.data || [], after: thread.items.after,
          more: thread.items.has_more};
        pages.set(id, page);
      }
      while (page.more && page.items.length < offset + limit) {
        const next = await data("items.list", {thread_id: id, after: page.after, limit: 50});
        const known = new Set(page.items.map(item => item.id));
        const older = (next.data || []).filter(item => !known.has(item.id));
        if (!older.length && next.has_more) throw new Error("历史消息分页没有前进");
        page.items.unshift(...older); page.after = next.after; page.more = next.has_more;
      }
      return {items: [...page.items].reverse().slice(offset, offset + limit).map(message),
        total: page.items.length + (page.more ? 1 : 0)};
    }
    async function stream(id, input, resume, signal) {
      const controller = new AbortController(); active.add(controller);
      signal?.addEventListener("abort", () => controller.abort(), {once: true});
      if (signal?.aborted) controller.abort();
      input = input?.state?.human || input;
      const text = typeof input?.input === "string" ? input.input :
        typeof input === "string" ? input : "";
      if (!resume && !text.trim()) { active.delete(controller); throw new Error("消息不能为空"); }
      let response;
      try { response = await call(resume ? "threads.resume" : "threads.add_user_message", {
        thread_id: id, input: {content: [{type: "input_text", text}]},
      }, controller.signal); } catch (error) { active.delete(controller); throw error; }
      const items = new Map((pages.get(id)?.items || []).map(item => [item.id, item]));
      liveItems.set(id, items);
      const reader = response.body.getReader();
      let cancelled = false;
      let buffer = ""; const decoder = new TextDecoder();
      return new Response(new ReadableStream({
        async start(output) {
          const emit = (event, value) => output.enqueue(new TextEncoder().encode(
            `event: ${event}\ndata: ${JSON.stringify(value)}\n\n`));
          try {
            const status = await options.runtimeStatus?.();
            const turn = status?.processing_conversation_id === id ? status.processing_turn_id : null;
            if (turn) {
              runs.set(id, turn);
              emit("events", {type: "event", event: "on_message_start", data: {executionId: turn}});
            }
            while (!controller.signal.aborted) {
              const chunk = await reader.read(); if (chunk.done) break;
              buffer += decoder.decode(chunk.value, {stream: true});
              const frames = buffer.split(/\r?\n\r?\n/); buffer = frames.pop();
              for (const frame of frames) {
                const body = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
                  .map(line => line.slice(5).trimStart()).join("\n");
                if (!body) continue;
                const event = JSON.parse(body);
                if (event.type === "turn.started" && event.turn_id) {
                  runs.set(id, event.turn_id);
                  emit("events", {type: "event", event: "on_message_start", data: {executionId: event.turn_id}});
                }
                if (event.type === "error") { emit("error", event.message); continue; }
                if (event.item) {
                  items.set(event.item.id, event.item);
                  emit("values", {messages: [...items.values()].map(message).filter(item => item.content)});
                }
              }
            }
          } catch (error) {
            if (!controller.signal.aborted) emit("error", error.message);
          } finally { liveItems.delete(id); runs.delete(id); active.delete(controller); reader.releaseLock(); if (!cancelled) output.close(); }
        },
        cancel() { cancelled = true; controller.abort(); void reader.cancel(); active.delete(controller); },
      }), {headers: {"Content-Type": "text/event-stream"}});
    }
    async function fetch(input, init = {}) {
      const url = new URL(typeof input === "string" ? input : input.url, location.origin);
      const parts = url.pathname.replace(/^.*\/ft-profile-bridge\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
      const method = (init.method || "GET").toUpperCase();
      const body = init.body ? JSON.parse(init.body) : {};
      const [kind, id, action, run, operation] = parts;
      if (kind === "assistants") {
        if (action === "models") return json({models: []});
        if (action === "runtime-capabilities") return json({skills: [], plugins: [], subAgents: [], workspaces: [], connectors: []});
        return json({id: "profile", name: "智能体助手"});
      }
      if (kind === "conversations" && id === "search") {
        let items = (await data("threads.list")).data.map(conversation);
        if (body.where?.threadId) items = items.filter(item => item.threadId === body.where.threadId);
        if (body.search) items = items.filter(item => (item.title || "").includes(body.search));
        return json({items: items.slice(body.offset || 0, (body.offset || 0) + (body.limit || 100)), total: items.length});
      }
      if (kind === "threads" && !id && method === "POST") {
        const thread = await data("threads.create");
        return json({thread_id: thread.id, metadata: {id: thread.id}, status: "idle"});
      }
      if (kind === "conversations" && !id && method === "POST") {
        return json(conversation(await data("threads.get_by_id", {thread_id: body.threadId})));
      }
      if (kind === "conversations" && action === "messages") return json(await history(id, body.offset || 0, body.limit || 50));
      if (kind === "conversations" && !action) {
        if (method === "PATCH") {
          if (typeof body.title !== "string") return json(conversation(await data("threads.get_by_id", {thread_id: id})));
          return json(conversation(await data("threads.update", {thread_id: id, title: body.title})));
        }
        if (method === "DELETE") { await data("threads.delete", {thread_id: id}); return json({}); }
        return json(conversation(await data("threads.get_by_id", {thread_id: id})));
      }
      if (kind === "threads" && action === "runs") {
        if (!run && method === "POST") {
          const input = body.input;
          const turn = runs.get(id);
          if (input?.action !== "follow_up" || input.mode !== "steer" || input.conversationId !== id
              || !turn || input.target?.executionId !== turn) {
            return json({error: "Steer 目标运行已结束或不匹配"}, 409);
          }
          const human = input.message?.input;
          const text = typeof human === "string" ? human : human?.input;
          if (typeof text !== "string" || !text.trim()) return json({error: "消息不能为空"}, 400);
          const result = await data("threads.steer", {thread_id: id, turn_id: turn,
            input: {content: [{type: "input_text", text}]}});
          const messageID = input.message.clientMessageId || crypto.randomUUID();
          liveItems.get(id)?.set(messageID, {id: messageID, type: "user_message",
            content: [{text}], created_at: new Date().toISOString()});
          return json(result);
        }
        if (run === "stream") return stream(id, body.input, false, init.signal);
        if (operation === "stream" || operation === "join") return stream(id, null, true, init.signal);
        if (operation === "cancel") { await data("threads.stop", {thread_id: id}); return json({}); }
        if (!run && method === "GET") {
          const status = await options.runtimeStatus?.();
          return json(status?.processing_conversation_id === id && status.processing_turn_id ?
            [{run_id: status.processing_turn_id, status: "running", thread_id: id}] : []);
        }
      }
      if (kind === "threads" && action === "context-usage") return json({usage: null});
      if (kind === "threads" && action === "services") return json([]);
      if (kind === "threads" && !action) {
        const thread = await data("threads.get_by_id", {thread_id: id});
        return json({thread_id: thread.id, metadata: {id: thread.id}, status: "idle"});
      }
      return json({error: `不支持的界面操作：${method} ${parts.join("/")}`}, 400);
    }
    const key = crypto.randomUUID();
    sessions.set(key, async (input, init) => {
      try { return await fetch(input, init); }
      catch (error) { return json({error: error.message}, error.status || 400); }
    });
    return {key, dispose() { disposed = true; sessions.delete(key); for (const controller of active) controller.abort(); active.clear(); }};
  }
  window.FTXpertTransport = Object.freeze({create,
    fetch(key, input, init) {
      const fetch = sessions.get(key);
      if (!fetch) return Promise.reject(new Error("会话界面通道已关闭"));
      return fetch(input, init);
    },
  });
})();
