"""Original short function-completion tasks, inspired by HumanEval's format.

Each case is (positional arguments, expected result). Inputs must not mutate.
Reference bodies stay here and are never sent to the evaluated model.
"""

TASKS = []


def task(name, title, signature, contract, body, cases):
    TASKS.append(dict(name=name, title=title, signature=signature, contract=contract, body=body, cases=cases))


task(
    "merge_windows",
    "Merge overlapping maintenance windows",
    "windows",
    "windows is a list of integer (start, end) pairs with start <= end. Return a sorted list of tuples merging overlapping OR touching closed intervals. Preserve disjoint intervals. Empty input returns [].",
    """out = []
for start, end in sorted(windows):
    if out and start <= out[-1][1]:
        out[-1] = (out[-1][0], max(end, out[-1][1]))
    else:
        out.append((start, end))
return out""",
    [
        (([],), []),
        (([(5, 8), (1, 3), (3, 6)],), [(1, 8)]),
        (([(1, 10), (2, 3), (12, 12)],), [(1, 10), (12, 12)]),
        (([(-4, -2), (-2, 0), (5, 5), (5, 5)],), [(-4, 0), (5, 5)]),
        (([(9, 10), (1, 2)],), [(1, 2), (9, 10)]),
    ],
)

task(
    "latest_records",
    "Select the latest event per ID",
    "records",
    "records is a list of dicts with string id, integer timestamp and arbitrary payload. Return one dict per id: highest timestamp wins; on ties the last input record wins. Order output by each id's FIRST appearance, even when its winner is replaced. Empty input returns [].",
    """best = {}
for r in records:
    if r['id'] not in best or r['timestamp'] >= best[r['id']]['timestamp']:
        best[r['id']] = r.copy()
return list(best.values())""",
    [
        (([],), []),
        (
            (
                [
                    {"id": "a", "timestamp": 2, "payload": 1},
                    {"id": "b", "timestamp": 1, "payload": 9},
                    {"id": "a", "timestamp": 2, "payload": 3},
                    {"id": "a", "timestamp": 0, "payload": 0},
                ],
            ),
            [{"id": "a", "timestamp": 2, "payload": 3}, {"id": "b", "timestamp": 1, "payload": 9}],
        ),
        (
            (
                [
                    {"id": "x", "timestamp": -3, "payload": None},
                    {"id": "x", "timestamp": -1, "payload": False},
                ],
            ),
            [{"id": "x", "timestamp": -1, "payload": False}],
        ),
    ],
)

task(
    "dependency_batches",
    "Schedule dependencies in deterministic batches",
    "dependencies",
    "dependencies maps every task name (string) to a list of prerequisite names; all referenced names exist as keys. Return batches of runnable tasks, each batch sorted lexicographically. A task may run only after ALL prerequisites completed in earlier batches. Duplicate prerequisites count once. Return None for any cycle (even if some tasks can run), and [] for an empty graph.",
    """done = set()
batches = []
while len(done) < len(dependencies):
    ready = sorted(k for k, v in dependencies.items() if k not in done and set(v) <= done)
    if not ready:
        return None
    batches.append(ready)
    done.update(ready)
return batches""",
    [
        (({},), []),
        (({"b": ["a", "a"], "a": [], "c": [], "d": ["b", "c"]},), [["a", "c"], ["b"], ["d"]]),
        (({"a": ["a"]},), None),
        (({"a": [], "b": ["c"], "c": ["b"]},), None),
        (({"c": ["b"], "b": ["a"], "a": []},), [["a"], ["b"], ["c"]]),
    ],
)

task(
    "resolve_path",
    "Normalize a virtual absolute path",
    "path",
    "path is an absolute POSIX path string beginning with /. Return its lexical normalization: collapse repeated slashes, remove . components, and apply .. by removing a previous component if one exists. Going above root stays at root. Remove trailing slash except for /. Do not access the filesystem; dot-prefixed names other than . and .. remain literal.",
    """parts = []
for part in path.split('/'):
    if part == '..':
        if parts: parts.pop()
    elif part and part != '.':
        parts.append(part)
return '/' + '/'.join(parts)""",
    [
        (("/",), "/"),
        (("/a//b/.././c/",), "/a/c"),
        (("/../../x",), "/x"),
        (("/.env/.../../z",), "/.env/z"),
        (("/a/..",), "/"),
    ],
)

