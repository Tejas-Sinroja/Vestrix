"""
vestrix.analyzer - static analysis of a Python codebase into:

  * a call graph        (which function calls which, resolved across modules)
  * local data flow     (inside each function: params -> variables -> calls -> return)
  * global data flow    (the same, stitched across calls: argument -> callee param,
                         callee return -> caller, and self.<attr> shared across methods)

Nothing is executed; everything comes from the `ast` module.
"""
from __future__ import annotations

import ast
import builtins
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

__all__ = ["Project", "Func", "Call"]
VERSION = "0.3.1"

SKIP_DIRS = {".git", ".hg", ".svn", "venv", ".venv", "env", ".env", "__pycache__", "node_modules",
             "build", "dist", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             "site-packages", ".idea", ".vscode", ".eggs"}
SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
MUTATORS = {"append", "extend", "insert", "update", "add", "setdefault", "put", "push", "appendleft"}
BUILTINS = set(dir(builtins))
ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "route", "api_route", "websocket"}
TASK_DECOS = {"task", "shared_task", "periodic_task", "job", "actor"}
CLI_DECOS = {"command", "group", "callback"}
BRANCHES = tuple(t for t in (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler,
                             ast.comprehension, getattr(ast, "match_case", None)) if t)
MAX_FILE_CHARS = 400_000


# ============================================================================ model
@dataclass
class Call:
    text: str                       # callee as written, e.g. "self.repo.save"
    line: int
    args: list                      # [{"star": bool, "src": [local node ids]}]
    kwargs: dict                    # name -> [local node ids]
    resolved: str | None = None     # project qualname (function or class) or None if external
    bindings: list = field(default_factory=list)   # [([src ids], callee_param)]

    @property
    def node(self):
        return f"call:{self.text}@{self.line}"


@dataclass
class Func:
    qual: str
    name: str
    module: str
    file: str
    line: int
    end: int
    cls: str | None
    kind: str                       # "function" | "method" | "module"
    pos_params: list
    kw_params: list
    vararg: str | None
    kwarg: str | None
    decorators: list
    doc: str
    is_async: bool
    entry: dict | None
    complexity: int
    calls: list = field(default_factory=list)
    flows: list = field(default_factory=list)   # [(src, dst, label)] local node ids
    types: dict = field(default_factory=dict)   # var -> call text that produced it

    @property
    def params(self):
        return (self.pos_params + ([f"*{self.vararg}"] if self.vararg else []) + self.kw_params
                + ([f"**{self.kwarg}"] if self.kwarg else []))

    @property
    def param_names(self):
        return self.pos_params + [x for x in (self.vararg,) if x] + self.kw_params + [x for x in (self.kwarg,) if x]


@dataclass
class Module:
    name: str
    file: str
    is_pkg: bool
    text: str
    aliases: dict = field(default_factory=dict)
    top_names: set = field(default_factory=set)
    imports: list = field(default_factory=list)    # [(dotted target, lineno, kind)]; kind: top | lazy | typing


