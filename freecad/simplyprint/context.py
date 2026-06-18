"""Detect the current FreeCAD "context" so the panel can adapt its options.

This is the FreeCAD analogue of the Onshape integration's Part-Studio-vs-Assembly
branching. Instead of an element type we read the *active workbench*, the
*objects in the active document*, and the *current selection*, and classify what
(if anything) is printable. The panel renders different controls per ``kind``.
"""

from typing import List, Optional

# Workbench internal names that indicate an assembly editing context.
_ASSEMBLY_WORKBENCHES = {
    "AssemblyWorkbench",      # FreeCAD 1.0 built-in Std Assembly
    "Assembly3Workbench",
    "Assembly4Workbench",
    "AssemblyWbWorkbench",    # a2plus
}


class PrintableObject:
    """A single document object that can be exported to a printable mesh."""

    def __init__(self, obj, kind: str, visible: bool):
        self.obj = obj                       # live FreeCAD document object
        self.name = getattr(obj, "Name", "")
        self.label = getattr(obj, "Label", self.name)
        self.kind = kind                     # "solid" | "mesh"
        self.visible = visible


class Context:
    """Snapshot of what the SimplyPrint panel should offer right now."""

    def __init__(
        self,
        kind: str,
        workbench_name: str = "",
        document_name: str = "",
        objects: Optional[List[PrintableObject]] = None,
        selected_names: Optional[List[str]] = None,
        is_assembly: bool = False,
    ):
        # kind ∈ {none, unsupported, solids, meshes, assembly, mixed}
        self.kind = kind
        self.workbench_name = workbench_name
        self.document_name = document_name
        self.objects = objects or []
        self.selected_names = selected_names or []
        self.is_assembly = is_assembly

    @property
    def has_solids(self) -> bool:
        return any(o.kind == "solid" for o in self.objects)

    @property
    def has_meshes(self) -> bool:
        return any(o.kind == "mesh" for o in self.objects)

    def selected_objects(self) -> List[PrintableObject]:
        sel = set(self.selected_names)
        return [o for o in self.objects if o.name in sel]

    def signature(self) -> str:
        """Stable string that changes whenever the rendered UI should change.

        The panel polls this and only re-renders when it differs, the FreeCAD
        analogue of the Onshape integration's light poll loop.
        """
        parts = [self.kind, self.workbench_name, self.document_name]
        for o in self.objects:
            parts.append(f"{o.name}:{o.kind}:{int(o.visible)}")
        parts.append("sel=" + ",".join(sorted(self.selected_names)))
        return "|".join(parts)


# Object types that are never printable even though they may expose a Shape:
# origin datums (planes/axes/points), sketches, containers, 2D/annotation docs.
# Origin planes are App::Plane with a single face – without this they'd show up
# as "solids" and their huge datum bounding box produced the 2e+100 size.
_BLOCKED_TYPES = {
    "App::Origin", "App::Plane", "App::Line", "App::Point",
    "App::Part", "App::DocumentObjectGroup", "App::LinkGroup",
    "App::Placement", "App::OriginGroupExtension",
}
_BLOCKED_PREFIXES = (
    "Sketcher::", "TechDraw::", "Drawing::", "Spreadsheet::", "Part::Datum",
)


def _is_blocked_type(obj) -> bool:
    type_id = getattr(obj, "TypeId", "")
    if type_id in _BLOCKED_TYPES:
        return True
    if type_id.startswith(_BLOCKED_PREFIXES):
        return True
    # PartDesign internal features (Pad, Pocket, datums…) – the Body carries the
    # final Shape, so only the Body itself is exportable.
    if type_id.startswith("PartDesign::") and type_id != "PartDesign::Body":
        return True
    return False


def _is_solid_candidate(obj) -> bool:
    """A B-rep object is printable only if it actually encloses a solid.

    Requiring solids (not just faces) excludes datum planes, sketches and stray
    surfaces – you can't 3D print an open face anyway.
    """
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return False
    try:
        if shape.isNull():
            return False
        return len(shape.Solids) > 0
    except Exception:
        return False


def _is_mesh_candidate(obj) -> bool:
    return hasattr(obj, "Mesh") and getattr(obj, "Mesh", None) is not None


def _is_consumed(obj, candidate_names) -> bool:
    """True if another candidate object uses *obj* (boolean operand, body feature).

    Lets us list the result of a Part::Cut or a PartDesign::Body without also
    listing the operands / internal features it's built from.
    """
    try:
        for parent in obj.InList:
            if getattr(parent, "Name", None) in candidate_names:
                return True
    except Exception:
        pass
    return False


def _is_visible(obj) -> bool:
    try:
        vo = getattr(obj, "ViewObject", None)
        if vo is not None and hasattr(vo, "Visibility"):
            return bool(vo.Visibility)
    except Exception:
        pass
    return True


def current_context() -> Context:
    """Build a :class:`Context` from the live FreeCAD GUI / document state."""
    try:
        import FreeCAD
    except Exception:
        return Context("none")

    if not getattr(FreeCAD, "GuiUp", False):
        return Context("none")

    import FreeCADGui

    workbench_name = ""
    try:
        workbench_name = FreeCADGui.activeWorkbench().name()
    except Exception:
        pass

    doc = getattr(FreeCAD, "ActiveDocument", None)
    if doc is None:
        return Context("none", workbench_name=workbench_name)

    all_objects = list(doc.Objects)

    # First pass: which objects are exportable at all (skip internal PartDesign
    # features – the Body carries the final Shape).
    candidate_names = set()
    for obj in all_objects:
        if _is_blocked_type(obj):
            continue
        if _is_solid_candidate(obj) or _is_mesh_candidate(obj):
            candidate_names.add(obj.Name)

    printable: List[PrintableObject] = []
    for obj in all_objects:
        if obj.Name not in candidate_names:
            continue
        if _is_consumed(obj, candidate_names):
            continue
        kind = "mesh" if _is_mesh_candidate(obj) else "solid"
        printable.append(PrintableObject(obj, kind, _is_visible(obj)))

    # Current selection, restricted to printable objects.
    selected_names: List[str] = []
    try:
        printable_names = {p.name for p in printable}
        for obj in FreeCADGui.Selection.getSelection():
            name = getattr(obj, "Name", None)
            if name in printable_names:
                selected_names.append(name)
    except Exception:
        pass

    is_assembly = workbench_name in _ASSEMBLY_WORKBENCHES or any(
        getattr(o.obj, "TypeId", "").startswith("Assembly::")
        or getattr(o.obj, "TypeId", "") == "App::Link"
        for o in printable
    )

    if not printable:
        kind = "unsupported"
    elif is_assembly:
        kind = "assembly"
    elif all(o.kind == "mesh" for o in printable):
        kind = "meshes"
    elif all(o.kind == "solid" for o in printable):
        kind = "solids"
    else:
        kind = "mixed"

    return Context(
        kind=kind,
        workbench_name=workbench_name,
        document_name=getattr(doc, "Name", ""),
        objects=printable,
        selected_names=selected_names,
        is_assembly=is_assembly,
    )
