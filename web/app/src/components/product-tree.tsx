import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Pagination, Spin, Tooltip } from "antd";
import { InfoCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { Tree } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { usePageInstance } from "../page-instance.ts";
import { useCompactLayout } from "../configuration/layout.ts";
import { ProductPathRules, sourceInstallationLabel } from "../product-selection.ts";
import "./product-tree.css";

type Row = Record<string, any>;
type Node = { key: string; title: React.ReactNode; children?: Node[]; isLeaf: boolean; raw: Row;
  path: string; ancestors: string[]; checkable?: boolean; disableCheckbox?: boolean; selectable?: boolean; pager?: boolean };
export type ProductTreeSelection = { paths: readonly string[]; onChange?: (paths: string[]) => void;
  readOnly?: boolean; multiple?: boolean; leafOnly?: boolean; allowExclusions?: boolean };
const EMPTY: readonly string[] = [];
const MAX_BRANCHES = 40; // At most 2,000 loaded product rows; selection lives elsewhere.

export function ProductTree({ selection, categoryIds = EMPTY }: {
  selection?: ProductTreeSelection; categoryIds?: readonly string[];
}): React.ReactElement {
  const { t } = useTranslation(), instance = usePageInstance(), compact = useCompactLayout();
  const [nodes, setNodes] = useState<Node[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [search, setSearch] = useState(""), [query, setQuery] = useState(""), [refresh, setRefresh] = useState(0);
  const [loaded, setLoaded] = useState<React.Key[]>([]), [expanded, setExpanded] = useState<React.Key[]>([]), [manager, setManager] = useState("");
  const refreshed = useRef(0), lifecycle = useRef<AbortController | null>(null);
  const pending = useRef(new Map<string, Promise<void>>()), branches = useRef(new Map<string, true>());
  const categories = JSON.stringify([...new Set(categoryIds)].sort()), selecting = !!selection;
  const rules = useMemo(() => new ProductPathRules(selection?.paths || EMPTY), [selection?.paths]);
  const latest = useRef(selection); latest.current = selection;
  useEffect(() => { const timer = window.setTimeout(() => setQuery(search.trim()), 250); return () => clearTimeout(timer); }, [search]);
  const params = (): URLSearchParams => {
    const value = new URLSearchParams();
    for (const id of JSON.parse(categories)) value.append("category", id);
    if (selecting) value.set("checkbox", "1");
    return value;
  };
  const convert = (rows: Row[], parent = "", ancestors: string[] = []): Node[] => rows.map(row => {
    const path = String(row.selection_path || row.product_path || row.key), product = !!row.product_name;
    const key = product ? JSON.stringify([parent, String(row.key)]) : String(row.key);
    const label = String(row.title === "Product Lists" ? t("catalog.products") : row.title || row.key);
    const bindings = Array.isArray(row.source_bindings) ? row.source_bindings : [];
    const sourceText = bindings.length ? bindings.map((binding: Row) => [
      sourceInstallationLabel(String(binding.manager_id || binding.installation?.authority || ""), binding.installation || binding),
      binding.member_id, binding.source_product_ref,
    ].filter(Boolean).join(" · ")).join("\n") : (row.source_ids || []).join(" · ");
    return { key, path, ancestors, raw: row, isLeaf: !row.lazy && !row.children?.length,
      title: <span className="tr-product-tree-label"><span title={String(row.desc || label)}>{label}</span>{sourceText ? <Tooltip title={<span className="tr-product-tree-sources">{bindings.length ? sourceText : `${t("productSelection.catalogSources")}\n${sourceText}`}</span>}><InfoCircleOutlined aria-label={t("productSelection.sources")} /></Tooltip> : null}</span>,
      ...(row.children?.length ? { children: convert(row.children, key, [...ancestors, path]) } : {}) };
  });
  const pager = (path: string, result: Row, action: (page: number) => void): Node => ({
    key: JSON.stringify([path, "pagination"]), path: "", ancestors: [], raw: {}, isLeaf: true, pager: true, selectable: false, checkable: false,
    title: <span className="tr-product-tree-pager" onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>
      <Pagination size="small" simple current={result.page || 1} pageSize={50} total={result.total || 0} showSizeChanger={false}
        onChange={action} />
    </span>,
  });
  useEffect(() => {
    const controller = new AbortController(); lifecycle.current = controller;
    setLoading(true); setError(""); setNodes([]); setLoaded([]); setExpanded([]); pending.current.clear(); branches.current.clear();
    const invalidate = refresh !== refreshed.current; refreshed.current = refresh;
    const value = params(); if (invalidate) value.set("refresh", "1");
    const load = async (): Promise<void> => {
      // Refresh the root snapshot once; searching never clears or fans out to branches.
      if (query && invalidate) await request(`/api/product-library/tree?${value}`, { signal: controller.signal });
      if (query) { value.delete("refresh"); value.set("scope", "catalog"); value.set("query", query); value.set("page", "1"); value.set("limit", "50"); }
      const result = await request(`/api/product-library/${query ? "contract-tree" : "tree"}${value.size ? `?${value}` : ""}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setManager(String(result.server_id || ""));
      const rows = convert(query ? result.nodes || [] : result.tree || []);
      if (query && result.total > 50) rows.push(pager("search", result, page => void searchPage(page, controller.signal)));
      setNodes(rows);
    };
    void load().catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [t, refresh, query, categories, selecting]);
  const searchPage = async (page: number, signal: AbortSignal): Promise<void> => {
    const value = params(); value.set("scope", "catalog"); value.set("query", query); value.set("page", String(page)); value.set("limit", "50");
    const ticket = new AbortController();
    const old = searchRequest.current; old?.abort(); searchRequest.current = ticket;
    const abort = (): void => ticket.abort(); signal.addEventListener("abort", abort, { once: true });
    setLoading(true); setError("");
    try {
      const result = await request(`/api/product-library/contract-tree?${value}`, { signal: ticket.signal });
      if (signal.aborted || ticket.signal.aborted) return;
      const next = convert(result.nodes || []); next.push(pager("search", result, p => void searchPage(p, signal))); setNodes(next);
    } catch (reason) { if (!signal.aborted && !ticket.signal.aborted) setError((reason as Error).message); }
    finally { signal.removeEventListener("abort", abort); if (!signal.aborted && !ticket.signal.aborted) setLoading(false); }
  };
  const searchRequest = useRef<AbortController | null>(null);
  const load = (node: Node, page = 1): Promise<void> => {
    const key = JSON.stringify([node.key, page]), old = pending.current.get(key); if (old) return old;
    const signal = lifecycle.current?.signal, value = params();
    value.set("path", String(node.raw.key)); value.set("page", String(page)); value.set("limit", "50");
    const task = request(`/api/product-library/contract-tree?${value}`, { signal }).then(result => {
      if (signal?.aborted) return;
      setError(""); const next = convert(result.nodes || [], node.key, [...node.ancestors, node.path]);
      if (result.total > 50) next.push(pager(node.key, result, p => void load(node, p).catch(() => undefined)));
      branches.current.delete(node.key); branches.current.set(node.key, true);
      const evicted = new Set<string>();
      while (branches.current.size > MAX_BRANCHES) { const oldest = branches.current.keys().next().value!; branches.current.delete(oldest); evicted.add(oldest); }
      const replace = (items: Node[]): Node[] => items.map(item => item.key === node.key ? { ...item, children: next } :
        evicted.has(item.key) ? { ...item, children: undefined } : item.children ? { ...item, children: replace(item.children) } : item);
      setNodes(current => replace(current)); setLoaded(current => [...current.filter(key => !evicted.has(String(key)) && key !== node.key), node.key]);
      if (evicted.size) setExpanded(current => current.filter(key => !evicted.has(String(key))));
    }).catch(reason => { if (!signal?.aborted) setError(reason.message); throw reason; });
    pending.current.set(key, task); void task.finally(() => { if (pending.current.get(key) === task) pending.current.delete(key); }).catch(() => undefined);
    return task;
  };
  const view = useMemo(() => {
    const checked: string[] = [], halfChecked: string[] = [];
    const decorate = (items: Node[]): Node[] => items.map(node => {
      const canCheck = selecting && !node.pager && (!!node.raw.product_name || node.raw.checkbox !== false && (!(selection?.leafOnly ?? true) || !!node.raw.lazy || node.isLeaf));
      const state = rules.state(node.path, node.ancestors);
      if (canCheck) { if (state.checked) checked.push(node.key); else if (state.partial) halfChecked.push(node.key); }
      return { ...node, checkable: canCheck, disableCheckbox: !!selection?.readOnly || !selection?.onChange || state.blocked ||
          selection?.allowExclusions === false && state.checked && !rules.included.has(node.path),
        ...(node.children ? { children: decorate(node.children) } : {}) };
    });
    return { nodes: decorate(nodes), checked: { checked, halfChecked } };
  }, [nodes, rules, selecting, selection?.leafOnly, selection?.readOnly, selection?.onChange, selection?.allowExclusions]);
  return <section className="tr-product-tree" aria-label={t("catalog.tree")}>
    <div className="tr-product-tree-toolbar"><Input.Search size="small" allowClear aria-label={t("productSelection.search")} placeholder={t("productSelection.search")} value={search}
      onChange={event => setSearch(event.target.value)} onSearch={value => setQuery(value.trim())} />
      <Tooltip title={t("catalogActions.refreshProducts")}><Button size="small" aria-label={t("catalogActions.refreshProducts")} icon={<ReloadOutlined />} disabled={loading} onClick={() => setRefresh(value => value + 1)} /></Tooltip></div>
    {manager ? <div className="tr-product-tree-caption"><span title={manager}>Manager · {manager}</span><Tooltip trigger={["hover","focus"]} title={t("productSelection.bindingHint")}><InfoCircleOutlined tabIndex={0} aria-label={t("productSelection.sourceScope")} /></Tooltip></div> : null}
    {error ? <Alert type="error" showIcon message={error} action={<Button size="small" onClick={() => setRefresh(value => value + 1)}>{t("retry")}</Button>} /> : null}
    <Spin spinning={loading}>{!loading && !nodes.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <Tree<Node>
      key={JSON.stringify([refresh, query, categories, selecting])} virtual height={compact ? 320 : 420} blockNode showLine treeData={view.nodes}
      checkable={selecting} checkStrictly checkedKeys={view.checked} loadedKeys={loaded} onLoad={() => undefined} expandedKeys={expanded} onExpand={setExpanded}
      loadData={node => node.isLeaf || node.children?.length ? Promise.resolve() : load(node)}
      onCheck={(_, info) => { const current = latest.current; if (!current?.readOnly && current?.onChange) {
        const model = current.paths === rules.paths ? rules : new ProductPathRules(current.paths);
        const paths = model.toggle(info.node.path, info.checked, info.node.ancestors, current.multiple !== false);
        latest.current = { ...current, paths }; current.onChange(paths);
      } }}
      onSelect={(_, info) => { const row = info.node.raw; if (!selecting && row.product_name) instance.open("product-detail", { productName: String(row.product_name), productTitle: String(row.desc || row.product_name), ...(row.contract_uid ? { contractUid: String(row.contract_uid) } : {}) }); }}
    />}</Spin>
  </section>;
}
