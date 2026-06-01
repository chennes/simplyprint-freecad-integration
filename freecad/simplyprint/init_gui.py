"""GUI entry point – imported by FreeCAD at startup (GUI mode).

As a real imported module (not an exec'd ``InitGui.py``) this can use ``__file__``
-derived paths and reference module-level names from the class body normally.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from freecad.simplyprint import ICONPATH, VERSION


class SimplyPrintWorkbench(Gui.Workbench):
    """Hosts the SimplyPrint commands and the context-aware dock panel."""

    MenuText = "SimplyPrint"
    ToolTip = "Send models to SimplyPrint for slicing and 3D printing"
    Icon = os.path.join(ICONPATH, "simplyprint.svg")

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        from freecad.simplyprint import commands

        commands.register_commands()
        self.appendToolbar("SimplyPrint", commands.COMMAND_ORDER)
        self.appendMenu("SimplyPrint", commands.COMMAND_ORDER)

    def Activated(self):
        try:
            from freecad.simplyprint import panel

            p = panel.ensure_panel()
            if p is not None:
                p.setVisible(True)
                p.raise_()
        except Exception as exc:  # pragma: no cover - GUI only
            App.Console.PrintError("SimplyPrint: %s\n" % exc)

    def Deactivated(self):
        pass


Gui.addWorkbench(SimplyPrintWorkbench())


def _deferred_startup():
    """Once the GUI event loop is up: register commands, build the always-on
    dock panel (available in every workbench), and restore any saved session."""
    try:
        from freecad.simplyprint import actions, commands, panel

        commands.register_commands()
        panel.ensure_panel()
        actions.restore_session()
        App.Console.PrintLog("SimplyPrint %s ready\n" % VERSION)
    except Exception as exc:  # pragma: no cover - GUI only
        App.Console.PrintError("SimplyPrint startup failed: %s\n" % exc)


from PySide import QtCore  # noqa: E402

# Defer until the main window and event loop are fully initialised.
QtCore.QTimer.singleShot(2000, _deferred_startup)
