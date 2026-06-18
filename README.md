# SimplyPrint for FreeCAD

A FreeCAD addon that sends your models, meshes and assemblies straight to
[SimplyPrint](https://simplyprint.io) for cloud slicing, storage and 3D printing.

![FreeCAD](https://img.shields.io/badge/FreeCAD-0.21%2B%20%7C%201.0-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

Unlike mesh-only tools, FreeCAD is a parametric **solid modeler** — and this
addon makes the most of that:

- **Adjustable mesh quality.** Parametric B-rep solids are tessellated on the fly
  with a Low / Medium / High preset or a custom surface-deviation (mm) and
  angular-deviation (°), so curved parts come out exactly as smooth as you need.
- **Physical preview.** Before you upload, the panel shows the real bounding box
  (mm) and volume (cm³) FreeCAD already knows — an easy way to catch scale or
  unit mistakes.
- **Context-aware.** A single SimplyPrint panel adapts to what you're doing:
  - **Part / Part Design** — pick which solids to send, choose mesh quality.
  - **Mesh** — send meshes as-is (no tessellation options shown).
  - **Assembly** — send the whole assembly as one file.
  - **Sketcher / Draft / TechDraw / …** — a hint to switch to a printable context.
- **Multi-object / per-object.** Send the whole document, just the objects you
  select, or one file per object.
- **Formats:** STL (default), 3MF (preserves mm units and multiple objects), OBJ.

It shares the secure, browser-based OAuth login and chunked-upload core with the
SimplyPrint Blender, Cura, Fusion 360 and Onshape integrations.

## Requirements

- FreeCAD **0.21** or newer (including **1.0**)
- A [SimplyPrint](https://simplyprint.io) account

## Installation

### Addon Manager (recommended)

1. In FreeCAD: **Tools → Addon Manager**.
2. (First time only) add this repository as a custom repository in the Addon
   Manager preferences, then search for **SimplyPrint** and install it.
3. Restart FreeCAD.

### From zip / for development

```
python build.py            # creates dist/SimplyPrint.zip
python build.py --install  # copies the addon straight into FreeCAD's user Mod/ dir
```

`--install` auto-detects the FreeCAD user `Mod/` directory. FreeCAD **1.1+**
stores user data under a versioned folder (e.g. `v1-1/Mod`), and the **flatpak**
build sandboxes everything under `~/.var/app/org.freecad.FreeCAD/` — both are
detected automatically:

| Install            | Location                                                                 |
| ------------------ | ------------------------------------------------------------------------ |
| Linux (native)     | `~/.local/share/FreeCAD/[vX-Y/]Mod/SimplyPrint`                          |
| Linux (flatpak)    | `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/vX-Y/Mod/SimplyPrint`       |
| Windows            | `%APPDATA%\FreeCAD\[vX-Y\]Mod\SimplyPrint`                               |
| macOS              | `~/Library/Application Support/FreeCAD/[vX-Y/]Mod/SimplyPrint`           |

To check where your FreeCAD looks, run `App.getUserAppDataDir()` in its Python
console — the addon goes in the `Mod` subfolder of that path. Restart FreeCAD
after installing.

## Usage

1. The **SimplyPrint** panel docks on the right of the FreeCAD window (it's
   available in every workbench). You can also pick the **SimplyPrint** workbench
   for its toolbar/menu, or toggle the panel from there.
2. Click **Log In** — your browser opens for a one-time SimplyPrint
   authentication. No passwords are stored locally; only OAuth tokens.
3. Open or model something with solids or meshes. The panel shows the objects it
   found, the mesh-quality options (for solids), and the physical size.
4. Choose a format and mesh quality, tick the objects to send, and click
   **Send to SimplyPrint**. Your browser opens to import the file into your
   SimplyPrint account.

## How it works

| Concern        | Where |
| -------------- | ----- |
| OAuth 2.0 PKCE login + token refresh | `freecad/simplyprint/oauth.py` |
| Authenticated requests + multipart / chunked upload | `freecad/simplyprint/api.py` |
| Token persistence (`~/.simplyprint/oauth_freecad.json`) + Qt signal bridge | `freecad/simplyprint/state.py` |
| Context detection (workbench / objects / selection) | `freecad/simplyprint/context.py` |
| Tessellation, measurement, `Mesh.export` | `freecad/simplyprint/export.py` |
| Login / upload orchestration (background threads) | `freecad/simplyprint/actions.py` |
| The context-aware dock panel | `freecad/simplyprint/panel.py` |
| Commands + workbench | `freecad/simplyprint/commands.py`, `freecad/simplyprint/init_gui.py` |

The addon uses the modern **`freecad.<name>` namespace-package** layout (the same
one as freecad.gears, freecad.curves and the official Workbench Starterkit), so
`init_gui.py` is a normal imported module — it is pip-installable and avoids the
`exec`-based quirks of a classic top-level `InitGui.py`.

## Configuration

### Switching backend (e.g. test.simplyprint.io)

The backend domain drives every URL (API → `https://<domain>/api`, OAuth, the
import redirect…), and defaults to `simplyprint.io`. To point at another
environment, copy `freecad/simplyprint/.env.example` → `freecad/simplyprint/.env`
(or `~/.simplyprint/.env`) and set `SP_BASE_DOMAIN` (e.g. `test.simplyprint.io`),
`SP_CLIENT_ID`, or `SP_CALLBACK_PORT`.

Resolution order for each setting (first wins): **process env var → addon `.env`
→ `~/.simplyprint/.env` → built-in default.**

## Removing your data

**Log Out** removes the stored token (`~/.simplyprint/oauth_freecad.json`). It is
namespaced so it never touches the tokens of other SimplyPrint integrations.

## License

MIT — see [LICENSE](LICENSE).
