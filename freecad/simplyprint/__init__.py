"""SimplyPrint integration for FreeCAD (``freecad.simplyprint`` namespace package).

Send parametric models, meshes and assemblies straight to the SimplyPrint cloud
for slicing, storage and 3D printing. The auth + upload core is shared with the
Blender / Cura / Fusion / Onshape integrations; the FreeCAD-specific value is in
:mod:`export` (adjustable B-rep tessellation + physical measurement) and
:mod:`panel` / :mod:`context` (a single panel that adapts to the active
workbench, document and selection).

Packaged as a ``freecad.<name>`` namespace package (the modern, pip-installable
FreeCAD addon layout): FreeCAD imports :mod:`init` / :mod:`init_gui` from here at
startup. Because this is a real imported module, ``__file__`` is available and the
classic ``InitGui.py`` ``exec`` quirks (no ``__file__``, split globals/locals) do
not apply.
"""

import os

# Resource directory – resolved from this module's location (works because the
# package is imported, not exec'd).
ICONPATH = os.path.join(os.path.dirname(__file__), "resources", "icons")

__version__ = "1.0.0"


def _read_version() -> str:
    """Best-effort read of <version> from the addon's package.xml (repo root)."""
    # __file__ = <addon>/freecad/simplyprint/__init__.py  ->  <addon>/package.xml
    path = os.path.join(os.path.dirname(__file__), "..", "..", "package.xml")
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        for el in tree.iter():
            if el.tag.endswith("version") and (el.text or "").strip():
                return el.text.strip()
    except Exception:
        pass
    return __version__


VERSION = _read_version()
