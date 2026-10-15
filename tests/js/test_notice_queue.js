const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element(tag = 'div') {
  return {
    tagName: tag.toUpperCase(), children: [], attributes: {}, listeners: {},
    append(...children) { this.children.push(...children); children.forEach(child => { child.parent = this; }); },
    prepend(child) { this.children.unshift(child); child.parent = this; },
    remove() {
      const index = this.parent?.children.indexOf(this) ?? -1;
      if (index >= 0) this.parent.children.splice(index, 1);
      this.parent = null;
    },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, listener) { this.listeners[name] = listener; },
  };
}

global.window = global;
global.document = {createElement: element};
vm.runInThisContext(fs.readFileSync('server/manager/web/app/runtime.js', 'utf8'));

const container = element('section');
let time = 100000;
let nextTimer = 0;
const timers = new Map();
const queue = FTAppRuntime.createNoticeQueue(container, {
  now: () => time,
  setTimeout: (callback, delay) => {
    const id = ++nextTimer;
    timers.set(id, {callback, at: time + delay});
    return id;
  },
  clearTimeout: id => timers.delete(id),
});
function advance(ms) {
  time += ms;
  for (const [id, timer] of [...timers]) {
    if (timer.at <= time) {
      timers.delete(id);
      timer.callback();
    }
  }
}
function messages() { return container.children.map(child => child.children[0].textContent); }

queue.enqueue('first');
queue.enqueue('second', true);
assert.deepEqual(messages(), ['second', 'first'], 'newest message is at top');
assert.equal(container.children[0].attributes.role, 'alert');
assert.equal(timers.size, 2);
queue.enqueue('second', true);
assert.deepEqual(messages(), ['second', 'first'], 'active duplicates do not stack');
assert.equal(timers.size, 2, 'a duplicate cannot extend an existing timer');
queue.enqueue('');
assert.deepEqual(messages(), ['second', 'first'], 'legacy empty notice does not clear the queue');

container.children[0].children[1].listeners.click();
assert.deepEqual(messages(), ['first'], '× closes only its own message');
assert.equal(timers.size, 1, 'manual close cancels its timer');
queue.enqueue('second', true);
assert.deepEqual(messages(), ['first'], 'immediate async repeat is suppressed');
advance(5000);
assert.deepEqual(messages(), [], 'information expires automatically');
advance(5000);
queue.enqueue('second', true);
assert.deepEqual(messages(), ['second'], 'the same text can be shown after cooldown');

for (let index = 0; index < 7; index += 1) queue.enqueue(`item ${index}`);
assert.equal(container.children.length, 5, 'the queue has a bounded visible size');
assert.equal(messages()[0], 'item 6');
assert.equal(messages()[4], 'item 2');
advance(8000);
assert.deepEqual(messages(), [], 'older timers cannot remove newer notices');

const html = fs.readFileSync('server/manager/web/research.html', 'utf8');
const css = fs.readFileSync('server/manager/web/styles/app.css', 'utf8');
assert.ok(html.indexOf('id="notice"') < html.indexOf('class="app-shell"'));
assert.match(css, /\.notice-stack\s*\{[^}]*position:\s*fixed/s);
assert.match(css, /\.notice-stack\s*\{[^}]*flex-direction:\s*column/s);
assert.doesNotMatch(css, /\.notice\s*\{[^}]*background:\s*#fff3cd/s);
console.log('NOTICE QUEUE: top stack, close, expiry, dedupe and layout contract PASSED');
