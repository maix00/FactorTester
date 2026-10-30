import marked from "../../../static/vendor/marked/marked.min.js";
import type { FormulaRenderer } from "./components/formula.tsx";

type MathToken = { type:string; raw:string; latex:string; display:boolean };
type LinkRenderer = (href: string, label: string) => string | null;
type ImageResolver = (href: string) => {url:string | null} | null;
const isFactorAlias = (value: string): boolean => /^\$(?:F|Rev|RF|COMMON)(?::|=|_|\b)/i.test(value);
const escapeHTML = (value: string): string => value.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function closingDollar(value: string, start: number): number {
  for (let i=start; i<value.length; i++) {
    if (value[i]==="\\") {i++;continue;}
    if (value[i]==="\n") return -1;
    if (value[i]==="$") return i;
  }
  return -1;
}

/** Marked handles code spans/fences first; factor metadata is never read as TeX. */
function parser(engine: FormulaRenderer | null, link?: LinkRenderer, image?: ImageResolver): InstanceType<typeof marked.Marked> {
  const result = new marked.Marked();
  const render = (token: MathToken): string => engine
    ? engine.renderToString(token.latex, {displayMode:token.display,throwOnError:false,trust:false,maxExpand:1000})
    : `<span>${escapeHTML(token.raw)}</span>`;
  if (link) result.use({renderer:{link(token:{href:string;text:string}) {
    const id = link(token.href,token.text);
    return id === null ? false : `<button type="button" class="tr-table-link tr-object-reference" data-tr-report-link="${escapeHTML(id).replace(/"/g,"&quot;")}">${escapeHTML(token.text)}</button>`;
  }}});
  if (image) result.use({renderer:{image(token:{href:string;text:string}) {
    const resolved = image(token.href);
    if (!resolved) return false;
    const alt = escapeHTML(token.text).replace(/"/g,"&quot;");
    return resolved.url ? `<img src="${escapeHTML(resolved.url).replace(/"/g,"&quot;")}" alt="${alt}" loading="lazy">` : `<span>${alt}</span>`;
  }}});
  result.use({extensions:[
    {name:"reportBlockMath",level:"block",start:(source:string) => source.search(/(?:^|\n) {0,3}(?:\$\$|\\\[)/),
      tokenizer(source:string): MathToken | undefined {
        const match = source.match(/^ {0,3}(\$\$|\\\[)[ \t]*\n([\s\S]+?)\n[ \t]*(\$\$|\\\])[ \t]*(?:\n|$)/);
        if (!match || (match[1] === "$$" ? match[3] !== "$$" : match[3] !== "\\]")) return undefined;
        return {type:"reportBlockMath",raw:match[0],latex:match[2],display:true};
      },renderer:render},
    {name:"reportInlineMath",level:"inline",start(source:string) {
      for (let i=0;i<source.length;i++) {
        if (source.startsWith("\\(",i) || source.startsWith("\\[",i)) return i;
        if (source[i] === "\\") {i++;continue;}
        if (source[i] === "$" && !isFactorAlias(source.slice(i))) return i;
      }
      return -1;
    },tokenizer(source:string): MathToken | undefined {
      if (source.startsWith("\\(")) {
        const end = source.indexOf("\\)",2); if (end < 0) return undefined;
        return {type:"reportInlineMath",raw:source.slice(0,end+2),latex:source.slice(2,end),display:false};
      }
      if (source.startsWith("\\[")) {
        const end = source.indexOf("\\]",2); if (end < 0) return undefined;
        return {type:"reportInlineMath",raw:source.slice(0,end+2),latex:source.slice(2,end),display:true};
      }
      if (!source.startsWith("$") || isFactorAlias(source) || /\s/.test(source[1] || "")) return undefined;
      const display = source.startsWith("$$"), start = display ? 2 : 1;
      const end = closingDollar(source,start); if (end <= start || display && source[end+1] !== "$") return undefined;
      return {type:"reportInlineMath",raw:source.slice(0,end+(display?2:1)),latex:source.slice(start,end),display};
    },renderer:render},
  ]});
  return result;
}

const plain = parser(null);
const cached = new WeakMap<FormulaRenderer, InstanceType<typeof marked.Marked>>();
export function reportMarkdown(value: string, engine: FormulaRenderer | null, link?: LinkRenderer, image?: ImageResolver): string {
  if (link || image) return parser(engine,link,image).parse(value,{async:false});
  let current = engine ? cached.get(engine) : plain;
  if (!current && engine) {current = parser(engine);cached.set(engine,current);}
  return current!.parse(value,{async:false});
}