# ============================================================================ AST helpers
def dotted(node):
    """a.b.c -> 'a.b.c'; f().g -> 'f().g'; anything else -> None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        inner = dotted(node.func)
        if inner is None:
            return None
        parts.append(inner + "()")
    else:
        return None
    return ".".join(reversed(parts))


def walk_local(nodes):
    """Walk nodes without entering nested functions/classes/lambdas."""
    stack = [n for n in nodes if not isinstance(n, SCOPE_TYPES)]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, SCOPE_TYPES))


def store_names(t):
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, ast.Attribute):
        d = dotted(t)
        return [d] if d and "()" not in d else []
    if isinstance(t, (ast.Tuple, ast.List)):
        return [n for e in t.elts for n in store_names(e)]
    if isinstance(t, (ast.Starred, ast.Subscript)):
        return store_names(t.value)
    return []


def sources(expr, ignore):
    """Direct inputs of an expression: (variable names, outermost Call nodes)."""
    vars_, calls, stack = set(), [], [expr]
    while stack:
        n = stack.pop()
        if isinstance(n, SCOPE_TYPES):
            continue
        if isinstance(n, ast.Call):
            calls.append(n)                  # its inputs are recorded as edges into the call node
            continue
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            d = dotted(n)
            if d and d.startswith("self.") and "()" not in d:
                vars_.add(d)
                continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in ignore:
            vars_.add(n.id)
        stack.extend(ast.iter_child_nodes(n))
    return sorted(vars_), calls


def call_text(c):
    d = dotted(c.func)
    if d:
        return d
    if isinstance(c.func, ast.Attribute):
        return f"(…).{c.func.attr}"
    return "<dynamic>"


def call_id(c):
    return f"call:{call_text(c)}@{c.lineno}"


def first_str_arg(call):
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def deco_text(d):
    if isinstance(d, ast.Call):
        t = dotted(d.func) or "?"
        s = first_str_arg(d)
        return f'{t}("{s}")' if s is not None else f"{t}(…)"
    return dotted(d) or "?"


def detect_entry(node):
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        t = dotted(target) or ""
        last = t.rsplit(".", 1)[-1]
        if "." in t and last in ROUTE_METHODS:
            path = first_str_arg(d) if isinstance(d, ast.Call) else None
            verb = "ROUTE" if last in ("route", "api_route") else last.upper()
            return {"kind": "route", "label": f"{verb} {path or ''}".strip()}
        if last in TASK_DECOS:
            return {"kind": "task", "label": t}
        if "." in t and last in CLI_DECOS:
            return {"kind": "cli", "label": t}
    if node.name.startswith("test_"):
        return {"kind": "test", "label": node.name}
    if node.name == "main":
        return {"kind": "main", "label": "main()"}
    return None


def has_main_guard(tree):
    for n in tree.body:
        if isinstance(n, ast.If):
            names = {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
            consts = {x.value for x in ast.walk(n.test) if isinstance(x, ast.Constant)}
            if "__name__" in names and "__main__" in consts:
                return True
    return False


def complexity(nodes):
    c = 1
    for n in walk_local(nodes):
        if isinstance(n, BRANCHES):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
    return c


def build_func(node, qual, mod, cls, is_module=False):
    if is_module:
        pos, kw, va, ka, decos = [], [], None, None, []
        entry = {"kind": "main", "label": f"python {mod.file}"} if has_main_guard(node) else None
        line, end, name, kind, is_async = 1, max(1, mod.text.count("\n") + 1), "<module>", "module", False
    else:
        a = node.args
        pos = [x.arg for x in a.posonlyargs + a.args]
        kw = [x.arg for x in a.kwonlyargs]
        va = a.vararg.arg if a.vararg else None
        ka = a.kwarg.arg if a.kwarg else None
        decos = [deco_text(d) for d in node.decorator_list]
        entry = detect_entry(node)
        line = min([d.lineno for d in node.decorator_list] + [node.lineno])
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        name, kind = node.name, ("method" if cls else "function")
        is_async = isinstance(node, ast.AsyncFunctionDef)
    doc = (ast.get_docstring(node) or "").strip().split("\n\n")[0][:400]
    f = Func(qual, name, mod.name, mod.file, line, end, cls, kind, pos, kw, va, ka, decos, doc,
             is_async, entry, complexity(node.body))
    ignore = (set(mod.aliases) | mod.top_names | BUILTINS | {"self", "cls"}) - set(f.param_names)

    def src_ids(expr):
        vs, cs = sources(expr, ignore)
        return [f"var:{v}" for v in vs] + [call_id(c) for c in cs]

    def link(expr, dst, label):
        for s in src_ids(expr):
            f.flows.append((s, dst, label))

    for n in walk_local(node.body):
        if isinstance(n, ast.Call):
            cid = call_id(n)
            args, kwargs = [], {}
            for a in n.args:
                star = isinstance(a, ast.Starred)
                ids = src_ids(a.value if star else a)
                args.append({"star": star, "src": ids})
                for s in ids:
                    f.flows.append((s, cid, "*arg" if star else "arg"))
            for k in n.keywords:
                ids = src_ids(k.value)
                kwargs[k.arg or "**"] = ids
                for s in ids:
                    f.flows.append((s, cid, k.arg or "**kw"))
            if isinstance(n.func, ast.Attribute):
                owner = dotted(n.func.value)
                if n.func.attr in MUTATORS and owner and "()" not in owner and owner not in ignore:
                    f.flows.append((cid, f"var:{owner}", "mutates"))
                else:
                    link(n.func.value, cid, "on")
            f.calls.append(Call(call_text(n), n.lineno, args, kwargs))
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and n.value is not None:
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names = [nm for t in targets for nm in store_names(t)]
            for nm in names:
                link(n.value, f"var:{nm}", "=")
            if isinstance(n.value, ast.Call) and dotted(n.value.func):
                for nm in names:
                    f.types[nm] = dotted(n.value.func)
        elif isinstance(n, ast.Return) and n.value is not None:
            link(n.value, "return", "return")
        elif isinstance(n, (ast.Yield, ast.YieldFrom)) and n.value is not None:
            link(n.value, "return", "yield")
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            for nm in store_names(n.target):
                link(n.iter, f"var:{nm}", "each")
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars is not None:
                    for nm in store_names(item.optional_vars):
                        link(item.context_expr, f"var:{nm}", "as")
        elif isinstance(n, ast.NamedExpr):
            link(n.value, f"var:{n.target.id}", ":=")
        elif isinstance(n, ast.comprehension):
            for nm in store_names(n.target):
                link(n.iter, f"var:{nm}", "each")
    f.calls.sort(key=lambda c: c.line)
    return f


def _sccs(adj):
    """Tarjan's strongly connected components (iterative)."""
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for root in adj:
        if root in index:
            continue
        work = [(root, iter(adj.get(root, ())))]
        index[root] = low[root] = counter[0]; counter[0] += 1
        stack.append(root); on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]; counter[0] += 1
                    stack.append(w); on.add(w)
                    work.append((w, iter(adj.get(w, ()))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop(); on.discard(w); comp.append(w)
                        if w == v:
                            break
                    out.append(comp)
    return out


def _shortest_cycle(adj, start, allowed):
    """Shortest path start -> ... -> start inside one component (BFS)."""
    prev, queue = {start: None}, deque([start])
    while queue:
        u = queue.popleft()
        for w in adj.get(u, ()):
            if w not in allowed:
                continue
            if w == start:
                nodes = [u]
                while prev[nodes[-1]] is not None:
                    nodes.append(prev[nodes[-1]])
                return nodes[::-1] + [start]                  # nodes[::-1] begins with start
            if w not in prev:
                prev[w] = u
                queue.append(w)
    return [start, start]


# ============================================================================ project
class Project:
    def __init__(self, root, exclude=(), include_source=True):
        self.root = Path(root).resolve()
        if not self.root.exists():
            raise FileNotFoundError(f"path not found: {root}")
        self.base = self.root.parent if self.root.is_file() else self.root
        self.exclude = set(exclude)
        self.include_source = include_source
        self.modules: dict[str, Module] = {}
        self.funcs: dict[str, Func] = {}
        self.classes: dict[str, dict] = {}
        self.attr_types: dict[str, dict] = {}
        self.module_types: dict[str, dict] = {}     # module -> {global var: constructor text}
        self.errors: list[str] = []
        t0 = time.perf_counter()
        self._load()
        self._link()
        self.elapsed = time.perf_counter() - t0

    # -- loading ----------------------------------------------------------------
    def _files(self):
        if self.root.is_file():
            yield self.root
            return
        skip = SKIP_DIRS | self.exclude
        for p in sorted(self.root.rglob("*.py")):
            if not any(part in skip for part in p.relative_to(self.root).parts):
                yield p

    def _load(self):
        for path in self._files():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text, filename=str(path))
            except (SyntaxError, ValueError, OSError) as e:
                self.errors.append(f"{path.relative_to(self.base).as_posix()}: {e}")
                continue
            parts = list(path.relative_to(self.base).with_suffix("").parts)
            is_pkg = parts[-1] == "__init__"
            if is_pkg:
                parts = parts[:-1]
            name = ".".join(parts) or self.base.name
            mod = Module(name, path.relative_to(self.base).as_posix(), is_pkg, text)
            self._imports(mod, tree)
            mod.top_names = {n.name for n in tree.body if isinstance(n, (*FUNC_TYPES, ast.ClassDef))}
            self.modules[name] = mod
            top = build_func(tree, f"{name}.<module>", mod, None, is_module=True)
            self.module_types[name] = {k: v for k, v in top.types.items() if "." not in k}
            if top.calls:
                self.funcs[top.qual] = top
            self._collect(tree, name, mod, None)

    def _imports(self, mod, tree):
        pkg = mod.name.split(".") if mod.is_pkg else mod.name.split(".")[:-1]
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:
                        mod.aliases[a.asname] = a.name
                    else:
                        head = a.name.split(".")[0]
                        mod.aliases[head] = head
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = pkg[: max(0, len(pkg) - (n.level - 1))]
                    src = ".".join(base + ([n.module] if n.module else []))
                else:
                    src = n.module or ""
                for a in n.names:
                    if a.name != "*":
                        mod.aliases[a.asname or a.name] = f"{src}.{a.name}" if src else a.name
        self._import_edges(mod, tree, pkg)

    @staticmethod
    def _is_type_checking(test):
        return any((isinstance(x, ast.Name) and x.id == "TYPE_CHECKING")
                   or (isinstance(x, ast.Attribute) and x.attr == "TYPE_CHECKING") for x in ast.walk(test))

    def _import_edges(self, mod, tree, pkg):
        """Record every import with *when* it runs: at import time (top), inside a function (lazy),
        or only for type checkers (typing). Only 'top' imports can cause import-time cycles."""
        def visit(node, kind):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (*FUNC_TYPES, ast.Lambda)):
                    visit(ch, "lazy" if kind == "top" else kind)
                elif isinstance(ch, ast.If) and self._is_type_checking(ch.test):
                    for s in ch.body:
                        visit_stmt(s, "typing")
                    for s in ch.orelse:
                        visit_stmt(s, kind)
                else:
                    visit_stmt(ch, kind)

        def visit_stmt(ch, kind):
            if isinstance(ch, ast.Import):
                for a in ch.names:
                    mod.imports.append((a.name, ch.lineno, kind))
            elif isinstance(ch, ast.ImportFrom):
                if ch.level:
                    base = pkg[: max(0, len(pkg) - (ch.level - 1))]
                    src = ".".join(base + ([ch.module] if ch.module else []))
                else:
                    src = ch.module or ""
                for a in ch.names:
                    target = f"{src}.{a.name}" if src and a.name != "*" else src or a.name
                    mod.imports.append((target, ch.lineno, kind))
            if isinstance(ch, (*FUNC_TYPES, ast.Lambda)):
                visit(ch, "lazy" if kind == "top" else kind)
            elif isinstance(ch, ast.AST):
                visit(ch, kind)

        visit(tree, "top")

    def _collect(self, node, prefix, mod, cls):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, FUNC_TYPES):
                q = f"{prefix}.{ch.name}"
                self.funcs[q] = build_func(ch, q, mod, cls)
                if cls:
                    self.classes[cls]["methods"].append(q)
                self._collect(ch, q, mod, None)
            elif isinstance(ch, ast.ClassDef):
                q = f"{prefix}.{ch.name}"
                self.classes[q] = {"module": mod.name, "file": mod.file, "line": ch.lineno, "scope": prefix,
                                   "bases_text": [dotted(b) for b in ch.bases if dotted(b)],
                                   "bases": [], "methods": [],
                                   "doc": (ast.get_docstring(ch) or "").strip().split("\n\n")[0][:400]}
                self._collect(ch, q, mod, q)
            elif isinstance(ch, ast.stmt):
                self._collect(ch, prefix, mod, cls)

    def _link(self):
        for q, c in self.classes.items():
            ctx = SimpleNamespace(module=c["module"], qual=c["scope"], cls=None, types={})
            c["bases"] = [r for r in (self._lookup(ctx, b) for b in c["bases_text"]) if r in self.classes]
        for f in self.funcs.values():
            if f.cls:
                for k, v in f.types.items():
                    if k.startswith("self."):
                        self.attr_types.setdefault(f.cls, {})[k] = v
        for f in self.funcs.values():
            for call in f.calls:
                call.resolved = self.resolve(f, call.text)
                if call.resolved in self.funcs:
                    call.bindings = self._bind(f, call)

    # -- resolution -------------------------------------------------------------
    def _canonical(self, name):
        """Follow re-exports: pkg.Name where pkg/__init__ does `from .mod import Name`."""
        for _ in range(6):
            if name in self.funcs or name in self.classes:
                return name
            parts = name.split(".")
            for i in range(len(parts) - 1, 0, -1):
                m = self.modules.get(".".join(parts[:i]))
                if m and parts[i] in m.aliases:
                    name = ".".join([m.aliases[parts[i]]] + parts[i + 1:])
                    break
            else:
                return name
        return name

    def _mro(self, cls_q):
        seen, queue, out = set(), deque([cls_q]), []
        while queue:
            c = queue.popleft()
            if c in seen or c not in self.classes:
                continue
            seen.add(c)
            out.append(c)
            queue.extend(self.classes[c]["bases"])
        return out

    def _member(self, cls_q, name):
        for c in self._mro(cls_q):
            if f"{c}.{name}" in self.funcs:
                return f"{c}.{name}"
        return None

    def _attr_type(self, cls_q, obj):
        for c in self._mro(cls_q):
            t = self.attr_types.get(c, {}).get(obj)
            if t:
                return t
        return None

    def _lookup(self, ctx, text, depth=0):
        if depth > 3 or not text or text.startswith("<") or text.startswith("(…)"):
            return None
        if text.startswith("super()."):
            name = text[len("super()."):]
            if ctx.cls and "." not in name:
                for b in self.classes.get(ctx.cls, {}).get("bases", []):
                    m = self._member(b, name)
                    if m:
                        return m
            return None
        if "()" in text:
            return None
        parts = text.split(".")
        head, rest = parts[0], parts[1:]
        mod = self.modules[ctx.module]
        cands = []
        if head in ("self", "cls") and ctx.cls:
            cands.append(".".join([ctx.cls] + rest) if rest else ctx.cls)
        cands.append(f"{ctx.qual}.{text}")
        if head in mod.top_names or head in self.module_types.get(ctx.module, {}):
            cands.append(f"{ctx.module}.{text}")
        if head in mod.aliases:
            cands.append(".".join([mod.aliases[head]] + rest))
        for i in range(len(parts) - 1, 0, -1):          # x = Cls(); x.method()
            obj = ".".join(parts[:i])
            typ = ctx.types.get(obj) or (self._attr_type(ctx.cls, obj) if ctx.cls else None)
            if typ and typ != text:
                tq = self._lookup(ctx, typ, depth + 1)
                if tq:
                    cands.append(".".join([tq] + parts[i:]))
                break
        for c in cands:
            c = self._canonical(c)
            if c in self.funcs or c in self.classes:
                return c
            owner, _, last = c.rpartition(".")
            if owner in self.classes:
                m = self._member(owner, last)
                if m:
                    return m
            r = self._via_module_var(c, depth)
            if r:
                return r
        return None

    def _via_module_var(self, name, depth):
        """pkg.mod.router.post where `router = Router()` at module level -> Router.post."""
        parts = name.split(".")
        for i in range(len(parts) - 1, 0, -1):
            m = ".".join(parts[:i])
            if m not in self.modules:
                continue
            typ = self.module_types.get(m, {}).get(parts[i])
            if not typ:
                return None
            mctx = SimpleNamespace(module=m, qual=f"{m}.<module>", cls=None, types=self.module_types[m])
            tq = self._lookup(mctx, typ, depth + 1)
            if tq and i + 1 < len(parts):
                c = self._canonical(".".join([tq] + parts[i + 1:]))
                if c in self.funcs or c in self.classes:
                    return c
                owner, _, last = c.rpartition(".")
                if owner in self.classes:
                    return self._member(owner, last)
            return None
        return None

    def resolve(self, f, text):
        """Map call text to a project qualname, or None when external/unknown."""
        q = self._lookup(f, text)
        if q in self.classes:
            return self._member(q, "__init__") or q
        return q

    def _bind(self, f, call):
        """Map a call's arguments onto the callee's parameters."""
        g = self.funcs[call.resolved]
        is_static = any(d.split("(")[0].endswith("staticmethod") for d in g.decorators)
        is_classm = any(d.split("(")[0].endswith("classmethod") for d in g.decorators)
        skip = g.kind == "method" and not is_static
        owner = call.text.rpartition(".")[0]
        if (skip and owner and owner not in ("self", "cls") and g.name != "__init__" and not is_classm
                and not owner.startswith("super()")):
            if self._lookup(f, owner) in self.classes:
                skip = False                      # Base.method(self, x): self passed explicitly
        pos = g.pos_params[1:] if skip else list(g.pos_params)
        out = []
        for i, a in enumerate(call.args):
            if a["star"]:
                break
            if i < len(pos):
                out.append((a["src"], pos[i]))
            elif g.vararg:
                out.append((a["src"], g.vararg))
        for k, ids in call.kwargs.items():
            if k != "**" and k in g.param_names:
                out.append((ids, k))
            elif g.kwarg:
                out.append((ids, g.kwarg))
        return [(ids, p) for ids, p in out if ids]

    # -- graphs -----------------------------------------------------------------
    def gid(self, q, local):
        f = self.funcs[q]
        if f.cls and local.startswith("var:self."):
            return f"{f.cls}::attr:{local[len('var:self.'):]}"
        return f"{q}::{local}"

    def global_flows(self):
        """Whole-program value-flow edges: (src_gid, dst_gid, label, kind)."""
        if hasattr(self, "_gflows"):
            return self._gflows
        out = []
        returns = {q for q, f in self.funcs.items() if any(d == "return" for _, d, _ in f.flows)}
        for q, f in self.funcs.items():
            bound = defaultdict(set)                 # call node -> sources consumed by bindings
            for c in f.calls:
                if c.resolved in self.funcs:
                    for ids, _ in c.bindings:
                        bound[c.node].update(ids)
            for s, d, lab in dict.fromkeys(f.flows):
                if s in bound.get(d, ()):
                    continue                         # replaced by precise arg -> param edge
                out.append((self.gid(q, s), self.gid(q, d), lab, "local"))
            for c in f.calls:
                if c.resolved not in self.funcs:
                    continue
                cid = self.gid(q, c.node)
                for ids, p in c.bindings:
                    for s in ids:
                        out.append((self.gid(q, s), self.gid(c.resolved, f"var:{p}"), p, "param"))
                if c.resolved in returns:
                    out.append((self.gid(c.resolved, "return"), cid, "returns", "return"))
        self._gflows = list(dict.fromkeys(out))
        return self._gflows

    def trace(self, start, direction="forward", limit=400):
        """BFS over global flows. Returns [(gid, depth, (prev_gid, label, kind) | None)]."""
        adj = defaultdict(list)
        for s, d, lab, kind in self.global_flows():
            if direction == "forward":
                adj[s].append((d, lab, kind))
            else:
                adj[d].append((s, lab, kind))
        seen = {start: (0, None)}
        order, queue = [start], deque([start])
        while queue and len(order) < limit:
            n = queue.popleft()
            for m, lab, kind in adj.get(n, []):
                if m not in seen:
                    seen[m] = (seen[n][0] + 1, (n, lab, kind))
                    order.append(m)
                    queue.append(m)
        return [(n, *seen[n]) for n in order]

    def module_of(self, name):
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            m = ".".join(parts[:i])
            if m in self.modules:
                return m
        return None

    def module_deps(self):
        return {m: sorted(edges) for m, edges in self.import_graph().items()}

    def import_graph(self):
        """module -> {imported project module: (line, kind)}; the strongest kind wins (top > lazy > typing)."""
        if hasattr(self, "_igraph"):
            return self._igraph
        rank = {"top": 0, "lazy": 1, "typing": 2}
        g = {}
        for m in self.modules.values():
            edges = {}
            for target, line, kind in m.imports:
                t = self.module_of(target)
                if not t or t == m.name:
                    continue
                if t not in edges or rank[kind] < rank[edges[t][1]]:
                    edges[t] = (line, kind)
            g[m.name] = edges
        self._igraph = g
        return g

    def import_cycles(self):
        """Circular imports. 'import-time' cycles use only module-level imports and can fail with
        'partially initialized module'; 'deferred' cycles only close through function-level imports."""
        g = self.import_graph()
        found, seen = [], set()
        for kinds, severity in (({"top"}, "import-time"), ({"top", "lazy"}, "deferred")):
            adj = {m: [t for t, (_, k) in e.items() if k in kinds] for m, e in g.items()}
            for comp in _sccs(adj):
                if len(comp) < 2:
                    continue
                key = frozenset(comp)
                if key in seen:
                    continue
                seen.add(key)
                path = _shortest_cycle(adj, sorted(comp)[0], set(comp))
                steps = [{"from": a, "to": b, "line": g[a][b][0], "kind": g[a][b][1],
                          "file": self.modules[a].file} for a, b in zip(path, path[1:])]
                found.append({"severity": severity, "modules": sorted(comp), "path": path, "steps": steps})
        return found

    def libraries(self):
        """Third-party packages the project imports -> modules that import them."""
        std = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
        used = defaultdict(set)
        for m in self.modules.values():
            for target in m.aliases.values():
                top = target.split(".")[0]
                if top and top not in std and top not in self.modules and not self.module_of(target):
                    used[top].add(m.name)
        return {k: sorted(v) for k, v in sorted(used.items(), key=lambda kv: (-len(kv[1]), kv[0]))}

    def find(self, name):
        if name in self.funcs:
            return name
        if f"{name}.<module>" in self.funcs:
            return f"{name}.<module>"
        hits = [q for q in self.funcs if q.endswith("." + name)]
        if len(hits) == 1:
            return hits[0]
        msg = "not found" if not hits else "is ambiguous: " + ", ".join(sorted(hits))
        raise LookupError(f"'{name}' {msg}")

    def stats(self):
        calls = [c for f in self.funcs.values() for c in f.calls]
        internal = sum(1 for c in calls if c.resolved)
        return {"modules": len(self.modules), "functions": sum(1 for f in self.funcs.values() if f.kind != "module"),
                "classes": len(self.classes), "calls": len(calls), "internal_calls": internal,
                "lines": sum(m.text.count("\n") + 1 for m in self.modules.values()),
                "elapsed_ms": round(self.elapsed * 1000)}

    def to_json(self):
        deps = self.module_deps()
        funcs = {}
        for q, f in self.funcs.items():
            funcs[q] = {"name": f.name, "module": f.module, "cls": f.cls, "kind": f.kind, "file": f.file,
                        "line": f.line, "end": f.end, "params": f.params, "decorators": f.decorators,
                        "doc": f.doc, "async": f.is_async, "entry": f.entry, "complexity": f.complexity,
                        "calls": [{"text": c.text, "line": c.line, "resolved": c.resolved,
                                   "binds": [p for _, p in c.bindings]} for c in f.calls],
                        "flows": [list(x) for x in dict.fromkeys(f.flows)]}
        files = {}
        if self.include_source:
            for m in self.modules.values():
                files[m.file] = m.text if len(m.text) <= MAX_FILE_CHARS else m.text[:MAX_FILE_CHARS]
        return {
            "meta": {"root": str(self.root), "name": self.root.name, "version": VERSION,
                     "generated": time.strftime("%Y-%m-%d %H:%M"), "stats": self.stats(),
                     "libraries": self.libraries(), "exclude": sorted(self.exclude), "served": False},
            "modules": {n: {"file": m.file, "pkg": m.is_pkg, "lines": m.text.count("\n") + 1,
                            "imports": deps[n],
                            "import_info": {t: {"line": ln, "kind": k} for t, (ln, k) in self.import_graph()[n].items()}}
                        for n, m in self.modules.items()},
            "cycles": self.import_cycles(),
            "classes": {q: {k: c[k] for k in ("module", "file", "line", "bases", "bases_text", "methods", "doc")}
                        for q, c in self.classes.items()},
            "functions": funcs,
            "gflows": [list(x) for x in self.global_flows()],
            "files": files,
            "errors": self.errors,
        }