task(
    "apply_patch",
    "Apply a recursive configuration patch",
    "base, patch",
    "base and patch are JSON-like dicts. Return a patched dict. In patch, null (None) deletes a key; a dict recursively patches the corresponding base value (use {} if it is not a dict); other values replace it. Lists replace wholesale. Neither input may mutate, including nested objects.",
    """from copy import deepcopy
out = deepcopy(base)
for key, value in patch.items():
    if value is None:
        out.pop(key, None)
    elif isinstance(value, dict):
        old = out.get(key)
        out[key] = apply_patch(old if isinstance(old, dict) else {}, value)
    else:
        out[key] = deepcopy(value)
return out""",
    [
        (({}, {}), {}),
        (
            ({"a": {"b": 1, "c": 2}, "x": [1, 2]}, {"a": {"b": None, "d": 0}, "x": []}),
            {"a": {"c": 2, "d": 0}, "x": []},
        ),
        (({"a": 7}, {"a": {"b": 1}, "z": None}), {"a": {"b": 1}}),
        (({"x": True}, {"x": False}), {"x": False}),
    ],
)

task(
    "inventory_ledger",
    "Deduplicate inventory events by event ID",
    "events",
    "events is a list of (event_id, sku, delta) tuples; IDs and SKUs are strings, delta is integer. First occurrence of an event_id wins globally, even if a later duplicate differs. Sum accepted deltas by SKU, omit zero balances, and return a list of (sku, balance) tuples sorted by SKU. Negative balances are allowed.",
    """seen = set()
stock = {}
for event, sku, delta in events:
    if event in seen: continue
    seen.add(event)
    stock[sku] = stock.get(sku, 0) + delta
return sorted((k,v) for k,v in stock.items() if v != 0)""",
    [
        (([],), []),
        (([("1", "b", 3), ("2", "a", 2), ("1", "a", 99), ("3", "b", -3)],), [("a", 2)]),
        (([("x", "z", -2), ("y", "z", 1)],), [("z", -1)]),
        (([("x", "a", 0), ("x", "b", 8)],), []),
    ],
)

task(
    "rolling_totals",
    "Compute event-time rolling totals at exact boundaries",
    "events, width",
    "events is a timestamp-nondecreasing list of (integer timestamp, integer value) pairs and width is a positive integer. For each event at time t, return the sum of values seen so far with timestamps in (t-width, t]. Later events, including later ties, must not be included yet. Return a list of integers in input order. Aim for linear time.",
    """from collections import deque
q = deque()
total = 0
out = []
for t,v in events:
    while q and q[0][0] <= t-width:
        total -= q.popleft()[1]
    q.append((t,v))
    total += v
    out.append(total)
return out""",
    [
        (([], 3), []),
        (([(0, 2), (2, 3), (3, -1), (3, 4), (8, 5)], 3), [2, 5, 2, 6, 5]),
        (([(1, 2), (1, 3), (2, 4)], 1), [2, 5, 4]),
        (([(-3, 1), (-1, 2), (0, 4)], 3), [1, 3, 6]),
    ],
)

task(
    "retry_delays",
    "Build a bounded exponential retry schedule",
    "initial, factor, cap, budget",
    "All arguments are positive integers. Proposed delays are min(initial * factor**k, cap) for k starting at 0. Return the longest prefix of delays whose sum is <= budget. Stop before the first delay that exceeds remaining budget; do not shorten it. factor >= 1.",
    """out = []
delay = min(initial, cap)
while delay <= budget:
    out.append(delay)
    budget -= delay
    delay = min(delay * factor, cap)
return out""",
    [
        ((2, 2, 5, 18), [2, 4, 5, 5]),
        ((8, 2, 3, 8), [3, 3]),
        ((4, 2, 9, 3), []),
        ((2, 1, 8, 6), [2, 2, 2]),
        ((1, 3, 5, 9), [1, 3, 5]),
    ],
)

