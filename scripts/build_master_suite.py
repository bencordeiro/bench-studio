"""Build the Master Suite from source, recomputing every answer.

Why this file exists
--------------------
The bundled suites follow one rule above all others: *an expected answer is
produced by execution, never written by hand*. For a suite this hard, that rule
has to be structural rather than a habit -- a hand-copied output that drifts one
character from its snippet turns a discriminating item into a trap that fails
every model equally, and it is invisible on inspection.

So the Master Suite has no hand-written answer key. Every code item's expected
output comes from running the snippet under CPython 3 / Node at build time,
every quantitative answer is recomputed here (several against a second,
independent method), and every long-context corpus is generated together with
the ground truth derived from it. Rebuild and the JSON either regenerates
byte-identically or the item was wrong.

Usage
-----
    python scripts/build_master_suite.py            # write the suite
    python scripts/build_master_suite.py --check    # verify it is up to date

Design of the difficulty ladder
-------------------------------
The suite is built to *separate*, not to be uniformly brutal. Four tiers:

    anchor   (w 1.5)  hardest items from the four base suites. A model that
                      fails these is not in the running -- separates bad/okay.
    hard     (w 2.0)  new items a strong local model can reach -- okay/good.
    extreme  (w 3.0)  compositions of 3+ subtleties -- good/great.
    frontier (w 4.0)  expected to break current frontier models -- headroom.

Weights here are *predicted*, not measured. Run scripts/calibrate_suite.py
against two real models and re-weight from observation before trusting a
ranking; see SCORING.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import random
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "backend" / "app" / "seed" / "suites" / "master_suite.json"


def _load_grader():
    """Import the real deterministic grader without the DB dependency stack.

    app.graders.deterministic is pure stdlib, but importing it through the `app`
    package pulls in SQLAlchemy and pydantic. Loading the file directly keeps
    this script runnable anywhere Python 3 is.
    """
    spec = importlib.util.spec_from_file_location(
        "_ms_deterministic", REPO / "backend" / "app" / "graders" / "deterministic.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GRADER = _load_grader()

SUITE_NAME = "Master Suite"
SUITE_VERSION = "3.0.0"

# Tier -> (difficulty label, importance weight). The declared difficulty and the
# weight must stay ordered together: test_declared_difficulty_matches_weight_ordering
# rejects a "medium" item that outweighs a "hard" one.
TIERS = {
    "anchor": ("medium", 1.5),
    "hard": ("hard", 2.0),
    "extreme": ("hard", 3.0),
    "frontier": ("hard", 4.0),
}

PROMPTS: list[dict] = []


def add_prompt(
    stable_id: str,
    title: str,
    description: str,
    category: str,
    tier: str,
    grader_config: dict,
    messages: list[dict],
    tags: list[str] | None = None,
) -> None:
    difficulty, weight = TIERS[tier]
    PROMPTS.append(
        {
            "stable_id": stable_id,
            "title": title,
            "description": description,
            "category": category,
            "tags": (tags or []) + [f"tier-{tier}", "unmeasured"],
            "difficulty": difficulty,
            "importance_weight": weight,
            "position": len(PROMPTS),
            "enabled": True,
            "grading_mode": "deterministic",
            # max_tokens is intentionally NOT capped here: suites must not force
            # a token budget (a chain-of-thought model would be truncated before
            # its answer lands). The run config owns the budget; 0 = server default.
            "generation_overrides": {"temperature": 0.0},
            "grader_config": grader_config,
            "messages": [
                {"role": m["role"], "content": m["content"], "position": i}
                for i, m in enumerate(messages)
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Execution helpers -- the answer key is whatever the interpreter says
# --------------------------------------------------------------------------- #
def run_python(src: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"python snippet failed:\n{proc.stderr}")
    out = proc.stdout.rstrip("\n")
    if "\n" in out:
        raise RuntimeError(f"snippet printed {out.count(chr(10)) + 1} lines, expected 1:\n{out}")
    return out


def run_node(src: str) -> str:
    proc = subprocess.run(
        ["node", "-e", src], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node snippet failed:\n{proc.stderr}")
    out = proc.stdout.rstrip("\n")
    if "\n" in out:
        raise RuntimeError(f"snippet printed {out.count(chr(10)) + 1} lines, expected 1:\n{out}")
    return out


CODE_PREAMBLE = (
    "You are given a short, self-contained {lang} program. Determine exactly what it "
    "writes to standard output. You MUST end "
    "your reply with a single final line in exactly this form:\n"
    "ANSWER: <output>\n"
    "where <output> is precisely what the program prints (one line), with no quotes, no "
    "code fences, and no extra words."
)

NUMERIC_PREAMBLE = (
    "You "
    "MUST end your reply with a single final line in exactly this form:\n"
    "ANSWER: <number>\n"
    "giving only the number -- no units, no thousands separators, no extra words."
)


def code_item(
    stable_id, title, description, lang, src, tier, tags=None, category=None
):
    """Register an output-prediction item, running the snippet for its answer."""
    src = textwrap.dedent(src).strip() + "\n"
    answer = run_python(src) if lang == "Python 3" else run_node(src)
    if not answer.strip():
        raise RuntimeError(f"{stable_id}: snippet printed nothing")
    body = CODE_PREAMBLE.format(lang=lang) + "\n\n```\n" + src + "```"
    add_prompt(
        stable_id,
        title,
        description,
        category or ("code-reasoning/python" if lang == "Python 3" else "code-reasoning/js"),
        tier,
        {
            "type": "exact",
            "canonical_answer": answer,
            "accepted_aliases": [],
            "case_sensitive": True,
            "trim_whitespace": True,
            "normalize_punctuation": False,
            "points": 100.0,
        },
        [{"role": "user", "content": body}],
        tags=(tags or []) + ["execution-verified"],
    )
    return answer


def numeric_item(
    stable_id, title, description, category, tier, question, value,
    *, decimals=None, rel_tol=0.0, abs_tol=0.0, tags=None,
):
    rounding = ""
    if decimals is not None:
        rounding = (
            f" Round your final answer to {decimals} decimal places."
            if decimals > 0
            else " Give your final answer as an exact integer."
        )
    body = question.strip() + "\n\n" + NUMERIC_PREAMBLE + rounding
    add_prompt(
        stable_id,
        title,
        description,
        category,
        tier,
        {
            "type": "numeric",
            "expected_value": float(value),
            "absolute_tolerance": float(abs_tol),
            "relative_tolerance": float(rel_tol),
            "points": 100.0,
        },
        [{"role": "user", "content": body}],
        tags=(tags or []) + ["computed-answer"],
    )


# =========================================================================== #
# 1. Code reasoning -- Python
# =========================================================================== #
def build_python_items() -> None:
    code_item(
        "ms-py-class-creation-order",
        "Class creation hook ordering",
        "Interleaving of metaclass __new__/__init__, __set_name__ and __init_subclass__.",
        "Python 3",
        '''
        log = []

        class Probe:
            def __set_name__(self, owner, name):
                log.append("set:" + name)
            def __get__(self, obj, objtype=None):
                return len(log)

        class Meta(type):
            def __new__(mcls, name, bases, ns):
                log.append("new:" + name)
                return super().__new__(mcls, name, bases, ns)
            def __init__(cls, name, bases, ns):
                log.append("init:" + name)
                super().__init__(name, bases, ns)

        class Base(metaclass=Meta):
            def __init_subclass__(cls):
                log.append("sub:" + cls.__name__)

        class Child(Base):
            probe = Probe()
            tail = "t"

        print(" ".join(log), Child.probe)
        ''',
        "frontier",
        tags=["metaclass", "descriptors"],
    )

    code_item(
        "ms-py-class-scope-comprehension",
        "Class scope versus comprehension scope",
        "The leftmost iterable is evaluated in the enclosing scope; the body is not.",
        "Python 3",
        '''
        x = "G"

        class C:
            x = "C"
            names = ["a", "b"]
            first = [x + n for n in names]
            second = [n + x for n in [x]]
            third = list(map(lambda n: n + x, names))

        print(C.first, C.second, C.third)
        ''',
        "extreme",
        tags=["scoping"],
    )

    code_item(
        "ms-py-reflected-operator-priority",
        "Reflected operator subclass priority",
        "A subclass overriding __radd__ is tried before the base's __add__, then "
        "NotImplemented falls back.",
        "Python 3",
        '''
        order = []

        class A:
            def __add__(self, o):
                order.append("A.add")
                return NotImplemented
            def __radd__(self, o):
                order.append("A.radd")
                return "ar"

        class B(A):
            def __radd__(self, o):
                order.append("B.radd")
                return "br"

        a, b = A(), B()
        r1 = a + b
        r2 = b + a
        print(r1, r2, ",".join(order))
        ''',
        "frontier",
        tags=["operators", "data-model"],
    )

    code_item(
        "ms-py-yield-from-delegation",
        "throw and close across a yield-from boundary",
        "throw() is delegated into the subgenerator and resumes inside its except "
        "clause; close() then unwinds both frames, so the delegating generator never "
        "receives the subgenerator's return value.",
        "Python 3",
        '''
        out = []

        def inner():
            try:
                out.append("i1")
                yield 1
                out.append("i2")
                yield 2
            except ValueError:
                out.append("icaught")
                yield 99
            finally:
                out.append("ifin")
            return "ret"

        def outer():
            try:
                r = yield from inner()
                out.append("r:" + str(r))
            except GeneratorExit:
                out.append("oexit")
                raise
            finally:
                out.append("ofin")

        g = outer()
        out.append(str(next(g)))
        out.append(str(g.throw(ValueError())))
        g.close()
        print("|".join(out))
        ''',
        "frontier",
        tags=["generators", "delegation"],
    )

    code_item(
        "ms-py-exception-groups",
        "except* splitting and re-raising",
        "Each except* clause sees only its matching subgroup; re-raising from one clause "
        "propagates a NEW group containing just those exceptions, and the unmatched "
        "handler still runs.",
        "Python 3",
        '''
        log = []

        def f():
            raise ExceptionGroup("g", [ValueError("v"), TypeError("t"), ValueError("v2")])

        try:
            try:
                f()
            except* ValueError as eg:
                log.append("V" + str(len(eg.exceptions)))
                raise
            except* TypeError as eg:
                log.append("T" + str(len(eg.exceptions)))
        except BaseException as e:
            log.append(type(e).__name__ + str(len(e.exceptions)))
            log.append(",".join(sorted(type(x).__name__ for x in e.exceptions)))
        print(" ".join(log))
        ''',
        "frontier",
        tags=["exceptions", "exception-groups"],
    )

    code_item(
        "ms-py-exitstack-unwind",
        "ExitStack unwinding with selective suppression",
        "Inner manager re-raises, outer swallows; the exception never reaches the "
        "surrounding except.",
        "Python 3",
        '''
        import contextlib

        log = []

        @contextlib.contextmanager
        def cm(name, swallow=False):
            log.append("enter:" + name)
            try:
                yield name
            except ValueError:
                log.append("swallow:" + name)
                if not swallow:
                    raise
            finally:
                log.append("exit:" + name)

        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(cm("outer", swallow=True))
                stack.enter_context(cm("inner"))
                raise ValueError("boom")
        except ValueError:
            log.append("escaped")
        print(",".join(log))
        ''',
        "frontier",
        tags=["context-managers", "exceptions"],
    )

    code_item(
        "ms-py-match-patterns",
        "Structural pattern matching resolution",
        "Sequence patterns skip str, mapping patterns allow extras, dotted names are "
        "value patterns while bare names capture.",
        "Python 3",
        '''
        class Cfg:
            LIMIT = 3

        class Point:
            __match_args__ = ("x", "y")
            def __init__(self, x, y):
                self.x, self.y = x, y

        def classify(v):
            match v:
                case [1, *rest] if len(rest) > 2:
                    return "long" + str(len(rest))
                case [1, *_]:
                    return "short1"
                case {"k": 1, **extra}:
                    return "map" + str(sorted(extra))
                case Point(0, y):
                    return "py" + str(y)
                case Point(x=1, y=2):
                    return "p12"
                case str() | bytes() as s:
                    return "txt" + str(len(s))
                case (a, b) if a == b:
                    return "pair"
                case Cfg.LIMIT:
                    return "limit"
                case _:
                    return "other"

        vals = [[1, 2, 3, 4], (1, 2), {"k": 1, "z": 9}, Point(0, 5), Point(1, 2),
                "abcd", (7, 7), 3, 9.5]
        print("|".join(classify(v) for v in vals))
        ''',
        "extreme",
        tags=["pattern-matching"],
    )

    code_item(
        "ms-py-groupby-tee",
        "groupby group invalidation and tee buffering",
        "Materializing groupby's groups after the fact yields empty groups; tee buffers "
        "rather than sharing.",
        "Python 3",
        '''
        import itertools

        data = [1, 1, 2, 2, 3, 1, 1]
        stale = [(k, list(g)) for k, g in list(itertools.groupby(data))]
        fresh = [(k, len(list(g))) for k, g in itertools.groupby(data)]
        t1, t2 = itertools.tee(iter(data))
        next(t1)
        head = list(itertools.islice(t2, 3))
        print(stale, fresh, head, len(list(t1)))
        ''',
        "extreme",
        tags=["itertools", "laziness"],
    )

    code_item(
        "ms-py-asyncio-scheduling",
        "asyncio task scheduling order",
        "create_task defers to the next loop iteration; gather does not reorder "
        "already-scheduled tasks.",
        "Python 3",
        '''
        import asyncio

        log = []

        async def w(n):
            log.append("s" + str(n))
            await asyncio.sleep(0)
            log.append("m" + str(n))
            await asyncio.sleep(0)
            log.append("e" + str(n))
            return n

        async def main():
            t1 = asyncio.create_task(w(1))
            log.append("created")
            t2 = asyncio.create_task(w(2))
            await asyncio.sleep(0)
            log.append("tick")
            r = await asyncio.gather(t1, t2)
            log.append("g" + str(r))

        asyncio.run(main())
        print(",".join(log))
        ''',
        "extreme",
        tags=["asyncio", "concurrency"],
    )

    code_item(
        "ms-py-singledispatch-ambiguity",
        "singledispatch over overlapping ABCs",
        "set and dict implement both Sized and Iterable with neither more specific, so "
        "dispatch raises rather than picking one. bool resolves to int, and str, bytes "
        "and range all resolve to Sequence.",
        "Python 3",
        '''
        from collections.abc import Iterable, Sequence, Sized
        from functools import singledispatch

        @singledispatch
        def go(x):
            return "obj"

        @go.register
        def _(x: Sized):
            return "sized"

        @go.register
        def _(x: Iterable):
            return "iter"

        @go.register
        def _(x: Sequence):
            return "seq"

        @go.register
        def _(x: int):
            return "int"

        out = []
        for v in [1, True, "a", [1], (1,), {1}, {1: 2}, iter([1]), 3.5, b"z", range(2)]:
            try:
                out.append(go(v))
            except RuntimeError:
                out.append("AMB")
        print(",".join(out))
        ''',
        "frontier",
        tags=["dispatch", "abcs"],
    )


# =========================================================================== #
# 2. Code reasoning -- JavaScript
# =========================================================================== #
def build_js_items() -> None:
    code_item(
        "ms-js-thenable-tick-cost",
        "Await on a thenable costs extra microtask ticks",
        "Interleaving of async functions, a plain thenable, a promise chain and "
        "queueMicrotask before the first macrotask.",
        "JavaScript (Node)",
        '''
        const log = [];
        async function a() { log.push('a1'); await null; log.push('a2'); await null; log.push('a3'); }
        async function b() { log.push('b1'); await Promise.resolve(); log.push('b2'); }
        const thenable = { then(res) { log.push('then'); res(); } };
        async function c() { log.push('c1'); await thenable; log.push('c2'); }
        a(); b(); c();
        Promise.resolve()
          .then(() => log.push('p1')).then(() => log.push('p2'))
          .then(() => log.push('p3')).then(() => log.push('p4'));
        queueMicrotask(() => log.push('q'));
        setTimeout(() => { log.push('t'); console.log(log.join(',')); }, 0);
        ''',
        "frontier",
        tags=["event-loop", "microtasks"],
    )

    code_item(
        "ms-js-to-primitive",
        "Symbol.toPrimitive overrides valueOf and toString",
        "Hint selection across +, template, *, == and String(), with a control object "
        "that has no Symbol.toPrimitive.",
        "JavaScript (Node)",
        '''
        const obj = {
          valueOf() { return 3; },
          toString() { return '7'; },
          [Symbol.toPrimitive](hint) { return hint === 'number' ? 5 : 'S'; },
        };
        const plain = { valueOf() { return 3; }, toString() { return '7'; } };
        console.log(obj + 1, String(obj), obj * 2, obj == 5, plain + 1, String(plain), plain == 3);
        ''',
        "extreme",
        tags=["coercion"],
    )

    code_item(
        "ms-js-generator-return-finally",
        "Generator return() with a yield inside finally",
        "for..of break calls return(); a yield in finally defers completion and changes "
        "the returned value.",
        "JavaScript (Node)",
        '''
        const log = [];
        function* g() { try { yield 1; yield 2; yield 3; } finally { log.push('fin'); } }
        const it = g();
        for (const v of it) { log.push(v); if (v === 2) break; }
        log.push(JSON.stringify(it.next()));
        function* h() { try { yield 1; } finally { yield 99; } }
        const it2 = h();
        it2.next();
        log.push(JSON.stringify(it2.return(5)));
        log.push(JSON.stringify(it2.next()));
        console.log(log.join(' '));
        ''',
        "frontier",
        tags=["generators"],
    )

    code_item(
        "ms-js-field-init-order",
        "Field initialization runs after super() returns",
        "A base constructor calling an overridden method observes the subclass field as "
        "undefined; static blocks run at class definition.",
        "JavaScript (Node)",
        '''
        const log = [];
        class Base { constructor() { log.push('base-ctor'); this.init(); } init() { log.push('base-init'); } }
        class Sub extends Base {
          field = (log.push('field'), 1);
          static s = log.push('static-s');
          static { log.push('static-block'); }
          init() { log.push('sub-init:' + this.field); }
        }
        new Sub();
        console.log(log.join(','));
        ''',
        "frontier",
        tags=["classes", "initialization"],
    )

    code_item(
        "ms-js-iterator-helpers",
        "Iterator helper laziness",
        "map/take pull only what they need; drop and some still consume eagerly up to "
        "their stopping point.",
        "JavaScript (Node)",
        '''
        const log = [];
        function* src() { for (let i = 1; i <= 6; i++) { log.push('y' + i); yield i; } }
        const taken = src().map((x) => { log.push('m' + x); return x * 2; }).take(2).toArray();
        log.push('T' + taken.join('/'));
        const dropped = src().drop(4).map((x) => x).toArray();
        log.push('D' + dropped.join('/'));
        log.push('S' + src().filter((x) => x % 2 === 0).some((x) => x > 3));
        console.log(log.join(','));
        ''',
        "extreme",
        tags=["iterators", "laziness"],
    )

    code_item(
        "ms-js-proxy-receiver",
        "Reflect.get receiver threading through a proxy",
        "Dropping the receiver argument makes an inherited getter read the prototype's "
        "own state; rest destructuring triggers one get per own key.",
        "JavaScript (Node)",
        '''
        const out = [];
        const base = { _v: 'base', get v() { return this._v; } };
        const child = Object.create(base);
        child._v = 'child';
        out.push(child.v);
        const noRecv = new Proxy(base, { get(t, k) { return Reflect.get(t, k); } });
        const withRecv = new Proxy(base, { get(t, k, r) { return Reflect.get(t, k, r); } });
        const c1 = Object.create(noRecv); c1._v = 'c1';
        const c2 = Object.create(withRecv); c2._v = 'c2';
        out.push(c1.v, c2.v);
        const counted = new Proxy({ a: 1, b: 2, c: 3 }, { get: (t, k) => (out.push('g:' + String(k)), t[k]) });
        const { a, ...restObj } = counted;
        out.push('a' + a, 'r' + Object.keys(restObj).join(''));
        console.log(out.join(','));
        ''',
        "frontier",
        tags=["proxy", "reflect"],
    )

    code_item(
        "ms-js-structured-clone",
        "structuredClone semantics",
        "Cycles and Map/Date survive; class prototypes do not; functions throw.",
        "JavaScript (Node)",
        '''
        const out = [];
        const cyc = { n: 1, d: new Date(0), m: new Map([['k', [1, 2]]]) };
        cyc.self = cyc;
        const c = structuredClone(cyc);
        out.push(String(c.self === c), String(c.d instanceof Date), String(c.m.get('k')[1]));
        out.push(String(c.m === cyc.m));
        class K { constructor() { this.z = 1; } }
        const ck = structuredClone(new K());
        out.push(ck.constructor.name, String(ck.z));
        try { structuredClone({ f() {} }); out.push('fn-ok'); }
        catch (e) { out.push(e.constructor.name); }
        console.log(out.join(','));
        ''',
        "extreme",
        tags=["serialization"],
    )

    code_item(
        "ms-js-copying-array-methods",
        "Copying array methods and holes",
        "toSorted/toSpliced/with leave the source intact; toReversed materializes holes "
        "as undefined.",
        "JavaScript (Node)",
        '''
        const a = [3, 1, 2];
        const sorted = a.toSorted();
        const spliced = a.toSpliced(1, 1, 'X', 'Y');
        const withed = a.with(0, 9);
        const sparse = [1, , 3];
        const rev = sparse.toReversed();
        console.log(
          JSON.stringify(a), JSON.stringify(sorted), JSON.stringify(spliced),
          JSON.stringify(withed), JSON.stringify(rev), 1 in rev, a.at(-1)
        );
        ''',
        "hard",
        tags=["arrays"],
    )

    code_item(
        "ms-js-group-by",
        "Object.groupBy versus Map.groupBy",
        "Object.groupBy returns a null-prototype object with stringified keys; "
        "Map.groupBy preserves key type and first-seen order.",
        "JavaScript (Node)",
        '''
        const items = [1, 2, 3, 4, 5, 6];
        const og = Object.groupBy(items, (x) => (x % 2 ? 'odd' : 'even'));
        const mg = Map.groupBy(items, (x) => x % 3);
        console.log(
          JSON.stringify(og),
          Object.getPrototypeOf(og) === null,
          [...mg.keys()].join(''),
          mg.get(0).join(''),
          Array.isArray(og.odd)
        );
        ''',
        "hard",
        tags=["collections"],
    )


# =========================================================================== #
# 3. Quantitative reasoning -- every answer recomputed here
# =========================================================================== #
def build_math_items() -> None:
    """Quantitative items.

    Rewritten after the first calibration run. The originals asked for a
    formula to be applied to given numbers, and a non-reasoning 35B took 6 of 7.
    Applying a known formula is not what separates models at this level;
    carrying exact state, or noticing that the reflexive formula is the wrong
    one, is. Every item here does one of those.
    """
    # -- M1: arrangements of a multiset with no two identical letters adjacent
    #    (kept: measured as a discriminator, qwen35b scored 0)
    letters = "AAABBCCD"
    brute = sum(
        1
        for p in set(itertools.permutations(letters))
        if all(p[i] != p[i + 1] for i in range(len(p) - 1))
    )

    def smirnov(counts):
        """Independent check: inclusion-exclusion over merged identical blocks."""
        total = 0
        for combo in itertools.product(*[range(1, c + 1) for c in counts]):
            ways, sign, blocks = 1, 1, 0
            for k, c in zip(combo, counts):
                ways *= math.comb(c - 1, k - 1)
                sign *= (-1) ** (c - k)
                blocks += k
            perm = math.factorial(blocks)
            for k in combo:
                perm //= math.factorial(k)
            total += sign * ways * perm
        return total

    assert brute == smirnov([3, 2, 2, 1]), (brute, smirnov([3, 2, 2, 1]))
    numeric_item(
        "ms-math-multiset-no-adjacent",
        "Multiset arrangements with no equal neighbours",
        "Inclusion-exclusion over merged blocks; brute force cross-checked.",
        "math/combinatorics",
        "extreme",
        "Consider the multiset of eight letters A, A, A, B, B, C, C, D.\n\n"
        "How many distinct arrangements of all eight letters are there in which no two "
        "adjacent letters are equal?\n\n"
        "(Arrangements are counted as distinct strings, so the three A's are "
        "interchangeable.)",
        brute,
        decimals=0,
        abs_tol=0,
    )

    # -- M2: which of two patterns appears first (Penney's game, non-transitive)
    def penney(pa, pb):
        pats = [pa, pb]
        L = max(len(pa), len(pb))
        states = {"".join(s) for k in range(L) for s in itertools.product("HT", repeat=k)}

        def step(s, ch):
            t = s + ch
            for p in pats:
                if t.endswith(p):
                    return ("WIN", pats.index(p))
            for k in range(min(len(t), L - 1), -1, -1):
                if t[len(t) - k:] in states:
                    return (t[len(t) - k:], None)
            return ("", None)

        idx = {s: i for i, s in enumerate(sorted(states))}
        n = len(idx)
        A = [[Fraction(0)] * (n + 1) for _ in range(n)]
        for s, i in idx.items():
            A[i][i] += 1
            for ch in "HT":
                nxt, who = step(s, ch)
                if nxt == "WIN":
                    if who == 0:
                        A[i][n] += Fraction(1, 2)
                else:
                    A[i][idx[nxt]] -= Fraction(1, 2)
        for col in range(n):
            piv = next(r for r in range(col, n) if A[r][col] != 0)
            A[col], A[piv] = A[piv], A[col]
            pv = A[col][col]
            A[col] = [z / pv for z in A[col]]
            for r in range(n):
                if r != col and A[r][col] != 0:
                    f = A[r][col]
                    A[r] = [z - f * y for z, y in zip(A[r], A[col])]
        return A[idx[""]][n]

    p_first = penney("THHT", "HHTT")
    assert p_first == Fraction(7, 12), p_first
    numeric_item(
        "ms-math-penney-race",
        "Which of two patterns appears first",
        "Waiting times do not decide the race; the answer needs the full Markov chain "
        "over overlap states. Comparing expected waiting times gives the wrong answer.",
        "math/probability",
        "extreme",
        "A fair coin is flipped repeatedly, producing an endless sequence of H and T.\n\n"
        "Player A wins the moment the four most recent flips read T, H, H, T in that "
        "order. Player B wins the moment the four most recent flips read H, H, T, T in "
        "that order. Whichever pattern completes first wins; the game ends there.\n\n"
        "What is the probability that player A wins?\n\n"
        "(Note: comparing the two patterns' expected waiting times does NOT answer this.)",
        float(p_first),
        decimals=4,
        abs_tol=5e-4,
    )

    # -- M3: posterior over the first coin, then a second coin drawn from the rest
    biases = [Fraction(1, 2), Fraction(7, 10), Fraction(1, 1)]
    obs = "HHTHH"

    def lik(p):
        out = Fraction(1)
        for ch in obs:
            out *= p if ch == "H" else (1 - p)
        return out

    w = [Fraction(1, 3) * lik(p) for p in biases]
    post = [x / sum(w) for x in w]
    predictive = Fraction(0)
    for i, pi in enumerate(post):
        rest = [biases[j] for j in range(3) if j != i]
        predictive += pi * (sum(rest) / 2)
    numeric_item(
        "ms-math-second-coin",
        "Predictive probability for a different coin",
        "The evidence updates which coin was drawn FIRST, which changes what remains in "
        "the drawer. The naive answer conditions the second flip on the first coin's "
        "posterior.",
        "math/probability",
        "extreme",
        "A drawer holds exactly three coins: one fair (P(heads) = 0.5), one biased with "
        "P(heads) = 0.7, and one with heads on both faces.\n\n"
        "You draw one coin uniformly at random, flip it five times, and observe in "
        "order: heads, heads, tails, heads, heads. You set that coin aside -- it does "
        "NOT go back in the drawer.\n\n"
        "You now draw one of the two REMAINING coins uniformly at random and flip it "
        "once. What is the probability that this flip lands heads?",
        float(predictive),
        decimals=4,
        abs_tol=5e-4,
    )

    # -- M4: ordered triples with a joint gcd condition
    N3 = 2 ** 4 * 3 ** 3 * 5 ** 2 * 7
    divs3 = [d for d in range(1, N3 + 1) if N3 % d == 0]
    triples = sum(
        1
        for a in divs3
        for b in divs3
        if N3 % (a * b) == 0 and math.gcd(math.gcd(a, b), N3 // (a * b)) == 1
    )
    numeric_item(
        "ms-math-gcd-triples",
        "Ordered factor triples with unit joint gcd",
        "Per prime the exponent must be split three ways with at least one part zero; "
        "the two-variable version has a clean closed form and this one does not.",
        "math/number-theory",
        "extreme",
        "How many ordered triples (a, b, c) of positive integers satisfy both\n\n"
        "    a * b * c = 75600    and    gcd(a, b, c) = 1 ?\n\n"
        "(75600 = 2^4 * 3^3 * 5^2 * 7. Ordered means (2, 3, 12600) and (3, 2, 12600) "
        "count separately.)",
        triples,
        decimals=0,
        abs_tol=0,
    )

    # -- M5: multiplicative order by prime-power lifting, combined with CRT
    MOD = 3 ** 7 * 5 ** 3

    def mult_order(a, m):
        o, x = 1, a % m
        while x != 1:
            x = x * a % m
            o += 1
        return o

    o3, o5 = mult_order(2, 3 ** 7), mult_order(2, 5 ** 3)
    order_mod = math.lcm(o3, o5)
    assert mult_order(2, MOD) == order_mod            # brute force agrees
    assert pow(2, order_mod, MOD) == 1
    numeric_item(
        "ms-math-multiplicative-order",
        "Multiplicative order modulo a composite",
        "Needs the order modulo each prime power (2 is a primitive root mod 3^k, but the "
        "order mod 5^k lifts only after 5^2) and then their lcm, not their product.",
        "math/number-theory",
        "frontier",
        "Let N = 3^7 * 5^3 = 273375.\n\n"
        "Find the smallest positive integer k such that 2^k is congruent to 1 modulo N.",
        order_mod,
        decimals=0,
        abs_tol=0,
    )

    # -- M6: circumradius of a tetrahedron in general position
    P = [(1, 0, 0), (0, 2, 1), (3, 1, 2), (2, 3, 5)]
    A = [[2 * (P[i + 1][k] - P[0][k]) for k in range(3)] for i in range(3)]
    bvec = [sum(P[i + 1][k] ** 2 - P[0][k] ** 2 for k in range(3)) for i in range(3)]
    M = [row[:] + [bvec[i]] for i, row in enumerate(A)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        M[col] = [z / pv for z in M[col]]
        for r in range(3):
            if r != col:
                f = M[r][col]
                M[r] = [z - f * y for z, y in zip(M[r], M[col])]
    centre = [M[i][3] for i in range(3)]
    circumradius = math.dist(centre, P[0])
    for q in P:
        assert abs(math.dist(centre, q) - circumradius) < 1e-9
    numeric_item(
        "ms-math-circumradius",
        "Circumradius of a tetrahedron in general position",
        "No axis is aligned, so the centre must come from solving three "
        "equidistance equations rather than from a right-corner shortcut.",
        "math/geometry",
        "extreme",
        "A tetrahedron has vertices at (1, 0, 0), (0, 2, 1), (3, 1, 2) and (2, 3, 5).\n\n"
        "Find the radius of the unique sphere passing through all four vertices.",
        circumradius,
        decimals=4,
        rel_tol=0.001,
    )

    # -- M7: determinant of the LCM matrix (no Smith-style product formula)
    size = 6
    LM = [[Fraction(math.lcm(i, j)) for j in range(1, size + 1)] for i in range(1, size + 1)]
    det = Fraction(1)
    for col in range(size):
        piv = next((r for r in range(col, size) if LM[r][col] != 0), None)
        if piv is None:
            det = Fraction(0)
            break
        if piv != col:
            LM[col], LM[piv] = LM[piv], LM[col]
            det = -det
        det *= LM[col][col]
        pv = LM[col][col]
        LM[col] = [z / pv for z in LM[col]]
        for r in range(col + 1, size):
            f = LM[r][col]
            if f:
                LM[r] = [z - f * y for z, y in zip(LM[r], LM[col])]
    numeric_item(
        "ms-math-lcm-matrix-determinant",
        "Determinant of an LCM matrix",
        "The GCD matrix has a classical product formula; the LCM matrix has no such "
        "shortcut at this size, so the determinant has to be computed.",
        "math/linear-algebra",
        "extreme",
        "Let A be the 6 x 6 matrix whose entry in row i and column j is lcm(i, j), the "
        "least common multiple, for i and j running from 1 to 6.\n\n"
        "Compute det(A).",
        int(det),
        decimals=0,
        abs_tol=0,
    )


# =========================================================================== #
# 4. Computer science -- all five rewritten as long-horizon simulations
# =========================================================================== #
def build_cs_items() -> None:
    """Every item here is an exact simulation carried over dozens of steps.

    The originals were 10-12 steps long and a non-reasoning 35B got all five.
    Length is the point: there is no closed form to jump to, so one slipped
    state update anywhere changes the answer.
    """
    # -- C1: segmented LRU over 48 accesses, 3 + 3
    ACCESSES = "AFBDCAGDBCADBCAECDCCBFDCEAADCBAAAABADBADBABEABAB"
    prob: list[str] = []
    prot: list[str] = []
    hits = 0
    for x in ACCESSES:
        if x in prot:
            prot.remove(x)
            prot.append(x)
            hits += 1
        elif x in prob:
            hits += 1
            prob.remove(x)
            prot.append(x)
            if len(prot) > 3:
                prob.append(prot.pop(0))
                if len(prob) > 3:
                    prob.pop(0)
        else:
            prob.append(x)
            if len(prob) > 3:
                prob.pop(0)
    assert hits == 26, hits
    numeric_item(
        "ms-cs-slru-hit-count",
        "Segmented LRU over a long access trace",
        "48 accesses over two ordered segments with promotion and demotion. No shortcut: "
        "the count depends on every preceding step.",
        "cs/systems",
        "extreme",
        "A segmented LRU cache has a probationary segment holding at most 3 entries and "
        "a protected segment holding at most 3 entries. The policy is:\n\n"
        "- On a miss, insert the item as most-recently-used in the probationary segment. "
        "If that overflows, evict the least-recently-used probationary entry from the "
        "cache entirely.\n"
        "- On a hit in the probationary segment, remove the item from probation and "
        "insert it as most-recently-used in the protected segment. If the protected "
        "segment overflows, demote its least-recently-used entry to the "
        "most-recently-used position of the probationary segment; if that in turn "
        "overflows, evict the least-recently-used probationary entry.\n"
        "- On a hit in the protected segment, the item simply becomes most-recently-used "
        "there.\n\n"
        "The cache starts empty. Process this access sequence left to right:\n\n"
        "    " + " ".join(ACCESSES) + "\n\n"
        "How many of the 48 accesses are hits?",
        hits,
        decimals=0,
        abs_tol=0,
    )

    # -- C2: vector clocks over 24 events and 4 processes; report the final stamp
    PROCS = ["P1", "P2", "P3", "P4"]
    EVENTS = [
        ("P1", "local", None), ("P1", "send", "a"), ("P2", "local", None),
        ("P2", "recv", "a"), ("P2", "send", "b"), ("P3", "local", None),
        ("P3", "send", "c"), ("P1", "recv", "c"), ("P4", "local", None),
        ("P4", "send", "d"), ("P3", "recv", "b"), ("P3", "send", "e"),
        ("P1", "recv", "d"), ("P1", "send", "f"), ("P4", "recv", "e"),
        ("P2", "recv", "f"), ("P2", "send", "g"), ("P4", "local", None),
        ("P4", "send", "h"), ("P3", "recv", "g"), ("P1", "recv", "h"),
        ("P3", "send", "i"), ("P4", "recv", "i"), ("P4", "local", None),
    ]
    idx = {p: i for i, p in enumerate(PROCS)}
    clocks = {p: [0, 0, 0, 0] for p in PROCS}
    sent: dict[str, list[int]] = {}
    for proc, kind, tag in EVENTS:
        if kind == "recv":
            clocks[proc] = [max(u, v) for u, v in zip(clocks[proc], sent[tag])]
        clocks[proc][idx[proc]] += 1
        if kind == "send":
            sent[tag] = list(clocks[proc])
    final = ",".join(str(v) for v in clocks["P4"])
    assert final == "5,5,6,7", final
    lines = []
    for i, (proc, kind, tag) in enumerate(EVENTS, 1):
        if kind == "local":
            lines.append(f"    {i:2d}. {proc}: local event")
        elif kind == "send":
            lines.append(f"    {i:2d}. {proc}: send message {tag}")
        else:
            lines.append(f"    {i:2d}. {proc}: receive message {tag}")
    add_prompt(
        "ms-cs-vector-clock-final",
        "Final vector clock after 24 events",
        "Four processes, nine messages, causal merges that must be propagated exactly. "
        "One missed merge changes the stamp.",
        "cs/distributed",
        "frontier",
        {
            "type": "exact",
            "canonical_answer": final,
            "accepted_aliases": [final.replace(",", ", "), "[" + final + "]",
                                 "(" + final + ")"],
            "case_sensitive": True,
            "trim_whitespace": True,
            "normalize_punctuation": False,
            "points": 100.0,
        },
        [
            {
                "role": "user",
                "content": (
                    "Four processes P1, P2, P3 and P4 each keep a vector clock over "
                    "(P1, P2, P3, P4), all starting at (0, 0, 0, 0).\n\n"
                    "Rules: on any event a process first merges (componentwise maximum) "
                    "the stamp carried by an incoming message if the event is a receive, "
                    "and then increments its OWN component by one. A message carries the "
                    "sender's stamp as of the send event. Every message is received after "
                    "it is sent.\n\n"
                    "The events happen in this global order:\n\n"
                    + "\n".join(lines)
                    + "\n\nGive the vector clock of P4 immediately after event 24.\n\n"
                    "You MUST end your reply "
                    "with a single final line in exactly this form:\n"
                    "ANSWER: a,b,c,d\n"
                    "giving the four components in order, comma separated, with no "
                    "spaces, brackets or extra words."
                ),
            }
        ],
        tags=["computed-answer"],
    )

    # -- C3: natural (run-detecting) mergesort comparison count
    ARR = [5, 9, 14, 2, 7, 11, 20, 3, 8, 1, 6, 17, 4, 12, 19, 10,
           15, 25, 13, 18, 23, 16, 21, 22, 24, 26]
    comparisons = 0
    runs: list[list[int]] = []
    cur = [ARR[0]]
    for i in range(1, len(ARR)):
        comparisons += 1
        if ARR[i] >= ARR[i - 1]:
            cur.append(ARR[i])
        else:
            runs.append(cur)
            cur = [ARR[i]]
    runs.append(cur)
    while len(runs) > 1:
        nxt: list[list[int]] = []
        for k in range(0, len(runs) - 1, 2):
            a, b = runs[k], runs[k + 1]
            out, i, j = [], 0, 0
            while i < len(a) and j < len(b):
                comparisons += 1
                if a[i] <= b[j]:
                    out.append(a[i])
                    i += 1
                else:
                    out.append(b[j])
                    j += 1
            out.extend(a[i:])
            out.extend(b[j:])
            nxt.append(out)
        if len(runs) % 2:
            nxt.append(runs[-1])
        runs = nxt
    assert runs[0] == sorted(ARR)
    numeric_item(
        "ms-cs-natural-mergesort",
        "Comparison count of run-detecting mergesort",
        "The initial runs must be found before any merging, and their uneven lengths "
        "make every later pass depend on that split.",
        "cs/algorithms",
        "frontier",
        "Natural mergesort works in two stages.\n\n"
        "Stage 1 -- run detection: scan the array once from left to right, comparing "
        "each element with its immediate predecessor (that is exactly n-1 comparisons "
        "for an array of n elements). Cut the array into maximal runs that are "
        "non-decreasing.\n\n"
        "Stage 2 -- merging: repeatedly merge adjacent runs in pairs, left to right. If "
        "the number of runs in a pass is odd, the final run is carried unchanged into "
        "the next pass. Merging two runs repeatedly compares the front element of each "
        "and emits the smaller, ties taking from the left run; once either run is "
        "exhausted the remainder of the other is emitted with no further comparisons. "
        "Repeat passes until one run remains.\n\n"
        "Run this on the 26-element array:\n\n"
        "    " + " ".join(str(x) for x in ARR) + "\n\n"
        "Counting BOTH stages, how many element-to-element comparisons are performed in "
        "total?",
        comparisons,
        decimals=0,
        abs_tol=0,
    )

    # -- C4: minimal complete DFA, two forbidden factors and a mod-7 counter
    FORBIDDEN = ["1101", "000"]
    MODULUS, TARGET = 7, 3
    maxlen = max(len(f) for f in FORBIDDEN)
    DEAD = ("DEAD", "")
    start = (0, "")
    seen = {start, DEAD}
    stack = [start]
    trans: dict = {}
    while stack:
        state = stack.pop()
        d, suf = state
        for ch in "01":
            if any(f in (suf + ch) for f in FORBIDDEN):
                nxt_state = DEAD
            else:
                nxt_state = ((d + (1 if ch == "0" else -1)) % MODULUS,
                             (suf + ch)[-maxlen:])
            trans[(state, ch)] = nxt_state
            if nxt_state not in seen:
                seen.add(nxt_state)
                stack.append(nxt_state)
    trans[(DEAD, "0")] = DEAD
    trans[(DEAD, "1")] = DEAD
    accepting = {s for s in seen if s != DEAD and s[0] == TARGET}
    part = {s: int(s in accepting) for s in seen}
    while True:
        sig = {s: (part[s], part[trans[(s, "0")]], part[trans[(s, "1")]]) for s in seen}
        groups: dict = {}
        for s in seen:
            groups.setdefault(sig[s], []).append(s)
        newpart = {}
        for i, (_, members) in enumerate(sorted(groups.items(), key=lambda kv: str(kv[0]))):
            for s in members:
                newpart[s] = i
        if len(set(newpart.values())) == len(set(part.values())):
            part = newpart
            break
        part = newpart
    min_states = len(set(part.values()))

    def in_lang(s):
        return (not any(f in s for f in FORBIDDEN)) and (
            s.count("0") - s.count("1")) % MODULUS == TARGET

    def signature(prefix, depth=9):
        return tuple(
            in_lang(prefix + "".join(suf))
            for L in range(depth + 1)
            for suf in itertools.product("01", repeat=L)
        )

    classes = {
        signature("".join(p))
        for L in range(0, 11)
        for p in itertools.product("01", repeat=L)
    }
    assert len(classes) == min_states, (len(classes), min_states)
    numeric_item(
        "ms-cs-minimal-dfa",
        "States in the minimal complete DFA",
        "A mod-7 counter crossed with a two-pattern suffix tracker; the many ways of "
        "entering the trap state all collapse to one, and several live states merge.",
        "cs/automata",
        "frontier",
        "Consider the language L over the alphabet {0, 1} consisting of exactly those "
        "strings w such that ALL of the following hold:\n\n"
        "  (a) (number of 0s in w) minus (number of 1s in w) is congruent to 3 modulo 7;\n"
        "  (b) w does not contain 1101 as a contiguous substring;\n"
        "  (c) w does not contain 000 as a contiguous substring.\n\n"
        "How many states does the MINIMAL complete deterministic finite automaton for L "
        "have? Count every state of the complete DFA, including any trap state from "
        "which no accepting state is reachable.",
        min_states,
        decimals=0,
        abs_tol=0,
    )

    # -- C5: dynamic array under an interleaved push/pop workload
    cap, size, copies = 1, 0, 0
    OPS = ["push"] * 25 + (["pop"] * 4 + ["push"] * 5) * 15 + ["pop"] * 30
    for op in OPS:
        if op == "push":
            if size == cap:
                copies += size
                cap = max(cap + 1, (cap * 3) // 2)
            size += 1
        else:
            if size == 0:
                continue
            size -= 1
            if cap > 1 and size <= cap // 4:
                copies += size
                cap = max(1, cap // 2)
    numeric_item(
        "ms-cs-dynamic-array-copies",
        "Element copies under an interleaved workload",
        "190 operations that repeatedly approach and retreat from the resize "
        "thresholds, so the capacity path cannot be summarised by the totals.",
        "cs/data-structures",
        "extreme",
        "A dynamic array starts with capacity 1 and size 0, and follows this policy:\n\n"
        "- push: if size equals capacity, first reallocate to a new capacity of "
        "max(capacity + 1, floor(capacity * 3 / 2)), copying all current elements into "
        "the new buffer; then append.\n"
        "- pop: if size is 0, do nothing. Otherwise remove the last element; then, if "
        "capacity is greater than 1 and the new size is less than or equal to "
        "floor(capacity / 4), reallocate to capacity max(1, floor(capacity / 2)), "
        "copying all remaining elements.\n\n"
        "Starting from empty, perform this exact sequence:\n\n"
        "  1. 25 pushes.\n"
        "  2. Then the following block repeated 15 times: 4 pops, then 5 pushes.\n"
        "  3. Then 30 pops.\n\n"
        "What is the total number of individual element copies performed across all "
        "reallocations?",
        copies,
        decimals=0,
        abs_tol=0,
    )


# =========================================================================== #
# 5. Science and automotive engineering
# =========================================================================== #
def build_science_items() -> None:
    """Round-2 rewrite.

    Round 1 replaced single-formula substitutions with traps -- an invalid
    approximation, a temperature-dependent Cp. qwen35b solved all four, so the
    trap is not the discriminator: this model reaches for the right formula and
    integrates correctly. What it failed everywhere else was carrying exact
    state through many stages. So each item now changes regime three or four
    times, and the output of every stage is the input to the next.
    """
    # -- S1: slip -> roll -> flat with rolling resistance, find total distance
    g = 9.81
    theta = math.radians(20.0)
    mu_k, v0 = 0.30, 5.00
    a_slip = g * (math.sin(theta) - mu_k * math.cos(theta))
    alpha_R = 2 * mu_k * g * math.cos(theta)
    assert alpha_R > a_slip
    t_roll = v0 / (alpha_R - a_slip)
    v_roll = v0 + a_slip * t_roll
    x_slip = v0 * t_roll + 0.5 * a_slip * t_roll ** 2
    a_roll = (2.0 / 3.0) * g * math.sin(theta)
    RAMP = 25.0
    assert RAMP > x_slip
    assert (1.0 / 3.0) * math.sin(theta) < mu_k * math.cos(theta)
    v_bottom = math.sqrt(v_roll ** 2 + 2 * a_roll * (RAMP - x_slip))
    # Phase 3: rolls onto level ground, decelerated by rolling resistance only.
    # For a rolling cylinder, a = C_rr * g / (1 + 1/2) = (2/3) C_rr g.
    C_rr = 0.045
    a_flat = (2.0 / 3.0) * C_rr * g
    d_flat = v_bottom ** 2 / (2 * a_flat)
    numeric_item(
        "ms-sci-three-phase-rolling",
        "Three-phase descent and run-out",
        "Slipping, then rolling on the incline, then rolling on the flat. Each phase has "
        "a different acceleration and the transition point of the first must be found "
        "before either later phase can be integrated.",
        "science/physics",
        "frontier",
        "A uniform solid cylinder (I = 1/2 m R^2 about its axis) is launched straight "
        "down a 20.0 degree incline with an initial centre-of-mass speed of 5.00 m/s and "
        "NO initial rotation. The coefficient of kinetic friction between cylinder and "
        "incline is 0.300; static friction is sufficient to sustain rolling once it "
        "begins. Take g = 9.81 m/s^2.\n\n"
        "Phase 1: the cylinder slides while friction spins it up, until it begins to "
        "roll without slipping.\n"
        "Phase 2: it then rolls without slipping for the remainder of the incline. The "
        "incline is 25.0 m long measured from the launch point.\n"
        "Phase 3: it rolls without slipping onto level ground, where it is opposed only "
        "by a rolling resistance whose coefficient is 0.045. For a rolling cylinder this "
        "gives a deceleration of (2/3) * 0.045 * g.\n\n"
        "How far, in metres, does the cylinder travel across the level ground before "
        "coming to rest?",
        d_flat,
        decimals=2,
        rel_tol=0.004,
    )

    # -- S2: two weak acids sharing one solution -> coupled proton balance
    Ka1, C1 = 1.8e-4, 1.50e-3          # acid HA
    Ka2, C2 = 6.3e-5, 2.50e-3          # acid HB
    # Charge balance: [H+] = Ka1*C1/(Ka1+[H+]) + Ka2*C2/(Ka2+[H+])   (water ignored)
    lo, hi = 1e-12, 1.0
    for _ in range(300):
        h = (lo + hi) / 2
        f = Ka1 * C1 / (Ka1 + h) + Ka2 * C2 / (Ka2 + h) - h
        if f > 0:
            lo = h
        else:
            hi = h
    h_exact = (lo + hi) / 2
    ph_two = -math.log10(h_exact)
    ph_single = -math.log10((-Ka1 + math.sqrt(Ka1 ** 2 + 4 * Ka1 * C1)) / 2)
    assert abs(ph_two - ph_single) > 0.1
    numeric_item(
        "ms-sci-coupled-diprotic-mixture",
        "pH of a mixture of two weak acids",
        "Both acids contribute to the same [H+] and each is suppressed by the other, so "
        "the proton balance is a single coupled equation. Treating them independently, "
        "or ignoring the weaker one, is wrong by more than 0.1 pH.",
        "science/chemistry",
        "frontier",
        "An aqueous solution at 25 degrees Celsius contains BOTH of the following weak "
        "monoprotic acids:\n\n"
        "    HA at 1.50 x 10^-3 M, with Ka = 1.8 x 10^-4\n"
        "    HB at 2.50 x 10^-3 M, with Ka = 6.3 x 10^-5\n\n"
        "The two acids share the same solution, so each one's dissociation is suppressed "
        "by the hydrogen ions produced by the other. Neglect the autoionisation of "
        "water, but make no other approximation that the numbers do not justify.\n\n"
        "What is the pH of the solution?",
        ph_two,
        decimals=3,
        abs_tol=0.02,
    )

    # -- S3: four-stage cycle, entropy change of the gas over the whole cycle
    n_mol, a_cp, b_cp = 2.50, 22.60, 0.02090
    R_GAS = 8.314
    TA, TB = 298.15, 675.00
    PA, PB = 100.0, 480.0

    def ds_temp(t1, t2):
        return n_mol * (a_cp * math.log(t2 / t1) + b_cp * (t2 - t1))

    def ds_press(p1, p2):
        return -n_mol * R_GAS * math.log(p2 / p1)

    s1 = ds_temp(TA, TB)                       # 1: isobaric heat at PA
    s2 = ds_press(PA, PB)                      # 2: isothermal compression at TB
    TC = 350.00
    s3 = ds_temp(TB, TC)                       # 3: isobaric cool at PB, to TC
    total_three = s1 + s2 + s3
    # Stage 3 must NOT return to the starting temperature: with TC == TA the
    # first and third contributions cancel exactly and the whole answer reduces
    # to the single pressure term, which is a much easier question than intended.
    assert abs(s1 + s3) > 5.0, (s1, s3)
    numeric_item(
        "ms-sci-cycle-entropy",
        "Entropy change across three stages of a cycle",
        "Temperature-dependent Cp on two stages and a pressure term on the third; the "
        "signs of the three contributions differ and they must be accumulated in order.",
        "science/thermodynamics",
        "frontier",
        "2.50 mol of a gas has a molar heat capacity at constant pressure that varies "
        "with temperature as\n\n"
        "    Cp(T) = 22.60 + 0.02090 * T      (J per mol per K, with T in kelvin)\n\n"
        "Treat it as an ideal gas with R = 8.314 J/(mol K). Starting at 298.15 K and "
        "100.0 kPa, it is taken reversibly through three stages:\n\n"
        "  Stage 1: heated at constant pressure (100.0 kPa) to 675.00 K.\n"
        "  Stage 2: compressed isothermally at 675.00 K from 100.0 kPa to 480.0 kPa.\n"
        "  Stage 3: cooled at constant pressure (480.0 kPa) to 350.00 K.\n\n"
        "What is the TOTAL entropy change of the gas, in J/K, from the start of stage 1 "
        "to the end of stage 3?",
        total_three,
        decimals=3,
        rel_tol=0.004,
    )

    # -- S4: three successive velocity compositions, then two timed legs
    def compose(a, b):
        return (a + b) / (1 + a * b)

    w1 = compose(0.50, 0.70)          # probe relative to station
    w2 = compose(w1, 0.40)            # dart relative to station
    LEG = 8.00
    tau_out = (LEG / w2) * math.sqrt(1 - w2 ** 2)
    w_back = compose(-0.60, -0.30)    # returning, both components toward station
    speed_back = abs(w_back)
    tau_back = (LEG / speed_back) * math.sqrt(1 - speed_back ** 2)
    tau_total = tau_out + tau_back
    numeric_item(
        "ms-sci-nested-velocity-legs",
        "Nested velocity composition over an out-and-back trip",
        "Three relativistic compositions, two of them chained, and each leg carries its "
        "own gamma. Composing in the wrong order, or adding classically anywhere, "
        "changes the answer.",
        "science/physics",
        "frontier",
        "A space station is at rest. A booster recedes from it along a straight line at "
        "0.500c. A probe is launched from the booster in the same direction at 0.700c "
        "relative to the booster. A dart is then launched from the probe, again in the "
        "same direction, at 0.400c relative to the probe.\n\n"
        "The dart travels away from the station until it is 8.00 light-years from it "
        "(measured in the station frame). It then instantly reverses. On the return leg "
        "it rides a carrier moving toward the station at 0.600c relative to the station, "
        "and the dart moves at 0.300c relative to that carrier, also toward the station. "
        "Ignore the turnaround itself.\n\n"
        "How much proper time, in years, elapses on the dart's own clock for the whole "
        "out-and-back journey?",
        tau_total,
        decimals=3,
        rel_tol=0.003,
    )


def build_automotive_items() -> None:
    # -- A3: charge air temperature (kept: measured as a discriminator)
    T1 = 28.0 + 273.15
    pr = (100.0 + 145.0) / 100.0
    gamma, eta_c, effectiveness = 1.4, 0.72, 0.78
    T2_ideal = T1 * pr ** ((gamma - 1) / gamma)
    T2 = T1 + (T2_ideal - T1) / eta_c
    T3 = T2 - effectiveness * (T2 - T1)
    numeric_item(
        "ms-auto-charge-air-temp",
        "Charge air temperature after compressor and intercooler",
        "Isentropic rise divided by compressor efficiency, then intercooler "
        "effectiveness applied against ambient rather than against zero.",
        "engineering/automotive",
        "extreme",
        "A turbocharged engine draws ambient air at 28.0 degrees Celsius and 100.0 kPa "
        "absolute. The compressor raises the pressure to 145.0 kPa GAUGE. Model the air "
        "as an ideal gas with a ratio of specific heats of 1.40; the compressor has an "
        "isentropic efficiency of 0.720.\n\n"
        "The compressed air then passes through an air-to-air intercooler whose "
        "effectiveness is 0.780, cooled by ambient air at 28.0 degrees Celsius.\n\n"
        "What is the charge air temperature, in degrees Celsius, leaving the "
        "intercooler?",
        T3,
        decimals=2,
        rel_tol=0.01,
    )


# =========================================================================== #
# 6. Abstention and false premises
# =========================================================================== #
def abstention_item(
    stable_id, title, description, tier, body, gate_pattern, checks, tags=None
):
    """An item whose credit depends on refusing to accept a planted falsehood.

    Every one carries a gate: without it an empty reply satisfies each
    "must not say X" check for free and scores full marks for silence.
    """
    add_prompt(
        stable_id,
        title,
        description,
        "abstention/false-premise",
        tier,
        {
            "checks": checks
            + [
                {
                    "type": "regex",
                    "required_patterns": [gate_pattern],
                    "case_sensitive": False,
                    "gate": True,
                    "points": 100.0,
                }
            ]
        },
        [{"role": "user", "content": textwrap.dedent(body).strip()}],
        tags=(tags or []) + ["abstention"],
    )


def build_abstention_items() -> None:
    abstention_item(
        "ms-abs-raft-byzantine",
        "False premise: Raft and Byzantine faults",
        "Raft tolerates crash faults, not Byzantine ones; the Byzantine bound is 3f+1, "
        "not 2f+1.",
        "extreme",
        """
        Our team is writing up the fault-tolerance section of a design document.

        Given that Raft requires a quorum of 2f+1 nodes in order to tolerate f
        Byzantine failures, explain precisely why the 2f+1 figure is the right one
        for Byzantine tolerance, and what a five-node Raft cluster therefore
        guarantees when two nodes are actively malicious.
        """,
        r"\braft\b",
        [
            {
                "type": "regex",
                "required_patterns": [
                    r"crash[\s\-]?(?:fault|stop|failure)|fail[\s\-]?stop|non-?byzantine|"
                    r"omission fault",
                    r"(?:not|n't|never|cannot|can't|does not|doesn't)[^.]{0,80}\bbyzantine|"
                    r"\bbyzantine\b[^.]{0,100}(?:not|n't|never|cannot|can't|assumes|outside|"
                    r"beyond|no guarantee)",
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [r"3\s*f\s*\+\s*1|3f\+1|\bpbft\b|3\s*\*\s*f\s*\+\s*1"],
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [
                    r"no (?:such )?guarantee|guarantees nothing|arbitrary(?:ly)? |"
                    r"safety (?:can be|is) violated|can be violated|breaks? down|"
                    r"undefined|not safe|loses safety"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
        tags=["distributed-systems"],
    )

    abstention_item(
        "ms-abs-nonexistent-stdlib",
        "False premise: a standard library function that does not exist",
        "There is no itertools.chunked; the real Python 3.12 addition is "
        "itertools.batched.",
        "hard",
        """
        In Python 3.12, itertools.chunked(iterable, n) splits an iterable into
        tuples of length n.

        Explain why itertools.chunked(range(7), 3) produces a final chunk of
        length 1 instead of padding it out to length 3, and show the exact
        signature that controls that padding behaviour.
        """,
        r"itertools",
        [
            {
                "type": "regex",
                "required_patterns": [
                    r"(?:no such|does ?n[o']?t exist|doesn't exist|not exist|"
                    r"is not a (?:real |valid |standard )?(?:function|attribute|member)|"
                    r"isn't a (?:real |valid |standard )?(?:function|attribute|member)|"
                    r"not part of|not in the standard library|attributeerror|"
                    r"no (?:function|attribute) (?:called|named))"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [r"\bbatched\b"],
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
        tags=["hallucination-resistance"],
    )

    # -- unsatisfiable scheduling problem, verified exhaustively
    #    5 talks, 3 slots; the stated constraints admit no assignment at all.
    talks = ["Ada", "Borg", "Cray", "Dijkstra", "Euler"]
    slots = [1, 2, 3]
    solutions = []
    for assign in itertools.product(slots, repeat=len(talks)):
        a = dict(zip(talks, assign))
        counts = {s: sum(1 for t in talks if a[t] == s) for s in slots}
        if any(c > 2 for c in counts.values()):
            continue
        if a["Ada"] == a["Borg"]:
            continue
        if a["Cray"] <= a["Ada"]:
            continue
        if a["Dijkstra"] != a["Borg"]:
            continue
        if a["Euler"] >= a["Cray"]:
            continue
        if a["Euler"] == a["Ada"]:
            continue
        solutions.append(a)
    assert not solutions, f"scheduling item is satisfiable: {solutions[:3]}"
    abstention_item(
        "ms-abs-unsatisfiable-schedule",
        "Unsatisfiable constraint problem presented as solvable",
        "Exhaustive search confirms no assignment satisfies all six constraints; the "
        "expected behaviour is to prove impossibility, not to emit a plausible schedule.",
        "extreme",
        """
        Schedule five conference talks -- Ada, Borg, Cray, Dijkstra and Euler --
        into three consecutive time slots numbered 1, 2 and 3. Every talk gets
        exactly one slot, and a slot may hold at most two talks.

        The constraints are:

          1. Ada and Borg must be in different slots.
          2. Cray must be in a strictly later slot than Ada.
          3. Dijkstra must be in the same slot as Borg.
          4. Euler must be in a strictly earlier slot than Cray.
          5. Euler must not share a slot with Ada.

        Give the assignment of talks to slots.
        """,
        r"\b(?:ada|borg|cray|dijkstra|euler)\b",
        [
            {
                "type": "regex",
                "required_patterns": [
                    r"no (?:valid |feasible |such )?(?:solution|assignment|schedule|"
                    r"arrangement)|impossible|unsatisfiable|cannot be satisfied|"
                    r"can't be satisfied|contradiction|infeasible|no way to"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                # Diagnostic language only. An earlier version also accepted
                # "slot 1"/"slot 3"/"three slots", which any fabricated schedule
                # matches -- it handed half marks to the exact failure the item
                # exists to catch.
                "type": "regex",
                "required_patterns": [
                    r"at most two|only two|two per slot|more than two|exceed|"
                    r"capacity|pigeonhole|no room|nowhere"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
        tags=["constraint-satisfaction"],
    )

    abstention_item(
        "ms-abs-underdetermined",
        "Underdetermined problem stated as if closed",
        "The heat-loss figure cannot be computed without the wall's thermal "
        "conductivity or U-value; producing a number requires inventing one.",
        "hard",
        """
        A rectangular exterior wall measures 4.20 m by 2.60 m and is 0.30 m
        thick. The inside surface is at 21.0 degrees Celsius and the outside
        surface is at -4.0 degrees Celsius, both steady.

        Compute the steady-state rate of heat loss through this wall in watts.
        """,
        r"wall|heat|conduct",
        [
            {
                "type": "regex",
                "required_patterns": [
                    r"thermal conductivity|\bk\b value|k-value|u-?value|r-?value|"
                    r"material|conductance"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [
                    r"cannot be (?:computed|determined|calculated)|can't be (?:computed|"
                    r"determined|calculated)|insufficient|not enough (?:information|data)|"
                    r"missing|need(?:s|ed)? to know|underdetermined|no unique|"
                    r"impossible to (?:compute|determine)"
                ],
                # A confident final numeric answer is the failure mode: it means a
                # conductivity was invented and then presented as given.
                "forbidden_patterns": [r"(?mi)^\s*ANSWER\s*[:=]\s*-?[\d.]+\s*$"],
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
        tags=["underspecification"],
    )

    # -- false premise about a snippet's behaviour; the true output is executed
    # The famous 0.1-summation trap, inverted. Since CPython 3.12, sum() applies
    # Neumaier compensation to floats, so the builtin lands exactly on 1.0 while
    # the hand-rolled loop -- the thing usually presented as equivalent -- does
    # not. A model reciting the familiar lesson agrees with the planted claim.
    fp_src = textwrap.dedent(
        '''
        vals = [0.1] * 10
        by_sum = sum(vals)
        acc = 0.0
        for v in vals:
            acc += v
        print(by_sum == 1.0, acc == 1.0, by_sum == acc)
        '''
    ).strip() + "\n"
    fp_answer = run_python(fp_src)
    assert fp_answer == "True False False", fp_answer
    abstention_item(
        "ms-abs-false-output-claim",
        "False premise about a program's output",
        "The prompt plants the textbook answer (False False True). Since Python 3.12 "
        "sum() is compensated, the real output inverts it.",
        "frontier",
        f"""
        A colleague reviewing this Python 3.12 program says it prints
        `False False True` -- their reasoning is that neither running total can
        represent one tenth exactly, so both comparisons against 1.0 fail while
        the two totals still agree with each other.

        ```
        {fp_src}```

        Explain what actually happens. If the claimed output is wrong, say so
        explicitly and end your reply with a single final line in exactly this
        form:
        ANSWER: <output>
        where <output> is precisely what the program prints.
        """,
        r"float|sum|binary|precision|0\.1",
        [
            {
                "type": "exact",
                "canonical_answer": fp_answer,
                "accepted_aliases": [],
                "case_sensitive": True,
                "trim_whitespace": True,
                "normalize_punctuation": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [
                    r"(?:is |claim(?:ed)? |premise |assertion )?(?:in)?correct|wrong|"
                    r"not (?:what|true)|mistaken|does ?n[o']?t print|doesn't print|"
                    r"actually prints|false"
                ],
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
        tags=["execution-verified", "premise-correction"],
    )


# =========================================================================== #
# 7. Multi-turn stateful tool use
# =========================================================================== #
HERMES_SYSTEM = (
    "You are a function-calling AI model. You are provided with function signatures "
    "within <tools></tools> XML tags. Call the appropriate function(s) to satisfy the "
    "user query. For each call, return a JSON object with the function name and "
    "arguments within <tool_call></tool_call> tags as: "
    '<tool_call>{"name": "<name>", "arguments": <args-dict>}</tool_call>. '
    "Results of previous calls are returned to you inside <tool_response></tool_response> "
    "tags. Use only the arguments defined in the schema, and follow every stated format "
    "exactly. If no provided function is relevant, or a required argument is missing, or "
    "the task should not be carried out, do NOT call any function -- reply in plain text "
    "instead."
)


def agentic_item(
    stable_id, title, description, tier, tools, turns, grader_checks, tags=None
):
    system = HERMES_SYSTEM + "\n<tools>\n" + json.dumps(tools) + "\n</tools>"
    messages = [{"role": "system", "content": system}] + turns
    add_prompt(
        stable_id,
        title,
        description,
        "agentic/multi-turn",
        tier,
        {"checks": grader_checks},
        messages,
        tags=(tags or []) + ["multi-turn", "tool-use"],
    )


def build_agentic_items() -> None:
    agentic_item(
        "ms-agent-id-propagation",
        "Disambiguate a record, then carry two of its fields forward",
        "Three near-identical matches: one is in the wrong region and one is a "
        "different person in the right region. The since-date must come from the "
        "chosen record, not from either neighbour.",
        "frontier",
        [
            {
                "name": "search_customer",
                "description": "Find customer records by free-text query.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "get_invoices",
                "description": "List invoices for a customer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {
                            "type": "string",
                            "description": "The customer_id returned by search_customer.",
                        },
                        "status": {"type": "string", "enum": ["paid", "unpaid", "all"]},
                        "since": {"type": "string", "description": "YYYY-MM-DD"},
                    },
                    "required": ["customer_id", "status", "since"],
                },
            },
        ],
        [
            {
                "role": "user",
                "content": (
                    "Pull up the account for Marisol Vega -- exact name match, she is "
                    "the one in our EU region -- and then list her unpaid invoices "
                    "dating from her last reconciliation onwards."
                ),
            },
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "search_customer", "arguments": '
                '{"query": "Marisol Vega"}}</tool_call>',
            },
            {
                "role": "user",
                "content": (
                    "<tool_response>"
                    '{"results": ['
                    '{"customer_id": "cus_2Qa41Xb", "name": "Marisol Vega", '
                    '"region": "us-east", "last_reconciled": "2026-02-11"}, '
                    '{"customer_id": "cus_7Kd92Lm", "name": "Marisol Vega", '
                    '"region": "eu-west", "last_reconciled": "2026-04-30"}, '
                    '{"customer_id": "cus_9Rt58Zc", "name": "Marisol M. Vega", '
                    '"region": "eu-west", "last_reconciled": "2026-01-05"}]}'
                    "</tool_response>"
                ),
            },
        ],
        [
            {
                "type": "tool_call",
                "expected_calls": [
                    {
                        "name": "get_invoices",
                        "arguments": {
                            "customer_id": "cus_7Kd92Lm",
                            "status": "unpaid",
                            "since": "2026-04-30",
                        },
                    }
                ],
                "strict_args": True,
                "points": 100.0,
            }
        ],
    )

    agentic_item(
        "ms-agent-error-recovery",
        "Recover from two successive tool errors cumulatively",
        "The second retry must keep the already-corrected ISO start while also fixing "
        "the timezone. Regressing the first fix is the failure mode.",
        "frontier",
        [
            {
                "name": "create_event",
                "description": "Create a calendar event.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {
                            "type": "string",
                            "description": "ISO-8601 local start time.",
                        },
                        "duration_minutes": {"type": "integer"},
                        "timezone": {
                            "type": "string",
                            "description": "IANA timezone name.",
                        },
                    },
                    "required": ["title", "start", "duration_minutes", "timezone"],
                },
            }
        ],
        [
            {
                "role": "user",
                "content": (
                    "Put 'Design sync' on the calendar for the 9th of March 2026 at 2pm "
                    "Berlin time, running 45 minutes."
                ),
            },
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "create_event", "arguments": '
                '{"title": "Design sync", "start": "March 9 2026 2:00 PM", '
                '"duration_minutes": 45, "timezone": "CET"}}</tool_call>',
            },
            {
                "role": "user",
                "content": (
                    "<tool_response>"
                    '{"error": "invalid_argument", "field": "start", "message": '
                    '"start must be ISO-8601 local time, for example 2026-01-31T09:30"}'
                    "</tool_response>"
                ),
            },
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "create_event", "arguments": '
                '{"title": "Design sync", "start": "2026-03-09T14:00", '
                '"duration_minutes": 45, "timezone": "CET"}}</tool_call>',
            },
            {
                "role": "user",
                "content": (
                    "<tool_response>"
                    '{"error": "invalid_argument", "field": "timezone", "message": '
                    '"timezone must be an IANA zone name such as America/New_York, not '
                    'an abbreviation"}'
                    "</tool_response>"
                ),
            },
        ],
        [
            {
                "type": "tool_call",
                "expected_calls": [
                    {
                        "name": "create_event",
                        "arguments": {
                            "title": "Design sync",
                            "start": {
                                "any_of": ["2026-03-09T14:00", "2026-03-09T14:00:00"]
                            },
                            "duration_minutes": 45,
                            "timezone": "Europe/Berlin",
                        },
                    }
                ],
                "strict_args": True,
                "points": 100.0,
            }
        ],
    )

    agentic_item(
        "ms-agent-selective-fanout",
        "Fan out over a two-criteria subset",
        "Six regions; only two are both active and strictly above 70 percent. The "
        "hottest region of all is decommissioned, and one sits exactly on the "
        "boundary.",
        "frontier",
        [
            {
                "name": "list_regions",
                "description": "List all configured deployment regions.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_region_status",
                "description": "Fetch live status for one region.",
                "parameters": {
                    "type": "object",
                    "properties": {"region_id": {"type": "string"}},
                    "required": ["region_id"],
                },
            },
        ],
        [
            {
                "role": "user",
                "content": (
                    "Check the current status of every active region that is running "
                    "hot -- I mean strictly above 70 percent utilisation."
                ),
            },
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "list_regions", "arguments": {}}'
                "</tool_call>",
            },
            {
                "role": "user",
                "content": (
                    # Two decommissioned regions, not one: with a single decoy a
                    # model that ignores the flag entirely still collected half
                    # marks from the grader's partial credit. With two, calling
                    # everything scores zero.
                    "<tool_response>"
                    '{"regions": ['
                    '{"region_id": "eu-west-1", "decommissioned": false, "utilization_pct": 82}, '
                    '{"region_id": "us-east-2", "decommissioned": true, "utilization_pct": 91}, '
                    '{"region_id": "ap-south-1", "decommissioned": false, "utilization_pct": 64}, '
                    '{"region_id": "sa-east-1", "decommissioned": true, "utilization_pct": 12}, '
                    '{"region_id": "af-south-1", "decommissioned": false, "utilization_pct": 77}, '
                    '{"region_id": "ca-central-1", "decommissioned": false, "utilization_pct": 70}]}'
                    "</tool_response>"
                ),
            },
        ],
        [
            {
                "type": "tool_call",
                "expected_calls": [
                    {"name": "get_region_status", "arguments": {"region_id": "eu-west-1"}},
                    {"name": "get_region_status", "arguments": {"region_id": "af-south-1"}},
                ],
                "strict_args": True,
                "allow_extra_calls": False,
                "points": 100.0,
            }
        ],
    )

    # The answer is already derivable from what came back; calling again is the error.
    agentic_item(
        "ms-agent-no-redundant-call",
        "Answer from state, applying a tiered tariff",
        "Everything needed is already in the transcript, but the tariff is banded, so "
        "a single rate multiplication gives the wrong total.",
        "extreme",
        [
            {
                "name": "get_meter_reading",
                "description": "Fetch a meter reading for a given date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "meter_id": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                    },
                    "required": ["meter_id", "date"],
                },
            },
            {
                "name": "get_tariff",
                "description": "Fetch the unit tariff in cents per kWh.",
                "parameters": {
                    "type": "object",
                    "properties": {"tariff_code": {"type": "string"}},
                    "required": ["tariff_code"],
                },
            },
        ],
        [
            {
                "role": "user",
                "content": (
                    "Meter M-4417 is on tariff RES-B. What did the electricity used "
                    "between 2026-01-01 and 2026-02-01 cost, in dollars? The tariff is "
                    "banded: the first 500 kWh bill at the first tier rate and "
                    "everything beyond that at the next tier rate."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    '<tool_call>{"name": "get_meter_reading", "arguments": '
                    '{"meter_id": "M-4417", "date": "2026-01-01"}}</tool_call>\n'
                    '<tool_call>{"name": "get_meter_reading", "arguments": '
                    '{"meter_id": "M-4417", "date": "2026-02-01"}}</tool_call>\n'
                    '<tool_call>{"name": "get_tariff", "arguments": '
                    '{"tariff_code": "RES-B"}}</tool_call>'
                ),
            },
            {
                "role": "user",
                "content": (
                    "<tool_response>"
                    '{"meter_id": "M-4417", "date": "2026-01-01", "reading_kwh": 18240.5}'
                    "</tool_response>\n"
                    "<tool_response>"
                    '{"meter_id": "M-4417", "date": "2026-02-01", "reading_kwh": 18933.0}'
                    "</tool_response>\n"
                    "<tool_response>"
                    '{"tariff_code": "RES-B", "tiers": [{"up_to_kwh": 500, '
                    '"cents_per_kwh": 12.4}, {"up_to_kwh": null, "cents_per_kwh": 16.9}]}'
                    "</tool_response>"
                ),
            },
        ],
        [
            {
                # Same reasoning as the precondition item: answering from state
                # is the whole task, so issuing a redundant call forfeits it
                # rather than costing a fraction. A non-answer makes no calls
                # either, but then earns nothing from the two scored checks.
                "type": "tool_call",
                "expect_no_calls": True,
                "gate": True,
                "points": 100.0,
            },
            {
                # 500 kWh @ 12.4c + 192.5 kWh @ 16.9c = 9453.25 cents = $94.5325
                "type": "regex",
                "required_patterns": [r"94\.53|94\.5325|\$94\b"],
                "strip_tool_calls": True,
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [r"692\.5|692\b"],
                "strip_tool_calls": True,
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
    )

    agentic_item(
        "ms-agent-precondition-refusal",
        "Withhold an action whose precondition failed",
        "The balance already returned is below the requested transfer; the correct "
        "behaviour is to not call transfer_funds and to say why.",
        "extreme",
        [
            {
                "name": "get_balance",
                "description": "Fetch the available balance of an account.",
                "parameters": {
                    "type": "object",
                    "properties": {"account_id": {"type": "string"}},
                    "required": ["account_id"],
                },
            },
            {
                "name": "transfer_funds",
                "description": (
                    "Move money between accounts. Only call this when the source "
                    "account's available balance covers the amount."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_account": {"type": "string"},
                        "to_account": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["from_account", "to_account", "amount"],
                },
            },
        ],
        [
            {
                "role": "user",
                "content": (
                    "Move 500 dollars from account ACC-1120 to account ACC-9087, but "
                    "check the balance first."
                ),
            },
            {
                "role": "assistant",
                "content": '<tool_call>{"name": "get_balance", "arguments": '
                '{"account_id": "ACC-1120"}}</tool_call>',
            },
            {
                "role": "user",
                "content": (
                    "<tool_response>"
                    '{"account_id": "ACC-1120", "available_balance": 120.50, '
                    '"currency": "USD", "pending_holds": 0}'
                    "</tool_response>"
                ),
            },
        ],
        [
            {
                # Withholding the action is a PRECONDITION, not one score
                # component among several. Measured against qwen35b this check
                # was scored rather than gated, and the model explained that the
                # balance was insufficient and then called transfer_funds for
                # the full 500 anyway -- the prose checks paid out and the item
                # returned 50. Explaining why an action is unsafe while
                # performing it is worse than useless, so it earns nothing.
                "type": "tool_call",
                "expect_no_calls": True,
                "forbidden_names": ["transfer_funds"],
                "gate": True,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [
                    r"insufficient|not enough|too low|less than|only .{0,12}120|"
                    r"short(?:fall)?|cannot cover|can't cover|exceeds"
                ],
                "strip_tool_calls": True,
                "case_sensitive": False,
                "points": 100.0,
            },
            {
                "type": "regex",
                "required_patterns": [r"120\.5|120\.50|\b120\b"],
                "strip_tool_calls": True,
                "case_sensitive": False,
                "points": 100.0,
            },
        ],
    )


# =========================================================================== #
# 8. Long-context synthesis -- corpora generated with their ground truth
# =========================================================================== #
def build_long_context_items() -> None:
    # ---- LC1: effective config default across a release history ------------
    rng = random.Random(20260801)
    keys = [
        "retry.backoff_ms", "cache.ttl_seconds", "pool.max_idle", "http.keepalive_ms",
        "index.shard_count", "auth.token_ttl_min", "queue.prefetch", "log.sample_rate",
    ]
    target_key = "retry.backoff_ms"
    versions = []
    for minor in range(0, 18):
        for patch in range(0, rng.randint(3, 5)):
            versions.append((2, minor, patch))
    entries = []
    effective: dict[str, int] = {}
    stack: dict[str, list] = {}
    history = []
    for (maj, minor, patch) in versions:
        ver = f"{maj}.{minor}.{patch}"
        lines = [f"## v{ver}"]
        n_changes = rng.randint(2, 4)
        changed = rng.sample(keys, n_changes)
        for k in changed:
            val = rng.choice([25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 750, 1000])
            kind = rng.random()
            if kind < 0.58:
                lines.append(f"- Changed default of `{k}` to {val}.")
                stack.setdefault(k, []).append((ver, effective.get(k)))
                effective[k] = val
                if k == target_key:
                    history.append((ver, val, "applied"))
            elif kind < 0.68 and stack.get(k):
                # Revert: the default goes back to whatever it was before the
                # most recent applied change. A model that only scans for the
                # last "Changed default" line reads straight past this.
                origin_ver, prior = stack[k].pop()
                lines.append(
                    f"- Reverted the v{origin_ver} change to `{k}`; the default returns "
                    f"to its previous value."
                )
                if prior is None:
                    effective.pop(k, None)
                else:
                    effective[k] = prior
                if k == target_key:
                    history.append((ver, prior, "reverted"))
            elif kind < 0.84:
                # Proposed but explicitly not shipped -- must not take effect.
                lines.append(
                    f"- PROPOSED (not shipped in this release): change `{k}` default to {val}."
                )
                if k == target_key:
                    history.append((ver, val, "proposed-only"))
            else:
                # Documentation-only correction: states a value without changing it.
                lines.append(
                    f"- Documentation fix: the reference incorrectly listed `{k}` as "
                    f"{val}; no behaviour change."
                )
                if k == target_key:
                    history.append((ver, val, "doc-only"))
        lines.append(
            f"- Internal: refactored {rng.choice(['scheduler', 'codec', 'planner', 'writer'])}"
            f" module ({rng.randint(3, 40)} files)."
        )
        entries.append("\n".join(lines))
    assert sum(1 for _, _, kind in history if kind == "applied") >= 3
    assert any(kind == "proposed-only" for _, _, kind in history)
    # The reverts must actually touch the key under test, or they are scenery.
    assert any(kind == "reverted" for _, _, kind in history), history
    # Summing all eight keys forces the whole history to be processed. Asking
    # for one key let a model scan backwards for a single line and stop; the
    # decoys and reverts on the other seven then cost it nothing.
    assert set(effective) == set(keys), sorted(set(keys) - set(effective))
    lc1_answer = sum(effective[k] for k in keys)
    corpus = "\n\n".join(entries)
    add_prompt(
        "ms-lc-config-precedence",
        "Effective default across a long release history",
        "Eight interleaved keys over 70 releases with applied changes, reverts that "
        "restore a prior value, and proposed and documentation-only decoys.",
        "long-context/synthesis",
        "extreme",
        {
            "type": "numeric",
            "expected_value": float(lc1_answer),
            "absolute_tolerance": 0.0,
            "relative_tolerance": 0.0,
            "points": 100.0,
        },
        [
            {
                "role": "user",
                "content": (
                    "Below is the complete release-note history for a service, oldest "
                    "release first.\n\n"
                    "Rules for reading it: a line only changes behaviour when it says "
                    "the default was changed. A line that REVERTS an earlier change "
                    "restores whatever the default was immediately before that earlier "
                    "change, which is not necessarily the shipped original. Lines "
                    "marked PROPOSED were never shipped, and documentation fixes "
                    "correct the reference manual without changing any default.\n\n"
                    f"{corpus}\n\n"
                    "After the final release listed above, take the effective default "
                    "value of EACH of these eight keys:\n"
                    + "".join(f"  - `{k}`\n" for k in keys)
                    + "\nWhat is the SUM of those eight values?\n\n"
                    + NUMERIC_PREAMBLE
                ),
            }
        ],
        tags=["long-context", "generated-corpus"],
    )

    # ---- LC2: ledger with retractions and amendments -----------------------
    # The question deliberately scopes to one category in one month. Asking for
    # the balance over all postings would make the item a 400-number addition
    # drill: every model fails it, for reasons that have nothing to do with
    # reading long context, and a floor item carries no information. Scoped this
    # way the whole ledger still has to be scanned -- including the adjustments,
    # which sit far below the entries they alter -- but the arithmetic at the end
    # is short enough that the score reflects retrieval rather than stamina.
    CATEGORIES = ["supplier", "payroll", "refund", "interest", "freight", "fees"]
    TARGET_CAT, TARGET_MONTH = "freight", "03"

    def make_ledger(seed):
        rng2 = random.Random(seed)
        rows, amounts, meta = [], {}, {}
        for i in range(1, 401):
            tid = f"TX-{i:04d}"
            amt = round(rng2.uniform(-900, 1400), 2)
            month = f"{rng2.randint(1, 6):02d}"
            cat = rng2.choice(CATEGORIES)
            amounts[tid] = amt
            meta[tid] = (month, cat)
            rows.append(
                f"{tid} | 2026-{month}-{rng2.randint(1, 28):02d} | "
                f"{'CREDIT' if amt >= 0 else 'DEBIT':6s} | {abs(amt):9.2f} | {cat}"
            )
        voided = set(rng2.sample(list(amounts), 30))
        for tid in sorted(voided):
            rows.append(f"ADJ | VOID {tid} | entry reversed in full, treat as never posted")
        amended = {}
        for tid in sorted(rng2.sample([t for t in amounts if t not in voided], 24)):
            new_amt = round(rng2.uniform(-900, 1400), 2)
            amended[tid] = new_amt
            rows.append(
                f"ADJ | AMEND {tid} | corrected amount is "
                f"{'CREDIT' if new_amt >= 0 else 'DEBIT'} {abs(new_amt):.2f}"
            )
        in_scope = [t for t in amounts if meta[t] == (TARGET_MONTH, TARGET_CAT)]
        selected = [t for t in in_scope if t not in voided and t not in amended]
        dropped = [t for t in in_scope if t in voided or t in amended]
        return rows, round(sum(amounts[t] for t in selected), 2), selected, dropped

    # Aim for a handful of qualifying entries: enough that the filter has to be
    # applied correctly, few enough that the sum is not the difficulty. Require
    # at least two in-scope entries to be voided or amended, otherwise those
    # rules are decoration and the item degenerates into a plain filter.
    for seed in range(4417, 4417 + 5000):
        ledger, balance, selected, dropped = make_ledger(seed)
        if 8 <= len(selected) <= 13 and len(dropped) >= 2:
            break
    else:  # pragma: no cover
        raise SystemExit("no seed produced 8-13 qualifying entries with >=2 exclusions")
    add_prompt(
        "ms-lc-ledger-reconciliation",
        "Reconcile a ledger with voids and amendments",
        "400 entries followed by 54 adjustments that void or amend earlier ids. Scoped "
        "to one category in one month so the work is retrieval, not addition.",
        "long-context/synthesis",
        "frontier",
        {
            "type": "numeric",
            "expected_value": float(balance),
            "absolute_tolerance": 0.05,
            "relative_tolerance": 0.0,
            "points": 100.0,
        },
        [
            {
                "role": "user",
                "content": (
                    "Below is a transaction ledger. Each posting line is\n"
                    "    ID | date | CREDIT or DEBIT | amount | category\n"
                    "A CREDIT counts as positive and a DEBIT counts as negative.\n\n"
                    "After the postings come adjustment lines. `VOID <id>` means that "
                    "entry never counted at all. `AMEND <id>` means that entry's amount "
                    "and direction were corrected after the fact. No entry is both "
                    "voided and amended.\n\n"
                    + "\n".join(ledger)
                    + f"\n\nConsider only the postings that are ALL of the following:\n"
                    f"  - dated in March 2026 (that is, 2026-{TARGET_MONTH}-XX)\n"
                    f"  - in the `{TARGET_CAT}` category\n"
                    f"  - neither voided nor amended by any adjustment line\n\n"
                    "What is the net total of those postings, counting CREDIT as "
                    "positive and DEBIT as negative?\n\n"
                    + NUMERIC_PREAMBLE
                    + " Round your final answer to 2 decimal places."
                ),
            }
        ],
        tags=["long-context", "generated-corpus"],
    )

    # ---- LC3: conflicting specifications under an authority order ----------
    rng3 = random.Random(99117)
    docs = []
    governing = None
    param = "handshake timeout"
    wiki_vals = [rng3.choice([15, 20, 30, 45, 60, 90]) for _ in range(4)]
    design_vals = [rng3.choice([10, 25, 35, 50, 75]) for _ in range(3)]
    # Not 42: "ANSWER: 42" is one of the canned non-answers the suite-quality
    # test probes every item with, and a numeric grader expecting 42 would pay
    # full marks for a reply that demonstrates nothing.
    rfc_val = 37
    assert rfc_val not in set(wiki_vals) | set(design_vals)
    # Authority order: RFC > design doc > wiki. The RFC states it exactly once,
    # deep inside a section that also contains two superseded drafts.
    wiki_body = []
    for i in range(1, 31):
        wiki_body.append(
            f"### Wiki note {i}\n"
            f"{rng3.choice(['Ops', 'Support', 'Field engineering', 'QA'])} observed that "
            f"the {param} is commonly set to {rng3.choice(wiki_vals)} seconds in "
            f"{rng3.choice(['staging', 'the lab', 'customer trials', 'the EU cluster'])}. "
            f"Reviewed {rng3.randint(2020, 2025)}."
        )
    design_body = []
    for i in range(1, 21):
        design_body.append(
            f"### Design section {i}\n"
            f"The transport layer negotiates in two phases. An earlier draft of this "
            f"document proposed a {param} of {rng3.choice(design_vals)} seconds; that "
            f"figure was carried over from the legacy stack and is retained here only "
            f"for historical context."
        )
    rfc_body = []
    for i in range(1, 26):
        if i == 17:
            rfc_body.append(
                f"### RFC section {i}\n"
                f"Draft-03 of this RFC specified a {param} of "
                f"{rng3.choice([8, 12, 18])} seconds; draft-05 revised it to "
                f"{rng3.choice([22, 28])} seconds. Both drafts are SUPERSEDED. "
                f"This document, at Proposed Standard, REQUIRES a {param} of "
                f"{rfc_val} seconds. Implementations MUST use this value."
            )
            governing = rfc_val
        else:
            rfc_body.append(
                f"### RFC section {i}\n"
                f"{rng3.choice(['Framing', 'Error codes', 'Versioning', 'Extensions', 'Security considerations'])} "
                f"are defined as follows. "
                + " ".join(
                    f"Field {chr(97 + j)} occupies {rng3.randint(1, 8)} octets."
                    for j in range(rng3.randint(3, 7))
                )
            )
    docs.append("# DOCUMENT A -- Team wiki (informational)\n\n" + "\n\n".join(wiki_body))
    docs.append("# DOCUMENT B -- Internal design document (draft)\n\n" + "\n\n".join(design_body))
    docs.append("# DOCUMENT C -- RFC, Proposed Standard\n\n" + "\n\n".join(rfc_body))
    # A published erratum outranks the RFC body it corrects, but only for the
    # named profile. The question asks about that profile, so a model that stops
    # at the RFC's own MUST clause reports the superseded figure.
    errata_val = rfc_val + 17
    errata_body = []
    for i in range(1, 9):
        if i == 5:
            errata_body.append(
                f"### Erratum {i} (VERIFIED)\n"
                f"Section 7 of the RFC states a {param} of {rfc_val} seconds. For "
                f"implementations operating in the constrained-link profile, and ONLY "
                f"for that profile, this value is corrected to {errata_val} seconds. "
                f"A verified erratum takes precedence over the text it corrects."
            )
        else:
            errata_body.append(
                f"### Erratum {i} (REJECTED)\n"
                f"A reporter proposed changing the {param} to "
                f"{rng3.choice([11, 19, 26, 33, 55])} seconds. This report was "
                f"classified REJECTED and has no effect."
            )
    docs.append("# DOCUMENT D -- Published errata for the RFC\n\n"
                + "\n\n".join(errata_body))
    governing = errata_val
    add_prompt(
        "ms-lc-authority-precedence",
        "Resolve conflicting specifications by authority",
        "Four documents disagree. The RFC states a MUST, but a verified erratum "
        "overrides it for the profile actually asked about.",
        "long-context/synthesis",
        "extreme",
        {
            "type": "numeric",
            "expected_value": float(governing),
            "absolute_tolerance": 0.0,
            "relative_tolerance": 0.0,
            "points": 100.0,
        },
        [
            {
                "role": "user",
                "content": (
                    "You are given four documents. When they disagree, authority runs: "
                    "a VERIFIED erratum overrides the RFC text it corrects; the RFC at "
                    "Proposed Standard overrides the internal design document; and that "
                    "overrides the team wiki. Within any single document, a value "
                    "explicitly marked as superseded, historical or REJECTED does not "
                    "govern.\n\n"
                    + "\n\n".join(docs)
                    + f"\n\nAccording to these documents, what {param}, in seconds, must "
                    "an implementation operating in the CONSTRAINED-LINK PROFILE use?\n\n"
                    + NUMERIC_PREAMBLE
                ),
            }
        ],
        tags=["long-context", "generated-corpus"],
    )

    # ---- LC4: conjunctive needle with a tie-break --------------------------
    depts = ["Platform", "Payments", "Growth", "Security", "Data", "Mobile"]
    langs = ["Go", "Rust", "Python", "TypeScript", "Java", "Kotlin"]

    def roster(seed):
        rng4 = random.Random(seed)
        rows, hits, years_map = [], [], {}
        for i in range(1, 221):
            emp = f"E-{1000 + i}"
            dept = rng4.choice(depts)
            lang = rng4.choice(langs)
            oncall = rng4.random() < 0.35
            years = rng4.randint(1, 14)
            hire = (f"20{rng4.randint(11, 25):02d}-{rng4.randint(1, 12):02d}"
                    f"-{rng4.randint(1, 28):02d}")
            rows.append(
                f"{emp} | dept={dept} | primary_language={lang} | "
                f"on_call_rotation={'yes' if oncall else 'no'} | "
                f"years_at_company={years} | hire_date={hire}"
            )
            years_map[emp] = years
            if (dept == "Payments" and lang == "Rust" and oncall and years >= 5
                    and not hire.startswith("2023")):
                hits.append((hire, emp))
        return rows, sorted(hits), years_map

    # The tie-break only measures anything if several records qualify, and the
    # item stops being a filter if too many do. Search deterministically for a
    # seed landing in that window rather than hand-tuning the probabilities.
    for seed in range(31337, 31337 + 5000):
        records, qualifying, years_by_emp = roster(seed)
        if 3 <= len(qualifying) <= 4 and len({h for h, _ in qualifying}) == len(qualifying):
            break
    else:  # pragma: no cover - would mean the generator changed shape
        raise SystemExit("no seed produced 3-4 uniquely dated qualifying records")
    # Summing over the whole qualifying set removes the early exit: a scan that
    # stops at the first match, or misses one record, gets a different number.
    lc4_answer = sum(years_by_emp[e] for _, e in qualifying)
    add_prompt(
        "ms-lc-conjunctive-needle",
        "Conjunctive filter and aggregation over 220 records",
        "Four simultaneous conditions, then a sum over the whole matching set, so a "
        "scan cannot stop at the first hit and every miss changes the total.",
        "long-context/synthesis",
        "extreme",
        {
            "type": "numeric",
            "expected_value": float(lc4_answer),
            "absolute_tolerance": 0.0,
            "relative_tolerance": 0.0,
            "points": 100.0,
        },
        [
            {
                "role": "user",
                "content": (
                    "Below is a personnel roster, one employee per line.\n\n"
                    + "\n".join(records)
                    + "\n\nConsider every employee satisfying ALL FOUR of the "
                    "following:\n"
                    "  - dept is Payments\n"
                    "  - primary_language is Rust\n"
                    "  - on_call_rotation is yes\n"
                    "  - years_at_company is 5 or more\n"
                    "  - hire_date is NOT in the year 2023\n\n"
                    "What is the SUM of years_at_company over all such employees?\n\n"
                    + NUMERIC_PREAMBLE
                ),
            }
        ],
        tags=["long-context", "generated-corpus"],
    )

    return {
        "lc1": lc1_answer,
        "lc2": balance,
        "lc3": governing,
        "lc4": lc4_answer,
        "lc4_qualifying": qualifying,
    }


# =========================================================================== #
# 9. Anchors -- hardest items lifted from the four base suites
# =========================================================================== #
ANCHOR_IDS = [
    ("code_reasoning_python.json", "cr3-generator-send"),
    ("web_dev_js.json", "wd3-number-precision-chain"),
    ("agentic_tool_use.json", "ag-nested-array-args"),
    ("instruction_following.json", "if-nested-json-array"),
]


def build_anchor_items() -> None:
    """Re-use the hardest base-suite items as low-weight calibration anchors.

    They are not here to be hard -- they are here so a run still says something
    about a model that scores zero on everything else. Their weight is the
    lowest in the suite for exactly that reason.
    """
    suites_dir = REPO / "backend" / "app" / "seed" / "suites"
    for filename, wanted in ANCHOR_IDS:
        data = json.loads((suites_dir / filename).read_text(encoding="utf-8"))
        matches = [p for p in data["prompts"] if p["stable_id"] == wanted]
        if not matches:
            raise SystemExit(
                f"anchor {wanted!r} not found in {filename}; "
                "update ANCHOR_IDS after editing a base suite"
            )
        pick = matches[0]
        add_prompt(
            "ms-anchor-" + pick["stable_id"],
            "Anchor: " + pick["title"],
            pick["description"],
            "anchor/" + pick["category"],
            "anchor",
            pick["grader_config"],
            [{"role": m["role"], "content": m["content"]} for m in pick["messages"]],
            tags=["anchor-from-base-suite"],
        )


# =========================================================================== #
# Positive controls -- proof that every item can actually be won
# =========================================================================== #
# The suite-quality test proves a non-answer scores 0. That is only half the
# guarantee: a required_pattern with a typo, or an expected_call whose argument
# spelling no model would produce, yields an item that scores 0 for *everyone*.
# Such an item is invisible -- it looks like difficulty. So every item is graded
# here against a model answer that ought to earn full marks, and the build fails
# if it does not.
#
# Items graded purely by exact/numeric/tool_call get their control constructed
# mechanically from the grader config. Prose-graded items need a written answer.
POSITIVE_CONTROLS: dict[str, str] = {
    "ms-abs-raft-byzantine": """
        The premise is wrong, so the question cannot be answered as put. Raft is a
        crash-fault tolerant (fail-stop) consensus protocol. Its 2f+1 quorum
        tolerates f *crash* failures -- nodes that stop, lose their state, or are
        partitioned away. It assumes every node that does respond follows the
        protocol honestly.

        Raft does not tolerate Byzantine failures at all. A single malicious node
        can forge AppendEntries, vote twice in a term, or lie about its log, and
        nothing in the protocol detects it -- there are no signatures and no
        cross-validation of leader claims.

        Byzantine agreement needs 3f+1 replicas to tolerate f faulty ones, which is
        the bound PBFT and its descendants are built around.

        So a five-node Raft cluster with two actively malicious members guarantees
        nothing: safety can be violated, and two colluding nodes can drive the
        cluster to commit conflicting entries or elect themselves arbitrarily.
    """,
    "ms-abs-nonexistent-stdlib": """
        The premise does not hold: there is no such function. itertools.chunked does
        not exist in Python 3.12 or in any other version -- calling it raises
        AttributeError: module 'itertools' has no attribute 'chunked'.

        You are probably thinking of one of two things. The standard library
        function added in Python 3.12 is itertools.batched(iterable, n), which
        yields tuples and whose final tuple is short rather than padded. The name
        `chunked` comes from the third-party more-itertools package.

        Since Python 3.13, batched also accepts strict=False, and there is no
        padding parameter at all -- padding is what itertools.zip_longest is for.
    """,
    "ms-abs-unsatisfiable-schedule": """
        There is no valid assignment: these constraints are contradictory, so the
        schedule you asked for cannot be produced.

        Constraint 2 forces Cray strictly after Ada, and constraint 4 forces Euler
        strictly before Cray. With only three slots, the only way to satisfy both is
        Ada and Euler in slot 1 and Cray in slot 2 or 3 -- but constraint 5 forbids
        Euler from sharing a slot with Ada.

        The alternative is Ada in slot 1 and Euler in slot 2 with Cray in slot 3.
        Then constraint 1 puts Borg somewhere other than slot 1, and constraint 3
        puts Dijkstra with Borg. Slot 2 already holds Euler and slot 3 already holds
        Cray, so the Borg/Dijkstra pair cannot fit anywhere without exceeding the
        limit of at most two talks per slot.

        Every branch dies, so the problem is unsatisfiable.
    """,
    "ms-abs-underdetermined": """
        This cannot be determined from the information given. Conduction through the
        wall follows Fourier's law, and that requires a material property that has
        not been supplied: either the thermal conductivity k of the wall material,
        or an equivalent U-value or R-value for the assembly.

        Everything else is present -- the area is 4.20 x 2.60 = 10.92 square metres,
        the thickness is 0.30 m and the temperature difference is 25.0 K -- so the
        heat loss is 10.92 * 25.0 / 0.30 * k = 910 * k watts.

        Without knowing k, the answer is not pinned down, and the range is wide:
        insulating board near 0.04 W/(m K) gives roughly 36 W, while dense concrete
        near 1.4 W/(m K) gives roughly 1270 W. Tell me the material or the U-value
        and I will finish the calculation.
    """,
    "ms-abs-false-output-claim": """
        The claimed output is wrong. Since Python 3.12, the built-in sum() uses
        Neumaier compensated summation for floats, so it tracks the rounding error
        and recovers it at the end. Summing ten copies of 0.1 with sum() therefore
        lands exactly on 1.0.

        The explicit loop gets no such help: each += rounds to the nearest double,
        and the accumulated error leaves acc at 0.9999999999999999, which is not
        equal to 1.0.

        Because the two totals differ in the last bit, by_sum == acc is also false --
        the opposite of the reasoning in the review.

        ANSWER: True False False
    """,
    "ms-agent-no-redundant-call": """
        No further calls are needed -- everything required is already in the
        readings I fetched.

        Consumption is the difference between the two meter readings:
        18933.0 - 18240.5 = 692.5 kWh.

        The RES-B tariff is banded, so the two tiers are billed separately:
          first 500 kWh at 12.4 c/kWh  = 6200.00 cents
          remaining 192.5 kWh at 16.9 c/kWh = 3253.25 cents

        Total 9453.25 cents, so the electricity used on meter M-4417 between
        2026-01-01 and 2026-02-01 cost $94.53 (94.5325 dollars before rounding).
    """,
    "ms-agent-precondition-refusal": """
        I am not going to run that transfer. The available balance on ACC-1120 is
        only 120.50 USD, which is insufficient to cover the requested 500.00 USD --
        it falls short by 379.50, and there are no pending holds to release.

        The transfer_funds tool is documented as safe to call only when the source
        account covers the amount, so calling it here would be incorrect.

        If you would like, I can move the full available 120.50 instead, or re-check
        the balance once you have funded the account.
    """,
}


# The mirror image of the positive controls. For the items that exist to catch a
# specific wrong move -- swallowing a planted premise, fabricating a schedule,
# reusing the decoy id, acting despite a failed precondition -- these are the
# confident wrong answers themselves. Each must stay well below full marks or the
# item has quietly stopped discriminating. Regressions here are silent: the suite
# still runs, the scores just stop meaning anything.
NEGATIVE_CONTROLS: dict[str, str] = {
    "ms-abs-raft-byzantine":
        "Raft needs 2f+1 nodes to tolerate f Byzantine failures because a majority "
        "quorum of 2f+1 always intersects in at least one correct node. With five "
        "nodes and two malicious members, the three honest nodes still form a "
        "quorum, so Raft remains both safe and live.",
    "ms-abs-nonexistent-stdlib":
        "itertools.chunked(range(7), 3) yields (0,1,2), (3,4,5) and (6,). The final "
        "chunk is short because chunked never pads by default; pass the fillvalue "
        "argument, itertools.chunked(iterable, n, fillvalue=None), to pad it out.",
    "ms-abs-unsatisfiable-schedule":
        "Here is a schedule that works. Slot 1: Ada and Euler. Slot 2: Borg and "
        "Dijkstra. Slot 3: Cray. Every constraint is satisfied.",
    "ms-abs-underdetermined":
        "Applying Fourier's law over the 10.92 square metre wall with a 25.0 K "
        "difference across 0.30 m of thickness gives the steady heat loss.\n"
        "ANSWER: 910.0",
    "ms-abs-false-output-claim":
        "Your colleague is right. Neither running total can represent one tenth "
        "exactly, so both comparisons against 1.0 are false, but the two totals are "
        "accumulated the same way and so agree with each other.\n"
        "ANSWER: False False True",
    "ms-agent-id-propagation":
        '<tool_call>{"name": "get_invoices", "arguments": {"customer_id": '
        '"CU-88213", "status": "unpaid"}}</tool_call>',
    "ms-agent-error-recovery":
        '<tool_call>{"name": "create_event", "arguments": {"title": "Design sync", '
        '"start": "March 9 2026 2:00 PM", "duration_minutes": 45, "timezone": '
        '"Europe/Berlin"}}</tool_call>',
    "ms-agent-selective-fanout":
        '<tool_call>{"name":"get_region_status","arguments":{"region_id":"eu-west-1"}}</tool_call>\n'
        '<tool_call>{"name":"get_region_status","arguments":{"region_id":"us-east-2"}}</tool_call>\n'
        '<tool_call>{"name":"get_region_status","arguments":{"region_id":"ap-south-1"}}</tool_call>\n'
        '<tool_call>{"name":"get_region_status","arguments":{"region_id":"sa-east-1"}}</tool_call>',
    "ms-agent-no-redundant-call":
        '<tool_call>{"name": "get_meter_reading", "arguments": {"meter_id": '
        '"M-4417", "date": "2026-02-01"}}</tool_call>',
    "ms-agent-precondition-refusal":
        '<tool_call>{"name": "transfer_funds", "arguments": {"from_account": '
        '"ACC-1120", "to_account": "ACC-9087", "amount": 500}}</tool_call>',
    # Verbatim from qwen35b, 2026-08-01. The bare call above was already caught;
    # this one is the response that actually got through -- a correct refusal
    # with the forbidden call appended, which scored 50 until the tool check was
    # made a gate. A synthetic wrong answer did not predict this shape, so the
    # measured one earns its place.
    "ms-agent-precondition-refusal/observed":
        "The available balance of ACC-1120 is $120.50, which is less than the "
        "requested transfer amount of $500. Therefore, the transfer cannot be "
        "completed.\n\n"
        '<tool_call>{"name": "transfer_funds", "arguments": {"from_account": '
        '"ACC-1120", "to_account": "ACC-9087", "amount": 500}}</tool_call>',
}

# A wrong answer may earn partial credit, but never this much.
NEGATIVE_CONTROL_CEILING = 35.0


def _mechanical_control(gc: dict) -> str | None:
    """Construct the answer a fully correct model would give, where derivable."""
    checks = gc.get("checks") or ([gc] if "type" in gc else [])
    if not checks:
        return None
    parts: list[str] = []
    for chk in checks:
        t = chk.get("type")
        if t == "exact":
            parts.append("ANSWER: " + str(chk["canonical_answer"]))
        elif t == "numeric":
            val = chk["expected_value"]
            shown = str(int(val)) if float(val).is_integer() else repr(val)
            parts.append("ANSWER: " + shown)
        elif t == "tool_call":
            if chk.get("expect_no_calls"):
                return None  # needs prose; must be written by hand
            for spec in chk.get("expected_calls", []):
                args = {}
                for k, v in (spec.get("arguments") or {}).items():
                    args[k] = v["any_of"][0] if isinstance(v, dict) and "any_of" in v else v
                parts.append(
                    "<tool_call>"
                    + json.dumps({"name": spec["name"], "arguments": args})
                    + "</tool_call>"
                )
        else:
            return None  # regex/count/concept/json -- not mechanically invertible
    return "\n".join(parts)


def verify_winnable(prompts: list[dict]) -> None:
    unwinnable, unchecked = [], []
    for p in prompts:
        sid = p["stable_id"]
        if sid.startswith("ms-anchor-"):
            continue  # provenance is the base suite that already validates them
        control = POSITIVE_CONTROLS.get(sid)
        if control is not None:
            control = textwrap.dedent(control).strip()
            mech = _mechanical_control(p["grader_config"])
            # A prose control still has to satisfy any exact/tool_call check.
            if mech and "<tool_call>" in mech:
                control = control + "\n" + mech
        else:
            control = _mechanical_control(p["grader_config"])
        if control is None:
            unchecked.append(sid)
            continue
        result = GRADER.run_deterministic(p["grader_config"], control)
        if round(result["score"], 6) < 100.0:
            failing = [
                f"{c.get('type')}={c['score']:.0f}/{c['max_score']:.0f}"
                for c in result["checks"]
                if c["score"] < c["max_score"]
            ]
            unwinnable.append(f"{sid}: scored {result['score']:.1f} ({', '.join(failing)})")
    if unchecked:
        raise SystemExit(
            "no positive control for:\n  " + "\n  ".join(unchecked)
            + "\nAdd one to POSITIVE_CONTROLS -- an item nobody can score full marks "
            "on looks exactly like a hard item."
        )
    if unwinnable:
        raise SystemExit(
            "items a fully correct answer cannot win:\n  " + "\n  ".join(unwinnable)
        )

    by_id = {p["stable_id"]: p for p in prompts}
    # "<id>/<label>" registers a second wrong answer for the same item.
    resolved = {sid: sid.split("/")[0] for sid in NEGATIVE_CONTROLS}
    missing = sorted(set(resolved.values()) - set(by_id))
    if missing:
        raise SystemExit(f"negative control for unknown item(s): {missing}")
    too_generous = []
    for sid, wrong in NEGATIVE_CONTROLS.items():
        score = GRADER.run_deterministic(by_id[resolved[sid]]["grader_config"], wrong)["score"]
        if score > NEGATIVE_CONTROL_CEILING:
            too_generous.append(f"{sid}: wrong answer scored {score:.1f}")
    if too_generous:
        raise SystemExit(
            "these items credit the mistake they exist to catch:\n  "
            + "\n  ".join(too_generous)
        )


def build_transaction_item() -> None:
    # Independent durable-state simulation; retries only deduplicate commits.
    balances = {"A": 90, "B": 40, "C": 10}
    committed = set()
    events = [
        ("k1", "A", "B", 25, True),
        ("k1", "A", "B", 25, True),
        ("k2", "B", "C", 50, False),
        ("k3", "A", "C", 70, True),
        ("k2", "B", "C", 30, True),
        ("k4", "C", "A", 15, True),
        ("k3", "A", "C", 70, True),
        ("k5", "B", "A", 10, False),
        ("k5", "B", "A", 10, True),
        ("k4", "C", "A", 15, True),
    ]
    outcomes = []
    for key, src, dst, amount, commit in events:
        if key in committed:
            outcomes.append("duplicate")
        elif balances[src] < amount:
            outcomes.append("rejected")
        elif not commit:
            outcomes.append("rollback")
        else:
            balances[src] -= amount
            balances[dst] += amount
            committed.add(key)
            outcomes.append("committed")
    assert sum(balances.values()) == 140
    assert balances == {"A": 20, "B": 25, "C": 95}
    answer = ",".join(str(balances[k]) for k in "ABC") + "|" + ",".join(sorted(committed))
    add_prompt(
        "ms-cs-transaction-replay", "Durable state after retries, rollback and lost acknowledgements",
        "Distinguish failed attempts from committed idempotency keys and recompute later preconditions.",
        "algorithms/transactions", "extreme",
        {"type": "exact", "canonical_answer": answer, "case_sensitive": True,
         "trim_whitespace": True, "normalize_punctuation": False},
        [{"role": "user", "content":
          "A transfer service starts with integer balances A=90, B=40, C=10 and no committed request keys. "
          "Process requests serially in the order below. A previously committed key returns duplicate without "
          "changing anything. Otherwise reject if the source has insufficient funds. Rejections do not record "
          "the key. Successful transactions atomically debit, credit, and record the key. A crash BEFORE commit "
          "rolls all three changes back. A lost acknowledgement AFTER commit rolls nothing back. No fees or "
          "other changes occur. A key reused after a rollback may carry corrected arguments.\n\n"
          "1. k1: A->B 25; commit, acknowledgement lost.\n"
          "2. k1: A->B 25; normal retry.\n"
          "3. k2: B->C 50; crash before commit.\n"
          "4. k3: A->C 70; normal attempt.\n"
          "5. k2: B->C 30; corrected retry, commit.\n"
          "6. k4: C->A 15; commit, acknowledgement lost.\n"
          "7. k3: A->C 70; retry, commit if allowed.\n"
          "8. k5: B->A 10; crash before commit.\n"
          "9. k5: B->A 10; retry, commit if allowed.\n"
          "10. k4: C->A 15; normal retry.\n\n"
          "Give final balances A,B,C, then |, then committed keys sorted lexicographically. "
          "End with ANSWER: <A>,<B>,<C>|<keys>, no spaces inside the value."}],
        tags=["computed-answer", "idempotency", "rollback"],
    )


# =========================================================================== #
# Assembly
# =========================================================================== #
def build() -> dict:
    PROMPTS.clear()
    build_python_items()
    build_js_items()
    build_math_items()
    build_cs_items()
    build_science_items()
    build_automotive_items()
    build_transaction_item()
    build_abstention_items()
    build_agentic_items()
    build_long_context_items()
    build_anchor_items()

    total_weight = sum(p["importance_weight"] for p in PROMPTS)
    heavy = sum(p["importance_weight"] for p in PROMPTS if p["importance_weight"] >= 3.0)
    assert heavy / total_weight >= 0.10, heavy / total_weight
    assert max(p["importance_weight"] for p in PROMPTS) / total_weight < 0.25
    assert len({p["stable_id"] for p in PROMPTS}) == len(PROMPTS), "duplicate stable_id"
    verify_winnable(PROMPTS)

    return {
        "format": "localbench-benchmark",
        "format_version": "1.0",
        "exported_at": datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat(),
        "name": SUITE_NAME,
        "description": (
            "A deliberately brutal cross-domain suite built to separate models at the "
            "top of the range. Spans extreme Python and JavaScript output prediction, "
            "quantitative reasoning, algorithms and distributed systems, physics, "
            "chemistry, automotive engineering, false-premise abstention, multi-turn "
            "stateful tool use, and long-context synthesis over generated corpora. "
            "Every answer is produced by execution or computation at build time "
            "(scripts/build_master_suite.py) -- none is hand-written. Items are graded "
            "deterministically, so no judge endpoint is required. Weights are PREDICTED, "
            "not measured: run scripts/calibrate_suite.py against two models of "
            "different capability before trusting a ranking."
        ),
        "version": SUITE_VERSION,
        "tags": ["master", "hard", "cross-domain", "deterministic"],
        "scoring_config": {},
        "performance_thresholds": {
            "desired_ttft": 1.0,
            "max_ttft": 15.0,
            "desired_tps": 25.0,
            "min_tps": 3.0,
            "max_failure_rate": 0.1,
        },
        "composite_weights": {"quality": 0.9, "reliability": 0.07, "performance": 0.03},
        "prompts": PROMPTS,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed suite matches a fresh build")
    args = ap.parse_args()

    suite = build()
    rendered = json.dumps(suite, indent=2, ensure_ascii=True) + "\n"

    if args.check:
        if not OUT.exists():
            print(f"MISSING: {OUT}", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != rendered:
            print(f"STALE: {OUT} differs from a fresh build", file=sys.stderr)
            return 1
        print(f"up to date: {OUT.relative_to(REPO)} ({len(suite['prompts'])} prompts)")
        return 0

    OUT.write_text(rendered, encoding="utf-8")
    by_tier: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for p in suite["prompts"]:
        tier = next(t for t in p["tags"] if t.startswith("tier-"))
        by_tier[tier] = by_tier.get(tier, 0) + 1
        top = p["category"].split("/")[0]
        by_cat[top] = by_cat.get(top, 0) + 1
    print(f"wrote {OUT.relative_to(REPO)}: {len(suite['prompts'])} prompts")
    print("  tiers:     ", dict(sorted(by_tier.items())))
    print("  categories:", dict(sorted(by_cat.items())))
    print(f"  total weight: {sum(p['importance_weight'] for p in suite['prompts']):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
