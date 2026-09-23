"""
Command line interface.

  vestrix build  <path> [-o vestrix.html] [--open]      interactive offline HTML
  vestrix ui     [path]                                  open the app; pick any folder in the browser
  vestrix serve  [path] [--port 8347] [--open]           live: re-analyzes on every refresh
  vestrix list   <path> [--entries]                      functions / entry points
  vestrix trace  <path> <function> <variable> [--back]   follow a value across functions
  vestrix cycles <path> [--no-fail]                      circular imports (fails CI on import-time cycles)
  vestrix json   <path> [-o graph.json]                  raw graph for other tools
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .analyzer import VERSION, Project
from .render import build_html
from .server import DEFAULT_PORT, serve


def _project(a):
    p = Project(a.path, exclude=a.exclude or (), include_source=not getattr(a, "no_source", False))
    for e in p.errors:
        print(f"  skipped (parse error): {e}", file=sys.stderr)
    return p


def _summary(p):
    s = p.stats()
    return (f"{s['modules']} modules, {s['functions']} functions, {s['classes']} classes, "
            f"{s['internal_calls']}/{s['calls']} calls resolved to project code ({s['elapsed_ms']} ms)")


def cmd_build(a):
    p = _project(a)
    out = Path(a.out).resolve()
    out.write_text(build_html(p), encoding="utf-8")
    print(f"vestrix: {_summary(p)}\nwrote {out}")
    if a.open:
        webbrowser.open(out.as_uri())
    return 0


def cmd_serve(a):
    if a.path and not Path(a.path).exists():
        raise FileNotFoundError(f"path not found: {a.path}")
    serve(a.path, host=a.host, port=a.port, open_browser=a.open, exclude=a.exclude or ())
    return 0


def cmd_list(a):
    p = _project(a)
    rows = sorted(p.funcs.items())
    if a.entries:
        rows = [(q, f) for q, f in rows if f.entry]
    for q, f in rows:
        tag = f"  [{f.entry['label']}]" if f.entry else ""
        print(f"{q:62s} {f.file}:{f.line}{tag}")
    print(f"\n{_summary(p)}", file=sys.stderr)
    return 0


def _label(p, gid):
    owner, _, local = gid.partition("::")
    f = p.funcs.get(owner)
    who = (f.cls.split(".")[-1] + "." + f.name) if f and f.cls else (f.name if f else owner.split(".")[-1])
    if local == "return":
        what = "return"
    elif local.startswith("call:"):
        text, _, line = local[5:].rpartition("@")
        what = f"{text}()  L{line}"
    elif local.startswith("attr:"):
        what = "self." + local[5:]
    else:
        what = local[4:]
    return what, who


def cmd_trace(a):
    p = _project(a)
    try:
        q = p.find(a.function)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 2
    var = a.variable
    local = "return" if var == "return" else f"var:{var}"
    start = p.gid(q, local)
    known = {n for e in p.global_flows() for n in e[:2]}
    if start not in known:
        names = sorted({n.split('::', 1)[1][4:] for n in known if n.startswith(q + "::var:")})
        print(f"'{var}' has no recorded flow in {q}. Values there: {', '.join(names) or '(none)'}", file=sys.stderr)
        return 2
    direction = "backward" if a.back else "forward"
    steps = p.trace(start, direction, limit=a.limit)
    what, who = _label(p, start)
    print(f"{direction} trace of '{what}' in {who}: {len(steps) - 1} steps\n")
    for gid, depth, via in steps:
        what, who = _label(p, gid)
        edge = f"  ◂ {via[1]} ({via[2]})" if via else ""
        print(f"{'  ' * depth}{what}   [{who}]{edge}")
    return 0


def cmd_cycles(a):
    p = _project(a)
    cycles = p.import_cycles()
    hard = [c for c in cycles if c["severity"] == "import-time"]
    if not cycles:
        print(f"no circular imports in {len(p.modules)} modules")
        return 0
    for c in cycles:
        label = "IMPORT-TIME CYCLE" if c["severity"] == "import-time" else "deferred cycle (via function-level import)"
        print(f"\n{label}: {' -> '.join(c['path'])}")
        for s in c["steps"]:
            print(f"    {s['file']}:{s['line']}  {s['from']} imports {s['to']}  [{s['kind']}]")
    print(f"\n{len(hard)} import-time, {len(cycles) - len(hard)} deferred")
    if hard:
        print("import-time cycles can fail with 'ImportError: cannot import name ... (partially initialized module)'.\n"
              "fix: move the import into the function that needs it, import the module instead of names,\n"
              "or move the shared code into a third module both can import.")
    return 1 if hard and not a.no_fail else 0


def cmd_json(a):
    p = _project(a)
    text = json.dumps(p.to_json(), indent=2, ensure_ascii=False)
    if a.out == "-":
        sys.stdout.write(text)
    else:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {Path(a.out).resolve()}")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):              # Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap =argparse.ArgumentParser(prog="vestrix", description="Interactive call-graph and data-flow explorer for Python.")
    ap.add_argument("--version", action="version", version=f"vestrix {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("path", help="project directory or a single .py file")
        sp.add_argument("--exclude", action="append", metavar="DIR", help="directory name to skip (repeatable)")
        return sp

    b = common(sub.add_parser("build", help="write a self-contained interactive HTML file"))
    b.add_argument("-o", "--out", default="vestrix.html")
    b.add_argument("--open", action="store_true", help="open it in the browser")
    b.add_argument("--no-source", action="store_true", help="don't embed source code in the HTML")
    b.set_defaults(fn=cmd_build)

    for name, hlp, auto_open in (("serve", "live server: pick any folder in the browser, re-analyzes on refresh", False),
                                 ("ui", "shortcut for `serve --open` (folder optional)", True)):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("path", nargs="?", help="folder to open first (omit to choose one in the browser)")
        s.add_argument("--exclude", action="append", metavar="DIR", help="directory name to skip (repeatable)")
        s.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"first port to try (default {DEFAULT_PORT})")
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--open", action="store_true", default=auto_open, help="open the browser")
        s.set_defaults(fn=cmd_serve)

    ls = common(sub.add_parser("list", help="list functions"))
    ls.add_argument("--entries", action="store_true", help="only entry points (routes, main, tasks, CLI, tests)")
    ls.set_defaults(fn=cmd_list)

    t = common(sub.add_parser("trace", help="follow a value across functions"))
    t.add_argument("function", help="function name or qualified name")
    t.add_argument("variable", help="parameter / variable name, or 'return'")
    t.add_argument("--back", action="store_true", help="where does it come from (instead of where it goes)")
    t.add_argument("--limit", type=int, default=200)
    t.set_defaults(fn=cmd_trace)

    cy = common(sub.add_parser("cycles", help="find circular imports (exit code 1 on import-time cycles, for CI)"))
    cy.add_argument("--no-fail", action="store_true", help="always exit 0")
    cy.set_defaults(fn=cmd_cycles)

    j = common(sub.add_parser("json", help="dump the analysis as JSON"))
    j.add_argument("-o", "--out", default="vestrix.json", help="output file, or - for stdout")
    j.set_defaults(fn=cmd_json)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except FileNotFoundError as e:
        print(f"vestrix: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
