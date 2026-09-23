# Changelog

All notable changes to Vestrix are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). See [RELEASING.md](RELEASING.md) for how releases are cut.

## [Unreleased]

### Added
- Published on PyPI: `pip install vestrix`. The release workflow uploads to PyPI through Trusted Publishing (no stored
  tokens) after building and verifying the wheel with `twine check` and a clean-venv smoke test.
- CI builds the package and validates its PyPI metadata on every push.

### Changed
- README links and images are absolute URLs so they also render on the PyPI project page.

## [0.3.0] - 2026-09-24

### Added
- **Circular import detection.** `vestrix cycles <path>` reports every import cycle with the `file:line` of each import,
  and exits with code 1 on import-time cycles so it can gate CI. Cycles are classified as **import-time** (module-level
  imports that can fail with "partially initialized module") or **deferred** (closed only through a function-level
  import). Imports under `if TYPE_CHECKING:` are ignored. In the app, cycles appear under Detected and Insights and as
  red edges in the Modules view, and the side panel explains how to break each one. Deep link: `#…&cycle=<n>`.
- Release process: single-source version, this changelog, `scripts/release.py`, and a GitHub Actions
  workflow that turns every `vX.Y.Z` tag into a GitHub Release with the wheel, sdist and a demo page.
- CI on every push and pull request: tests on Windows and Linux with Python 3.9, 3.11 and 3.13.
- Deep-link parameters: `#…&sel=<node>` preselects a node and `#…&pick=1` opens the folder dialog.
- README screenshots of every view.
- Logo and brand kit (`docs/brand`): the "V" flow-path mark, light and dark wordmarks, and a social-preview banner.
  The app uses the mark as its favicon and header logo.
- README "Why Vestrix" section: understanding and debugging AI-written ("vibe-coded") code.
- License: [PolyForm Noncommercial 1.0.0](LICENSE) for noncommercial use, and paid commercial licenses
  ([COMMERCIAL.md](COMMERCIAL.md)); contribution terms in CONTRIBUTING.md and a pull-request template.

### Changed
- **Renamed from `codeflow` to Vestrix.** The package, the CLI command (`vestrix`), the module (`python -m vestrix`)
  and the launcher (`vestrix.bat`) all changed. The old name was crowded: `CodeFlow` is taken on PyPI and used by
  Microsoft and several code tools.
- `pyproject.toml` reads the version from `vestrix/analyzer.py` (`VERSION`), so it can't drift.
- Minimum Python is now 3.9, matching what CI tests.

## [0.2.0] - 2026-09-24

First public version, published as **codeflow**.

### Added
- Interactive offline viewer (vanilla JS + SVG, no CDN): **Calls**, **Data flow**, **Trace** and **Modules** views,
  with search, a call-path finder, caller/callee depth, a rotatable layered layout, highlighted source and "Open in VS Code".
- Whole-program value tracing: argument → parameter, return → caller, and `self.<attr>` shared across methods.
- Resolution of imports, relative imports, package re-exports, inheritance, `super()`, and simple type inference
  (`x = Cls()`, `self.repo = Repo()`, module-level instances).
- Entry-point detection (HTTP routes, `__main__` scripts, `main()`, CLI commands, tasks, tests) and a
  third-party library/framework summary.
- **Open folder**: the local app has a folder browser that shows what each folder contains, plus a native folder
  dialog. Static HTML files can analyze a chosen folder in the browser via Pyodide.
- CLI: `ui`, `serve`, `build`, `list`, `trace`, `json`.

## [0.1.0] - 2026-09-24

Prototype (not published): a single script rendering a static Mermaid call graph and per-function data flow.

[Unreleased]: https://github.com/Tejas-Sinroja/Vestrix/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Tejas-Sinroja/Vestrix/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Tejas-Sinroja/Vestrix/releases/tag/v0.2.0
