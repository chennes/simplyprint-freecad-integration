"""Headless export smoke test – run inside FreeCAD, not plain Python.

    freecadcmd tests/freecad_smoke.py
    # or:  FreeCADCmd tests/freecad_smoke.py

Builds a box, exports it through ``simplyprint.export`` to STL/3MF/OBJ at every
quality preset, and checks the files are non-empty and that a finer preset
produces a finer mesh. Also exercises :func:`export.measure`.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import FreeCAD  # noqa: E402
import Part  # noqa: E402

from freecad.simplyprint import export  # noqa: E402


def _tri_count(path):
    """Count triangles in a binary STL (header 80 bytes + uint32 count)."""
    import struct

    with open(path, "rb") as fh:
        fh.read(80)
        (n,) = struct.unpack("<I", fh.read(4))
    return n


def main():
    doc = FreeCAD.newDocument("smoke")
    # A cylinder so curvature makes the deflection setting matter.
    cyl = doc.addObject("Part::Cylinder", "Cyl")
    cyl.Radius = 10
    cyl.Height = 20
    doc.recompute()

    tmp = tempfile.mkdtemp(prefix="sp_smoke_")
    failures = 0

    # 1. Every format writes a non-empty file.
    for fmt in ("STL", "3MF", "OBJ"):
        paths = export.export_objects([cyl], fmt=fmt, out_dir=tmp, base_name="cyl", quality="medium")
        ok = paths and os.path.getsize(paths[0]) > 0
        print(f"{'PASS' if ok else 'FAIL'} export {fmt} -> {paths}")
        failures += 0 if ok else 1

    # 2. Finer preset => more triangles (STL).
    low = export.export_objects([cyl], fmt="STL", out_dir=tmp, base_name="low", quality="low")[0]
    high = export.export_objects([cyl], fmt="STL", out_dir=tmp, base_name="high", quality="high")[0]
    n_low, n_high = _tri_count(low), _tri_count(high)
    ok = n_high > n_low
    print(f"{'PASS' if ok else 'FAIL'} quality: low={n_low} tris, high={n_high} tris")
    failures += 0 if ok else 1

    # 3. measure() reports a sensible bbox + volume.
    info = export.measure([cyl])
    x, y, z = info["bbox"]
    ok = abs(x - 20) < 0.5 and abs(y - 20) < 0.5 and abs(z - 20) < 0.5 and info["has_volume"]
    print(f"{'PASS' if ok else 'FAIL'} measure: bbox=({x:.1f},{y:.1f},{z:.1f}) vol={info['volume_cm3']:.2f} cm3")
    failures += 0 if ok else 1

    # 4. per-object writes one file each.
    box = doc.addObject("Part::Box", "Box")
    doc.recompute()
    paths = export.export_objects([cyl, box], fmt="STL", out_dir=tmp, base_name="multi", per_object=True)
    ok = len(paths) == 2 and all(os.path.getsize(p) > 0 for p in paths)
    print(f"{'PASS' if ok else 'FAIL'} per-object -> {len(paths)} files")
    failures += 0 if ok else 1

    FreeCAD.closeDocument(doc.Name)
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILURES'}")
    return failures


# freecadcmd executes this file with __name__ set to the module basename
# (e.g. "freecad_smoke"), not "__main__", so run unconditionally.
_failures = main()
if __name__ == "__main__":
    sys.exit(1 if _failures else 0)
