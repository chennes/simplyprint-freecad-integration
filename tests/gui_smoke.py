"""GUI smoke test – run inside FreeCAD *GUI* (offscreen), not freecadcmd.

    QT_QPA_PLATFORM=offscreen freecad tests/gui_smoke.py

Validates the GUI-only modules that need PySide / a main window: registering
commands, building the dock panel, and the context detection + per-context
widget visibility. Forces process exit at the end so the event loop doesn't hang.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import FreeCAD  # noqa: E402
import FreeCADGui  # noqa: E402
import Part  # noqa: E402

fail = 0

# In GUI mode FreeCAD redirects sys.stdout to its Report view, so also log to a
# host-accessible file we can read back from outside the (offscreen) process.
_LOG = os.path.join(ROOT, "tests", "_gui_result.txt")
_log_fh = open(_LOG, "w")


def _emit(line):
    print(line)
    _log_fh.write(line + "\n")
    _log_fh.flush()


def check(ok, label):
    global fail
    _emit(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        fail += 1


try:
    from freecad.simplyprint import commands, context, panel  # noqa: E402

    commands.register_commands()
    check(True, "import + register_commands")
except Exception as exc:  # noqa: BLE001
    check(False, f"import + register_commands: {exc!r}")
    print("GUI SMOKE ABORTED")
    os._exit(1)

# Commands are registered with FreeCADGui.
check(FreeCADGui.listCommands().count("SP_Send") == 1, "SP_Send command registered")

# Solid context.
doc = FreeCAD.newDocument("g")
box = doc.addObject("Part::Box", "Box")
doc.recompute()
ctx = context.current_context()
_emit(f"   context: kind={ctx.kind} objects={[o.name for o in ctx.objects]} wb={ctx.workbench_name}")
check(ctx.kind == "solids", "solid document -> kind 'solids'")
check([o.name for o in ctx.objects] == ["Box"], "Box listed as printable")

# Build the dock panel and refresh it for the solid context.
p = panel.ensure_panel()
check(p is not None, "ensure_panel built the dock")
if p is not None:
    p.setVisible(True)
    p.refresh()
    check(p._objects_group.isVisible(), "objects checklist visible for solids")
    check(p._quality_group.isVisible(), "mesh-quality group visible for solids")
    check(p._checked_objects_count() == 1, "Box checked by default")

# Boolean cut: only the result should be listed, not the operands.
cyl = doc.addObject("Part::Cylinder", "Cyl")
doc.recompute()
cut = doc.addObject("Part::Cut", "Cut")
cut.Base = box
cut.Tool = cyl
doc.recompute()
ctx2 = context.current_context()
names = sorted(o.name for o in ctx2.objects)
_emit(f"   after cut: objects={names}")
check(names == ["Cut"], "boolean lists only the Cut result, not operands")

# Empty document -> unsupported / none.
doc2 = FreeCAD.newDocument("empty")
FreeCAD.setActiveDocument("empty")
ctx3 = context.current_context()
check(ctx3.kind in ("none", "unsupported"), f"empty document -> non-printable (kind={ctx3.kind})")

_emit("ALL PASSED" if not fail else f"{fail} FAILURES")
sys.stdout.flush()
os._exit(1 if fail else 0)
