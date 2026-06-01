"""FreeCAD Gui.Command definitions for the SimplyPrint workbench / toolbar."""

import os

import FreeCADGui

from . import ICONPATH, actions, api, context as ctx_mod, panel, state


def _icon(name: str) -> str:
    return os.path.join(ICONPATH, name)


class _Send:
    """Send the current context's geometry to SimplyPrint (one click)."""

    def GetResources(self):
        return {
            "Pixmap": _icon("send.svg"),
            "MenuText": "Send to SimplyPrint",
            "ToolTip": "Export the active model and upload it to SimplyPrint",
        }

    def IsActive(self):
        if not state.is_logged_in() or state.state.busy:
            return False
        return ctx_mod.current_context().kind in ("solids", "meshes", "mixed", "assembly")

    def Activated(self):
        p = panel.ensure_panel()
        if p is None:
            return
        p.setVisible(True)
        p.raise_()
        p._on_send()


class _Login:
    def GetResources(self):
        return {
            "Pixmap": _icon("login.svg"),
            "MenuText": "Log In to SimplyPrint",
            "ToolTip": "Authenticate with SimplyPrint in your browser",
        }

    def IsActive(self):
        return not state.is_logged_in() and not state.state.busy

    def Activated(self):
        panel.ensure_panel()
        actions.start_login()


class _Logout:
    def GetResources(self):
        return {
            "Pixmap": _icon("logout.svg"),
            "MenuText": "Log Out",
            "ToolTip": "Log out of SimplyPrint on this computer",
        }

    def IsActive(self):
        return state.is_logged_in()

    def Activated(self):
        actions.logout()


class _OpenPanel:
    def GetResources(self):
        return {
            "Pixmap": _icon("simplyprint.svg"),
            "MenuText": "Open SimplyPrint",
            "ToolTip": "Open the SimplyPrint dashboard in your browser",
        }

    def IsActive(self):
        return True

    def Activated(self):
        import webbrowser

        webbrowser.open(api.make_panel_url())


class _TogglePanel:
    def GetResources(self):
        return {
            "Pixmap": _icon("simplyprint.svg"),
            "MenuText": "SimplyPrint Panel",
            "ToolTip": "Show or hide the SimplyPrint panel",
        }

    def IsActive(self):
        return True

    def Activated(self):
        panel.toggle_panel()


COMMANDS = {
    "SP_Send": _Send,
    "SP_Login": _Login,
    "SP_Logout": _Logout,
    "SP_OpenPanel": _OpenPanel,
    "SP_TogglePanel": _TogglePanel,
}

# Order used when building toolbar / menu.
COMMAND_ORDER = ["SP_Send", "SP_TogglePanel", "SP_Login", "SP_Logout", "SP_OpenPanel"]

_registered = False


def register_commands():
    global _registered
    if _registered:
        return
    for name, cls in COMMANDS.items():
        FreeCADGui.addCommand(name, cls())
    _registered = True
