(() => {
  // Xpert is a local presentation client. Manager remains the only conversation
  // authority; the iframe receives no provider credentials or remote API access.
  function identifier() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, "0")).join("");
  }
  const sessions = new Map();
  const controls = new Map();
  const closers = new Map();
  const previews = new Map();
  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status, headers: {"Content-Type": "application/json"},
  });
  function content(item) {
    if (item.type === "workflow") return (item.workflow?.tasks || []).map(task =>
      [task.title, typeof task.content === "string" ? task.content : ""].filter(Boolean).join("\n")
    ).join("\n\n");
    return (item.content || []).map(part => part.text || "").join("");
  }
  function attachmentParts(item) {
    if (item.type !== "user_message") return {text: content(item), files: []};
    if (item.attachments?.length) return {text: content(item), files: item.attachments};
    const text = content(item), start = "\n\n<factortester-attachments>\n", end = "\n</factortester-attachments>";
    const at = text.lastIndexOf(start);
    if (at < 0 || !text.endsWith(end)) return {text, files: []};
    try {
      const files = JSON.parse(text.slice(at + start.length, -end.length));
      if (!Array.isArray(files) || files.length > 10 || files.some(f => !/^uploads\/\d{4}-\d{2}-\d{2}\/[a-f0-9]{32}\/[^/\\]+$/.test(f.workspacePath))) return {text, files: []};
      return {text: text.slice(0, at), files: files.map(file => ({...file, id: file.workspacePath, originalName: file.workspacePath.split("/").at(-1)}))};
    } catch { return {text, files: []}; }
  }
  function toolText(value) {
    return typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  }
  function fenced(value, language = "text") {
    const text = toolText(value);
    const longest = Math.max(2, ...[...text.matchAll(/`+/g)].map(match => match[0].length));
    const fence = "`".repeat(longest + 1);
    return `${fence}${language}\n${text}\n${fence}`;
  }
  function processItem(item) {
    if (item.type !== "client_tool_call") return item;
    let args = item.arguments;
    // Legacy projection wrapped JSON arguments in {input: "..."}.
    for (let depth = 0; depth < 4; depth += 1) {
      if (typeof args === "string") {
        try { args = JSON.parse(args); } catch { break; }
      } else if (args && typeof args === "object" && Object.keys(args).length === 1 && "input" in args) {
        args = args.input;
      } else break;
    }
    const command = args?.cmd || args?.command;
    const body = command
      ? `命令\n\n${fenced(command, "sh")}`
      : `参数\n\n${fenced(args, typeof args === "object" ? "json" : "text")}`;
    return {...item, type: "workflow", workflow: {tasks: [{title: item.display_summary || command || item.name || "工具调用",
      status_indicator: item.status === "pending" ? "loading" : "complete",
      content: item.details_deferred ? "" : body + (item.output == null ? "" : `\n\n输出\n\n${fenced(item.output)}`),
    }]}};
  }
  function messages(items) {
    const result = [];
    for (const raw of items) {
      const item = processItem(raw);
      const previous = result.at(-1);
      const process = item.type === "workflow";
      const role = item.type === "user_message" ? "human" : "ai";
      if (process) {
        const part = previous?.content?.[0];
        if (part?.data?.type === "FTProcess" && previous.executionId === item.turn_id) {
          part.data.items.push(item);
          continue;
        }
      } else if (role === "ai" && previous?.role === "ai" && item.turn_id && previous?.executionId === item.turn_id
          && typeof previous.content === "string") {
        previous.content += "\n\n" + content(item);
        continue;
      }
      result.push({id: item.id, role, type: role, executionId: item.turn_id,
        content: process ? [{type: "component", data: {
          type: "FTProcess", conversationId: item.thread_id, items: [item],
        }}] : attachmentParts(item).text, fileAssets: attachmentParts(item).files, createdAt: item.created_at});
    }
    return result;
  }
  function conversation(thread) {
    return {id: thread.id, threadId: thread.id, title: thread.title,
      createdAt: thread.created_at, updatedAt: thread.created_at, status: "idle"};
  }
  function create(adapter, options = {}) {
    let disposed = false;
    let currentConversation = "";
    const active = new Set();
    const pages = new Map();
    const runs = new Map();
    const liveItems = new Map();
    const uploads = new Map();
    const pendingSteers = new Map();
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
      currentConversation = id;
      let page = pages.get(id);
      if (!page || offset === 0) {
        const thread = await data("threads.get_by_id", {thread_id: id});
        page = {items: thread.items.data || [], after: thread.items.after,
          more: thread.items.has_more};
        pages.set(id, page);
      }
      while (page.more && messages(page.items).length < offset + limit) {
        const next = await data("items.list", {thread_id: id, after: page.after, limit: 50});
        const known = new Set(page.items.map(item => item.id));
        const older = (next.data || []).filter(item => !known.has(item.id));
        if (!older.length && next.has_more) throw new Error("历史消息分页没有前进");
        page.items.unshift(...older); page.after = next.after; page.more = next.has_more;
      }
      return {items: messages(page.items).slice(Math.max(0, messages(page.items).length - offset - limit), messages(page.items).length - offset),
        total: messages(page.items).length + (page.more ? 1 : 0)};
    }
    function withAttachments(text, input) {
      const files = (input?.files || []).map(file => uploads.get(file.fileId || file.id) || file);
      if (!files.length) return text;
      if (files.some(file => !/^uploads\/\d{4}-\d{2}-\d{2}\/[a-f0-9]{32}\/[^/\\]+$/.test(file.workspacePath)))
        throw new Error("附件引用无效，请重新上传");
      return text + "\n\n<factortester-attachments>\n" + JSON.stringify(files.map(({workspacePath, sha256, size, mimeType}) => ({workspacePath, sha256, size, mimeType}))) + "\n</factortester-attachments>";
    }
    async function stream(id, input, resume, signal) {
      currentConversation = id;
      const controller = new AbortController(); active.add(controller);
      signal?.addEventListener("abort", () => controller.abort(), {once: true});
      if (signal?.aborted) controller.abort();
      input = input?.state?.human || input;
      let text = typeof input?.input === "string" ? input.input :
        typeof input === "string" ? input : "";
      text = withAttachments(text, input);
      if (!resume && !text.trim()) { active.delete(controller); throw new Error("消息不能为空"); }
      let response;
      try { response = await call(resume ? "threads.resume" : "threads.add_user_message", {
        thread_id: id, skill_ids: input?.runtimeCapabilities?.skills?.ids, input: {content: [{type: "input_text", text}]},
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
                if (event.type === "thread.items.replaced") {
                  const canonical = event.items || [];
                  const turns = new Set(canonical.map(item => item.turn_id).filter(Boolean));
                  const older = event.has_more ? [...items.values()].filter(item => (
                    item.turn_id && !turns.has(item.turn_id)
                  )) : [];
                  items.clear();
                  for (const item of [...older, ...canonical]) items.set(item.id, item);
                  emit("values", {ft_authoritative: true, messages: messages([...items.values()])});
                  continue;
                }
                if (event.type === "thread.item.removed") items.delete(event.item_id);
                if (event.item?.type === "user_message") {
                  const pending = [...pendingSteers.values()].find(entry => entry.thread === id
                    && entry.turn === (event.item.turn_id || runs.get(id)) && entry.text === attachmentParts(event.item).text);
                  if (pending) {
                    pendingSteers.delete(pending.clientID);
                    emit("events", {type: "event", event: "on_chat_event", data: {
                      type: "follow_up_consumed", mode: "steer", clientMessageIds: [pending.clientID],
                      messageIds: [event.item.id], executionId: pending.turn, visibleAt: event.item.created_at,
                    }});
                  }
                }
                if (event.item || event.type === "thread.item.removed") {
                  if (event.item) items.set(event.item.id, {...event.item,
                    thread_id: event.item.thread_id || id, turn_id: event.item.turn_id || runs.get(id)});
                  emit("values", {ft_authoritative: true, messages: messages([...items.values()]).filter(item => item.content || item.fileAssets?.length)});
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
      const body = typeof init.body === "string" ? JSON.parse(init.body) : (init.body || {});
      const [kind, id, action, run, operation] = parts;
      if (kind === "contexts" && id === "file" && method === "POST") {
        if (!options.upload) return json({error: "当前会话不允许上传附件"}, 403);
        const file = body.get?.("file");
        if (!file || typeof file.arrayBuffer !== "function") return json({error: "缺少附件文件"}, 400);
        const saved = await options.upload(file);
        const fileID = identifier();
        const result = {id: fileID, fileId: fileID, storageFileId: fileID,
          originalName: saved.name, size: saved.size_bytes, mimeType: file.type,
          workspacePath: saved.path, sha256: saved.sha256, status: "ready", parseStatus: "ready", parseMode: "none"};
        uploads.set(fileID, result); return json(result);
      }
      if (kind === "files" && action === "status" && uploads.has(id)) return json(uploads.get(id));
      if (kind === "contexts" && method === "DELETE") return json({});
      if (kind === "assistants") {
        if (action === "models") return json({models: []});
        if (action === "runtime-capabilities") return json(await options.capabilities?.() || {skills: [], plugins: [], subAgents: [], workspaces: [], connectors: []});
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
      if (kind === "conversations" && action === "process-details") {
        const detail = await data("items.detail", {thread_id: id, after: body.after || ""});
        return json({...detail, data: (detail.data || []).map(processItem)});
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
          if (!turn && input?.mode === "steer") return json({error: "Steer target turn has ended"}, 409);
          if (input?.action !== "follow_up" || input.mode !== "steer" || input.conversationId !== id
              || !turn || input.target?.executionId !== turn) {
            return json({error: "Steer 目标运行已结束或不匹配"}, 409);
          }
          const human = input.message?.input;
          const text = withAttachments(typeof human === "string" ? human : human?.input || "", human);
          if (typeof text !== "string" || !text.trim()) return json({error: "消息不能为空"}, 400);
          const clientID = input.message.clientMessageId;
          if (clientID) pendingSteers.set(clientID, {clientID, thread: id, turn, text: attachmentParts({type:"user_message", content:[{text}]}).text});
          let result;
          try {
            result = await data("threads.steer", {thread_id: id, turn_id: turn,
              input: {content: [{type: "input_text", text}]}});
          } catch (error) {
            pendingSteers.delete(clientID);
            throw error;
          }
          // Acceptance is not the application position. The provider's user
          // item event inserts the steer instruction in the current turn.
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
    const key = identifier();
    controls.set(key, options.mountControls);
    closers.set(key, options.onClose);
    previews.set(key, file => options.preview?.(file, currentConversation));
    sessions.set(key, async (input, init) => {
      try { return await fetch(input, init); }
      catch (error) { return json({error: error.message}, error.status || 400); }
    });
    return {key, dispose() { disposed = true; sessions.delete(key); controls.delete(key); closers.delete(key); previews.delete(key); for (const controller of active) controller.abort(); active.clear(); }};
  }
  window.FTXpertTransport = Object.freeze({create,
    close(key) { closers.get(key)?.(); },
    preview(key, file) { return previews.get(key)?.(file); },
    mountControls(key, kind, slot) { controls.get(key)?.(kind, slot); },
    fetch(key, input, init) {
      const fetch = sessions.get(key);
      if (!fetch) return Promise.reject(new Error("会话界面通道已关闭"));
      return fetch(input, init);
    },
  });
})();
