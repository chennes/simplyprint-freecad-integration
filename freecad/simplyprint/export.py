"""Export FreeCAD geometry to printable mesh files.

This module is where FreeCAD earns its keep over mesh-only tools:

* **Adjustable mesh quality** – parametric B-rep solids are tessellated with
  ``MeshPart.meshFromShape`` at a chosen linear (mm) / angular (deg) deflection,
  so curved parts come out as smooth as the user wants.
* **Physical measurement** – :func:`measure` reports the true bounding box (mm)
  and volume (cm³) FreeCAD already knows, so the user can catch scale/unit
  mistakes before uploading.
* **Multi-object / per-object** – any number of objects export into one file, or
  one file each.

Output goes through ``Mesh.export`` (format inferred from the extension), which
covers STL, 3MF and OBJ.
"""

import os
import re
from math import radians
from typing import List, Sequence, Tuple

# fmt -> file extension
EXTENSION_MAP = {
    "STL": ".stl",
    "3MF": ".3mf",
    "OBJ": ".obj",
}

# quality -> (LinearDeflection in mm, AngularDeflection in degrees).
# Lower deflection => finer mesh => more triangles => higher fidelity.
QUALITY_PRESETS = {
    "low": (0.5, 30.0),
    "medium": (0.1, 20.0),
    "high": (0.05, 10.0),
}

DEFAULT_QUALITY = "medium"


def deflection_for(quality: str, custom_linear: float = 0.1, custom_angular: float = 20.0) -> Tuple[float, float]:
    """Resolve a quality preset (or ``"custom"``) to (linear_mm, angular_deg)."""
    if quality == "custom":
        return (max(custom_linear, 1e-4), max(custom_angular, 0.1))
    return QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])


def sanitize(name: str) -> str:
    """Make *name* safe to use as a file name."""
    cleaned = re.sub(r"[^\w.-]+", "_", name or "").strip("_")
    return cleaned or "model"


def _live(obj):
    """Accept either a context.PrintableObject or a raw document object."""
    return getattr(obj, "obj", obj)


def measure(objects: Sequence) -> dict:
    """Return ``{bbox: (x, y, z) mm, volume_cm3, has_volume}`` for *objects*.

    Bounding box always available; volume only for objects with a solid Shape.
    """
    import FreeCAD

    bbox = None
    volume_mm3 = 0.0
    has_volume = False

    for o in objects:
        live = _live(o)
        shape = getattr(live, "Shape", None)
        if shape is not None and not shape.isNull():
            try:
                b = shape.BoundBox
                bbox = b if bbox is None else bbox.united(b)
            except Exception:
                pass
            try:
                if shape.Solids:
                    volume_mm3 += shape.Volume
                    has_volume = True
            except Exception:
                pass
            continue

        mesh = getattr(live, "Mesh", None)
        if mesh is not None:
            try:
                b = mesh.BoundBox
                bbox = b if bbox is None else bbox.united(b)
            except Exception:
                pass

    if bbox is None:
        dims = (0.0, 0.0, 0.0)
    else:
        dims = (bbox.XLength, bbox.YLength, bbox.ZLength)

    return {
        "bbox": dims,
        "volume_cm3": volume_mm3 / 1000.0,
        "has_volume": has_volume,
    }


def _mesh_for(live, linear_mm: float, angular_deg: float):
    """Return a ``Mesh.Mesh`` for a document object.

    Mesh objects pass through unchanged; B-rep shapes are tessellated at the
    requested deflection.
    """
    mesh = getattr(live, "Mesh", None)
    if mesh is not None:
        return mesh

    shape = getattr(live, "Shape", None)
    if shape is None or shape.isNull():
        raise RuntimeError(f"Object '{getattr(live, 'Label', '?')}' has no exportable geometry")

    import MeshPart

    return MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=linear_mm,
        AngularDeflection=radians(angular_deg),
        Relative=False,
    )


def _new_hidden_document():
    import FreeCAD

    try:
        return FreeCAD.newDocument("SimplyPrintExport", hidden=True)
    except TypeError:
        # Older FreeCAD without the hidden kwarg.
        return FreeCAD.newDocument("SimplyPrintExport")


def _write(pairs: List[Tuple[object, object]], path: str) -> None:
    """Write (object, mesh_data) pairs to *path* via a throwaway document.

    Building Mesh::Feature objects in a temporary hidden document lets us use
    ``Mesh.export`` (which keeps objects separate in 3MF) without mutating the
    user's real document.
    """
    import FreeCAD
    import Mesh

    tmp = _new_hidden_document()
    try:
        features = []
        for live, mesh_data in pairs:
            feat = tmp.addObject("Mesh::Feature", sanitize(getattr(live, "Label", "mesh")))
            feat.Label = getattr(live, "Label", feat.Name)
            feat.Mesh = mesh_data
            features.append(feat)
        Mesh.export(features, path)
    finally:
        FreeCAD.closeDocument(tmp.Name)


def export_objects(
    objects: Sequence,
    fmt: str,
    out_dir: str,
    base_name: str = "model",
    quality: str = DEFAULT_QUALITY,
    custom_linear: float = 0.1,
    custom_angular: float = 20.0,
    per_object: bool = False,
) -> List[str]:
    """Export *objects* to *out_dir* and return the list of written file paths.

    With ``per_object`` each object becomes its own file; otherwise all objects
    go into a single file named after *base_name*.
    """
    if not objects:
        raise RuntimeError("Nothing to export")

    fmt = fmt.upper()
    ext = EXTENSION_MAP.get(fmt)
    if ext is None:
        raise ValueError(f"Unsupported export format: {fmt}")

    linear_mm, angular_deg = deflection_for(quality, custom_linear, custom_angular)

    pairs = [(_live(o), None) for o in objects]
    pairs = [(live, _mesh_for(live, linear_mm, angular_deg)) for live, _ in pairs]

    if per_object:
        paths = []
        for live, mesh_data in pairs:
            path = os.path.join(out_dir, sanitize(getattr(live, "Label", base_name)) + ext)
            _write([(live, mesh_data)], path)
            paths.append(path)
        return paths

    path = os.path.join(out_dir, sanitize(base_name) + ext)
    _write(pairs, path)
    return [path]
