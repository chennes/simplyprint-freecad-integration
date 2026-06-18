#!/usr/bin/env python3
"""Bump the addon version across all the files that carry it.

The canonical version lives in ``package.xml`` (that is what ``build.py`` reads),
but the same number is mirrored in ``pyproject.toml`` and in the
``__version__`` fallback in ``freecad/simplyprint/__init__.py``. This script keeps
them in lock-step and (by default) updates the ``<date>`` in ``package.xml``.

  python scripts/bump_version.py patch       -> 1.0.0 -> 1.0.1
  python scripts/bump_version.py minor       -> 1.0.1 -> 1.1.0
  python scripts/bump_version.py major       -> 1.1.0 -> 2.0.0
  python scripts/bump_version.py 1.4.2        -> set an explicit version
  python scripts/bump_version.py patch --tag  -> also git commit + tag v1.0.1

The ``--tag`` flag commits the changed files and creates an annotated ``vX.Y.Z``
tag; pushing that tag triggers the release workflow, which builds the zip and
attaches it to a GitHub release.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PACKAGE_XML = os.path.join(ROOT, "package.xml")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
INIT_PY = os.path.join(ROOT, "freecad", "simplyprint", "__init__.py")

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_current_version() -> str:
    text = _read(PACKAGE_XML)
    m = re.search(r"<version>\s*(.*?)\s*</version>", text)
    if not m:
        sys.exit("error: could not find <version> in package.xml")
    return m.group(1)


def compute_new_version(current: str, bump: str) -> str:
    if SEMVER_RE.match(bump):
        return bump
    if bump not in ("major", "minor", "patch"):
        sys.exit(f"error: '{bump}' is not 'major', 'minor', 'patch' or an X.Y.Z version")
    if not SEMVER_RE.match(current):
        sys.exit(f"error: current version '{current}' is not X.Y.Z; pass an explicit version")
    major, minor, patch = (int(p) for p in current.split("."))
    if bump == "major":
        major, minor, patch = major + 1, 0, 0
    elif bump == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _sub_once(path: str, pattern: str, repl: str) -> None:
    text = _read(path)
    new_text, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        sys.exit(f"error: expected exactly one match for {pattern!r} in {os.path.relpath(path, ROOT)}")
    _write(path, new_text)


def apply_version(new: str, today: str) -> None:
    _sub_once(PACKAGE_XML, r"<version>\s*.*?\s*</version>", f"<version>{new}</version>")
    _sub_once(PACKAGE_XML, r"<date>\s*.*?\s*</date>", f"<date>{today}</date>")
    _sub_once(PYPROJECT, r'(?m)^version\s*=\s*".*?"', f'version = "{new}"')
    _sub_once(INIT_PY, r'(?m)^__version__\s*=\s*".*?"', f'__version__ = "{new}"')


def git(*args: str) -> None:
    subprocess.run(["git", "-C", ROOT, *args], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump the SimplyPrint FreeCAD addon version")
    parser.add_argument("bump", help="'major', 'minor', 'patch', or an explicit X.Y.Z version")
    parser.add_argument(
        "--tag", action="store_true",
        help="git commit the changed files and create an annotated vX.Y.Z tag",
    )
    parser.add_argument(
        "--no-date", action="store_true",
        help="leave the <date> in package.xml untouched",
    )
    args = parser.parse_args()

    current = read_current_version()
    new = compute_new_version(current, args.bump)
    if new == current:
        sys.exit(f"error: version is already {new}")

    today = datetime.date.today().isoformat()
    if args.no_date:
        # Re-read the existing date and keep it.
        m = re.search(r"<date>\s*(.*?)\s*</date>", _read(PACKAGE_XML))
        today = m.group(1) if m else today

    apply_version(new, today)
    print(f"Bumped {current} -> {new}")
    print(f"  package.xml, pyproject.toml, freecad/simplyprint/__init__.py")

    if args.tag:
        tag = f"v{new}"
        git("add", "package.xml", "pyproject.toml", "freecad/simplyprint/__init__.py")
        git("commit", "-m", f"Release {tag}")
        git("tag", "-a", tag, "-m", f"Release {tag}")
        print(f"Committed and tagged {tag}.")
        print(f"Push it to trigger the release build:  git push origin main {tag}")
    else:
        print("Review the changes, then commit. To also build a release, tag with:")
        print(f"  git tag -a v{new} -m 'Release v{new}' && git push origin v{new}")


if __name__ == "__main__":
    main()
