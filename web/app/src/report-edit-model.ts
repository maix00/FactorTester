export type ReportComponent = { component_id?: string; kind?: string; title?: string; body?: string; parent_id?: string | null };
export type ReportChapter = { chapter_id?: string; title?: string; components?: ReportComponent[] };

/** Use the actual chapter root and the last root-level sibling as insertion anchors. */
export function insertParagraph(chapter: ReportChapter, id:string, title:string, body:string): Record<string, unknown> | null {
  const items = chapter.components || [], root = items.find(item => item.kind === "chapter" && item.component_id === chapter.chapter_id);
  if (!root?.component_id || !id || !body.trim()) return null;
  const last = items.filter(item => item.parent_id === root.component_id).at(-1);
  return {op:"insert_component",chapter_id:chapter.chapter_id,parent_id:root.component_id,after_component_id:last?.component_id || root.component_id,
    component:{component_id:id,kind:"paragraph",title,body}};
}

/** Component movement is limited to siblings; the parent is the first-position anchor. */
export function moveReportComponent(chapter:ReportChapter, id:string, direction:"up" | "down"): Record<string, unknown> | null {
  const items = chapter.components || [], item = items.find(entry => entry.component_id === id);
  if (!item?.parent_id) return null;
  const siblings = items.filter(entry => entry.parent_id === item.parent_id && entry.component_id), index = siblings.findIndex(entry => entry.component_id === id);
  if (index < 0 || direction === "up" && index === 0 || direction === "down" && index === siblings.length - 1) return null;
  const after = direction === "up" ? index > 1 ? siblings[index - 2].component_id : item.parent_id : siblings[index + 1].component_id;
  return {op:"move_component",chapter_id:chapter.chapter_id,component_id:id,parent_id:item.parent_id,after_component_id:after};
}

/** A selected parent already removes its descendants; never issue a second delete for them. */
export function removeReportComponents(chapter:ReportChapter, selected:string[]): Record<string, unknown>[] {
  const items = chapter.components || [], byID = new Map(items.map(item => [item.component_id,item])), chosen = new Set(selected);
  return items.filter(item => {
    if (!item.component_id || item.kind === "chapter" || !chosen.has(item.component_id)) return false;
    const seen = new Set<string>(); let parent = item.parent_id;
    while (parent && !seen.has(parent)) {
      if (chosen.has(parent)) return false;
      seen.add(parent); parent = byID.get(parent)?.parent_id;
    }
    return true;
  }).map(item => ({op:"remove_component",chapter_id:chapter.chapter_id,component_id:item.component_id,include_children:true}));
}
