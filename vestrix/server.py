"""
Local web server for vestrix.

  GET /                     analyze the default folder (or show the folder picker)
  GET /?path=D:\\repo       analyze any folder; re-runs on every refresh, so edits show up live
  GET /api/ls?path=...      folder browser used by the picker (sub-folders + what was detected in them)
  GET /api/pick             open the OS-native "choose folder" dialog (tkinter), return the path

Binds to 127.0.0.1 by default: the folder browser exposes your file system to whoever can reach the port.
"""
from __future__ import annotations

import http.server
import json
import os
import string
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analyzer import SKIP_DIRS, Project
from .render import build_html, empty_data

MARKERS = {".git": "git", "pyproject.toml": "pyproject", "setup.py": "setup.py", "setup.cfg": "setup.cfg",
           "requirements.txt": "requirements", "manage.py": "django", "Pipfile": "pipenv", "uv.lock": "uv",
           "poetry.lock": "poetry", "__init__.py": "package", "Dockerfile": "docker"}
_pick_lock = threading.Lock()
PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def drives():
    if os.name == "nt":
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return ["/"]


def count_py(path, cap=5000, seconds=1.2):
    """Recursive .py count, skipping venvs/caches; capped so huge folders stay fast."""
    n, stack, deadline = 0, [path], time.monotonic() + seconds
    while stack:
        if n >= cap or time.monotonic() > deadline:
            return n, True
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in SKIP_DIRS and not e.name.startswith("."):
                                stack.append(e.path)
                        elif e.name.endswith(".py"):
                            n += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return n, False


def list_dir(path):
    p = Path(path).expanduser() if path else Path.cwd()
    p = p.resolve()
    if not p.is_dir():
        raise NotADirectoryError(f"not a folder: {p}")
    dirs = []
    with os.scandir(p) as it:
        entries = []
        for e in it:
            try:
                if e.is_dir():
                    entries.append(e)
            except OSError:
                pass
    for e in sorted(entries, key=lambda e: e.name.lower())[:800]:
        info = {"name": e.name, "path": e.path, "hidden": e.name.startswith((".", "$")),
                "skipped": e.name in SKIP_DIRS, "py": 0, "marks": []}
        if not info["skipped"]:
            try:
                with os.scandir(e.path) as it2:
                    for c in it2:
                        if c.name in MARKERS:
                            info["marks"].append(MARKERS[c.name])
                        if c.name.endswith(".py"):
                            info["py"] += 1
            except OSError:
                info["denied"] = True
        dirs.append(info)
    total, capped = count_py(str(p))
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs,
            "drives": drives(), "home": str(Path.home()), "cwd": str(Path.cwd()),
            "py_total": total, "py_capped": capped,
            "marks": [label for name, label in MARKERS.items() if (p / name).exists()]}


def pick_native(initial=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:                                     # pragma: no cover - platform dependent
        return None, f"native dialog unavailable ({e}); use the folder list instead"
    with _pick_lock:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(parent=root, initialdir=initial or None, mustexist=True,
                                             title="Choose a Python project folder for vestrix")
        finally:
            root.destroy()
    return (str(Path(chosen)) if chosen else None), None


def make_handler(default_path, default_exclude, log):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, status, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj), "application/json; charset=utf-8")

        def do_GET(self):
            url = urlparse(self.path)
            qs = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    return self._page(qs)
                if url.path == "/api/ping":
                    return self._json({"ok": True})
                if url.path == "/api/ping.gif":           # image probe: works from file:// pages without CORS
                    return self._send(200, PIXEL, "image/gif")
                if url.path == "/api/ls":
                    return self._json(list_dir(qs.get("path", "")))
                if url.path == "/api/pick":
                    path, err = pick_native(qs.get("path"))
                    return self._json({"path": path, "error": err})
                self.send_error(404)
            except (OSError, ValueError) as e:
                self._json({"error": str(e)}, 400)
            except Exception:
                self._send(500, f"<pre>{traceback.format_exc()}</pre>", "text/html; charset=utf-8")

        def _page(self, qs):
            path = qs.get("path") or default_path
            exclude = [x.strip() for x in qs.get("exclude", ",".join(default_exclude)).split(",") if x.strip()]
            if not path:
                return self._send(200, build_html(data=empty_data(Path.cwd())), "text/html; charset=utf-8")
            try:
                project = Project(path, exclude=exclude)
            except FileNotFoundError as e:
                return self._send(200, build_html(data=empty_data(Path.cwd(), message=str(e))), "text/html; charset=utf-8")
            s = project.stats()
            log(f"  analyzed {project.root}: {s['modules']} modules, {s['functions']} functions ({s['elapsed_ms']} ms)")
            self._send(200, build_html(project, served=True), "text/html; charset=utf-8")

        def log_message(self, *args):
            pass

    return Handler


DEFAULT_PORT = 8347          # static pages probe DEFAULT_PORT .. DEFAULT_PORT+4 to find a running app


def serve(path=None, host="127.0.0.1", port=DEFAULT_PORT, open_browser=False, exclude=(), log=print):
    handler = make_handler(path, list(exclude or ()), log)
    server = None
    for candidate in range(port, port + 10):                # skip ports other apps already use
        try:
            server = http.server.ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError:
            log(f"  port {candidate} is busy, trying {candidate + 1}")
    if server is None:
        raise OSError(f"no free port in {port}-{port + 9}")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{server.server_address[1]}/"
    log(f"vestrix serving {Path(path).resolve() if path else '(pick a folder in the browser)'}")
    log(f"  open {url}   · refresh the page after editing code · Ctrl+C to stop")
    if host not in ("127.0.0.1", "localhost"):
        log("  warning: the folder browser is reachable from other machines on this network")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped")
    finally:
        server.server_close()