task(
    "parse_query",
    "Parse repeated URL query parameters",
    "query",
    "Parse a query string, optionally beginning with ?. Split on &, ignoring empty segments. Split each segment at the first =; a missing = means an empty value. Decode percent escapes as UTF-8 and + as space in both keys and values, using urllib.parse.unquote_plus behavior. Return a dict mapping decoded keys to lists of values in occurrence order. Preserve blank keys and values.",
    """from urllib.parse import unquote_plus
out = {}
for part in query.removeprefix('?').split('&'):
    if not part: continue
    key, _, value = part.partition('=')
    out.setdefault(unquote_plus(key), []).append(unquote_plus(value))
return out""",
    [
        (("",), {}),
        (("?a=1&a=2&empty&x=a=b",), {"a": ["1", "2"], "empty": [""], "x": ["a=b"]}),
        (("q=a+b&q=%2B&=x&&a%20b=c",), {"q": ["a b", "+"], "": ["x"], "a b": ["c"]}),
        (("x=%E2%9C%93",), {"x": ["✓"]}),
    ],
)

task(
    "diff_records",
    "Compare snapshots by record identity",
    "before, after",
    "Each input is a list of dicts with unique string id within that input. Return a dict with keys added, removed, changed; each value is a sorted list of IDs. changed contains shared IDs whose whole dict differs under Python equality. Input order is irrelevant.",
    """a = {r['id']:r for r in before}
b = {r['id']:r for r in after}
return {'added':sorted(b.keys()-a.keys()),'removed':sorted(a.keys()-b.keys()),'changed':sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}""",
    [
        (([], []), {"added": [], "removed": [], "changed": []}),
        (
            ([{"id": "a", "v": 1}, {"id": "b", "v": 2}], [{"id": "a", "v": 3}, {"id": "c", "v": 2}]),
            {"added": ["c"], "removed": ["b"], "changed": ["a"]},
        ),
        (([{"id": "x", "v": [1]}], [{"v": [1], "id": "x"}]), {"added": [], "removed": [], "changed": []}),
        (([{"id": "x", "v": None}], [{"id": "x"}]), {"added": [], "removed": [], "changed": ["x"]}),
    ],
)

task(
    "allocate_cents",
    "Allocate cents using largest remainders",
    "total, weights",
    "total is a nonnegative integer number of cents. weights is a nonempty list of nonnegative integers with positive sum. Allocate total proportionally: floor every exact share, then distribute remaining cents to descending fractional remainders, ties by lower input index. Return integer allocations in input order. Use exact integer arithmetic.",
    """den = sum(weights)
parts = [total*w//den for w in weights]
order = sorted(range(len(weights)), key=lambda i: (-(total*weights[i]%den), i))
for i in order[:total-sum(parts)]: parts[i] += 1
return parts""",
    [
        ((10, [1, 1, 1]), [4, 3, 3]),
        ((2, [0, 1, 1, 1]), [0, 1, 1, 0]),
        ((0, [2, 3]), [0, 0]),
        ((7, [1, 2]), [2, 5]),
        ((10**18 + 1, [1, 1]), [500000000000000001, 500000000000000000]),
    ],
)

task(
    "longest_streak",
    "Find a longest run of consecutive observed days",
    "days",
    "days is an unsorted list of integer day numbers, possibly duplicated or negative. Return (start, length) of the longest run of consecutive distinct days. Break ties by smallest start. For no days return (None, 0).",
    """seen = set(days)
best = (None, 0)
for start in seen:
    if start-1 in seen: continue
    end = start
    while end in seen: end += 1
    length = end-start
    if length > best[1] or (length == best[1] and start < best[0]):
        best = (start, length)
return best""",
    [
        (([],), (None, 0)),
        (([5, 2, 1, 2, 6],), (1, 2)),
        (([-1, -3, -2, 7],), (-3, 3)),
        (([4, 4],), (4, 1)),
        (([3, 2, 4, 1],), (1, 4)),
    ],
)

