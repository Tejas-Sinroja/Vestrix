"""
Release helper for codeflow. The version lives in exactly one place: VERSION in codeflow/analyzer.py.

  python scripts/release.py bump patch|minor|major [--dry-run] [--push]
      bump the version, move CHANGELOG "Unreleased" notes under the new version,
      run the tests, commit "Release vX.Y.Z" and create an annotated tag vX.Y.Z.
      --push also pushes main and the tag, which triggers the GitHub release workflow.

  python scripts/release.py notes X.Y.Z      print that version's CHANGELOG section (used by CI)
  python scripts/release.py check-tag vX.Y.Z  fail unless the tag matches VERSION (used by CI)
  python scripts/release.py current           print the current version
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "codeflow" / "analyzer.py"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/Tejas-Sinroja/CodeFlow"
VERSION_RE = re.compile(r'^VERSION = "(\d+)\.(\d+)\.(\d+)"$', re.M)


def die(msg):
    print(f"release: {msg}", file=sys.stderr)
    raise SystemExit(1)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def current():
    m = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        die(f"VERSION not found in {VERSION_FILE}")
    return tuple(int(x) for x in m.groups())


def fmt(v):
    return ".".join(map(str, v))


def section(text, version):
    """Body of '## [version]' up to the next '## [' heading."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def has_content(body):
    return any(line.strip() and not line.startswith("#") for line in (body or "").splitlines())


def cmd_bump(a):
    old = current()
    new = {"major": (old[0] + 1, 0, 0), "minor": (old[0], old[1] + 1, 0), "patch": (old[0], old[1], old[2] + 1)}[a.part]
    old_s, new_s, tag = fmt(old), fmt(new), f"v{fmt(new)}"

    if git("status", "--porcelain"):
        die("working tree has uncommitted changes; commit or stash them first")
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        die("releases are cut from main")
    if git("tag", "--list", tag):
        die(f"tag {tag} already exists")

    log = CHANGELOG.read_text(encoding="utf-8")
    notes = section(log, "Unreleased")
    if not has_content(notes):
        die("CHANGELOG has nothing under '## [Unreleased]'; describe the changes first")

    today = datetime.date.today().isoformat()
    log = log.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new_s}] - {today}", 1)
    log = re.sub(r"^\[Unreleased\]: .*$", f"[Unreleased]: {REPO_URL}/compare/{tag}...HEAD", log, count=1, flags=re.M)
    link = f"[{new_s}]: {REPO_URL}/compare/v{old_s}...{tag}"
    log = log.replace(f"[Unreleased]: {REPO_URL}/compare/{tag}...HEAD",
                      f"[Unreleased]: {REPO_URL}/compare/{tag}...HEAD\n{link}", 1)

    print(f"codeflow {old_s} -> {new_s} ({a.part})\n\n{notes}\n")
    print("running tests…")
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)
    if r.returncode:
        die("tests failed; not releasing")
    if a.dry_run:
        print("\ndry run: nothing written")
        return 0

    VERSION_FILE.write_text(VERSION_RE.sub(f'VERSION = "{new_s}"', VERSION_FILE.read_text(encoding="utf-8"), count=1),
                            encoding="utf-8")
    CHANGELOG.write_text(log, encoding="utf-8")
    git("add", str(VERSION_FILE), str(CHANGELOG))
    git("commit", "-m", f"Release {tag}")
    git("tag", "-a", tag, "-m", f"codeflow {tag}\n\n{notes}")
    print(f"\ncommitted and tagged {tag}")
    if a.push:
        git("push", "origin", "main", "--follow-tags")
        print(f"pushed; GitHub Actions will publish {REPO_URL}/releases/tag/{tag}")
    else:
        print("next: git push origin main --follow-tags")
    return 0


def cmd_notes(a):
    body = section(CHANGELOG.read_text(encoding="utf-8"), a.version.lstrip("v"))
    if body is None:
        die(f"no CHANGELOG section for {a.version}")
    print(body)
    print(f"\n**Full changelog:** {REPO_URL}/blob/v{a.version.lstrip('v')}/CHANGELOG.md")
    return 0


def cmd_check_tag(a):
    want = f"v{fmt(current())}"
    if a.tag != want:
        die(f"tag {a.tag} does not match codeflow VERSION ({want})")
    print(f"tag {a.tag} matches VERSION")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):              # CHANGELOG has non-ASCII (→, …); Windows consoles are cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="codeflow release helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump")
    b.add_argument("part", choices=["patch", "minor", "major"])
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--push", action="store_true")
    b.set_defaults(fn=cmd_bump)
    n = sub.add_parser("notes")
    n.add_argument("version")
    n.set_defaults(fn=cmd_notes)
    c = sub.add_parser("check-tag")
    c.add_argument("tag")
    c.set_defaults(fn=cmd_check_tag)
    sub.add_parser("current").set_defaults(fn=lambda a: print(fmt(current())) or 0)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
