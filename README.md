# codeflow

Interactive explorer that helps developers understand **how a Python codebase fits together and how data moves through it**.
Point it at a repo and get a single offline HTML app, or a live server, with four linked views:

| View | Answers | How to use |
|---|---|---|
| **Calls** | "When this runs, what else runs? Who calls it?" | Adjust caller/callee depth, toggle library calls, **find the call path** between two functions |
| **Data flow** | "Inside this function, where does each value come from and go?" | Params → variables → calls → return. Double-click a yellow call to step into it |
| **Trace** | "If I change this value, what does it affect across the whole program?" | Click any value in Data flow → *Where does it go?* / *Where does it come from?* |
| **Modules** | "How are the files wired together?" | Import graph; click for imports / imported-by / contents |

The side panel shows the signature, docstring, callers, callees, library calls, complexity, and **highlighted source**,
plus an *Open in VS Code* link. The sidebar lists detected **entry points** (HTTP routes, `__main__` scripts, CLI commands,
Celery-style tasks, tests) and **insights** (most-called, most-complex, never-called functions).

## Quick start

```bash
cd D:\Project\codeflow
python -m codeflow ui                                      # opens the app with a folder picker
python -m codeflow ui D:\Project\RangeBreak                # or start with a folder
python -m codeflow build path/to/your/repo -o flow.html --open   # one offline file to share
```

**Easiest on Windows:** double-click `codeflow.bat` (or drag a project folder onto it). It starts the app on
`http://127.0.0.1:8347` (and moves to the next port if that one is busy), then opens your browser.

### Choosing a folder

Click the folder button in the header (or press `O`). It works in both kinds of page:

**Opened as an HTML file** (for example `examples/sample_shop.html`):

- **Choose folder…**: pick any folder. The browser reads the `.py` files and runs the same analyzer on the page
  (Python compiled to WebAssembly, using Pyodide). Nothing is uploaded. The first time, it downloads the ~10 MB runtime,
  which is then cached. Needs Edge, Chrome or another Chromium browser; Firefox uses the upload-style folder picker.
- **Folder path**: paste a path such as `D:\Project\RangeBreak`. If the local app is running, the page opens that path
  in the app. If it isn't, the path is kept for "Open in VS Code" links when you choose the folder.

**Running the local app** (`codeflow.bat` / `python -m codeflow ui`), the picker lets you:

- type or paste a path, or use **Browse…** for the normal Windows folder dialog
- browse drives, Home, the current directory, and **recently opened** projects
- see what's in each folder before you open it: `.py` count and markers like `git`, `pyproject`, `requirements`,
  `uv`, `poetry`, `django`, `docker`, `package`
- skip extra folders (for example `tests, migrations`); `.venv`, `__pycache__`, `node_modules`, etc. are always skipped

After a folder is analyzed, the **Detected** section in the sidebar lists the frameworks and libraries it uses
(FastAPI, pandas, pytest, Pydantic, …) and counts its entry points. Click a library to see which modules and functions use it.
The server re-analyzes on every page refresh, so code changes show up immediately. Analysis only reads files; it never writes into the project.

Other commands:

```bash
python -m codeflow list  <repo> --entries                   # entry points
python -m codeflow trace <repo> checkout_endpoint body      # follow a value in the terminal
python -m codeflow trace <repo> apply_tax amount --back     # where does it come from?
python -m codeflow json  <repo> -o graph.json               # raw graph for other tools
```

Or install it as a command: `pip install -e .` then `codeflow serve .`

No dependencies (stdlib only, Python 3.8+). The HTML is fully self-contained and works offline.

### Keyboard

`O` open folder · `/` search · `1`–`4` switch view · `F` fit · `R` rotate layout · `+`/`-` zoom · `Esc` clear · drag to pan · wheel to zoom ·
hover a node to highlight its connections · double-click to refocus. The URL hash keeps your place, so links are shareable.

## How it works

```
.py files ──ast──▶ per-function facts ──resolve──▶ call graph ──bind args→params──▶ global value-flow graph ──▶ viewer
```

1. **Parse** each file with `ast` (code is never executed).
2. **Extract** per function: params, calls (with each argument's sources), local def→use edges, decorators, docstring, complexity.
3. **Resolve** every call to a project function: local defs, imports / relative imports / package re-exports,
   `self.method` with **inheritance**, `super()`, simple type inference (`x = Cls(); x.m()`, `self.repo = Repo()` in `__init__`,
   module-level instances like `router = Router()`).
4. **Stitch** data flow across functions: argument → callee parameter, callee `return` → caller, and `self.<attr>` shared by all
   methods of a class. That global graph powers **Trace**.

## Project layout

```
codeflow/
  analyzer.py   static analysis engine (Project, trace, JSON export)
  render.py     embeds the analysis into viewer.html
  viewer.html   the interactive app (vanilla JS + SVG, layered graph layout, no CDN)
  server.py     local server: live re-analysis, folder browser, native folder dialog
  cli.py        ui / build / serve / list / trace / json
examples/sample_shop/   runnable demo app (route → service → pricing → repository)
tests/                  python -m unittest discover -s tests
```

## Known limits

Static analysis over-approximates in some places and misses dynamic behaviour:
calls through variables holding functions (`handler(body)`), `getattr`, dependency-injection containers,
and decorators that replace functions are not followed. Data flow is flow-insensitive (it ignores branch order).

## Roadmap

1. **Runtime overlay** — record real calls and values with `sys.monitoring` (3.12+) / `sys.settrace` while tests run, and paint what *actually* happened on top of the static graph.
2. **Framework adapters** — FastAPI/Flask/Django route tables, dependency injection, Celery, SQLAlchemy models as data sinks.
3. **Diff mode** — compare two commits: which call paths and data flows a PR changes.
4. **Editor integration** — VS Code extension that opens the viewer beside the code and syncs selection.
5. **Explanations** — LLM summaries of a function or a traced path; more languages via tree-sitter.
