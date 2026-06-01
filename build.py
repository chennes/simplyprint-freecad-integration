"""Build / install script for the SimplyPrint FreeCAD addon.

  python build.py            -> dist/SimplyPrint.zip (for manual install / release)
  python build.py --install  -> copy the addon into FreeCAD's user Mod/ folder

For most users the easiest install is via FreeCAD's built-in Addon Manager
(Tools → Addon Manager) pointed at the git repository – this script is for
development and for producing release zips.
"""

import argparse
import os
import platform
import re
import shutil
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ADDON_NAME = "SimplyPrint"
ROOT = os.path.dirname(os.path.abspath(__file__))

# Top-level entries that make up the addon (everything else is dev tooling).
INCLUDE = ["package.xml", "pyproject.toml", "README.md", "LICENSE", "freecad"]

EXCLUDE_DIRS = {"__pycache__", ".git", "dist", "tests"}
EXCLUDE_FILES_SUFFIX = (".pyc",)
EXCLUDE_FILES = {".env"}


def read_version() -> str:
    try:
        tree = ET.parse(os.path.join(ROOT, "package.xml"))
        for el in tree.iter():
            if el.tag.endswith("version") and (el.text or "").strip():
                return el.text.strip()
    except Exception:
        pass
    return "0.0.0"


def iter_files():
    """Yield (absolute_path, relative_path) for every file to ship."""
    for entry in INCLUDE:
        abs_entry = os.path.join(ROOT, entry)
        if os.path.isfile(abs_entry):
            yield abs_entry, entry
        elif os.path.isdir(abs_entry):
            for subdir, dirs, files in os.walk(abs_entry):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for f in files:
                    if f in EXCLUDE_FILES or f.endswith(EXCLUDE_FILES_SUFFIX):
                        continue
                    full = os.path.join(subdir, f)
                    yield full, os.path.relpath(full, ROOT)


def build_zip(dest_dir: str) -> str:
    version = read_version()
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, f"{ADDON_NAME}.zip")

    count = 0
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for full, rel in iter_files():
            # Nest under the addon name so it extracts into Mod/SimplyPrint/.
            zf.write(full, os.path.join(ADDON_NAME, rel))
            count += 1

    print(f"Built {ADDON_NAME} v{version}: {count} files -> {zip_path}")
    return zip_path


def _freecad_base_dirs() -> list:
    """Candidate FreeCAD user-data base dirs, most-specific first.

    Includes the flatpak sandbox location (org.freecad.FreeCAD), which is what's
    used on this machine, before the standard per-OS locations.
    """
    home = os.path.expanduser("~")
    system = platform.system()
    flatpak = os.path.join(home, ".var", "app", "org.freecad.FreeCAD", "data", "FreeCAD")

    if system == "Windows":
        return [os.path.join(os.path.expandvars("%APPDATA%"), "FreeCAD")]
    if system == "Darwin":
        return [
            os.path.join(home, "Library", "Application Support", "FreeCAD"),
            flatpak,
        ]
    # Linux / BSD – prefer flatpak if it exists, else the standard XDG location.
    return [flatpak, os.path.join(home, ".local", "share", "FreeCAD")]


def _mod_dir_for_base(base: str) -> str:
    """Return the Mod dir under *base*, honouring FreeCAD 1.1+ versioned dirs.

    FreeCAD >= 1.1 stores user data under a version folder (e.g. ``v1-1/Mod``);
    older versions use ``Mod`` directly.
    """
    if os.path.isdir(base):
        versions = sorted(
            (d for d in os.listdir(base) if re.fullmatch(r"v\d+-\d+", d)),
            reverse=True,
        )
        if versions:
            return os.path.join(base, versions[0], "Mod")
    return os.path.join(base, "Mod")


def user_mod_dir() -> str:
    for base in _freecad_base_dirs():
        if os.path.isdir(base):
            return _mod_dir_for_base(base)
    # None exist yet – fall back to the first candidate.
    return _mod_dir_for_base(_freecad_base_dirs()[0])


def install(dest: str) -> None:
    target = os.path.join(dest, ADDON_NAME)
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)

    count = 0
    for full, rel in iter_files():
        out = os.path.join(target, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(full, out)
        count += 1

    print(f"Installed {ADDON_NAME} v{read_version()}: {count} files -> {target}")
    print("Restart FreeCAD (or use Refresh in the Addon Manager) to load it.")


def main():
    parser = argparse.ArgumentParser(description="Build or install the SimplyPrint FreeCAD addon")
    parser.add_argument(
        "-i", "--install", action="store_true",
        help="Install into FreeCAD's user Mod/ directory instead of building a zip",
    )
    parser.add_argument(
        "-p", "--path",
        help="Override destination (Mod dir for --install, output dir for the zip)",
    )
    args = parser.parse_args()

    if args.install:
        install(args.path or user_mod_dir())
    else:
        build_zip(args.path or os.path.join(ROOT, "dist"))


if __name__ == "__main__":
    main()