task(
    "flatten_records",
    "Flatten nested dictionaries without losing empty objects",
    "data",
    "data is a nested dict. Keys are nonempty strings without dots. Return a flat dict with dot-separated key paths. Only dicts are expanded: lists and other values are leaves. Preserve empty nested dicts as {} at their path. Empty root returns {}.",
    """out = {}
def visit(node, prefix):
    for key,value in node.items():
        path = prefix + '.' + key if prefix else key
        if isinstance(value, dict) and value:
            visit(value, path)
        else:
            out[path] = value
visit(data, '')
return out""",
    [
        (({},), {}),
        (({"a": {"b": 1, "c": {}}, "d": [{"x": 2}]},), {"a.b": 1, "a.c": {}, "d": [{"x": 2}]}),
        (({"x": None, "y": {"z": False}},), {"x": None, "y.z": False}),
    ],
)

task(
    "missing_ranges",
    "Compress missing IDs into inclusive ranges",
    "ids, low, high",
    "low <= high are integers. ids is an unsorted list of integers, with duplicates and possible values outside [low, high]. Return sorted inclusive (start, end) tuples covering exactly the missing integers within that interval. Do not enumerate every integer in the interval; it may span billions.",
    """out = []
start = low
for value in sorted({v for v in ids if low <= v <= high}):
    if start < value: out.append((start,value-1))
    start = value+1
if start <= high: out.append((start,high))
return out""",
    [
        (([], 1, 5), [(1, 5)]),
        (([5, 1, 1, 3, 8], 1, 5), [(2, 2), (4, 4)]),
        (([1, 2], 1, 2), []),
        (([0], -(10**9), 10**9), [(-(10**9), -1), (1, 10**9)]),
        (([8], 3, 3), [(3, 3)]),
    ],
)

task(
    "lru_misses",
    "Simulate a bounded LRU cache",
    "keys, capacity",
    "keys is a list of hashable strings; capacity is a nonnegative integer. Starting empty, access each key. A hit refreshes its recency. A miss inserts it and, if necessary, evicts the least recently used key. Capacity zero stores nothing. Return (miss_count, final_keys), with final_keys ordered least to most recently used.",
    """from collections import OrderedDict
cache = OrderedDict()
misses = 0
for key in keys:
    if key in cache:
        cache.move_to_end(key)
    else:
        misses += 1
        if capacity:
            cache[key] = None
            if len(cache) > capacity: cache.popitem(last=False)
return misses, list(cache)""",
    [
        (([], 2), (0, [])),
        ((["a", "b", "a", "c", "b"], 2), (4, ["c", "b"])),
        ((["x", "x"], 0), (2, [])),
        ((["a", "a", "b", "b"], 1), (2, ["b"])),
        ((["a", "b", "a"], 4), (2, ["b", "a"])),
    ],
)

task(
    "sessionize",
    "Split timestamped events at idle gaps",
    "timestamps, timeout",
    "timestamps is a nondecreasing list of integer timestamps. timeout is a nonnegative integer. Consecutive timestamps belong to one session iff their difference is <= timeout. Return (first_time, last_time, event_count) tuples for each session, including duplicates in counts.",
    """out = []
for t in timestamps:
    if out and t-out[-1][1] <= timeout:
        start, _, count = out[-1]
        out[-1] = (start,t,count+1)
    else:
        out.append((t,t,1))
return out""",
    [
        (([], 3), []),
        (([1, 2, 5, 9, 9], 3), [(1, 5, 3), (9, 9, 2)]),
        (([1, 1, 2], 0), [(1, 1, 2), (2, 2, 1)]),
        (([-5, -2, 1], 3), [(-5, 1, 3)]),
    ],
)

