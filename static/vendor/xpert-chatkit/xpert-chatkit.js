(function(factory) {
  typeof define === "function" && define.amd ? define(factory) : factory();
})(function() {
  "use strict";var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __knownSymbol = (name, symbol) => (symbol = Symbol[name]) ? symbol : Symbol.for("Symbol." + name);
var __typeError = (msg) => {
  throw TypeError(msg);
};
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
var __decoratorStart = (base) => [, , , __create((base == null ? void 0 : base[__knownSymbol("metadata")]) ?? null)];
var __decoratorStrings = ["class", "method", "getter", "setter", "accessor", "field", "value", "get", "set"];
var __expectFn = (fn) => fn !== void 0 && typeof fn !== "function" ? __typeError("Function expected") : fn;
var __decoratorContext = (kind, name, done, metadata, fns) => ({ kind: __decoratorStrings[kind], name, metadata, addInitializer: (fn) => done._ ? __typeError("Already initialized") : fns.push(__expectFn(fn || null)) });
var __decoratorMetadata = (array, target) => __defNormalProp(target, __knownSymbol("metadata"), array[3]);
var __runInitializers = (array, flags, self, value) => {
  for (var i = 0, fns = array[flags >> 1], n = fns && fns.length; i < n; i++) flags & 1 ? fns[i].call(self) : value = fns[i].call(self, value);
  return value;
};
var __decorateElement = (array, flags, name, decorators, target, extra) => {
  var fn, it, done, ctx, access, k = flags & 7, s = !!(flags & 8), p = !!(flags & 16);
  var j = k > 3 ? array.length + 1 : k ? s ? 1 : 2 : 0, key = __decoratorStrings[k + 5];
  var initializers = k > 3 && (array[j - 1] = []), extraInitializers = array[j] || (array[j] = []);
  var desc = k && (!p && !s && (target = target.prototype), k < 5 && (k > 3 || !p) && __getOwnPropDesc(k < 4 ? target : { get [name]() {
    return __privateGet(this, extra);
  }, set [name](x) {
    return __privateSet(this, extra, x);
  } }, name));
  k ? p && k < 4 && __name(extra, (k > 2 ? "set " : k > 1 ? "get " : "") + name) : __name(target, name);
  for (var i = decorators.length - 1; i >= 0; i--) {
    ctx = __decoratorContext(k, name, done = {}, array[3], extraInitializers);
    if (k) {
      ctx.static = s, ctx.private = p, access = ctx.access = { has: p ? (x) => __privateIn(target, x) : (x) => name in x };
      if (k ^ 3) access.get = p ? (x) => (k ^ 1 ? __privateGet : __privateMethod)(x, target, k ^ 4 ? extra : desc.get) : (x) => x[name];
      if (k > 2) access.set = p ? (x, y) => __privateSet(x, target, y, k ^ 4 ? extra : desc.set) : (x, y) => x[name] = y;
    }
    it = (0, decorators[i])(k ? k < 4 ? p ? extra : desc[key] : k > 4 ? void 0 : { get: desc.get, set: desc.set } : target, ctx), done._ = 1;
    if (k ^ 4 || it === void 0) __expectFn(it) && (k > 4 ? initializers.unshift(it) : k ? p ? extra = it : desc[key] = it : target = it);
    else if (typeof it !== "object" || it === null) __typeError("Object expected");
    else __expectFn(fn = it.get) && (desc.get = fn), __expectFn(fn = it.set) && (desc.set = fn), __expectFn(fn = it.init) && initializers.unshift(fn);
  }
  return k || __decoratorMetadata(array, target), desc && __defProp(target, name, desc), p ? k ^ 4 ? extra : desc : target;
};
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);
var __accessCheck = (obj, member, msg) => member.has(obj) || __typeError("Cannot " + msg);
var __privateIn = (member, obj) => Object(obj) !== obj ? __typeError('Cannot use the "in" operator on this value') : member.has(obj);
var __privateGet = (obj, member, getter) => (__accessCheck(obj, member, "read from private field"), getter ? getter.call(obj) : member.get(obj));
var __privateAdd = (obj, member, value) => member.has(obj) ? __typeError("Cannot add the same private member more than once") : member instanceof WeakSet ? member.add(obj) : member.set(obj, value);
var __privateSet = (obj, member, value, setter) => (__accessCheck(obj, member, "write to private field"), setter ? setter.call(obj, value) : member.set(obj, value), value);
var __privateMethod = (obj, member, method) => (__accessCheck(obj, member, "access private method"), method);

  var _a, _b, _setTrainingOptOut_dec, _hideHistory_dec, _showHistory_dec, _sendCustomAction_dec, _shareThread_dec, _setThreadId_dec, _setRuntimeCapabilities_dec, _setComposerValue_dec, _sendUserMessage_dec, _fetchUpdates_dec, _focusComposer_dec, _c, _opts, _frameUrl, _frame, _wrapper, _launcherCloseButton, _launcherOpen, _chatMinimizedToPet, _framePetOptionsOverride, _petClosedByContextMenu, _shadow, _petOverlay, _resolveLoaded, _loaded, _channelId, _messenger, _ChatKitElementBase_instances, emitAndThrow_fn, setOptionsDataAttributes_fn, getDisplayMode_fn, getConfiguredPetOptions_fn, mergeConfiguredPetPositionDefaults_fn, getOverlayPetOptions_fn, resolvePetAssetUrl_fn, resolveOverlayPetOptions_fn, getFrameOptions_fn, setLauncherOpen_fn, setChatMinimizedToPet_fn, syncPetOverlayOptions_fn, handlePetActivate_fn, handlePetClose_fn, handlePetReply_fn, handlePetThreadSummaryActivate_fn, _handleLauncherClose, getFrameUrl_fn, setFrameUrl_fn, consumeFrameUrl_fn, _handleFrameLoad, _initialized, maybeInit_fn, _init;
  class EventEmitter {
    constructor() {
      __publicField(this, "callbacks", /* @__PURE__ */ new Map());
    }
    on(event, callback) {
      if (!this.callbacks.has(event)) {
        this.callbacks.set(event, /* @__PURE__ */ new Set());
      }
      this.callbacks.get(event).add(callback);
    }
    emit(event, ...args) {
      var _a2;
      const data = args[0];
      (_a2 = this.callbacks.get(event)) == null ? void 0 : _a2.forEach((callback) => callback(data));
    }
    off(event, callback) {
      var _a2;
      if (!callback) {
        this.callbacks.delete(event);
      } else {
        (_a2 = this.callbacks.get(event)) == null ? void 0 : _a2.delete(callback);
      }
    }
    allOff() {
      this.callbacks.clear();
    }
  }
  async function getBytes(stream, onChunk) {
    const reader = stream.getReader();
    let result;
    while (!(result = await reader.read()).done) {
      onChunk(result.value);
    }
  }
  function getLines(onLine) {
    let buffer;
    let position;
    let fieldLength;
    let discardTrailingNewline = false;
    return function onChunk(arr) {
      if (buffer === void 0) {
        buffer = arr;
        position = 0;
        fieldLength = -1;
      } else {
        buffer = concat(buffer, arr);
      }
      const bufLength = buffer.length;
      let lineStart = 0;
      while (position < bufLength) {
        if (discardTrailingNewline) {
          if (buffer[position] === 10) {
            lineStart = ++position;
          }
          discardTrailingNewline = false;
        }
        let lineEnd = -1;
        for (; position < bufLength && lineEnd === -1; ++position) {
          switch (buffer[position]) {
            case 58:
              if (fieldLength === -1) {
                fieldLength = position - lineStart;
              }
              break;
            case 13:
              discardTrailingNewline = true;
            case 10:
              lineEnd = position;
              break;
          }
        }
        if (lineEnd === -1) {
          break;
        }
        onLine(buffer.subarray(lineStart, lineEnd), fieldLength);
        lineStart = position;
        fieldLength = -1;
      }
      if (lineStart === bufLength) {
        buffer = void 0;
      } else if (lineStart !== 0) {
        buffer = buffer.subarray(lineStart);
        position -= lineStart;
      }
    };
  }
  function getMessages(onId, onRetry, onMessage) {
    let message = newMessage();
    const decoder = new TextDecoder();
    return function onLine(line, fieldLength) {
      if (line.length === 0) {
        onMessage === null || onMessage === void 0 ? void 0 : onMessage(message);
        message = newMessage();
      } else if (fieldLength > 0) {
        const field = decoder.decode(line.subarray(0, fieldLength));
        const valueOffset = fieldLength + (line[fieldLength + 1] === 32 ? 2 : 1);
        const value = decoder.decode(line.subarray(valueOffset));
        switch (field) {
          case "data":
            message.data = message.data ? message.data + "\n" + value : value;
            break;
          case "event":
            message.event = value;
            break;
          case "id":
            onId(message.id = value);
            break;
          case "retry":
            const retry = parseInt(value, 10);
            if (!isNaN(retry)) {
              onRetry(message.retry = retry);
            }
            break;
        }
      }
    };
  }
  function concat(a, b) {
    const res = new Uint8Array(a.length + b.length);
    res.set(a);
    res.set(b, a.length);
    return res;
  }
  function newMessage() {
    return {
      data: "",
      event: "",
      id: "",
      retry: void 0
    };
  }
  var __rest = function(s, e) {
    var t = {};
    for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p) && e.indexOf(p) < 0)
      t[p] = s[p];
    if (s != null && typeof Object.getOwnPropertySymbols === "function")
      for (var i = 0, p = Object.getOwnPropertySymbols(s); i < p.length; i++) {
        if (e.indexOf(p[i]) < 0 && Object.prototype.propertyIsEnumerable.call(s, p[i]))
          t[p[i]] = s[p[i]];
      }
    return t;
  };
  const EventStreamContentType = "text/event-stream";
  const DefaultRetryInterval = 1e3;
  const LastEventId = "last-event-id";
  function fetchEventSource(input, _a2) {
    var { signal: inputSignal, headers: inputHeaders, onopen: inputOnOpen, onmessage, onclose, onerror, openWhenHidden, fetch: inputFetch } = _a2, rest = __rest(_a2, ["signal", "headers", "onopen", "onmessage", "onclose", "onerror", "openWhenHidden", "fetch"]);
    return new Promise((resolve, reject) => {
      const headers = Object.assign({}, inputHeaders);
      if (!headers.accept) {
        headers.accept = EventStreamContentType;
      }
      let curRequestController;
      function onVisibilityChange() {
        curRequestController.abort();
        if (!document.hidden) {
          create();
        }
      }
      if (!openWhenHidden) {
        document.addEventListener("visibilitychange", onVisibilityChange);
      }
      let retryInterval = DefaultRetryInterval;
      let retryTimer = 0;
      function dispose() {
        document.removeEventListener("visibilitychange", onVisibilityChange);
        window.clearTimeout(retryTimer);
        curRequestController.abort();
      }
      inputSignal === null || inputSignal === void 0 ? void 0 : inputSignal.addEventListener("abort", () => {
        dispose();
        resolve();
      });
      const fetch2 = inputFetch !== null && inputFetch !== void 0 ? inputFetch : window.fetch;
      const onopen = inputOnOpen !== null && inputOnOpen !== void 0 ? inputOnOpen : defaultOnOpen;
      async function create() {
        var _a3;
        curRequestController = new AbortController();
        try {
          const response = await fetch2(input, Object.assign(Object.assign({}, rest), { headers, signal: curRequestController.signal }));
          await onopen(response);
          await getBytes(response.body, getLines(getMessages((id) => {
            if (id) {
              headers[LastEventId] = id;
            } else {
              delete headers[LastEventId];
            }
          }, (retry) => {
            retryInterval = retry;
          }, onmessage)));
          onclose === null || onclose === void 0 ? void 0 : onclose();
          dispose();
          resolve();
        } catch (err) {
          if (!curRequestController.signal.aborted) {
            try {
              const interval = (_a3 = onerror === null || onerror === void 0 ? void 0 : onerror(err)) !== null && _a3 !== void 0 ? _a3 : retryInterval;
              window.clearTimeout(retryTimer);
              retryTimer = window.setTimeout(create, interval);
            } catch (innerErr) {
              dispose();
              reject(innerErr);
            }
          }
        }
      }
      create();
    });
  }
  function defaultOnOpen(response) {
    const contentType = response.headers.get("content-type");
    if (!(contentType === null || contentType === void 0 ? void 0 : contentType.startsWith(EventStreamContentType))) {
      throw new Error(`Expected content-type to be ${EventStreamContentType}, Actual: ${contentType}`);
    }
  }
  const FRAME_SAFE_ERROR_KEY = "__chatkit_error__";
  class HttpError extends Error {
    constructor(message, res, metadata) {
      super(message);
      __publicField(this, "status");
      __publicField(this, "statusText");
      __publicField(this, "metadata");
      this.name = "HttpError";
      this.statusText = res.statusText;
      this.status = res.status;
      this.metadata = metadata;
    }
    static fromPossibleFrameSafeError(error) {
      if (error instanceof HttpError) {
        return error;
      }
      if (error && typeof error === "object" && FRAME_SAFE_ERROR_KEY in error && error[FRAME_SAFE_ERROR_KEY] === "HttpError") {
        const safeError = error;
        const parsedError = new HttpError(
          safeError.message,
          {
            status: safeError.status,
            statusText: safeError.statusText
          },
          safeError.metadata
        );
        parsedError.stack = safeError.stack;
        return parsedError;
      }
      return null;
    }
  }
  _a = FRAME_SAFE_ERROR_KEY;
  const _FrameSafeHttpError = class _FrameSafeHttpError {
    constructor(message, res, metadata) {
      __publicField(this, _a, "HttpError");
      __publicField(this, "message");
      __publicField(this, "stack");
      __publicField(this, "status");
      __publicField(this, "statusText");
      __publicField(this, "metadata");
      this.message = message;
      this.stack = new Error(message).stack;
      this.status = res.status;
      this.statusText = res.statusText;
      this.metadata = metadata;
    }
    static fromHttpError(error) {
      return new _FrameSafeHttpError(
        error.message,
        {
          status: error.status,
          statusText: error.statusText
        },
        error.metadata
      );
    }
  };
  let FrameSafeHttpError = _FrameSafeHttpError;
  const BASE_RETRY_DELAY_MS = 1e3;
  const MAX_RETRY_DELAY_MS = 1e4;
  const MAX_RETRY_ATTEMPTS = 5;
  const nextDelay = (attempt, maxRetryDelay = MAX_RETRY_DELAY_MS, baseDelayMs = BASE_RETRY_DELAY_MS) => {
    const max = Math.min(maxRetryDelay, baseDelayMs * 2 ** attempt);
    return Math.floor(max * (0.5 + Math.random() * 0.5));
  };
  class RetryableError extends Error {
    constructor(cause) {
      super();
      this.cause = cause;
    }
  }
  const fetchEventSourceWithRetry = async (url, params) => {
    let retryAttempt = 0;
    const { onopen, ...restParams } = params;
    await fetchEventSource(url, {
      ...restParams,
      onopen: async (res) => {
        var _a2;
        onopen == null ? void 0 : onopen(res);
        if (res.ok && ((_a2 = res.headers.get("content-type")) == null ? void 0 : _a2.startsWith("text/event-stream"))) {
          retryAttempt = 0;
          return;
        }
        const httpError = new FrameSafeHttpError(`Streaming failed: ${res.statusText}`, res);
        if (res.status >= 400 && res.status < 500) {
          throw httpError;
        } else {
          throw new RetryableError(httpError);
        }
      },
      onerror: (error) => {
        if (error instanceof RetryableError) {
          if (retryAttempt >= MAX_RETRY_ATTEMPTS) {
            throw error.cause;
          }
          retryAttempt += 1;
          return nextDelay(retryAttempt);
        }
        throw error;
      }
    });
  };
  function createSecureChannelId() {
    const cryptoRef = globalThis.crypto;
    if (typeof (cryptoRef == null ? void 0 : cryptoRef.randomUUID) === "function") {
      return cryptoRef.randomUUID();
    }
    if (typeof (cryptoRef == null ? void 0 : cryptoRef.getRandomValues) === "function") {
      const bytes = new Uint8Array(16);
      cryptoRef.getRandomValues(bytes);
      bytes[6] = bytes[6] & 15 | 64;
      bytes[8] = bytes[8] & 63 | 128;
      return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("").replace(/^(.{8})(.{4})(.{4})(.{4})(.{12})$/, "$1-$2-$3-$4-$5");
    }
    return null;
  }
  function safeRandomUUID() {
    return createSecureChannelId() ?? `ck_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
  function isTrustedChatKitMessageEvent(event, { channelId, expectedOrigin, expectedSource }) {
    const payload = event.data;
    if (!payload || typeof payload !== "object" || !("__xpaiChatKit" in payload)) {
      return false;
    }
    if (payload.__xpaiChatKit !== true) {
      return false;
    }
    if (expectedOrigin !== "*" && event.origin !== expectedOrigin) {
      return false;
    }
    if (event.source === expectedSource) {
      return true;
    }
    const normalizedChannelId = channelId == null ? void 0 : channelId.trim();
    if (normalizedChannelId) {
      return "channelId" in payload && payload.channelId === normalizedChannelId;
    }
    return false;
  }
  let IntegrationError$1 = class IntegrationError2 extends Error {
    constructor(message) {
      super(message);
      __publicField(this, "_name");
      this.name = "IntegrationError";
      this._name = this.name;
    }
    static fromPossibleFrameSafeError(error) {
      if (error && typeof error === "object" && FRAME_SAFE_ERROR_KEY in error && error[FRAME_SAFE_ERROR_KEY] === "IntegrationError") {
        const safeError = error;
        const parsedError = new IntegrationError2(safeError.message);
        parsedError.stack = safeError.stack;
        return parsedError;
      }
      return null;
    }
  };
  _b = FRAME_SAFE_ERROR_KEY;
  class FrameSafeIntegrationError {
    constructor(message) {
      __publicField(this, _b, "IntegrationError");
      __publicField(this, "message");
      __publicField(this, "stack");
      this.message = message;
      this.stack = new Error(message).stack;
    }
  }
  class BaseMessenger {
    constructor({
      handlers,
      target,
      targetOrigin,
      channelId,
      fetch: fetch2 = window.fetch
    }) {
      __publicField(this, "targetOrigin");
      __publicField(this, "target");
      __publicField(this, "channelId");
      __publicField(this, "commandHandlers");
      __publicField(this, "_fetch");
      __publicField(this, "emitter", new EventEmitter());
      __publicField(this, "handlers", /* @__PURE__ */ new Map());
      __publicField(this, "fetchEventSourceHandlers", /* @__PURE__ */ new Map());
      __publicField(this, "abortControllers", /* @__PURE__ */ new Map());
      __publicField(this, "commands", new Proxy(
        {},
        {
          get: (_, command) => {
            return (data, transfer) => {
              return new Promise((resolve, reject) => {
                const nonce = safeRandomUUID();
                this.handlers.set(nonce, { resolve, reject, stack: new Error().stack || "" });
                this.sendMessage(
                  {
                    type: "command",
                    nonce,
                    command: `on${command.charAt(0).toUpperCase()}${command.slice(1)}`,
                    data
                  },
                  transfer
                );
              });
            };
          }
        }
      ));
      __publicField(this, "handleMessage", async (event) => {
        var _a2, _b2, _c2, _d;
        if (!isTrustedChatKitMessageEvent(event, {
          channelId: this.channelId,
          expectedOrigin: this.targetOrigin,
          expectedSource: this.target()
        })) {
          return;
        }
        const data = event.data;
        switch (data.type) {
          case "event": {
            this.emitter.emit(data.event, data.data);
            break;
          }
          case "fetch": {
            try {
              if (data.formData) {
                const formData = new FormData();
                for (const [key, value] of Object.entries(data.formData)) {
                  formData.append(key, value);
                }
                data.params.body = formData;
              }
              const controller = new AbortController();
              this.abortControllers.set(data.nonce, controller);
              data.params.signal = controller.signal;
              const res = await this._fetch(data.url, data.params);
              if (!res.ok) {
                const message = await res.json().then((json2) => json2.message || res.statusText).catch(() => res.statusText);
                throw new FrameSafeHttpError(message, res);
              }
              const json = await res.json().catch(() => ({}));
              this.sendMessage({
                type: "response",
                response: json,
                nonce: data.nonce
              });
            } catch (error) {
              this.sendMessage({
                type: "response",
                error,
                nonce: data.nonce
              });
            }
            break;
          }
          case "fetchEventSource": {
            try {
              const controller = new AbortController();
              this.abortControllers.set(data.nonce, controller);
              await fetchEventSourceWithRetry(data.url, {
                ...data.params,
                signal: controller.signal,
                fetch: this._fetch,
                onmessage: (message) => {
                  this.sendMessage({
                    type: "fetchEventSourceMessage",
                    message,
                    nonce: data.nonce
                  });
                }
              });
              this.sendMessage({
                type: "response",
                response: void 0,
                nonce: data.nonce
              });
            } catch (error) {
              this.sendMessage({
                type: "response",
                error,
                nonce: data.nonce
              });
            }
            break;
          }
          case "command": {
            if (!this.canReceiveCommand(data.command)) {
              this.sendMessage({
                type: "response",
                error: new FrameSafeIntegrationError(`Command ${data.command} not supported`),
                nonce: data.nonce
              });
              return;
            }
            try {
              const response = await ((_b2 = (_a2 = this.commandHandlers)[data.command]) == null ? void 0 : _b2.call(_a2, data.data));
              this.sendMessage({
                type: "response",
                response,
                nonce: data.nonce
              });
            } catch (error) {
              this.sendMessage({
                type: "response",
                error,
                nonce: data.nonce
              });
            }
            break;
          }
          case "response": {
            const handler = this.handlers.get(data.nonce);
            if (!handler) {
              console.error("No handler found for nonce", data.nonce);
              return;
            }
            if (data.error) {
              const integrationError = IntegrationError$1.fromPossibleFrameSafeError(data.error);
              const httpError = HttpError.fromPossibleFrameSafeError(data.error);
              if (integrationError) {
                integrationError.stack = handler.stack;
                handler.reject(integrationError);
              } else if (httpError) {
                handler.reject(httpError);
              } else {
                handler.reject(data.error);
              }
            } else {
              handler.resolve(data.response);
            }
            this.handlers.delete(data.nonce);
            break;
          }
          case "fetchEventSourceMessage": {
            const handler = this.fetchEventSourceHandlers.get(data.nonce);
            if (!handler) {
              console.error("No handler found for nonce", data.nonce);
              return;
            }
            (_d = (_c2 = this.fetchEventSourceHandlers.get(data.nonce)) == null ? void 0 : _c2.onmessage) == null ? void 0 : _d.call(_c2, data.message);
            break;
          }
          case "abortSignal": {
            const controller = this.abortControllers.get(data.nonce);
            if (controller) {
              controller.abort(data.reason);
              this.abortControllers.delete(data.nonce);
            }
            break;
          }
        }
      });
      this.commandHandlers = handlers;
      this.target = target;
      this.targetOrigin = targetOrigin;
      this.channelId = (channelId == null ? void 0 : channelId.trim()) || void 0;
      this._fetch = (...args) => fetch2(...args);
    }
    setTargetOrigin(targetOrigin) {
      this.targetOrigin = targetOrigin;
    }
    sendMessage(data, transfer) {
      var _a2;
      const message = {
        __xpaiChatKit: true,
        ...this.channelId ? { channelId: this.channelId } : {},
        ...data
      };
      (_a2 = this.target()) == null ? void 0 : _a2.postMessage(message, this.targetOrigin, transfer);
    }
    connect() {
      window.addEventListener("message", this.handleMessage);
    }
    disconnect() {
      window.removeEventListener("message", this.handleMessage);
    }
    fetch(url, params) {
      return new Promise((resolve, reject) => {
        const nonce = safeRandomUUID();
        this.handlers.set(nonce, { resolve, reject, stack: new Error().stack || "" });
        let formData;
        if (params.body instanceof FormData) {
          formData = {};
          for (const [key, value] of params.body.entries()) {
            formData[key] = value;
          }
          params.body = void 0;
        }
        if (params.signal) {
          params.signal.addEventListener("abort", () => {
            var _a2;
            this.sendMessage({
              type: "abortSignal",
              nonce,
              reason: (_a2 = params.signal) == null ? void 0 : _a2.reason
            });
          });
          params.signal = void 0;
        }
        this.sendMessage({ type: "fetch", nonce, params, formData, url });
      });
    }
    // Supporting onopen would require a good way for us to serialize the Response object
    // across the iframe boundary, which is not trivial and also not really necessary.
    fetchEventSource(url, params) {
      return new Promise((resolve, reject) => {
        const { onmessage, signal, ...rest } = params;
        const nonce = safeRandomUUID();
        this.handlers.set(nonce, { resolve, reject, stack: new Error().stack || "" });
        this.fetchEventSourceHandlers.set(nonce, {
          onmessage
        });
        if (signal) {
          signal.addEventListener("abort", () => {
            this.sendMessage({
              type: "abortSignal",
              nonce,
              reason: signal.reason
            });
          });
        }
        this.sendMessage({ type: "fetchEventSource", nonce, params: rest, url });
      });
    }
    emit(...[event, data, transfer]) {
      this.sendMessage(
        {
          type: "event",
          event,
          data
        },
        transfer
      );
    }
    on(...[event, callback]) {
      this.emitter.on(event, callback);
    }
    destroy() {
      window.removeEventListener("message", this.handleMessage);
      this.emitter.allOff();
      this.handlers.clear();
    }
  }
  const toUrlBase64 = (bin) => btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const encodeBase64 = (value) => {
    if (value === void 0) {
      throw new TypeError(
        "encodeBase64: `undefined` cannot be encoded to valid JSON. Pass null instead."
      );
    }
    const json = JSON.stringify(value);
    const bytes = new TextEncoder().encode(json);
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    return toUrlBase64(bin);
  };
  class IntegrationError extends Error {
  }
  function fromPossibleFrameSafeError(err) {
    return err.message;
  }
  const BASE_CAPABILITY_ALLOWLIST = [
    // commands
    "command.setOptions",
    "command.sendUserMessage",
    "command.setComposerValue",
    "command.setRuntimeCapabilities",
    "command.setThreadId",
    "command.focusComposer",
    "command.fetchUpdates",
    "command.sendCustomAction",
    "command.showHistory",
    "command.hideHistory",
    // events
    "event.ready",
    "event.error",
    "event.log",
    "event.response.start",
    "event.response.end",
    "event.response.stop",
    "event.thread.change",
    "event.project.change",
    "event.connectors.change",
    "event.tool.change",
    "event.thread.load.start",
    "event.thread.load.end",
    "event.deeplink",
    "event.effect",
    // errors
    "error.StreamError",
    "error.StreamEventParsingError",
    "error.WidgetItemError",
    "error.InitialThreadLoadError",
    "error.FileAttachmentError",
    "error.HistoryViewError",
    "error.FatalAppError",
    "error.IntegrationError",
    "error.EntitySearchError",
    "error.DomainVerificationRequestError",
    // backend
    "backend.threads.get_by_id",
    "backend.threads.list",
    "backend.threads.update",
    "backend.threads.delete",
    "backend.threads.create",
    "backend.threads.add_user_message",
    "backend.threads.add_client_tool_output",
    "backend.threads.retry_after_item",
    "backend.threads.custom_action",
    "backend.attachments.create",
    "backend.attachments.get_preview",
    "backend.attachments.delete",
    "backend.items.list",
    "backend.items.feedback",
    // thread item types
    "thread.item.generated_image",
    "thread.item.user_message",
    "thread.item.assistant_message",
    "thread.item.client_tool_call",
    "thread.item.widget",
    "thread.item.task",
    "thread.item.workflow",
    "thread.item.end_of_turn",
    "thread.item.image_generation",
    // widgets
    "widget.Basic",
    "widget.Card",
    "widget.ListView",
    "widget.ListViewItem",
    "widget.Badge",
    "widget.Box",
    "widget.Row",
    "widget.Col",
    "widget.Button",
    "widget.Caption",
    "widget.Chart",
    "widget.Checkbox",
    "widget.DatePicker",
    "widget.Divider",
    "widget.Form",
    "widget.Icon",
    "widget.Image",
    "widget.Input",
    "widget.Label",
    "widget.Markdown",
    "widget.RadioGroup",
    "widget.Select",
    "widget.Spacer",
    "widget.Text",
    "widget.Textarea",
    "widget.Title",
    "widget.Transition"
  ];
  const BASE_CAPABILITY_DENYLIST = [
    // --- commands
    "command.shareThread",
    "command.setTrainingOptOut",
    // --- events
    "event.thread.restore",
    "event.message.share",
    "event.image.download",
    "event.history.open",
    "event.history.close",
    "event.log.chatgpt",
    // --- errors
    // These errors considered internal and are not exposed to the user by default.
    "error.HttpError",
    "error.NetworkError",
    "error.UnhandledError",
    "error.UnhandledPromiseRejectionError",
    "error.StreamEventHandlingError",
    "error.StreamStopError",
    "error.ThreadRenderingError",
    "error.IntlError",
    "error.AppError",
    // --- backend
    "backend.threads.stop",
    "backend.threads.share",
    "backend.threads.create_from_shared",
    "backend.threads.init",
    "backend.attachments.process",
    // widgets
    "widget.CardCarousel",
    "widget.Favicon",
    "widget.CardLinkItem",
    "widget.Map"
  ];
  const PROFILE_TO_RULES = {
    chatkit: {
      allow: [...BASE_CAPABILITY_ALLOWLIST, "thread.item.image_generation"],
      deny: BASE_CAPABILITY_DENYLIST
    }
  };
  const getCapabilities = (profile) => {
    const rules = PROFILE_TO_RULES[profile];
    const effective = new Set(rules.allow);
    for (const capability of rules.deny ?? []) {
      effective.delete(capability);
    }
    const commands = /* @__PURE__ */ new Set();
    const events = /* @__PURE__ */ new Set();
    const backend = /* @__PURE__ */ new Set();
    const threadItems = /* @__PURE__ */ new Set();
    const errors = /* @__PURE__ */ new Set();
    const widgets = /* @__PURE__ */ new Set();
    for (const capability of effective) {
      if (capability.startsWith("command.")) {
        commands.add(capability.slice("command.".length));
        continue;
      }
      if (capability.startsWith("event.")) {
        events.add(capability.slice("event.".length));
        continue;
      }
      if (capability.startsWith("backend.")) {
        backend.add(capability.slice("backend.".length));
        continue;
      }
      if (capability.startsWith("thread.item.")) {
        threadItems.add(capability.slice("thread.item.".length));
      }
      if (capability.startsWith("error.")) {
        errors.add(capability.slice("error.".length));
        continue;
      }
      if (capability.startsWith("widget.")) {
        widgets.add(capability.slice("widget.".length));
        continue;
      }
    }
    return { commands, events, backend, threadItems, errors, widgets };
  };
  class ChatFrameMessenger extends BaseMessenger {
    // Messenger running in outer can always handle commands coming from inner
    canReceiveCommand(_) {
      return true;
    }
  }
  const PET_ANIMATION_NAMES = [
    "idle",
    "running-right",
    "running-left",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review"
  ];
  const petSpriteAtlas = {
    columns: 8,
    rows: 9,
    cellWidth: 192,
    cellHeight: 208,
    animations: {
      idle: {
        row: 0,
        frames: 6,
        frameDurations: [280, 110, 110, 140, 140, 320]
      },
      "running-right": {
        row: 1,
        frames: 8,
        frameDurations: [120, 120, 120, 120, 120, 120, 120, 220]
      },
      "running-left": {
        row: 2,
        frames: 8,
        frameDurations: [120, 120, 120, 120, 120, 120, 120, 220]
      },
      waving: {
        row: 3,
        frames: 4,
        frameDurations: [140, 140, 140, 280]
      },
      jumping: {
        row: 4,
        frames: 5,
        frameDurations: [140, 140, 140, 140, 280]
      },
      failed: {
        row: 5,
        frames: 8,
        frameDurations: [140, 140, 140, 140, 140, 140, 140, 240]
      },
      waiting: {
        row: 6,
        frames: 6,
        frameDurations: [150, 150, 150, 150, 150, 260]
      },
      running: {
        row: 7,
        frames: 6,
        frameDurations: [120, 120, 120, 120, 120, 220]
      },
      review: {
        row: 8,
        frames: 6,
        frameDurations: [150, 150, 150, 150, 150, 280]
      }
    }
  };
  const DEFAULT_PET_BOUNDS_PADDING = {
    top: 0,
    right: 0,
    bottom: 0,
    left: 0
  };
  const DEFAULT_PET_STORAGE_KEY = "chatkit:pet:position:v1";
  const DEFAULT_PET_SPRITESHEET_URL = "/pets/boba/spritesheet.webp";
  const DEFAULT_PET_CHARACTER = {
    type: "sprite-atlas",
    src: DEFAULT_PET_SPRITESHEET_URL
  };
  const DEFAULT_POSITION = {
    pin: "bottom-right",
    draggable: true,
    scale: 0.25,
    persist: true,
    zIndex: 40
  };
  function mergeFrameAnimation(base, override) {
    return {
      row: (override == null ? void 0 : override.row) ?? base.row,
      frames: (override == null ? void 0 : override.frames) ?? base.frames,
      frameDurations: (override == null ? void 0 : override.frameDurations) && override.frameDurations.length > 0 ? override.frameDurations : base.frameDurations
    };
  }
  function mergePetSpriteAtlas(override) {
    var _a2;
    const animations = {};
    for (const name of PET_ANIMATION_NAMES) {
      animations[name] = mergeFrameAnimation(
        petSpriteAtlas.animations[name],
        (_a2 = override == null ? void 0 : override.animations) == null ? void 0 : _a2[name]
      );
    }
    return {
      columns: (override == null ? void 0 : override.columns) ?? petSpriteAtlas.columns,
      rows: (override == null ? void 0 : override.rows) ?? petSpriteAtlas.rows,
      cellWidth: (override == null ? void 0 : override.cellWidth) ?? petSpriteAtlas.cellWidth,
      cellHeight: (override == null ? void 0 : override.cellHeight) ?? petSpriteAtlas.cellHeight,
      animations
    };
  }
  function normalizeCharacter(character) {
    if (!character) {
      return DEFAULT_PET_CHARACTER;
    }
    if (character.src) {
      return character;
    }
    return DEFAULT_PET_CHARACTER;
  }
  function normalizePetOptions(pet) {
    if (!pet) {
      return null;
    }
    if (pet === true) {
      return {
        character: DEFAULT_PET_CHARACTER,
        position: DEFAULT_POSITION,
        behavior: "auto",
        ariaLabel: "Animated pet",
        imageRendering: "auto"
      };
    }
    if (pet.enabled === false) {
      return null;
    }
    return {
      character: normalizeCharacter(pet.character),
      position: {
        ...DEFAULT_POSITION,
        ...pet.position
      },
      behavior: pet.behavior ?? "auto",
      ariaLabel: pet.ariaLabel ?? "Animated pet",
      imageRendering: pet.imageRendering ?? "auto"
    };
  }
  function resolvePetCharacter(character) {
    if (!character.src) {
      return null;
    }
    return {
      kind: "atlas",
      src: character.src,
      atlas: mergePetSpriteAtlas(character.atlas)
    };
  }
  function normalizeBoundsPadding(value) {
    if (typeof value === "number") {
      return {
        top: value,
        right: value,
        bottom: value,
        left: value
      };
    }
    return {
      top: (value == null ? void 0 : value.top) ?? DEFAULT_PET_BOUNDS_PADDING.top,
      right: (value == null ? void 0 : value.right) ?? DEFAULT_PET_BOUNDS_PADDING.right,
      bottom: (value == null ? void 0 : value.bottom) ?? DEFAULT_PET_BOUNDS_PADDING.bottom,
      left: (value == null ? void 0 : value.left) ?? DEFAULT_PET_BOUNDS_PADDING.left
    };
  }
  function clampPetPosition(position, size, viewport, padding) {
    const minX = padding.left;
    const minY = padding.top;
    const maxX = Math.max(minX, viewport.width - size.width - padding.right);
    const maxY = Math.max(minY, viewport.height - size.height - padding.bottom);
    return {
      x: Math.min(maxX, Math.max(minX, position.x)),
      y: Math.min(maxY, Math.max(minY, position.y))
    };
  }
  function getPinnedPetPosition(pin, size, viewport, padding) {
    const horizontalCenter = (viewport.width - size.width) / 2;
    const verticalCenter = (viewport.height - size.height) / 2;
    const right = viewport.width - size.width - padding.right;
    const bottom = viewport.height - size.height - padding.bottom;
    switch (pin) {
      case "top-left":
        return clampPetPosition(
          { x: padding.left, y: padding.top },
          size,
          viewport,
          padding
        );
      case "top":
        return clampPetPosition(
          { x: horizontalCenter, y: padding.top },
          size,
          viewport,
          padding
        );
      case "top-right":
        return clampPetPosition(
          { x: right, y: padding.top },
          size,
          viewport,
          padding
        );
      case "left":
        return clampPetPosition(
          { x: padding.left, y: verticalCenter },
          size,
          viewport,
          padding
        );
      case "center":
        return clampPetPosition(
          { x: horizontalCenter, y: verticalCenter },
          size,
          viewport,
          padding
        );
      case "right":
        return clampPetPosition(
          { x: right, y: verticalCenter },
          size,
          viewport,
          padding
        );
      case "bottom-left":
        return clampPetPosition(
          { x: padding.left, y: bottom },
          size,
          viewport,
          padding
        );
      case "bottom":
        return clampPetPosition(
          { x: horizontalCenter, y: bottom },
          size,
          viewport,
          padding
        );
      case "bottom-right":
      default:
        return clampPetPosition({ x: right, y: bottom }, size, viewport, padding);
    }
  }
  const removeMethods = (obj, seen = /* @__PURE__ */ new WeakSet()) => {
    if (typeof obj === "function") return "[ChatKitMethod]";
    if (typeof obj !== "object" || obj === null) return obj;
    if (seen.has(obj)) return obj;
    seen.add(obj);
    if (Array.isArray(obj)) {
      return obj.map((c) => removeMethods(c, seen));
    }
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value !== "function") {
        result[key] = removeMethods(value, seen);
      } else {
        result[key] = "[ChatKitMethod]";
      }
    }
    return result;
  };
  const DRAG_DIRECTION_THRESHOLD_PX = 2;
  const PET_BASE_RENDER_SCALE = 0.5;
  const PET_FRAME_DURATION_MULTIPLIER = 1.5;
  const PET_RESTING_FRAME_DURATION_MULTIPLIER = 3;
  const PET_RESTING_DELAY_MS = 2e3;
  const PET_SUMMARY_GAP = 12;
  const PET_SUMMARY_WIDTH = 320;
  const PET_SUMMARY_MARGIN = 12;
  const PET_CONTEXT_MENU_MARGIN = 8;
  const PET_SUMMARY_FONT_FAMILY = 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  const PET_OVERLAY_COPY = {
    "en-US": {
      closePetMenuItem: "Close pet",
      hideMessage: "Hide message",
      expandMessage: "Expand message",
      collapseMessage: "Collapse message",
      restoreMessage: "Show message",
      replyButton: "Reply",
      replyPlaceholder: "Reply...",
      sendButton: "Send",
      sendingButton: "Sending...",
      sendFailed: "Failed to send"
    },
    "zh-CN": {
      closePetMenuItem: "关闭宠物",
      hideMessage: "隐藏消息",
      expandMessage: "展开消息",
      collapseMessage: "收起消息",
      restoreMessage: "显示消息",
      replyButton: "回复",
      replyPlaceholder: "输入回复...",
      sendButton: "发送",
      sendingButton: "发送中...",
      sendFailed: "发送失败"
    }
  };
  function stopEventPropagation(event) {
    event.stopPropagation();
  }
  function getViewportSize() {
    const visualViewport = window.visualViewport;
    return {
      width: (visualViewport == null ? void 0 : visualViewport.width) || window.innerWidth || 320,
      height: (visualViewport == null ? void 0 : visualViewport.height) || window.innerHeight || 480
    };
  }
  function readPersistedPosition(storageKey, persist) {
    if (!persist) {
      return null;
    }
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || typeof parsed.x !== "number" || typeof parsed.y !== "number") {
        return null;
      }
      return { x: parsed.x, y: parsed.y };
    } catch {
      return null;
    }
  }
  function writePersistedPosition(storageKey, persist, position) {
    if (!persist) {
      return;
    }
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(position));
    } catch {
    }
  }
  function escapeCssUrl(value) {
    return value.replace(/["\\]/g, "\\$&");
  }
  function getRenderScale(scale) {
    return Math.max(0.1, scale) * PET_BASE_RENDER_SCALE;
  }
  function clampNumber(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }
  function getDefaultLocale() {
    if (typeof window !== "undefined") {
      try {
        const stored = window.localStorage.getItem("chatkit:locale");
        if (stored) {
          return stored;
        }
      } catch {
      }
    }
    return typeof navigator !== "undefined" ? navigator.language : null;
  }
  function resolveCopyLocale(locale) {
    const normalized = (locale ?? getDefaultLocale() ?? "").trim().toLowerCase();
    if (normalized === "zh-cn" || normalized === "zh-hans" || normalized.startsWith("zh")) {
      return "zh-CN";
    }
    return "en-US";
  }
  function getSummaryDensityMetrics(density) {
    switch (density) {
      case "compact":
        return {
          padding: "8px 10px",
          gap: 6,
          marginTop: 3,
          toggleSize: 30,
          actionSize: 22
        };
      case "spacious":
        return {
          padding: "14px 16px",
          gap: 10,
          marginTop: 6,
          toggleSize: 38,
          actionSize: 28
        };
      case "normal":
      default:
        return {
          padding: "12px 14px",
          gap: 8,
          marginTop: 4,
          toggleSize: 34,
          actionSize: 26
        };
    }
  }
  function getSummaryRadius(radius) {
    switch (radius) {
      case "pill":
        return 24;
      case "round":
        return 16;
      case "sharp":
        return 0;
      case "soft":
      default:
        return 12;
    }
  }
  function getSummaryThemeMetrics(theme) {
    var _a2, _b2;
    const themeObject = typeof theme === "string" ? null : theme;
    const baseSize = ((_a2 = themeObject == null ? void 0 : themeObject.typography) == null ? void 0 : _a2.baseSize) ?? 16;
    const density = (themeObject == null ? void 0 : themeObject.density) ?? "normal";
    const densityOffset = density === "compact" ? -1 : density === "spacious" ? 1 : 0;
    const bodySize = clampNumber(baseSize - 2 + densityOffset, 11, 17);
    const densityMetrics = getSummaryDensityMetrics(density);
    return {
      ...densityMetrics,
      bodySize,
      titleSize: bodySize + 1,
      iconSize: clampNumber(bodySize + 2, 13, 19),
      radius: getSummaryRadius(themeObject == null ? void 0 : themeObject.radius),
      fontFamily: ((_b2 = themeObject == null ? void 0 : themeObject.typography) == null ? void 0 : _b2.fontFamily) ?? PET_SUMMARY_FONT_FAMILY
    };
  }
  function isPetState(value) {
    return value === "idle" || value === "running-right" || value === "running-left" || value === "waving" || value === "jumping" || value === "failed" || value === "waiting" || value === "running" || value === "review";
  }
  function parsePetStateChangePayload(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value;
    return isPetState(payload.state) ? { state: payload.state } : null;
  }
  function parsePetOptionsChangePayload(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value;
    if (payload.pet === null || typeof payload.pet === "boolean") {
      return { pet: payload.pet };
    }
    if (payload.pet && typeof payload.pet === "object" && !Array.isArray(payload.pet)) {
      return { pet: payload.pet };
    }
    return null;
  }
  function isThreadSummaryStatus(value) {
    return value === "running" || value === "completed" || value === "failed";
  }
  function getThreadSummaryKey(summary) {
    if (!summary) {
      return null;
    }
    return [
      summary.threadId,
      summary.messageId || summary.updatedAt || summary.message
    ].join(":");
  }
  function getThreadSummaryInteractionKey(summary) {
    if (!summary) {
      return null;
    }
    return [summary.threadId, summary.messageId ?? ""].join(":");
  }
  function parseThreadSummaryPayload(value) {
    if (value === null) {
      return { summary: null };
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value;
    if (typeof payload.threadId !== "string" || !payload.threadId.trim() || typeof payload.title !== "string" || !payload.title.trim() || typeof payload.message !== "string" || !payload.message.trim() || !isThreadSummaryStatus(payload.status)) {
      return null;
    }
    return {
      summary: {
        threadId: payload.threadId,
        title: payload.title,
        message: payload.message,
        status: payload.status,
        ...typeof payload.messageId === "string" && payload.messageId.trim() ? { messageId: payload.messageId } : {},
        ...typeof payload.updatedAt === "string" && payload.updatedAt.trim() ? { updatedAt: payload.updatedAt } : {}
      }
    };
  }
  function parseThreadSummaryLogPayload(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value;
    if (payload.name !== "thread.summary") {
      return null;
    }
    return parseThreadSummaryPayload(payload.data ?? null);
  }
  class PetOverlay {
    constructor(root, options) {
      this.overlayElement = null;
      this.petElement = null;
      this.contextMenuElement = null;
      this.summaryElement = null;
      this.summaryToggleElement = null;
      this.mediaElement = null;
      this.options = null;
      this.theme = null;
      this.resolved = null;
      this.summary = null;
      this.summaryRenderKey = null;
      this.dismissedSummaryKey = null;
      this.isSummaryCollapsed = false;
      this.isSummaryExpanded = false;
      this.isSummaryHovering = false;
      this.isReplyOpen = false;
      this.isReplySubmitting = false;
      this.replyError = null;
      this.replyDraft = "";
      this.replyInputElement = null;
      this.copyLocale = resolveCopyLocale();
      this.copy = PET_OVERLAY_COPY[this.copyLocale];
      this.currentState = "waiting";
      this.lastAutoState = "waiting";
      this.transient = null;
      this.position = null;
      this.dragPosition = null;
      this.dragOffset = { x: 0, y: 0 };
      this.lastDragPosition = null;
      this.lastDragClientX = null;
      this.dragAnimation = null;
      this.activePointerId = null;
      this.isDragging = false;
      this.isHovering = false;
      this.movedDuringDrag = false;
      this.prefersReducedMotion = false;
      this.frame = 0;
      this.completed = false;
      this.activeAnimationName = null;
      this.activeAnimationMode = null;
      this.frameTimer = null;
      this.restingDelayTimer = null;
      this.mediaQuery = null;
      this.connected = false;
      this.handleViewportChange = () => {
        this.closeContextMenu();
        this.render();
      };
      this.handleReducedMotionChange = () => {
        var _a2;
        this.prefersReducedMotion = Boolean((_a2 = this.mediaQuery) == null ? void 0 : _a2.matches);
        if (this.prefersReducedMotion) {
          this.transient = null;
        }
        this.render();
      };
      this.handlePointerEnter = () => {
        this.clearRestingDelayTimer();
        this.isHovering = true;
        this.rescheduleAnimation();
      };
      this.handlePointerLeave = () => {
        if (!this.isDragging) {
          this.enterRestingAfterDelay();
        }
      };
      this.handleContextMenu = (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.openContextMenu({ x: event.clientX, y: event.clientY });
      };
      this.handleContextMenuEvent = (event) => {
        event.preventDefault();
        event.stopPropagation();
      };
      this.handleContextMenuOutsidePointerDown = (event) => {
        const menu = this.contextMenuElement;
        if (menu && event.composedPath().includes(menu)) {
          return;
        }
        this.closeContextMenu();
      };
      this.handleContextMenuKeyDown = (event) => {
        if (event.key !== "Escape") {
          return;
        }
        event.preventDefault();
        this.closeContextMenu();
      };
      this.handleClosePetMenuItemClick = (event) => {
        var _a2;
        event.preventDefault();
        event.stopPropagation();
        this.closeContextMenu();
        (_a2 = this.onClose) == null ? void 0 : _a2.call(this);
      };
      this.handleSummaryPointerEnter = () => {
        this.isSummaryHovering = true;
        this.render();
      };
      this.handleSummaryPointerLeave = () => {
        this.isSummaryHovering = false;
        if (!this.isReplyOpen) {
          this.render();
        }
      };
      this.handleSummaryClick = () => {
        var _a2, _b2;
        const threadId = (_a2 = this.summary) == null ? void 0 : _a2.threadId.trim();
        if (!threadId) {
          return;
        }
        (_b2 = this.onThreadSummaryActivate) == null ? void 0 : _b2.call(this, threadId);
      };
      this.handleSummaryDelete = () => {
        const summaryKey = getThreadSummaryKey(this.summary);
        if (summaryKey) {
          this.dismissedSummaryKey = summaryKey;
        }
        this.isSummaryCollapsed = false;
        this.isReplyOpen = false;
        this.replyDraft = "";
        this.replyError = null;
        this.removeSummaryElements();
      };
      this.handleSummaryCollapseToggle = () => {
        this.isSummaryCollapsed = !this.isSummaryCollapsed;
        this.isSummaryExpanded = false;
        this.isReplyOpen = false;
        this.replyError = null;
        this.render();
      };
      this.handleSummaryExpandToggle = () => {
        this.isSummaryExpanded = !this.isSummaryExpanded;
        this.render();
      };
      this.handleReplyOpen = () => {
        this.isReplyOpen = true;
        this.replyError = null;
        this.render();
      };
      this.handleReplyInput = (event) => {
        const target = event.currentTarget;
        if (target instanceof HTMLInputElement) {
          this.replyDraft = target.value;
          this.replyError = null;
        }
      };
      this.handleReplySubmit = (event) => {
        event.preventDefault();
        void this.submitReply();
      };
      this.handleReplyKeyDown = (event) => {
        if (event.key !== "Escape") {
          return;
        }
        event.preventDefault();
        this.isReplyOpen = false;
        this.replyError = null;
        this.render();
      };
      this.handlePointerDown = (event) => {
        var _a2, _b2;
        if (event.button !== 0 || event.ctrlKey || this.isDragging) {
          return;
        }
        this.closeContextMenu();
        if (!((_a2 = this.options) == null ? void 0 : _a2.position.draggable)) {
          return;
        }
        event.preventDefault();
        const rect = (_b2 = this.petElement) == null ? void 0 : _b2.getBoundingClientRect();
        if (!rect) {
          return;
        }
        const nextPosition = {
          x: rect.left,
          y: rect.top
        };
        this.dragOffset = {
          x: event.clientX - rect.left,
          y: event.clientY - rect.top
        };
        this.lastDragPosition = nextPosition;
        this.lastDragClientX = event.clientX;
        this.dragAnimation = null;
        this.movedDuringDrag = false;
        this.dragPosition = nextPosition;
        this.isDragging = true;
        this.activePointerId = event.pointerId;
        this.clearRestingDelayTimer();
        this.isHovering = true;
        this.captureActivePointer();
        this.installDragListeners();
        this.rescheduleAnimation();
      };
      this.handlePointerMove = (event) => {
        if (!this.isActiveDragPointer(event)) {
          return;
        }
        const nextPosition = this.getNextDragPosition(event);
        const last = this.lastDragPosition;
        if (last && (Math.abs(last.x - nextPosition.x) > DRAG_DIRECTION_THRESHOLD_PX || Math.abs(last.y - nextPosition.y) > DRAG_DIRECTION_THRESHOLD_PX)) {
          this.movedDuringDrag = true;
        }
        if (this.lastDragClientX !== null) {
          const deltaX = event.clientX - this.lastDragClientX;
          if (deltaX > DRAG_DIRECTION_THRESHOLD_PX) {
            this.dragAnimation = "running-right";
          } else if (deltaX < -DRAG_DIRECTION_THRESHOLD_PX) {
            this.dragAnimation = "running-left";
          }
        }
        this.lastDragClientX = event.clientX;
        this.lastDragPosition = nextPosition;
        this.dragPosition = nextPosition;
        this.render();
      };
      this.handlePointerUp = (event) => {
        if (!this.isActiveDragPointer(event)) {
          return;
        }
        const finalPosition = this.lastDragPosition ?? this.getNextDragPosition(event);
        this.finishDrag(finalPosition, event);
      };
      this.handleLostPointerCapture = (event) => {
        if (!this.isActiveDragPointer(event)) {
          return;
        }
        const finalPosition = this.lastDragPosition ?? this.getNextDragPosition(event);
        this.finishDrag(finalPosition, event);
      };
      this.handleClick = () => {
        var _a2;
        if (this.movedDuringDrag) {
          return;
        }
        (_a2 = this.onActivate) == null ? void 0 : _a2.call(this);
        if (this.prefersReducedMotion) {
          return;
        }
        this.transient = { name: "waving" };
        this.render();
      };
      this.root = root;
      this.onActivate = options == null ? void 0 : options.onActivate;
      this.onClose = options == null ? void 0 : options.onClose;
      this.onReply = options == null ? void 0 : options.onReply;
      this.onThreadSummaryActivate = options == null ? void 0 : options.onThreadSummaryActivate;
      this.connect();
    }
    connect() {
      if (this.connected) {
        return;
      }
      this.connected = true;
      this.installViewportListeners();
      this.installReducedMotionListener();
      this.render();
    }
    setOptions(pet, theme) {
      this.closeContextMenu();
      const nextOptions = normalizePetOptions(pet);
      this.options = nextOptions;
      this.theme = theme ?? null;
      if (!nextOptions) {
        this.isDragging = false;
        this.isHovering = false;
        this.position = null;
        this.dragPosition = null;
        this.dragAnimation = null;
        this.lastDragPosition = null;
        this.lastDragClientX = null;
        this.transient = null;
        this.resolved = null;
        this.clearRestingDelayTimer();
        this.removeDragListeners();
        this.removeOverlay();
        return;
      }
      this.position = readPersistedPosition(
        DEFAULT_PET_STORAGE_KEY,
        nextOptions.position.persist
      );
      if (nextOptions.behavior === "auto" && !this.prefersReducedMotion) {
        this.transient = { name: "waving" };
      }
      this.resolveCharacter();
      this.render();
    }
    setState(state) {
      var _a2;
      const previous = this.lastAutoState;
      this.lastAutoState = state;
      this.currentState = state;
      if (((_a2 = this.options) == null ? void 0 : _a2.behavior) === "auto" && !this.prefersReducedMotion && state === "idle" && (previous === "running" || previous === "review") && !this.transient) {
        this.transient = { name: "jumping" };
      } else if (state !== "idle") {
        this.transient = null;
      }
      this.render();
    }
    setLocale(locale) {
      const nextLocale = resolveCopyLocale(locale);
      if (nextLocale === this.copyLocale) {
        return;
      }
      this.copyLocale = nextLocale;
      this.copy = PET_OVERLAY_COPY[nextLocale];
      this.summaryRenderKey = null;
      this.closeContextMenu();
      this.render();
    }
    setThreadSummary(summary) {
      const previousKey = getThreadSummaryInteractionKey(this.summary);
      const nextKey = getThreadSummaryInteractionKey(summary);
      this.summary = summary;
      if (!summary) {
        this.isSummaryCollapsed = false;
        this.isSummaryExpanded = false;
        this.isSummaryHovering = false;
        this.isReplyOpen = false;
        this.isReplySubmitting = false;
        this.replyError = null;
        this.replyDraft = "";
        this.summaryRenderKey = null;
        this.removeSummaryElements();
        return;
      }
      if (previousKey !== nextKey) {
        this.isSummaryCollapsed = false;
        this.isSummaryExpanded = false;
        this.isSummaryHovering = false;
        this.isReplyOpen = false;
        this.isReplySubmitting = false;
        this.replyError = null;
        this.replyDraft = "";
      }
      this.render();
    }
    setThreadSummaryStatus(status) {
      if (!this.summary || this.summary.status === status) {
        return;
      }
      this.summary = { ...this.summary, status };
      this.render();
    }
    destroy() {
      var _a2, _b2, _c2, _d;
      if (!this.connected) {
        return;
      }
      this.connected = false;
      this.clearRestingDelayTimer();
      this.clearTimers();
      this.removeDragListeners();
      this.removeOverlay();
      window.removeEventListener("resize", this.handleViewportChange);
      (_a2 = window.visualViewport) == null ? void 0 : _a2.removeEventListener(
        "resize",
        this.handleViewportChange
      );
      (_b2 = window.visualViewport) == null ? void 0 : _b2.removeEventListener(
        "scroll",
        this.handleViewportChange
      );
      (_d = (_c2 = this.mediaQuery) == null ? void 0 : _c2.removeEventListener) == null ? void 0 : _d.call(
        _c2,
        "change",
        this.handleReducedMotionChange
      );
      this.mediaQuery = null;
    }
    installViewportListeners() {
      var _a2, _b2;
      window.addEventListener("resize", this.handleViewportChange);
      (_a2 = window.visualViewport) == null ? void 0 : _a2.addEventListener(
        "resize",
        this.handleViewportChange
      );
      (_b2 = window.visualViewport) == null ? void 0 : _b2.addEventListener(
        "scroll",
        this.handleViewportChange
      );
    }
    installReducedMotionListener() {
      var _a2, _b2;
      if (!window.matchMedia) {
        return;
      }
      this.mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
      this.prefersReducedMotion = this.mediaQuery.matches;
      (_b2 = (_a2 = this.mediaQuery).addEventListener) == null ? void 0 : _b2.call(
        _a2,
        "change",
        this.handleReducedMotionChange
      );
    }
    resolveCharacter() {
      if (!this.options) {
        this.resolved = null;
        return;
      }
      const character = this.options.character;
      this.resolved = resolvePetCharacter(character);
    }
    ensureOverlay() {
      if (this.overlayElement && this.petElement) {
        return;
      }
      const overlay = document.createElement("div");
      overlay.setAttribute("data-chatkit-host-pet-layer", "");
      overlay.style.position = "fixed";
      overlay.style.inset = "0";
      overlay.style.pointerEvents = "none";
      overlay.style.overflow = "visible";
      const style = document.createElement("style");
      style.textContent = `
      @keyframes chatkit-pet-summary-spin {
        to { transform: rotate(360deg); }
      }
    `;
      const pet = document.createElement("div");
      pet.setAttribute("data-chatkit-host-pet", "");
      pet.style.position = "absolute";
      pet.style.top = "0";
      pet.style.left = "0";
      pet.style.pointerEvents = "auto";
      pet.style.touchAction = "none";
      pet.style.userSelect = "none";
      pet.style.willChange = "transform";
      pet.addEventListener("pointerenter", this.handlePointerEnter);
      pet.addEventListener("pointerleave", this.handlePointerLeave);
      pet.addEventListener("pointerdown", this.handlePointerDown);
      pet.addEventListener("lostpointercapture", this.handleLostPointerCapture);
      pet.addEventListener("contextmenu", this.handleContextMenu);
      pet.addEventListener("click", this.handleClick);
      overlay.append(style, pet);
      this.root.append(overlay);
      this.overlayElement = overlay;
      this.petElement = pet;
    }
    removeOverlay() {
      var _a2;
      this.cancelActiveDrag();
      this.clearRestingDelayTimer();
      this.clearTimers();
      this.closeContextMenu();
      if (this.petElement) {
        this.petElement.removeEventListener(
          "pointerenter",
          this.handlePointerEnter
        );
        this.petElement.removeEventListener(
          "pointerleave",
          this.handlePointerLeave
        );
        this.petElement.removeEventListener(
          "pointerdown",
          this.handlePointerDown
        );
        this.petElement.removeEventListener(
          "lostpointercapture",
          this.handleLostPointerCapture
        );
        this.petElement.removeEventListener(
          "contextmenu",
          this.handleContextMenu
        );
        this.petElement.removeEventListener("click", this.handleClick);
      }
      this.isHovering = false;
      this.removeSummaryElements();
      (_a2 = this.overlayElement) == null ? void 0 : _a2.remove();
      this.overlayElement = null;
      this.petElement = null;
      this.mediaElement = null;
    }
    removeSummaryElements() {
      var _a2, _b2;
      (_a2 = this.summaryElement) == null ? void 0 : _a2.remove();
      (_b2 = this.summaryToggleElement) == null ? void 0 : _b2.remove();
      this.summaryElement = null;
      this.summaryToggleElement = null;
      this.replyInputElement = null;
      this.summaryRenderKey = null;
    }
    getSize() {
      if (!this.options || !this.resolved) {
        return { width: 0, height: 0 };
      }
      const scale = getRenderScale(this.options.position.scale);
      const baseSize = {
        width: this.resolved.atlas.cellWidth,
        height: this.resolved.atlas.cellHeight
      };
      return {
        width: baseSize.width * scale,
        height: baseSize.height * scale
      };
    }
    getCurrentPosition(size) {
      const options = this.options;
      if (!options) {
        return { x: 0, y: 0 };
      }
      const viewport = getViewportSize();
      const padding = normalizeBoundsPadding(options.position.boundsPadding);
      const pin = options.position.pin === void 0 ? "bottom-right" : options.position.pin;
      const pinnedPosition = pin ? getPinnedPetPosition(pin, size, viewport, padding) : null;
      return clampPetPosition(
        this.dragPosition ?? this.position ?? pinnedPosition ?? { x: padding.left, y: padding.top },
        size,
        viewport,
        padding
      );
    }
    persistPosition(nextPosition) {
      if (!this.options) {
        return;
      }
      const size = this.getSize();
      const clamped = clampPetPosition(
        nextPosition,
        size,
        getViewportSize(),
        normalizeBoundsPadding(this.options.position.boundsPadding)
      );
      this.position = clamped;
      writePersistedPosition(
        DEFAULT_PET_STORAGE_KEY,
        this.options.position.persist,
        clamped
      );
    }
    getActiveAnimationName() {
      if (!this.options) {
        return "idle";
      }
      if (this.isDragging) {
        return this.dragAnimation ?? "running";
      }
      if (this.transient) {
        return this.transient.name;
      }
      if (this.options.behavior === "manual") {
        return "idle";
      }
      return this.currentState;
    }
    getActiveAnimationMode() {
      if (this.isDragging) {
        return "loop";
      }
      return this.transient ? "once" : "loop";
    }
    resetAnimationIfNeeded(name, mode) {
      if (this.activeAnimationName === name && this.activeAnimationMode === mode) {
        return;
      }
      this.clearTimers();
      this.activeAnimationName = name;
      this.activeAnimationMode = mode;
      this.frame = 0;
      this.completed = false;
    }
    render() {
      if (!this.options || !this.resolved) {
        this.clearTimers();
        if (this.petElement) {
          this.petElement.replaceChildren();
        }
        this.removeSummaryElements();
        this.mediaElement = null;
        this.activeAnimationName = null;
        this.activeAnimationMode = null;
        this.frame = 0;
        this.completed = false;
        return;
      }
      this.ensureOverlay();
      const overlay = this.overlayElement;
      const pet = this.petElement;
      if (!overlay || !pet) {
        return;
      }
      const size = this.getSize();
      const position = this.getCurrentPosition(size);
      const animationName = this.getActiveAnimationName();
      const animationMode = this.getActiveAnimationMode();
      this.resetAnimationIfNeeded(animationName, animationMode);
      overlay.style.zIndex = String(this.options.position.zIndex);
      pet.style.width = `${size.width}px`;
      pet.style.height = `${size.height}px`;
      pet.style.transform = `translate3d(${position.x}px, ${position.y}px, 0)`;
      pet.style.cursor = this.options.position.draggable ? this.isDragging ? "grabbing" : "grab" : "default";
      pet.dataset.petAnimation = animationName;
      pet.setAttribute("aria-label", this.options.ariaLabel);
      pet.setAttribute("role", "img");
      this.renderAtlas(animationName, animationMode);
      this.renderThreadSummary(position, size);
      this.scheduleNextFrame(animationName, animationMode);
    }
    renderThreadSummary(position, size) {
      var _a2, _b2, _c2;
      const summary = this.summary;
      const summaryKey = getThreadSummaryKey(summary);
      if (!summary || !summaryKey || this.dismissedSummaryKey === summaryKey) {
        this.removeSummaryElements();
        return;
      }
      if (this.isSummaryCollapsed) {
        this.renderCollapsedSummary(position, size);
        return;
      }
      const nextRenderKey = [
        this.copyLocale,
        this.isSummaryExpanded ? "expanded" : "compact",
        this.isSummaryHovering ? "hover" : "rest",
        this.isReplyOpen ? "reply" : "closed",
        this.isReplySubmitting ? "submitting" : "ready",
        this.replyError ?? ""
      ].join("|");
      if (!this.summaryElement || this.summaryRenderKey !== nextRenderKey) {
        (_a2 = this.summaryElement) == null ? void 0 : _a2.remove();
        (_b2 = this.summaryToggleElement) == null ? void 0 : _b2.remove();
        this.summaryElement = this.createSummaryBubble(summary);
        this.summaryToggleElement = this.createSummaryToggleButton("v");
        (_c2 = this.overlayElement) == null ? void 0 : _c2.append(
          this.summaryElement,
          this.summaryToggleElement
        );
        this.summaryRenderKey = nextRenderKey;
        if (this.isReplyOpen && !this.isReplySubmitting) {
          window.setTimeout(() => {
            var _a3;
            return (_a3 = this.replyInputElement) == null ? void 0 : _a3.focus();
          }, 0);
        }
      }
      this.updateSummaryBubbleContent(summary);
      this.positionSummaryBubble(position, size);
    }
    renderCollapsedSummary(position, size) {
      var _a2, _b2;
      (_a2 = this.summaryElement) == null ? void 0 : _a2.remove();
      this.summaryElement = null;
      this.summaryRenderKey = null;
      if (!this.summaryToggleElement) {
        this.summaryToggleElement = this.createSummaryToggleButton("1");
        (_b2 = this.overlayElement) == null ? void 0 : _b2.append(this.summaryToggleElement);
      }
      this.summaryToggleElement.textContent = "1";
      this.positionSummaryToggleBadge(position, size);
    }
    positionSummaryToggleBadge(position, size) {
      const badge = this.summaryToggleElement;
      if (!badge) {
        return;
      }
      const viewport = getViewportSize();
      const badgeSize = getSummaryThemeMetrics(this.theme).toggleSize;
      const x = clampNumber(
        position.x + size.width - badgeSize * 0.35,
        PET_SUMMARY_MARGIN,
        viewport.width - badgeSize - PET_SUMMARY_MARGIN
      );
      const y = clampNumber(
        position.y - badgeSize * 0.35,
        PET_SUMMARY_MARGIN,
        viewport.height - badgeSize - PET_SUMMARY_MARGIN
      );
      badge.style.width = `${badgeSize}px`;
      badge.style.height = `${badgeSize}px`;
      badge.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      badge.style.borderRadius = "999px";
    }
    positionSummaryBubble(position, size) {
      const bubble = this.summaryElement;
      const toggle = this.summaryToggleElement;
      if (!bubble || !toggle) {
        return;
      }
      const viewport = getViewportSize();
      const width = Math.min(
        PET_SUMMARY_WIDTH,
        viewport.width - PET_SUMMARY_MARGIN * 2
      );
      bubble.style.width = `${width}px`;
      const bubbleHeight = bubble.offsetHeight || 96;
      const aboveY = position.y - bubbleHeight - PET_SUMMARY_GAP;
      const showAbove = aboveY >= PET_SUMMARY_MARGIN;
      const y = showAbove ? aboveY : clampNumber(
        position.y + size.height + PET_SUMMARY_GAP,
        PET_SUMMARY_MARGIN,
        viewport.height - bubbleHeight - PET_SUMMARY_MARGIN
      );
      const x = clampNumber(
        position.x + size.width / 2 - width / 2,
        PET_SUMMARY_MARGIN,
        viewport.width - width - PET_SUMMARY_MARGIN
      );
      bubble.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      this.positionSummaryToggleBadge(position, size);
    }
    createSummaryBubble(summary) {
      const shouldShowReplyButton = this.isSummaryHovering && !this.isReplyOpen;
      const metrics = getSummaryThemeMetrics(this.theme);
      const bubble = document.createElement("div");
      bubble.setAttribute("data-chatkit-pet-summary", "");
      bubble.addEventListener("pointerenter", this.handleSummaryPointerEnter);
      bubble.addEventListener("pointerleave", this.handleSummaryPointerLeave);
      bubble.addEventListener("click", this.handleSummaryClick);
      bubble.style.position = "absolute";
      bubble.style.top = "0";
      bubble.style.left = "0";
      bubble.style.boxSizing = "border-box";
      bubble.style.pointerEvents = "auto";
      bubble.style.padding = metrics.padding;
      bubble.style.border = "1px solid rgba(148, 163, 184, 0.22)";
      bubble.style.borderRadius = `${metrics.radius}px`;
      bubble.style.background = "rgba(255, 255, 255, 0.94)";
      bubble.style.color = "#1f2937";
      bubble.style.boxShadow = "0 8px 24px rgba(15, 23, 42, 0.1)";
      bubble.style.font = `500 ${metrics.bodySize}px/1.35 ${metrics.fontFamily}`;
      bubble.style.backdropFilter = "blur(10px)";
      const header = document.createElement("div");
      header.style.display = "flex";
      header.style.alignItems = "center";
      header.style.gap = `${metrics.gap}px`;
      if (this.isSummaryHovering || this.isReplyOpen) {
        header.append(
          this.createSummaryActionButton(
            "x",
            this.copy.hideMessage,
            this.handleSummaryDelete
          )
        );
      }
      const title = document.createElement("div");
      title.textContent = summary.title;
      title.style.minWidth = "0";
      title.style.flex = "1";
      title.style.overflow = "hidden";
      title.style.textOverflow = "ellipsis";
      title.style.whiteSpace = "nowrap";
      title.style.fontWeight = "700";
      title.style.fontSize = `${metrics.titleSize}px`;
      title.dataset.chatkitPetSummaryTitle = "";
      header.append(title);
      if (this.isSummaryHovering || this.isReplyOpen) {
        header.append(
          this.createSummaryActionButton(
            this.isSummaryExpanded ? "-" : ">",
            this.isSummaryExpanded ? this.copy.collapseMessage : this.copy.expandMessage,
            this.handleSummaryExpandToggle
          )
        );
      } else {
        header.append(this.createStatusIcon(summary.status));
      }
      const message = document.createElement("div");
      message.textContent = summary.message;
      message.style.marginTop = `${metrics.marginTop}px`;
      message.style.fontWeight = "400";
      message.style.color = "#374151";
      message.style.overflow = "hidden";
      if (this.isSummaryExpanded) {
        message.style.maxHeight = "7em";
        message.style.overflowY = "auto";
      } else {
        message.style.display = "-webkit-box";
        message.style.setProperty("-webkit-line-clamp", "2");
        message.style.setProperty("-webkit-box-orient", "vertical");
      }
      message.dataset.chatkitPetSummaryMessage = "";
      bubble.append(header, message);
      if (shouldShowReplyButton) {
        const reply = this.createTextButton(
          this.copy.replyButton,
          this.handleReplyOpen
        );
        reply.style.position = "absolute";
        reply.style.right = "14px";
        reply.style.bottom = "10px";
        bubble.append(reply);
      }
      if (this.isReplyOpen) {
        bubble.append(this.createReplyForm());
      }
      return bubble;
    }
    updateSummaryBubbleContent(summary) {
      var _a2, _b2, _c2;
      const title = (_a2 = this.summaryElement) == null ? void 0 : _a2.querySelector(
        "[data-chatkit-pet-summary-title]"
      );
      if (title && title.textContent !== summary.title) {
        title.textContent = summary.title;
      }
      const message = (_b2 = this.summaryElement) == null ? void 0 : _b2.querySelector(
        "[data-chatkit-pet-summary-message]"
      );
      if (message && message.textContent !== summary.message) {
        message.textContent = summary.message;
      }
      const statusIcon = (_c2 = this.summaryElement) == null ? void 0 : _c2.querySelector(
        "[data-chatkit-pet-summary-status]"
      );
      if (statusIcon && statusIcon.dataset.chatkitPetSummaryStatus !== summary.status) {
        const nextIcon = this.createStatusIcon(summary.status);
        statusIcon.replaceWith(nextIcon);
      }
    }
    createSummaryToggleButton(label) {
      const metrics = getSummaryThemeMetrics(this.theme);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = label === "1" ? this.copy.restoreMessage : this.copy.collapseMessage;
      button.addEventListener("click", stopEventPropagation);
      button.addEventListener("click", this.handleSummaryCollapseToggle);
      button.style.position = "absolute";
      button.style.top = "0";
      button.style.left = "0";
      button.style.pointerEvents = "auto";
      button.style.border = "1px solid rgba(148, 163, 184, 0.28)";
      button.style.background = "rgba(248, 250, 252, 0.94)";
      button.style.color = "#475569";
      button.style.boxShadow = "0 6px 18px rgba(15, 23, 42, 0.1)";
      button.style.cursor = "pointer";
      button.style.font = `600 ${metrics.titleSize}px/1 ${metrics.fontFamily}`;
      button.style.display = "flex";
      button.style.alignItems = "center";
      button.style.justifyContent = "center";
      return button;
    }
    createStatusIcon(status) {
      const metrics = getSummaryThemeMetrics(this.theme);
      const iconSize = metrics.iconSize;
      const icon = document.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.dataset.chatkitPetSummaryStatus = status;
      icon.style.display = "inline-flex";
      icon.style.width = `${iconSize}px`;
      icon.style.height = `${iconSize}px`;
      icon.style.alignItems = "center";
      icon.style.justifyContent = "center";
      icon.style.flex = "0 0 auto";
      if (status === "running") {
        icon.style.border = "2px solid rgba(71, 85, 105, 0.32)";
        icon.style.borderTopColor = "#64748b";
        icon.style.borderRadius = "999px";
        icon.style.animation = "chatkit-pet-summary-spin 900ms linear infinite";
        return icon;
      }
      icon.style.borderRadius = "999px";
      icon.style.fontSize = `${Math.max(10, iconSize - 4)}px`;
      icon.style.fontWeight = "700";
      if (status === "failed") {
        icon.textContent = "!";
        icon.style.background = "#fee2e2";
        icon.style.color = "#b91c1c";
        return icon;
      }
      icon.textContent = "";
      icon.style.border = "2px solid #22c55e";
      icon.style.position = "relative";
      const check = document.createElement("span");
      check.style.width = `${Math.round(iconSize * 0.44)}px`;
      check.style.height = `${Math.round(iconSize * 0.25)}px`;
      check.style.borderLeft = "2px solid #22c55e";
      check.style.borderBottom = "2px solid #22c55e";
      check.style.transform = "rotate(-45deg) translate(1px, -1px)";
      icon.append(check);
      return icon;
    }
    createSummaryActionButton(label, title, onClick) {
      const metrics = getSummaryThemeMetrics(this.theme);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = title;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      });
      button.style.width = `${metrics.actionSize}px`;
      button.style.height = `${metrics.actionSize}px`;
      button.style.border = "0";
      button.style.borderRadius = "999px";
      button.style.background = "rgba(241, 245, 249, 0.96)";
      button.style.color = "#475569";
      button.style.cursor = "pointer";
      button.style.font = `600 ${metrics.titleSize}px/1 ${metrics.fontFamily}`;
      return button;
    }
    createTextButton(label, onClick) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      });
      button.style.border = "1px solid rgba(148, 163, 184, 0.28)";
      button.style.borderRadius = "999px";
      button.style.background = "rgba(248, 250, 252, 0.95)";
      button.style.color = "#334155";
      button.style.cursor = "pointer";
      button.style.padding = "3px 10px";
      button.style.font = '600 12px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      return button;
    }
    createReplyForm() {
      const form = document.createElement("form");
      form.addEventListener("click", stopEventPropagation);
      form.addEventListener("submit", this.handleReplySubmit);
      form.addEventListener("keydown", this.handleReplyKeyDown);
      form.style.display = "flex";
      form.style.gap = "6px";
      form.style.alignItems = "center";
      form.style.marginTop = "8px";
      const input = document.createElement("input");
      input.type = "text";
      input.value = this.replyDraft;
      input.disabled = this.isReplySubmitting;
      input.placeholder = this.copy.replyPlaceholder;
      input.addEventListener("input", this.handleReplyInput);
      input.style.minWidth = "0";
      input.style.flex = "1";
      input.style.border = "1px solid rgba(148, 163, 184, 0.35)";
      input.style.borderRadius = "999px";
      input.style.padding = "6px 10px";
      input.style.font = '400 13px/1.2 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      this.replyInputElement = input;
      const send = document.createElement("button");
      send.type = "submit";
      send.textContent = this.isReplySubmitting ? this.copy.sendingButton : this.copy.sendButton;
      send.disabled = this.isReplySubmitting;
      send.style.border = "0";
      send.style.borderRadius = "999px";
      send.style.background = "#22c55e";
      send.style.color = "#052e16";
      send.style.cursor = this.isReplySubmitting ? "default" : "pointer";
      send.style.padding = "6px 10px";
      send.style.font = '700 12px/1.2 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      form.append(input, send);
      if (this.replyError) {
        const error = document.createElement("div");
        error.textContent = this.copy.sendFailed;
        error.style.flexBasis = "100%";
        error.style.color = "#b91c1c";
        error.style.fontSize = "12px";
        form.style.flexWrap = "wrap";
        form.append(error);
      }
      return form;
    }
    createContextMenu() {
      const menu = document.createElement("div");
      menu.setAttribute("data-chatkit-pet-context-menu", "");
      menu.setAttribute("role", "menu");
      menu.addEventListener("contextmenu", this.handleContextMenuEvent);
      menu.addEventListener("pointerdown", stopEventPropagation);
      menu.addEventListener("click", stopEventPropagation);
      menu.style.position = "absolute";
      menu.style.top = "0";
      menu.style.left = "0";
      menu.style.boxSizing = "border-box";
      menu.style.minWidth = "132px";
      menu.style.padding = "4px";
      menu.style.pointerEvents = "auto";
      menu.style.border = "1px solid rgba(148, 163, 184, 0.28)";
      menu.style.borderRadius = "10px";
      menu.style.background = "rgba(255, 255, 255, 0.96)";
      menu.style.color = "#1f2937";
      menu.style.boxShadow = "0 12px 28px rgba(15, 23, 42, 0.16)";
      menu.style.font = '500 13px/1.3 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      menu.style.backdropFilter = "blur(10px)";
      const closeItem = document.createElement("button");
      closeItem.type = "button";
      closeItem.textContent = this.copy.closePetMenuItem;
      closeItem.setAttribute("role", "menuitem");
      closeItem.addEventListener("click", this.handleClosePetMenuItemClick);
      closeItem.style.display = "block";
      closeItem.style.width = "100%";
      closeItem.style.border = "0";
      closeItem.style.borderRadius = "7px";
      closeItem.style.background = "transparent";
      closeItem.style.color = "inherit";
      closeItem.style.cursor = "pointer";
      closeItem.style.padding = "7px 10px";
      closeItem.style.textAlign = "left";
      closeItem.style.font = "inherit";
      menu.append(closeItem);
      return menu;
    }
    openContextMenu(position) {
      var _a2;
      const overlay = this.overlayElement;
      if (!overlay) {
        return;
      }
      this.closeContextMenu();
      const menu = this.createContextMenu();
      overlay.append(menu);
      this.contextMenuElement = menu;
      this.positionContextMenu(position);
      (_a2 = menu.querySelector("button")) == null ? void 0 : _a2.focus({ preventScroll: true });
      window.addEventListener(
        "pointerdown",
        this.handleContextMenuOutsidePointerDown,
        true
      );
      window.addEventListener("keydown", this.handleContextMenuKeyDown);
    }
    closeContextMenu() {
      var _a2;
      (_a2 = this.contextMenuElement) == null ? void 0 : _a2.remove();
      this.contextMenuElement = null;
      window.removeEventListener(
        "pointerdown",
        this.handleContextMenuOutsidePointerDown,
        true
      );
      window.removeEventListener("keydown", this.handleContextMenuKeyDown);
    }
    positionContextMenu(position) {
      const menu = this.contextMenuElement;
      if (!menu) {
        return;
      }
      const viewport = getViewportSize();
      const width = menu.offsetWidth || 132;
      const height = menu.offsetHeight || 40;
      const maxX = Math.max(
        PET_CONTEXT_MENU_MARGIN,
        viewport.width - width - PET_CONTEXT_MENU_MARGIN
      );
      const maxY = Math.max(
        PET_CONTEXT_MENU_MARGIN,
        viewport.height - height - PET_CONTEXT_MENU_MARGIN
      );
      const x = clampNumber(position.x, PET_CONTEXT_MENU_MARGIN, maxX);
      const y = clampNumber(position.y, PET_CONTEXT_MENU_MARGIN, maxY);
      menu.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    }
    renderAtlas(animationName, animationMode) {
      var _a2;
      if (!this.petElement || ((_a2 = this.resolved) == null ? void 0 : _a2.kind) !== "atlas" || !this.options) {
        return;
      }
      if (!(this.mediaElement instanceof HTMLDivElement)) {
        const frame = document.createElement("div");
        frame.setAttribute("aria-hidden", "true");
        this.petElement.replaceChildren(frame);
        this.mediaElement = frame;
      }
      const frameElement = this.mediaElement;
      const atlas = this.resolved.atlas;
      const definition = atlas.animations[animationName] ?? atlas.animations.idle;
      const safeFrame = animationMode === "once" && this.completed ? Math.max(0, definition.frames - 1) : Math.min(this.frame, Math.max(0, definition.frames - 1));
      const scale = getRenderScale(this.options.position.scale);
      const sourceWidth = atlas.cellWidth;
      const sourceHeight = atlas.cellHeight;
      const backgroundWidth = atlas.columns * sourceWidth;
      const backgroundHeight = atlas.rows * sourceHeight;
      frameElement.style.width = `${sourceWidth}px`;
      frameElement.style.height = `${sourceHeight}px`;
      frameElement.style.overflow = "hidden";
      frameElement.style.transform = `scale(${scale})`;
      frameElement.style.transformOrigin = "top left";
      frameElement.style.pointerEvents = "none";
      frameElement.style.backgroundImage = `url("${escapeCssUrl(
        this.resolved.src
      )}")`;
      frameElement.style.backgroundRepeat = "no-repeat";
      frameElement.style.backgroundSize = `${backgroundWidth}px ${backgroundHeight}px`;
      frameElement.style.backgroundPosition = `${-safeFrame * sourceWidth}px ${-definition.row * sourceHeight}px`;
      frameElement.style.imageRendering = this.options.imageRendering;
      frameElement.dataset.petFrame = String(safeFrame);
    }
    scheduleNextFrame(animationName, animationMode) {
      if (this.prefersReducedMotion || this.completed || !this.resolved) {
        this.clearTimers();
        return;
      }
      if (this.frameTimer !== null) {
        return;
      }
      const atlas = this.resolved.atlas;
      const definition = atlas.animations[animationName] ?? atlas.animations.idle;
      const duration = definition.frameDurations[this.frame] ?? definition.frameDurations[definition.frameDurations.length - 1] ?? 150;
      const baseDuration = duration * PET_FRAME_DURATION_MULTIPLIER;
      const effectiveDuration = this.isHovering || this.isDragging ? baseDuration : baseDuration * PET_RESTING_FRAME_DURATION_MULTIPLIER;
      this.frameTimer = window.setTimeout(() => {
        this.frameTimer = null;
        const nextFrame = this.frame + 1;
        if (nextFrame >= definition.frames) {
          if (animationMode === "once") {
            this.completed = true;
            this.frame = Math.max(0, definition.frames - 1);
            this.finishTransient();
            return;
          }
          this.frame = 0;
          this.render();
          return;
        }
        this.frame = nextFrame;
        this.render();
      }, effectiveDuration);
    }
    clearTimers() {
      if (this.frameTimer !== null) {
        window.clearTimeout(this.frameTimer);
        this.frameTimer = null;
      }
    }
    clearRestingDelayTimer() {
      if (this.restingDelayTimer !== null) {
        window.clearTimeout(this.restingDelayTimer);
        this.restingDelayTimer = null;
      }
    }
    finishTransient() {
      this.transient = null;
      this.activeAnimationName = null;
      this.activeAnimationMode = null;
      this.render();
    }
    rescheduleAnimation() {
      this.clearTimers();
      this.render();
    }
    enterRestingAfterDelay() {
      this.clearRestingDelayTimer();
      this.isHovering = true;
      this.restingDelayTimer = window.setTimeout(() => {
        this.restingDelayTimer = null;
        if (this.isDragging) {
          return;
        }
        this.isHovering = false;
        this.rescheduleAnimation();
      }, PET_RESTING_DELAY_MS);
    }
    isPointOverPet(clientX, clientY) {
      var _a2;
      const rect = (_a2 = this.petElement) == null ? void 0 : _a2.getBoundingClientRect();
      if (!rect) {
        return false;
      }
      return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    }
    isPointerOverPet(event) {
      return this.isPointOverPet(event.clientX, event.clientY);
    }
    async submitReply() {
      var _a2;
      const text = this.replyDraft.trim();
      if (!text || this.isReplySubmitting) {
        return;
      }
      this.isReplySubmitting = true;
      this.replyError = null;
      this.render();
      try {
        await ((_a2 = this.onReply) == null ? void 0 : _a2.call(this, text));
        this.replyDraft = "";
        this.isReplyOpen = false;
        this.isSummaryHovering = false;
      } catch {
        this.replyError = "Failed to send";
      } finally {
        this.isReplySubmitting = false;
        this.render();
      }
    }
    captureActivePointer() {
      const pointerId = this.activePointerId;
      const pet = this.petElement;
      if (pointerId === null || typeof (pet == null ? void 0 : pet.setPointerCapture) !== "function") {
        return;
      }
      try {
        pet.setPointerCapture(pointerId);
      } catch {
      }
    }
    releaseActivePointer() {
      const pointerId = this.activePointerId;
      const pet = this.petElement;
      this.activePointerId = null;
      if (pointerId === null || typeof (pet == null ? void 0 : pet.hasPointerCapture) !== "function" || typeof pet.releasePointerCapture !== "function") {
        return;
      }
      try {
        if (pet.hasPointerCapture(pointerId)) {
          pet.releasePointerCapture(pointerId);
        }
      } catch {
      }
    }
    isActiveDragPointer(event) {
      return this.isDragging && event.pointerId === this.activePointerId;
    }
    getNextDragPosition(event) {
      if (!this.options) {
        return { x: 0, y: 0 };
      }
      return clampPetPosition(
        {
          x: event.clientX - this.dragOffset.x,
          y: event.clientY - this.dragOffset.y
        },
        this.getSize(),
        getViewportSize(),
        normalizeBoundsPadding(this.options.position.boundsPadding)
      );
    }
    finishDrag(finalPosition, event) {
      this.isDragging = false;
      this.dragPosition = null;
      this.dragAnimation = null;
      this.lastDragClientX = null;
      this.removeDragListeners();
      this.releaseActivePointer();
      this.persistPosition(finalPosition);
      if (event.pointerType === "mouse" && this.isPointerOverPet(event)) {
        this.isHovering = true;
        this.rescheduleAnimation();
      } else {
        this.enterRestingAfterDelay();
        this.rescheduleAnimation();
      }
    }
    cancelActiveDrag() {
      this.isDragging = false;
      this.dragPosition = null;
      this.dragAnimation = null;
      this.lastDragPosition = null;
      this.lastDragClientX = null;
      this.removeDragListeners();
      this.releaseActivePointer();
    }
    installDragListeners() {
      window.addEventListener("pointermove", this.handlePointerMove);
      window.addEventListener("pointerup", this.handlePointerUp);
      window.addEventListener("pointercancel", this.handlePointerUp);
    }
    removeDragListeners() {
      window.removeEventListener("pointermove", this.handlePointerMove);
      window.removeEventListener("pointerup", this.handlePointerUp);
      window.removeEventListener("pointercancel", this.handlePointerUp);
    }
  }
  function getInnerOptions(options) {
    return removeMethods(options);
  }
  function requireCommandCapability(value, context) {
    const command = String(context.name);
    return function(...args) {
      if (!this.capabilities.commands.has(command)) {
        throw new IntegrationError(
          `ChatKit command "${String(command)}" is not available for the "${this.profile}" profile.`
        );
      }
      return value.apply(this, args);
    };
  }
  class ChatKitElementBase extends (_c = HTMLElement, _focusComposer_dec = [requireCommandCapability], _fetchUpdates_dec = [requireCommandCapability], _sendUserMessage_dec = [requireCommandCapability], _setComposerValue_dec = [requireCommandCapability], _setRuntimeCapabilities_dec = [requireCommandCapability], _setThreadId_dec = [requireCommandCapability], _shareThread_dec = [requireCommandCapability], _sendCustomAction_dec = [requireCommandCapability], _showHistory_dec = [requireCommandCapability], _hideHistory_dec = [requireCommandCapability], _setTrainingOptOut_dec = [requireCommandCapability], _c) {
    constructor({ profile }) {
      super();
      __runInitializers(_init, 5, this);
      __privateAdd(this, _ChatKitElementBase_instances);
      __privateAdd(this, _opts);
      __privateAdd(this, _frameUrl);
      __privateAdd(this, _frame);
      __privateAdd(this, _wrapper);
      __privateAdd(this, _launcherCloseButton);
      __privateAdd(this, _launcherOpen, false);
      __privateAdd(this, _chatMinimizedToPet, false);
      __privateAdd(this, _framePetOptionsOverride);
      __privateAdd(this, _petClosedByContextMenu, false);
      __privateAdd(this, _shadow, this.attachShadow({ mode: "open" }));
      __privateAdd(this, _petOverlay, new PetOverlay(__privateGet(this, _shadow), {
        onActivate: () => __privateMethod(this, _ChatKitElementBase_instances, handlePetActivate_fn).call(this),
        onClose: () => __privateMethod(this, _ChatKitElementBase_instances, handlePetClose_fn).call(this),
        onReply: (text) => __privateMethod(this, _ChatKitElementBase_instances, handlePetReply_fn).call(this, text),
        onThreadSummaryActivate: (threadId) => void __privateMethod(this, _ChatKitElementBase_instances, handlePetThreadSummaryActivate_fn).call(this, threadId)
      }));
      __privateAdd(this, _resolveLoaded);
      __privateAdd(this, _loaded, new Promise((resolve) => {
        __privateSet(this, _resolveLoaded, resolve);
      }));
      __privateAdd(this, _channelId, createSecureChannelId());
      __privateAdd(this, _messenger, new ChatFrameMessenger({
        channelId: __privateGet(this, _channelId) ?? void 0,
        fetch: (...args) => {
          var _a2;
          const customFetch = ((_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.api) && "fetch" in __privateGet(this, _opts).api && __privateGet(this, _opts).api.fetch;
          return customFetch ? customFetch(...args) : fetch(...args);
        },
        target: () => {
          var _a2;
          return ((_a2 = __privateGet(this, _frame)) == null ? void 0 : _a2.contentWindow) ?? null;
        },
        targetOrigin: window.location.origin,
        handlers: {
          onFileInputClick: ({
            inputAttributes
          }) => {
            return new Promise((resolve) => {
              const input = document.createElement("input");
              for (const [key, value] of Object.entries(inputAttributes)) {
                input.setAttribute(key, String(value));
              }
              const respond = () => {
                resolve(Array.from(input.files || []));
                if (__privateGet(this, _shadow).contains(input)) {
                  __privateGet(this, _shadow).removeChild(input);
                }
              };
              input.addEventListener("cancel", respond);
              input.addEventListener("change", respond);
              __privateGet(this, _shadow).appendChild(input);
              input.click();
            });
          },
          onClientToolCall: async ({
            name,
            params,
            id,
            tool_call_id
          }) => {
            var _a2;
            const onClientTool = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.onClientTool;
            if (!onClientTool) {
              __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, new IntegrationError(
                `No handler for client tool calls. You'll need to add onClientTool to your ChatKit options.`
              ));
            }
            return onClientTool({ name, params, id, tool_call_id });
          },
          onToolOutputAttachmentPreview: async (request) => {
            var _a2, _b2;
            const onRequestPreview = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.toolOutputAttachments) == null ? void 0 : _b2.onRequestPreview;
            if (!onRequestPreview) {
              __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, new IntegrationError(
                "No handler for tool-output attachment previews. Add toolOutputAttachments.onRequestPreview to your ChatKit options."
              ));
            }
            return onRequestPreview(request);
          },
          onWorkbenchClientCommand: async ({
            commandKey,
            payload,
            hostType,
            hostId,
            viewKey
          }) => {
            var _a2, _b2;
            const onClientCommand = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.workbench) == null ? void 0 : _b2.onClientCommand;
            if (!onClientCommand) {
              __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, new IntegrationError(
                `No handler for workbench client command "${commandKey}". Add workbench.onClientCommand to your ChatKit options.`
              ));
            }
            return onClientCommand({
              commandKey,
              payload,
              hostType,
              hostId,
              viewKey
            });
          },
          onWidgetAction: async ({
            action,
            widgetItem
          }) => {
            var _a2, _b2;
            const onAction = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.widgets) == null ? void 0 : _b2.onAction;
            if (!onAction) {
              __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, new IntegrationError(
                `No handler for widget actions. You'll need to add widgets.onAction to your ChatKit options.`
              ));
            }
            return onAction(action, widgetItem);
          },
          onEntitySearch: async ({ query }) => {
            var _a2, _b2, _c2;
            return ((_c2 = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.entities) == null ? void 0 : _b2.onTagSearch) == null ? void 0 : _c2.call(_b2, query)) ?? [];
          },
          onEntityClick: async ({ entity }) => {
            var _a2, _b2, _c2;
            return (_c2 = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.entities) == null ? void 0 : _b2.onClick) == null ? void 0 : _c2.call(_b2, entity);
          },
          onEntityPreview: async ({ entity }) => {
            var _a2, _b2, _c2;
            return ((_c2 = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.entities) == null ? void 0 : _b2.onRequestPreview) == null ? void 0 : _c2.call(_b2, entity)) ?? { preview: null };
          },
          onGetClientSecret: async (currentClientSecret) => {
            if (!__privateGet(this, _opts) || !("getClientSecret" in __privateGet(this, _opts).api) || !__privateGet(this, _opts).api.getClientSecret) {
              __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, new IntegrationError(
                "Could not refresh the session because ChatKitOptions.api.getClientSecret is not configured."
              ));
            }
            return __privateGet(this, _opts).api.getClientSecret(currentClientSecret ?? null);
          },
          onAddMetadataToRequest: ({
            op,
            params
          }) => {
            throw new IntegrationError(
              "ChatKit: onAddMetadataToRequest is unimplemented."
            );
          }
        }
      }));
      __privateAdd(this, _handleLauncherClose, () => {
        __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, false);
      });
      __privateAdd(this, _handleFrameLoad, () => {
        var _a2;
        this.dataset.loaded = "true";
        this.dispatchEvent(
          new CustomEvent("chatkit.ready", { bubbles: true, composed: true })
        );
        (_a2 = __privateGet(this, _resolveLoaded)) == null ? void 0 : _a2.call(this);
      });
      __privateAdd(this, _initialized, false);
      this.profile = profile;
      this.capabilities = getCapabilities(profile);
    }
    setProfile(profile) {
      this.profile = profile;
      this.capabilities = getCapabilities(profile);
    }
    connectedCallback() {
      __privateGet(this, _petOverlay).connect();
      const style = document.createElement("style");
      style.textContent = `
      :host {
        display: block;
        position: relative;
        height: 100%;
        width: 100%;
        overflow: visible;
      }
      :host([data-display-mode="pet"]) {
        display: contents;
      }
      :host([data-chat-minimized-to-pet="true"]) {
        display: contents;
      }
      .ck-iframe {
        border: none;
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        color-scheme: light only;
      }
      .ck-wrapper {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        opacity: 0;
      }
      .ck-launcher-close {
        display: none;
      }
      :host([data-display-mode="pet"]) .ck-wrapper {
        position: fixed;
        inset: auto 16px 16px auto;
        width: min(420px, calc(100vw - 32px));
        height: min(720px, calc(100vh - 32px));
        max-height: calc(100vh - 32px);
        overflow: visible;
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 18px;
        background: Canvas;
        box-shadow:
          0 24px 80px rgba(15, 23, 42, 0.22),
          0 0 0 1px rgba(15, 23, 42, 0.04);
        opacity: 0;
        pointer-events: none;
        transform: translateY(12px) scale(0.98);
        transition:
          opacity 160ms ease,
          transform 160ms ease;
        z-index: 39;
      }
      :host([data-display-mode="pet"][data-chat-open="true"]) .ck-wrapper {
        opacity: 1;
        pointer-events: auto;
        transform: translateY(0) scale(1);
      }
      :host([data-display-mode="pet"]) .ck-iframe {
        border-radius: inherit;
      }
      :host([data-display-mode="pet"]) .ck-launcher-close {
        display: inline-flex;
        position: absolute;
        top: -10px;
        right: -10px;
        z-index: 2;
        width: 28px;
        height: 28px;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(148, 163, 184, 0.45);
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.96);
        color: #475569;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
        cursor: pointer;
        font: inherit;
        font-size: 0;
        line-height: 1;
      }
      :host([data-display-mode="pet"]) .ck-launcher-close::before,
      :host([data-display-mode="pet"]) .ck-launcher-close::after {
        content: '';
        position: absolute;
        top: 50%;
        left: 50%;
        width: 14px;
        height: 2px;
        border-radius: 999px;
        background: currentColor;
        transform: translate(-50%, -50%) rotate(45deg);
      }
      :host([data-display-mode="pet"]) .ck-launcher-close::after {
        transform: translate(-50%, -50%) rotate(-45deg);
      }
      :host([data-display-mode="pet"]) .ck-launcher-close:hover {
        background: #fff;
        color: #0f172a;
      }
      :host([data-color-scheme="dark"]) .ck-iframe {
        color-scheme: dark only;
      }
      :host([data-color-scheme="dark"][data-display-mode="pet"]) .ck-wrapper {
        border-color: rgba(148, 163, 184, 0.28);
        background: #020617;
        box-shadow:
          0 24px 80px rgba(0, 0, 0, 0.5),
          0 0 0 1px rgba(255, 255, 255, 0.06);
      }
      :host([data-color-scheme="dark"][data-display-mode="pet"]) .ck-launcher-close {
        background: rgba(15, 23, 42, 0.88);
        border-color: rgba(148, 163, 184, 0.32);
        color: #cbd5e1;
      }
      :host([data-color-scheme="dark"][data-display-mode="pet"]) .ck-launcher-close:hover {
        background: #1e293b;
        color: #f8fafc;
      }
      :host([data-loaded="true"]) .ck-wrapper {
        opacity: 1;
      }
      :host([data-chat-minimized-to-pet="true"]) .ck-wrapper {
        opacity: 0;
        pointer-events: none;
        visibility: hidden;
      }
      :host([data-display-mode="pet"]:not([data-chat-open="true"])) .ck-wrapper {
        opacity: 0;
      }
      @media (max-width: 520px) {
        :host([data-display-mode="pet"]) .ck-wrapper {
          inset: auto 8px 8px 8px;
          width: auto;
          height: min(680px, calc(100vh - 16px));
          max-height: calc(100vh - 16px);
          border-radius: 16px;
        }
        :host([data-display-mode="pet"]) .ck-launcher-close {
          top: -8px;
          right: 8px;
        }
      }
    `;
      const frame = document.createElement("iframe");
      frame.className = "ck-iframe";
      frame.name = "chatkit";
      frame.role = "presentation";
      frame.tabIndex = 0;
      frame.setAttribute("allowtransparency", "true");
      frame.setAttribute("frameborder", "0");
      frame.setAttribute("scrolling", "no");
      frame.setAttribute("allow", "clipboard-read; clipboard-write");
      __privateSet(this, _frame, frame);
      const wrapper = document.createElement("div");
      wrapper.className = "ck-wrapper";
      wrapper.appendChild(frame);
      __privateSet(this, _wrapper, wrapper);
      const closeButton = document.createElement("button");
      closeButton.className = "ck-launcher-close";
      closeButton.type = "button";
      closeButton.setAttribute("aria-label", "Close chat");
      closeButton.addEventListener("click", __privateGet(this, _handleLauncherClose));
      wrapper.appendChild(closeButton);
      __privateSet(this, _launcherCloseButton, closeButton);
      __privateGet(this, _shadow).append(style);
      __privateGet(this, _messenger).on("left_header_icon_click", () => {
        var _a2, _b2, _c2;
        (_c2 = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.header) == null ? void 0 : _b2.leftAction) == null ? void 0 : _c2.onClick();
      });
      __privateGet(this, _messenger).on("right_header_icon_click", () => {
        var _a2, _b2, _c2;
        (_c2 = (_b2 = (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.header) == null ? void 0 : _b2.rightAction) == null ? void 0 : _c2.onClick();
      });
      __privateGet(this, _messenger).on("public_event", ([event, data]) => {
        if (event === "log") {
          const payload = parseThreadSummaryLogPayload(data);
          if (payload) {
            __privateGet(this, _petOverlay).setThreadSummary(payload.summary);
          }
        } else if (event === "response.start") {
          __privateGet(this, _petOverlay).setThreadSummaryStatus("running");
        } else if (event === "response.end") {
          __privateGet(this, _petOverlay).setThreadSummaryStatus("completed");
        } else if (event === "response.stop") {
          __privateGet(this, _petOverlay).setThreadSummaryStatus("completed");
        }
        if (!this.capabilities.events.has(event)) return;
        if (event === "error" && "error" in data) {
          const error = fromPossibleFrameSafeError(data.error);
          this.dispatchEvent(
            new CustomEvent("chatkit.error", { detail: { error } })
          );
          if (error instanceof IntegrationError) {
            throw error;
          }
          return;
        }
        this.dispatchEvent(new CustomEvent(`chatkit.${event}`, { detail: data }));
      });
      __privateGet(this, _messenger).on("pet_state_change", (data) => {
        const payload = parsePetStateChangePayload(data);
        if (payload) {
          __privateGet(this, _petOverlay).setState(payload.state);
        }
      });
      __privateGet(this, _messenger).on("pet_options_change", (data) => {
        const payload = parsePetOptionsChangePayload(data);
        if (payload) {
          if (!__privateGet(this, _petClosedByContextMenu) || payload.pet === null) {
            __privateSet(this, _petClosedByContextMenu, false);
          }
          __privateSet(this, _framePetOptionsOverride, payload.pet);
          __privateMethod(this, _ChatKitElementBase_instances, syncPetOverlayOptions_fn).call(this);
        }
      });
      __privateGet(this, _messenger).on("chat_minimize_change", (data) => {
        const minimized = typeof data === "object" && data !== null && "minimized" in data && data.minimized === true;
        if (minimized && !__privateMethod(this, _ChatKitElementBase_instances, getOverlayPetOptions_fn).call(this)) {
          return;
        }
        __privateMethod(this, _ChatKitElementBase_instances, setChatMinimizedToPet_fn).call(this, minimized);
        if (minimized) {
          __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, false);
        }
      });
      __privateGet(this, _messenger).on("unmount", () => {
        if (__privateGet(this, _wrapper) && __privateGet(this, _shadow).contains(__privateGet(this, _wrapper))) {
          __privateGet(this, _shadow).removeChild(__privateGet(this, _wrapper));
          __privateSet(this, _wrapper, void 0);
          __privateSet(this, _frame, void 0);
        }
      });
      __privateGet(this, _messenger).on(
        "capabilities_profile_change",
        ({ profile }) => {
          this.setProfile(profile);
        }
      );
      frame.addEventListener("load", __privateGet(this, _handleFrameLoad), { once: true });
      try {
        __privateMethod(this, _ChatKitElementBase_instances, maybeInit_fn).call(this);
      } catch (error) {
        console.error(error);
        __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, error instanceof Error ? error : new IntegrationError("Failed to initialize ChatKit"));
      }
    }
    disconnectedCallback() {
      var _a2, _b2;
      (_a2 = __privateGet(this, _frame)) == null ? void 0 : _a2.removeEventListener("load", __privateGet(this, _handleFrameLoad));
      (_b2 = __privateGet(this, _launcherCloseButton)) == null ? void 0 : _b2.removeEventListener(
        "click",
        __privateGet(this, _handleLauncherClose)
      );
      __privateGet(this, _messenger).disconnect();
      __privateGet(this, _petOverlay).destroy();
    }
    applySanitizedOptions(newOptions) {
      __privateSet(this, _opts, newOptions);
      __privateSet(this, _petClosedByContextMenu, false);
      __privateGet(this, _petOverlay).setLocale(newOptions.locale);
      __privateMethod(this, _ChatKitElementBase_instances, syncPetOverlayOptions_fn).call(this);
      if (__privateGet(this, _initialized)) {
        __privateMethod(this, _ChatKitElementBase_instances, setOptionsDataAttributes_fn).call(this, __privateGet(this, _opts));
        __privateGet(this, _loaded).then(() => {
          __privateGet(this, _messenger).commands.setOptions(
            getInnerOptions(__privateMethod(this, _ChatKitElementBase_instances, getFrameOptions_fn).call(this, newOptions))
          );
        });
      } else {
        __privateMethod(this, _ChatKitElementBase_instances, maybeInit_fn).call(this);
      }
    }
    setOptions(newOptions) {
      try {
        const sanitized = this.sanitizeOptions(newOptions);
        __privateMethod(this, _ChatKitElementBase_instances, consumeFrameUrl_fn).call(this, sanitized);
        this.applySanitizedOptions(sanitized);
      } catch (error) {
        __privateMethod(this, _ChatKitElementBase_instances, emitAndThrow_fn).call(this, error instanceof Error ? error : new IntegrationError("Failed to parse options"));
      }
    }
    async focusComposer() {
      var _a2, _b2;
      await __privateGet(this, _loaded);
      (_a2 = __privateGet(this, _frame)) == null ? void 0 : _a2.focus();
      await ((_b2 = __privateGet(this, _messenger)) == null ? void 0 : _b2.commands.focusComposer());
    }
    async fetchUpdates() {
      var _a2;
      await __privateGet(this, _loaded);
      await ((_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.fetchUpdates());
    }
    async sendUserMessage(params) {
      var _a2;
      await __privateGet(this, _loaded);
      await ((_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.sendUserMessage(params));
    }
    async setComposerValue(params) {
      var _a2;
      await __privateGet(this, _loaded);
      await ((_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.setComposerValue(params));
    }
    async setRuntimeCapabilities(selection) {
      var _a2;
      await __privateGet(this, _loaded);
      await ((_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.setRuntimeCapabilities(selection));
    }
    async setThreadId(threadId) {
      var _a2;
      await __privateGet(this, _loaded);
      await ((_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.setThreadId({ threadId }));
    }
    async shareThread() {
      var _a2;
      await __privateGet(this, _loaded);
      return (_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.shareThread();
    }
    async sendCustomAction(action, itemId) {
      var _a2;
      await __privateGet(this, _loaded);
      return (_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.sendCustomAction({ action, itemId });
    }
    async showHistory() {
      var _a2;
      await __privateGet(this, _loaded);
      return (_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.showHistory();
    }
    async hideHistory() {
      var _a2;
      await __privateGet(this, _loaded);
      return (_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.hideHistory();
    }
    async setTrainingOptOut(value) {
      var _a2;
      await __privateGet(this, _loaded);
      return (_a2 = __privateGet(this, _messenger)) == null ? void 0 : _a2.commands.setTrainingOptOut({ value });
    }
  }
  _init = __decoratorStart(_c);
  _opts = new WeakMap();
  _frameUrl = new WeakMap();
  _frame = new WeakMap();
  _wrapper = new WeakMap();
  _launcherCloseButton = new WeakMap();
  _launcherOpen = new WeakMap();
  _chatMinimizedToPet = new WeakMap();
  _framePetOptionsOverride = new WeakMap();
  _petClosedByContextMenu = new WeakMap();
  _shadow = new WeakMap();
  _petOverlay = new WeakMap();
  _resolveLoaded = new WeakMap();
  _loaded = new WeakMap();
  _channelId = new WeakMap();
  _messenger = new WeakMap();
  _ChatKitElementBase_instances = new WeakSet();
  emitAndThrow_fn = function(error) {
    this.dispatchEvent(new CustomEvent("chatkit.error", { detail: { error } }));
    throw error;
  };
  setOptionsDataAttributes_fn = function(options) {
    var _a2;
    this.dataset.colorScheme = typeof options.theme === "string" ? options.theme : ((_a2 = options.theme) == null ? void 0 : _a2.colorScheme) ?? "light";
    this.dataset.displayMode = __privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this, options);
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this, options) !== "pet") {
      __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, false);
    }
  };
  getDisplayMode_fn = function(options = __privateGet(this, _opts)) {
    return (options == null ? void 0 : options.displayMode) === "pet" ? "pet" : "chat";
  };
  getConfiguredPetOptions_fn = function(options = __privateGet(this, _opts)) {
    if (!options) {
      return null;
    }
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this, options) === "pet" && !normalizePetOptions(options.pet ?? null)) {
      return true;
    }
    return options.pet ?? null;
  };
  mergeConfiguredPetPositionDefaults_fn = function(pet) {
    if (!pet) {
      return pet;
    }
    const configured = normalizePetOptions(
      __privateMethod(this, _ChatKitElementBase_instances, getConfiguredPetOptions_fn).call(this) ?? null
    );
    if (!configured) {
      return pet;
    }
    if (pet === true) {
      return { position: configured.position };
    }
    if (!pet.position) {
      return { ...pet, position: configured.position };
    }
    return {
      ...pet,
      position: {
        ...configured.position,
        ...pet.position,
        boundsPadding: pet.position.boundsPadding ?? configured.position.boundsPadding,
        pin: "pin" in pet.position ? pet.position.pin : configured.position.pin
      }
    };
  };
  getOverlayPetOptions_fn = function() {
    if (__privateGet(this, _petClosedByContextMenu)) {
      return null;
    }
    let pet;
    if (__privateGet(this, _framePetOptionsOverride) !== void 0) {
      pet = __privateMethod(this, _ChatKitElementBase_instances, mergeConfiguredPetPositionDefaults_fn).call(this, __privateGet(this, _framePetOptionsOverride));
    } else {
      pet = __privateMethod(this, _ChatKitElementBase_instances, getConfiguredPetOptions_fn).call(this);
    }
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this) === "pet" && !normalizePetOptions(pet ?? null)) {
      pet = true;
    }
    return __privateMethod(this, _ChatKitElementBase_instances, resolveOverlayPetOptions_fn).call(this, pet);
  };
  resolvePetAssetUrl_fn = function(src) {
    try {
      const base = new URL(
        __privateGet(this, _frameUrl) ?? window.location.href,
        window.location.origin
      );
      return new URL(src, base).toString();
    } catch {
      return src;
    }
  };
  resolveOverlayPetOptions_fn = function(pet) {
    const normalized = normalizePetOptions(pet ?? null);
    if (!normalized) {
      return null;
    }
    return {
      character: {
        ...normalized.character,
        src: __privateMethod(this, _ChatKitElementBase_instances, resolvePetAssetUrl_fn).call(this, normalized.character.src)
      },
      position: normalized.position,
      behavior: normalized.behavior,
      ariaLabel: normalized.ariaLabel,
      imageRendering: normalized.imageRendering
    };
  };
  getFrameOptions_fn = function(options) {
    const pet = __privateMethod(this, _ChatKitElementBase_instances, getConfiguredPetOptions_fn).call(this, options);
    if (pet === (options.pet ?? null)) {
      return options;
    }
    const nextOptions = { ...options };
    if (pet === null) {
      delete nextOptions.pet;
    } else {
      nextOptions.pet = pet;
    }
    return nextOptions;
  };
  setLauncherOpen_fn = function(open) {
    __privateSet(this, _launcherOpen, open);
    if (open) {
      this.dataset.chatOpen = "true";
    } else {
      delete this.dataset.chatOpen;
    }
  };
  setChatMinimizedToPet_fn = function(minimized) {
    const next = minimized && Boolean(__privateMethod(this, _ChatKitElementBase_instances, getOverlayPetOptions_fn).call(this));
    __privateSet(this, _chatMinimizedToPet, next);
    if (next) {
      this.dataset.chatMinimizedToPet = "true";
    } else {
      delete this.dataset.chatMinimizedToPet;
    }
  };
  syncPetOverlayOptions_fn = function() {
    var _a2;
    const overlayPetOptions = __privateMethod(this, _ChatKitElementBase_instances, getOverlayPetOptions_fn).call(this);
    __privateGet(this, _petOverlay).setOptions(overlayPetOptions, (_a2 = __privateGet(this, _opts)) == null ? void 0 : _a2.theme);
    if (!overlayPetOptions) {
      __privateMethod(this, _ChatKitElementBase_instances, setChatMinimizedToPet_fn).call(this, false);
    }
  };
  handlePetActivate_fn = function() {
    if (__privateGet(this, _chatMinimizedToPet)) {
      __privateMethod(this, _ChatKitElementBase_instances, setChatMinimizedToPet_fn).call(this, false);
      if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this) === "pet") {
        __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, true);
      }
      __privateGet(this, _loaded).then(() => this.focusComposer()).catch(() => void 0);
      return;
    }
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this) !== "pet") {
      return;
    }
    __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, true);
    __privateGet(this, _loaded).then(() => this.focusComposer()).catch(() => void 0);
  };
  handlePetClose_fn = function() {
    __privateSet(this, _petClosedByContextMenu, true);
    __privateSet(this, _framePetOptionsOverride, null);
    __privateMethod(this, _ChatKitElementBase_instances, setChatMinimizedToPet_fn).call(this, false);
    __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, false);
    __privateGet(this, _petOverlay).setOptions(null);
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this) === "pet") {
      return;
    }
    __privateGet(this, _loaded).then(() => __privateGet(this, _messenger).commands.setPetEnabled({ enabled: false })).catch(() => void 0);
  };
  handlePetReply_fn = async function(text) {
    await this.sendUserMessage({ text });
  };
  handlePetThreadSummaryActivate_fn = async function(threadId) {
    if (__privateMethod(this, _ChatKitElementBase_instances, getDisplayMode_fn).call(this) === "pet") {
      __privateMethod(this, _ChatKitElementBase_instances, setLauncherOpen_fn).call(this, true);
    }
    await this.setThreadId(threadId);
    await this.focusComposer();
  };
  _handleLauncherClose = new WeakMap();
  getFrameUrl_fn = function() {
    if (!__privateGet(this, _frameUrl)) {
      throw new IntegrationError(
        "ChatKit frameUrl is not configured. Provide it via setOptions({ frameUrl }) before mounting."
      );
    }
    return __privateGet(this, _frameUrl);
  };
  setFrameUrl_fn = function(frameUrl) {
    if (__privateGet(this, _initialized) && __privateGet(this, _frameUrl) && __privateGet(this, _frameUrl) !== frameUrl) {
      throw new IntegrationError(
        "ChatKit frameUrl cannot be changed after initialization. Create a new element to use a different URL."
      );
    }
    __privateSet(this, _frameUrl, frameUrl);
  };
  consumeFrameUrl_fn = function(options) {
    if (!("frameUrl" in options)) return;
    const frameUrl = options.frameUrl;
    delete options.frameUrl;
    if (frameUrl == null) return;
    if (typeof frameUrl !== "string" || frameUrl.trim() === "") {
      throw new IntegrationError(
        "ChatKit frameUrl must be a non-empty string."
      );
    }
    __privateMethod(this, _ChatKitElementBase_instances, setFrameUrl_fn).call(this, frameUrl);
  };
  _handleFrameLoad = new WeakMap();
  _initialized = new WeakMap();
  maybeInit_fn = function() {
    if (__privateGet(this, _initialized) || !__privateGet(this, _frame) || !__privateGet(this, _opts)) {
      return;
    }
    __privateSet(this, _initialized, true);
    __privateMethod(this, _ChatKitElementBase_instances, setOptionsDataAttributes_fn).call(this, __privateGet(this, _opts));
    const frameURL = new URL(__privateMethod(this, _ChatKitElementBase_instances, getFrameUrl_fn).call(this), window.location.origin);
    __privateGet(this, _messenger).setTargetOrigin(frameURL.origin);
    frameURL.hash = encodeBase64({
      options: getInnerOptions(__privateMethod(this, _ChatKitElementBase_instances, getFrameOptions_fn).call(this, __privateGet(this, _opts))),
      referrer: window.location.origin,
      profile: this.profile,
      ...__privateGet(this, _channelId) ? { channelId: __privateGet(this, _channelId) } : {}
    });
    __privateGet(this, _messenger).connect();
    __privateGet(this, _frame).src = frameURL.toString();
    if (__privateGet(this, _wrapper)) {
      __privateGet(this, _shadow).append(__privateGet(this, _wrapper));
    }
  };
  __decorateElement(_init, 1, "focusComposer", _focusComposer_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "fetchUpdates", _fetchUpdates_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "sendUserMessage", _sendUserMessage_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "setComposerValue", _setComposerValue_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "setRuntimeCapabilities", _setRuntimeCapabilities_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "setThreadId", _setThreadId_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "shareThread", _shareThread_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "sendCustomAction", _sendCustomAction_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "showHistory", _showHistory_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "hideHistory", _hideHistory_dec, ChatKitElementBase);
  __decorateElement(_init, 1, "setTrainingOptOut", _setTrainingOptOut_dec, ChatKitElementBase);
  __decoratorMetadata(_init, ChatKitElementBase);
  class ChatKitElement extends ChatKitElementBase {
    constructor() {
      super({ profile: "chatkit" });
    }
    sanitizeOptions(options) {
      var _a2;
      (_a2 = options.threadItemActions) == null ? true : delete _a2.share;
      return options;
    }
  }
  function registerChatKitElement(tag = "xpertai-chatkit") {
    if (!("customElements" in globalThis)) return;
    if (!customElements.get(tag)) {
      customElements.define(tag, ChatKitElement);
    }
  }
  registerChatKitElement();
});
//# sourceMappingURL=xpert-chatkit.umd.cjs.map
