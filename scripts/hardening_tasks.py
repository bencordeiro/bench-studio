"""Original executable reasoning questions; references in BENCHMARK_REFRESH.md."""

PYTHON_REASONING = {
    "stable_id": "cr8-generator-delegation-unwind",
    "title": "Delegated generator throw, return and cleanup",
    "description": "Track an exception injected through yield from, its return value, and close unwinding.",
    "code": '''trace = []
def child():
    try:
        try:
            yield 'ready'
        except ValueError as exc:
            trace.append(str(exc))
            value = yield 'handled'
            return value * 2
    finally:
        trace.append('child-finally')
def parent():
    try:
        result = yield from child()
        trace.append(result)
        yield 'tail'
    finally:
        trace.append('parent-finally')
g = parent()
a = next(g)
b = g.throw(ValueError('fault'))
c = g.send(7)
g.close()
print(a, b, c, trace, sep='|')
''',
}

# Each program is self-contained and writes a single deterministic output line.
# No network, wall-clock timing, random scheduling, DOM emulation, or packages.
WEB_TASKS = [
    ("url-live-state", "URLSearchParams live state and encoding normalization", "url", '''
const url = new URL('https://app.test/search?q=a%20b&tag=x&tag=y');
const p = url.searchParams;
const snapshot = new URLSearchParams(p);
p.set('tag', 'z');
url.search = '?q=c%2Bd&tag=k&tag=m';
p.append('q', 'e f');
p.sort();
console.log(JSON.stringify([p === url.searchParams, p.getAll('q'), snapshot.getAll('tag'), url.search]));
'''),
    ("response-clone", "Cloned response bodies, consumption and HTTP error status", "fetch", '''
(async () => {
  const response = new Response('not-json', {status: 409});
  const copy = response.clone();
  let first, second;
  try { await response.json(); } catch (e) { first = e.name; }
  try { await response.text(); } catch (e) { second = e.name; }
  const text = await copy.text();
  console.log(JSON.stringify([response.ok, response.bodyUsed, first, second, text, copy.bodyUsed]));
})();
'''),
    ("abort-reentrancy", "Abort dispatch, reentrant abort and promise checkpoints", "abort", '''
const c = new AbortController();
const out = [];
c.signal.addEventListener('abort', () => {
  out.push('listener:' + c.signal.reason);
  c.abort('second');
  queueMicrotask(() => out.push('listener-microtask'));
});
Promise.resolve().then(() => out.push('promise'));
c.abort('first');
out.push('after:' + c.signal.reason);
c.signal.addEventListener('abort', () => out.push('late'));
queueMicrotask(() => console.log(out.join('|')));
'''),
    ("thenable-jobs", "Thenable assimilation, ignored settlement and finally adoption", "promise", '''
const out = [];
const value = { get then() {
  out.push('get');
  return resolve => {
    out.push('then'); resolve('ok'); out.push('after-resolve'); throw Error('ignored');
  };
}};
const p = Promise.resolve(value);
out.push('sync');
p.finally(() => { out.push('finally'); return Promise.resolve('replacement'); })
 .then(x => { out.push(x); console.log(out.join('|')); });
queueMicrotask(() => out.push('micro'));
'''),
    ("proxy-receiver", "Proxy receiver writes through inherited accessors", "proxy", '''
const events = [];
const base = { get score() { return this._score * 2; },
  set score(v) { this._score = v + 1; } };
const target = Object.create(base);
target._score = 3;
const proxy = new Proxy(target, {
  set(t, k, v, receiver) {
    events.push(String(k) + ':' + v);
    return Reflect.set(t, k, v, receiver);
  }
});
const child = Object.create(proxy);
child.score = 5;
console.log(JSON.stringify([child.score, proxy.score, child._score, target._score,
  Object.hasOwn(child, 'score'), events]));
'''),
    ("clone-transfer", "Transferred buffers and alias identity in structuredClone", "clone", '''
const buffer = new ArrayBuffer(4);
const a = new Uint8Array(buffer);
a.set([3, 5, 7, 9]);
const source = {a, b: new Uint8Array(buffer, 1, 2)};
source.self = source;
const cloned = structuredClone(source, {transfer: [buffer]});
cloned.b[0] = 11;
console.log(JSON.stringify([buffer.byteLength, a.length, cloned.self === cloned,
  cloned.a.buffer === cloned.b.buffer, [...cloned.a], [...cloned.b]]));
'''),
    ("json-replacer", "toJSON runs before replacers and changes the holder", "json", '''
const trace = [];
const source = {secret: 7, child: {value: 4,
  toJSON(key) { trace.push('json:' + key); return {value: this.value + 1, drop: undefined}; }
}};
const text = JSON.stringify(source, function(key, value) {
  if (key) trace.push(key + ':' + (this === source ? 'source' : 'other'));
  if (key === 'secret') return undefined;
  if (key === 'value') return value * 2;
  return value;
});
console.log(JSON.stringify([text, trace]));
'''),
    ("async-generator-close", "Breaking async iteration awaits yielding finally cleanup", "async-generator", '''
(async () => {
  const out = [];
  async function* values() {
    try { yield 1; yield 2; }
    finally { out.push('cleanup-start'); await Promise.resolve(); out.push('cleanup-end'); }
  }
  for await (const x of values()) { out.push(x); break; }
  out.push('after-loop');
  console.log(out.join('|'));
})();
'''),
    ("store-reentrancy", "Snapshot subscriber lists during nested state updates", "state", '''
let state = 0;
const listeners = new Set();
const trace = [];
function set(value) {
  state = value;
  for (const listener of [...listeners]) listener(state);
}
const b = value => trace.push('B' + value);
listeners.add(value => {
  trace.push('A' + value);
  if (value === 1) { listeners.delete(b); listeners.add(x => trace.push('C' + x)); set(2); }
});
listeners.add(b);
set(1);
console.log(trace.join('|'));
'''),
    ("cache-age", "HTTP cache age includes transit time and shared freshness", "http-cache", '''
// All times below are seconds on the same clock. Implemented RFC 9111 rules:
// apparent_age=max(0,response_time-Date), corrected_age=Age+response_delay;
// current_age=max(apparent_age,corrected_age)+(now-response_time).
const response = {date: 90, age: 8, requestTime: 100, responseTime: 104,
  maxAge: 60, sMaxAge: 20, vary: ['accept-language']};
const storedRequest = {'accept-language': 'en', 'x-theme': 'dark'};
function reusable(now, request, shared) {
  const delay = response.responseTime - response.requestTime;
  const age = Math.max(0, response.responseTime - response.date, response.age + delay)
    + now - response.responseTime;
  const lifetime = shared ? response.sMaxAge : response.maxAge;
  return [age, age < lifetime && response.vary.every(k => request[k] === storedRequest[k])];
}
console.log(JSON.stringify([
  reusable(109, {'accept-language':'en','x-theme':'light'}, true),
  reusable(110, {'accept-language':'en'}, true),
  reusable(110, {'accept-language':'en'}, false),
  reusable(109, {'accept-language':'fr'}, false)
]));
'''),
]

RETIRED_WEB_IDS = {
    "wd-map-parseint", "wd-default-sort", "wd-unary-plus-coercion", "wd-float-add",
    "wd-array-plus-object", "wd-equality-trio", "wd-bitwise-string-coerce",
    "wd-negative-zero", "wd-math-empty", "wd-parseint-number-edge",
}