task(
    "expand_template",
    "Expand placeholders in a single pass",
    "text, values",
    "Replace ${name} placeholders with values[name] (all values are strings). Names match [A-Za-z_][A-Za-z0-9_]*. Leave unknown or malformed placeholders unchanged. Expansion is one pass: never re-expand inserted values. There is no escape syntax.",
    r"""import re
return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', lambda m: values.get(m.group(1), m.group(0)), text)""",
    [
        (("Hi ${user}!", {"user": "Ana"}), "Hi Ana!"),
        (("${a}/${b}/${bad-name}", {"a": "${b}", "b": "X"}), "${b}/X/${bad-name}"),
        (("${_x}${missing}${1x}", {"_x": ""}), "${missing}${1x}"),
        (("", {}), ""),
    ],
)

task(
    "match_route",
    "Match a URL path against named route segments",
    "pattern, path",
    "Both strings begin with /. Split into slash-separated segments after removing at most one trailing slash (except root). A pattern segment starting with : captures one NONEMPTY segment by its remaining name. Capture names are nonempty and unique. Other segments are literal and case-sensitive. Return a dict of captures on full match, {} for a literal match, or None on mismatch. Do not URL-decode.",
    """def split(s):
    if s == '/': return []
    return s.removesuffix('/')[1:].split('/')
a,b = split(pattern),split(path)
if len(a) != len(b): return None
out = {}
for x,y in zip(a,b):
    if x.startswith(':'):
        if not y: return None
        out[x[1:]] = y
    elif x != y: return None
return out""",
    [
        (("/users/:id", "/users/42/"), {"id": "42"}),
        (("/", "/"), {}),
        (("/x/:id", "/x//"), None),
        (("/a", "/A"), None),
        (("/:a/:b", "/x/y"), {"a": "x", "b": "y"}),
        (("/x/:id", "/x/a/b"), None),
    ],
)

task(
    "first_conflict",
    "Find the earliest conflicting reservation pair",
    "bookings",
    "bookings is a list of (resource, start, end) tuples, with string resource and integers start <= end. Intervals are half-open [start,end); empty intervals never conflict. Return the lexicographically smallest pair of input indices (i,j), i<j, whose intervals overlap on the same resource, or None. Endpoint touching is not overlap.",
    """for i,(r,a,b) in enumerate(bookings):
    for j in range(i+1,len(bookings)):
        s,c,d = bookings[j]
        if r == s and max(a,c) < min(b,d):
            return (i,j)
return None""",
    [
        (([],), None),
        (([("a", 1, 3), ("a", 3, 5)],), None),
        (([("a", 1, 5), ("b", 2, 4), ("a", 3, 3), ("a", 4, 6)],), (0, 3)),
        (([("a", 5, 9), ("a", 1, 3), ("a", 2, 6)],), (0, 2)),
        (([("x", 1, 2), ("x", 1, 2)],), (0, 1)),
    ],
)

task(
    "paginate",
    "Paginate after a possibly missing cursor",
    "records, cursor, limit",
    'records is a list of dicts with unique integer id, in arbitrary order. cursor is an integer or None; limit is a positive integer. Sort ascending by id, keep ids strictly greater than cursor (all if None), and take up to limit records. Return {"items": page, "next_cursor": last returned id IF additional eligible records remain, otherwise None}. The cursor need not correspond to a record.',
    """eligible = sorted((r for r in records if cursor is None or r['id'] > cursor), key=lambda r:r['id'])
page = eligible[:limit]
return {'items':page,'next_cursor':page[-1]['id'] if len(eligible)>limit else None}""",
    [
        (([], None, 2), {"items": [], "next_cursor": None}),
        (([{"id": 3}, {"id": 1}, {"id": 5}], None, 2), {"items": [{"id": 1}, {"id": 3}], "next_cursor": 3}),
        (([{"id": 3}, {"id": 1}, {"id": 5}], 2, 1), {"items": [{"id": 3}], "next_cursor": 3}),
        (([{"id": 0}, {"id": 2}], 0, 1), {"items": [{"id": 2}], "next_cursor": None}),
        (([{"id": 1}], 9, 1), {"items": [], "next_cursor": None}),
    ],
)
