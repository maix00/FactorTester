/** Path rules, never a list expanded from the currently loaded product page. */
export function readProductPaths(text: string): string[] {
  return [...new Set(text.split(/\r?\n/).map(path => path.trim()).filter(Boolean))];
}
const within = (path: string, parent: string): boolean => path === parent || path.startsWith(parent + "/");
function minimal(paths: Iterable<string>): string[] {
  const result: string[] = [];
  for (const path of [...new Set(paths)].sort()) {
    if (!result.length || !within(path, result[result.length - 1])) result.push(path);
  }
  return result;
}
export class ProductPathRules {
  readonly included = new Set<string>();
  readonly excluded = new Set<string>();
  private includeParents = new Set<string>();
  private excludeParents = new Set<string>();
  readonly paths: readonly string[];
  constructor(paths: readonly string[]) {
    this.paths = paths;
    for (const signed of paths) {
      const negative = signed.startsWith("-"), path = negative ? signed.slice(1) : signed;
      (negative ? this.excluded : this.included).add(path);
      const parents = negative ? this.excludeParents : this.includeParents;
      let offset = path.indexOf("/");
      while (offset >= 0) { parents.add(path.slice(0, offset)); offset = path.indexOf("/", offset + 1); }
    }
  }
  private covers(set: Set<string>, path: string, proper = false): boolean {
    if (!proper && set.has(path)) return true;
    let offset = path.indexOf("/");
    while (offset >= 0) { if (set.has(path.slice(0, offset))) return true; offset = path.indexOf("/", offset + 1); }
    return false;
  }
  state(path: string, ancestors: readonly string[] = []): { checked: boolean; partial: boolean; blocked: boolean } {
    const included = this.covers(this.included, path) || ancestors.some(p => this.included.has(p));
    const excluded = this.covers(this.excluded, path) || ancestors.some(p => this.excluded.has(p));
    const partial = !excluded && (included ? this.excludeParents.has(path) : this.includeParents.has(path));
    return { checked: included && !excluded && !partial, partial,
      blocked: this.covers(this.excluded, path, true) || ancestors.some(p => this.excluded.has(p) && p !== path) };
  }
  toggle(path: string, checked: boolean, ancestors: readonly string[] = [], multiple = true): string[] {
    if (!path || this.state(path, ancestors).blocked) return [...this.paths];
    if (!multiple) return checked ? [path] : [];
    let positive = [...this.included], negative = [...this.excluded];
    if (checked) {
      positive.push(path);
      // An explicit check of a partly selected folder means include it all.
      negative = negative.filter(value => !within(value, path));
    } else {
      positive = positive.filter(value => !within(value, path));
      const covered = this.covers(new Set(positive), path) || ancestors.some(p => positive.includes(p));
      if (covered) negative.push(path);
    }
    return [...minimal(positive), ...minimal(negative).map(value => "-" + value)];
  }
}

/** Full installation identity. Display names never serve as cross-node keys. */
export function sourceInstallationKey(manager: string, installation: Record<string, unknown>): string {
  return JSON.stringify([manager, installation.authority, installation.owner, installation.node_id,
    installation.installation_id, installation.bundle_id, installation.bundle_version, installation.bundle_fingerprint]);
}
export function sourceInstallationLabel(manager: string, installation: Record<string, unknown>): string {
  return [manager, installation.node_id, installation.bundle_id, installation.bundle_version,
    installation.owner, installation.installation_id, installation.bundle_fingerprint].filter(value => value !== undefined && value !== "").join(" · ");
}
