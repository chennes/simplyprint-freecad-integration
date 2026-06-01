"""Console-mode entry point – imported by FreeCAD at startup (both modes).

Kept minimal and GUI-free so the addon stays import-safe under ``freecadcmd`` /
headless use. All UI lives in :mod:`init_gui`.
"""

import FreeCAD as App

from freecad.simplyprint import VERSION

App.Console.PrintLog("SimplyPrint %s loaded (console)\n" % VERSION)
