# Changelog

All notable changes to codeflow are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). See [RELEASING.md](RELEASING.md) for how releases are cut.

## [Unreleased]

### Added
- Release process: single-source version, this changelog, `scripts/release.py`, and a GitHub Actions
  workflow that turns every `vX.Y.Z` tag into a GitHub Release with the wheel, sdist and a demo page.
- CI on every push and pull request: tests on Windows and Linux with Python 3.9, 3.11 and 3.13.
- Deep-link parameters: `#…&sel=<node>` preselects a node and `#…&pick=1` opens the folder dialog.
- README screenshots of every view.
- Logo and brand kit (`docs/brand`): app mark, light and dark wordmarks, and a social-preview banner.
  The app now uses the mark as its favicon and header logo.
- README "Why codeflow" section: understanding AI-written ("vibe-coded") code.

- License: [PolyForm Noncommercial 1.0.0](LICENSE) for noncommercial use, and paid commercial licenses
  ([COMMERCIAL.md](COMMERCIAL.md)); contribution terms in CONTRIBUTING.md and a pull-request template.

### Changed
- `pyproject.toml` reads the version from `codeflow/analyzer.py` (`VERSION`), so it can't drift.
- Minimum Python is now 3.9, matching what CI tests.

## [0.2.0] - 2026-09-24

First public version.

### Added
- Interactive offline viewer (vanilla JS + SVG, no CDN): **Calls**, **Data flow**, **Trace** and **Modules** views,
  with search, a call-path finder, caller/callee depth, a rotatable layered layout, highlighted source and "Open in VS Code".
- Whole-program value tracing: argument → parameter, return → caller, and `self.<attr>` shared across methods.
- Resolution of imports, relative imports, package re-exports, inheritance, `super()`, and simple type inference
  (`x = Cls()`, `self.repo = Repo()`, module-level instances).
- Entry-point detection (HTTP routes, `__main__` scripts, `main()`, CLI commands, tasks, tests) and a
  third-party library/framework summary.
- **Open folder**: the local app (`codeflow ui` / `codeflow.bat`) has a folder browser that shows what each folder
  contains and a native folder dialog. Static HTML files can analyze a chosen folder in the browser via Pyodide.
- CLI: `ui`, `serve`, `build`, `list`, `trace`, `json`.

## [0.1.0] - 2026-09-24

Prototype (not published): a single script rendering a static Mermaid call graph and per-function data flow.

[Unreleased]: https://github.com/Tejas-Sinroja/CodeFlow/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Tejas-Sinroja/CodeFlow/releases/tag/v0.2.0
