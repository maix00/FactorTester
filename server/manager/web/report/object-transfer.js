(() => {
  function text(context, key) {
    return context?.t?.(key) || key;
  }

  function errorMessage(value, fallback) {
    if (typeof value === "string" && value) return value;
    if (value && typeof value === "object" && typeof value.message === "string") {
      return value.message;
    }
    return fallback;
  }

  async function response(context, publicationID, objectKind, objectID) {
    const issued = await context.api("/api/transfers/objects/download-access", {
      method: "POST",
      body: JSON.stringify({
        publication_id: publicationID,
        object_kind: objectKind,
        object_id: objectID,
      }),
    });
    const access = issued?.access || {};
    if (!access.url || !access.bearer) {
      throw new Error(text(context, "研究对象传输授权无效"));
    }
    const headers = new Headers({Authorization: `Bearer ${access.bearer}`});
    let result;
    try {
      result = await fetch(access.url, {
        credentials: "omit",
        redirect: "error",
        headers,
      });
    } catch (error) {
      throw new Error(errorMessage(
        error?.message,
        text(context, "研究对象数据源不可用"),
      ));
    }
    if (!result.ok) {
      const value = await result.json().catch(() => ({}));
      throw new Error(errorMessage(
        value?.error,
        `${text(context, "研究对象下载失败")} (HTTP ${result.status})`,
      ));
    }
    return {response: result, issued};
  }

  async function blob(context, publicationID, objectKind, objectID) {
    const value = await response(context, publicationID, objectKind, objectID);
    const result = await value.response.blob();
    const expected = Number(
      value.issued?.access?.expected_size
        ?? value.issued?.object?.size_bytes
        ?? 0,
    );
    if (expected > 0 && result.size !== expected) {
      throw new Error(text(context, "研究对象大小校验失败"));
    }
    return result;
  }

  async function evidenceBlob(context, evidenceRef, sourceRef) {
    const issued = await context.api("/api/transfers/objects/download-access", {
      method: "POST",
      body: JSON.stringify({
        object_kind: "evidence_file",
        evidence_ref: evidenceRef,
        source_ref: sourceRef,
      }),
    });
    const access = issued?.access || {};
    if (!access.url || !access.bearer) {
      throw new Error(text(context, "证据文件传输授权无效"));
    }
    let result;
    try {
      result = await fetch(access.url, {
        credentials: "omit",
        redirect: "error",
        headers: new Headers({Authorization: `Bearer ${access.bearer}`}),
      });
    } catch (error) {
      throw new Error(errorMessage(error?.message, text(context, "证据来源离线")));
    }
    if (!result.ok) {
      const value = await result.json().catch(() => ({}));
      throw new Error(errorMessage(value?.error, text(context, "证据文件下载失败")));
    }
    const value = await result.blob();
    const expected = Number(access.expected_size ?? issued?.object?.size_bytes ?? 0);
    if (expected > 0 && value.size !== expected) {
      throw new Error(text(context, "证据文件大小校验失败"));
    }
    return {blob: value, object: issued.object || {}};
  }

  window.FTResearchObjectTransfer = Object.freeze({response, blob, evidenceBlob});
})();
