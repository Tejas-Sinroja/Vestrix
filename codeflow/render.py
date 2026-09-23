"""Turn a Project into the self-contained interactive HTML viewer."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .analyzer import SKIP_DIRS, VERSION, Project

TEMPLATE = Path(__file__).with_name("viewer.html")
ANALYZER = Path(__file__).with_name("analyzer.py")


def empty_data(start_dir="", served=True, message=""):
    """Data for the landing page (no folder analyzed yet)."""
    stats = {"modules": 0, "functions": 0, "classes": 0, "calls": 0, "internal_calls": 0, "lines": 0, "elapsed_ms": 0}
    return {"meta": {"root": str(start_dir), "name": "", "version": VERSION, "generated": "", "stats": stats,
                     "libraries": {}, "exclude": [], "served": served, "landing": True, "message": message},
            "modules": {}, "classes": {}, "functions": {}, "gflows": [], "files": {}, "errors": []}


def build_html(project: Project | None = None, served: bool = False, data: dict | None = None) -> str:
    if data is None:
        data = project.to_json()
        data["meta"]["served"] = served
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    text = text.replace("</", "<\\/")          # never let embedded source close the <script> tag
    name = data["meta"].get("name") or "open a folder"
    data["meta"].setdefault("skip_dirs", sorted(SKIP_DIRS))
    # the analyzer's own source ships inside the page so a static file can analyze a folder in-browser (Pyodide)
    analyzer_src = json.dumps(ANALYZER.read_text(encoding="utf-8")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__CODEFLOW_TITLE__", html.escape(f"codeflow · {name}"))
    page = page.replace("__CODEFLOW_ANALYZER__", analyzer_src)
    return page.replace("__CODEFLOW_DATA__", text)
