import assert from "node:assert/strict";
import test from "node:test";
import { reportMarkdown } from "./report-markdown.ts";

test("report math renders TeX while leaving code and factor identifiers intact", () => {
  const calls: {value:string;display:unknown}[] = [];
  const engine = {renderToString:(value:string,options:Record<string,unknown>) => {calls.push({value,display:options.displayMode});return `<span class="math">${value}</span>`;}};
  const html = reportMarkdown('公式 $x^2$ 和 \\(y+1\\)，因子 $F:30m|$Rev:2。\n\n`$z$`\n\n$$\na+b\n$$\n\n\\[c+d\\]',engine);
  assert.deepEqual(calls,[{value:'x^2',display:false},{value:'y+1',display:false},{value:'a+b',display:true},{value:'c+d',display:true}]);
  assert.match(html,/\$F:30m\|\$Rev:2/);assert.match(html,/<code>\$z\$<\/code>/);
});

test("report links can become safe buttons without changing ordinary links", () => {
  const html = reportMarkdown('[因子](factortester://factor/factor%3Av2%3Aabc) [external](https://example.com) [bad](javascript:alert(1))',null,
    href => href.startsWith('factortester://') ? 'a"b' : null);
  assert.match(html,/data-tr-report-link="a&amp;quot;b"|data-tr-report-link="a&quot;b"/);
  assert.match(html,/<button[^>]*>因子<\/button>/);
  assert.match(html,/<a href="https:\/\/example.com">external<\/a>/);
});

test("report images use the authorized resource URL and keep unavailable content inert", () => {
  const html = reportMarkdown('![本地图片](factortester-local://a) ![缺失](factortester-local://b) ![外部](https://example.com/a.png)',null,undefined,
    href => href.endsWith('//a') ? {url:'/api/image?owner=one&inline=1'} : href.endsWith('//b') ? {url:null} : null);
  assert.match(html,/<img src="\/api\/image\?owner=one&amp;inline=1" alt="本地图片" loading="lazy">/);
  assert.match(html,/<span>缺失<\/span>/);
  assert.match(html,/<img src="https:\/\/example.com\/a.png" alt="外部">/);
});
