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
