"""The SimplyPrint dock panel – a single, context-aware UI.

Like the Onshape integration shows different options for a Part Studio vs an
Assembly, this panel shows different options depending on the FreeCAD *context*
(active workbench + document objects + selection). It lives in a dock widget
attached to the main window so it is available in every workbench, and refreshes
live (selection observer + a light poll timer) as the user moves around.
"""

import os
import tempfile

from PySide import QtCore, QtGui, QtWidgets

from . import ICONPATH, VERSION, actions, api, context as ctx_mod, export, state

_PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/SimplyPrint"

_QUALITY_LABELS = [
    ("Low (fast, coarse)", "low"),
    ("Medium", "medium"),
    ("High (fine, slow)", "high"),
    ("Custom…", "custom"),
]
_FORMATS = ["STL", "3MF", "OBJ"]

# Module-level handle so InitGui / commands can find the single panel instance.
_panel = None


def _params():
    import FreeCAD

    return FreeCAD.ParamGet(_PARAM_PATH)


class _SelectionObserver:
    """Bridges FreeCAD selection changes to a panel refresh."""

    def __init__(self, panel):
        self._panel = panel

    def addSelection(self, *args):
        self._panel.request_refresh()

    def removeSelection(self, *args):
        self._panel.request_refresh()

    def clearSelection(self, *args):
        self._panel.request_refresh()

    def setSelection(self, *args):
        self._panel.request_refresh()


class SimplyPrintPanel(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("SimplyPrint", parent)
        self.setObjectName("SimplyPrintPanel")

        self._context = ctx_mod.Context("none")
        self._last_structure_sig = None
        self._user_touched_selection = False

        self._build_ui()
        self._connect_signals()
        self._load_prefs()

        # Live updates: selection observer + a light poll for workbench/doc change.
        self._observer = _SelectionObserver(self)
        try:
            import FreeCADGui

            FreeCADGui.Selection.addObserver(self._observer)
        except Exception:
            pass

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QtWidgets.QWidget()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setWidget(scroll)

        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # -- Header + account, merged into one box --------------------------
        #   [logo]  SimplyPrint v1.0.0                         [Log In/Out]
        #           <signed-in status>
        head = QtWidgets.QFrame()
        head.setFrameShape(QtWidgets.QFrame.StyledPanel)
        head_l = QtWidgets.QHBoxLayout(head)
        head_l.setSpacing(8)

        logo = QtWidgets.QLabel()
        icon = QtGui.QIcon(os.path.join(ICONPATH, "simplyprint.svg"))
        logo.setPixmap(icon.pixmap(QtCore.QSize(36, 36)))
        head_l.addWidget(logo)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(0)
        text_col.addWidget(QtWidgets.QLabel("<b>SimplyPrint</b> <small>v%s</small>" % VERSION))
        self._account_label = QtWidgets.QLabel("Not signed in")
        self._account_label.setWordWrap(True)
        text_col.addWidget(self._account_label)
        head_l.addLayout(text_col)

        head_l.addStretch(1)

        # Account action, far right (vertically centred).
        self._login_btn = QtWidgets.QPushButton("Log In")
        self._login_btn.clicked.connect(self._on_login)
        self._logout_btn = QtWidgets.QPushButton("Log Out")
        self._logout_btn.clicked.connect(self._on_logout)
        head_l.addWidget(self._login_btn, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        head_l.addWidget(self._logout_btn, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(head)

        # -- Context message (unsupported / no document) --------------------
        self._context_msg = QtWidgets.QLabel("")
        self._context_msg.setWordWrap(True)
        # Use the standard text colour (just italic) so it stays legible on both
        # light and dark themes – palette(mid) was nearly invisible on light.
        self._context_msg.setStyleSheet("font-style: italic;")
        layout.addWidget(self._context_msg)

        # -- Objects --------------------------------------------------------
        self._objects_group = QtWidgets.QGroupBox("Objects to send")
        obj_l = QtWidgets.QVBoxLayout(self._objects_group)
        sel_row = QtWidgets.QHBoxLayout()
        self._sel_summary = QtWidgets.QLabel("")
        all_btn = QtWidgets.QPushButton("All")
        none_btn = QtWidgets.QPushButton("None")
        for b in (all_btn, none_btn):
            b.setMaximumWidth(56)
        all_btn.clicked.connect(lambda: self._set_all_checked(True))
        none_btn.clicked.connect(lambda: self._set_all_checked(False))
        sel_row.addWidget(self._sel_summary)
        sel_row.addStretch(1)
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        obj_l.addLayout(sel_row)
        self._object_list = QtWidgets.QListWidget()
        self._object_list.setMaximumHeight(160)
        self._object_list.itemChanged.connect(self._on_item_changed)
        obj_l.addWidget(self._object_list)
        self._per_object = QtWidgets.QCheckBox("One file per object")
        self._per_object.stateChanged.connect(lambda *_: self._save_prefs())
        obj_l.addWidget(self._per_object)
        layout.addWidget(self._objects_group)

        # -- Assembly note --------------------------------------------------
        self._assembly_note = QtWidgets.QLabel(
            "The whole assembly will be exported as a single file."
        )
        self._assembly_note.setWordWrap(True)
        layout.addWidget(self._assembly_note)

        # -- Format ---------------------------------------------------------
        fmt_group = QtWidgets.QGroupBox("Format")
        fmt_l = QtWidgets.QFormLayout(fmt_group)
        self._format_combo = QtWidgets.QComboBox()
        self._format_combo.addItems(_FORMATS)
        self._format_combo.currentTextChanged.connect(lambda *_: self._save_prefs())
        fmt_l.addRow("File format", self._format_combo)
        self._format_group = fmt_group
        layout.addWidget(fmt_group)

        # -- Mesh quality (the FreeCAD perk) --------------------------------
        self._quality_group = QtWidgets.QGroupBox("Mesh quality")
        q_l = QtWidgets.QFormLayout(self._quality_group)
        self._quality_combo = QtWidgets.QComboBox()
        for label, _key in _QUALITY_LABELS:
            self._quality_combo.addItem(label)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        q_l.addRow("Preset", self._quality_combo)

        self._linear_spin = QtWidgets.QDoubleSpinBox()
        self._linear_spin.setDecimals(3)
        self._linear_spin.setRange(0.001, 5.0)
        self._linear_spin.setSingleStep(0.01)
        self._linear_spin.setSuffix(" mm")
        self._linear_spin.valueChanged.connect(lambda *_: self._save_prefs())
        self._linear_row_label = QtWidgets.QLabel("Surface deviation")
        q_l.addRow(self._linear_row_label, self._linear_spin)

        self._angular_spin = QtWidgets.QDoubleSpinBox()
        self._angular_spin.setDecimals(1)
        self._angular_spin.setRange(1.0, 60.0)
        self._angular_spin.setSingleStep(1.0)
        self._angular_spin.setSuffix(" °")
        self._angular_spin.valueChanged.connect(lambda *_: self._save_prefs())
        self._angular_row_label = QtWidgets.QLabel("Angular deviation")
        q_l.addRow(self._angular_row_label, self._angular_spin)
        layout.addWidget(self._quality_group)

        # -- Physical preview (the FreeCAD perk) ----------------------------
        self._preview_group = QtWidgets.QGroupBox("Physical size")
        prev_l = QtWidgets.QVBoxLayout(self._preview_group)
        self._preview_label = QtWidgets.QLabel("–")
        self._preview_label.setWordWrap(True)
        prev_l.addWidget(self._preview_label)
        layout.addWidget(self._preview_group)

        # -- Send + progress ------------------------------------------------
        self._send_btn = QtWidgets.QPushButton("Send to SimplyPrint")
        self._send_btn.setMinimumHeight(34)
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status_label = QtWidgets.QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch(1)

    def _connect_signals(self):
        sig = state.signals()
        sig.auth_changed.connect(self.refresh)
        sig.status_changed.connect(self._set_status)
        sig.progress_changed.connect(self._on_progress)
        sig.upload_done.connect(self._on_upload_done)

    # ------------------------------------------------------------ prefs
    def _load_prefs(self):
        p = _params()
        fmt = p.GetString("Format", "STL")
        idx = self._format_combo.findText(fmt)
        self._format_combo.setCurrentIndex(idx if idx >= 0 else 0)

        quality = p.GetString("Quality", export.DEFAULT_QUALITY)
        keys = [k for _l, k in _QUALITY_LABELS]
        self._quality_combo.setCurrentIndex(keys.index(quality) if quality in keys else 1)

        self._linear_spin.setValue(p.GetFloat("CustomLinear", 0.1))
        self._angular_spin.setValue(p.GetFloat("CustomAngular", 20.0))
        self._per_object.setChecked(p.GetBool("PerObject", False))
        self._update_custom_rows()

    def _save_prefs(self):
        p = _params()
        p.SetString("Format", self._format_combo.currentText())
        p.SetString("Quality", self._quality_key())
        p.SetFloat("CustomLinear", self._linear_spin.value())
        p.SetFloat("CustomAngular", self._angular_spin.value())
        p.SetBool("PerObject", self._per_object.isChecked())

    def _quality_key(self) -> str:
        return _QUALITY_LABELS[self._quality_combo.currentIndex()][1]

    def _on_quality_changed(self, *_):
        self._update_custom_rows()
        self._save_prefs()

    def _update_custom_rows(self):
        custom = self._quality_key() == "custom"
        for w in (self._linear_spin, self._angular_spin, self._linear_row_label, self._angular_row_label):
            w.setVisible(custom)

    # --------------------------------------------------------- refresh
    def request_refresh(self):
        # Selection changed in the 3D view. Refresh account / preview / Send
        # state, but DON'T clobber the user's checklist: the object list is only
        # repopulated when the document's *structure* changes (see
        # _structure_signature), not when the viewport selection changes.
        QtCore.QTimer.singleShot(0, self.refresh)

    def _poll(self):
        if not self.isVisible():
            return  # no need to track context while the dock is hidden
        context = ctx_mod.current_context()
        if context.signature() != (self._context.signature() if self._context else None):
            self._context = context
            self._apply_context()

    def refresh(self):
        self._context = ctx_mod.current_context()
        self._apply_context()

    def _apply_context(self):
        context = self._context
        self._refresh_account()

        logged_in = state.is_logged_in()
        kind = context.kind

        structure_sig = self._structure_signature(context)
        structure_changed = structure_sig != self._last_structure_sig
        self._last_structure_sig = structure_sig

        # Decide which sections apply for this context.
        show_objects = kind in ("solids", "meshes", "mixed")
        show_assembly_note = kind == "assembly"
        show_quality = kind in ("solids", "mixed", "assembly")  # meshes are already faceted
        show_body = kind in ("solids", "meshes", "mixed", "assembly")

        self._objects_group.setVisible(show_objects)
        self._assembly_note.setVisible(show_assembly_note)
        self._quality_group.setVisible(show_quality)
        self._format_group.setVisible(show_body)
        self._preview_group.setVisible(show_body)
        self._send_btn.setVisible(show_body)

        # Context message for the non-printable cases.
        if kind == "none":
            self._context_msg.setText("Open or create a model to get started.")
            self._context_msg.setVisible(True)
        elif kind == "unsupported":
            self._context_msg.setText(
                "No 3D-printable geometry in this context. Switch to the Part, "
                "Part Design, Mesh or Assembly workbench, or open a model with "
                "solids or meshes."
            )
            self._context_msg.setVisible(True)
        else:
            self._context_msg.setVisible(False)

        if show_objects and structure_changed:
            self._populate_objects(context)

        self._update_preview()

        can_send = logged_in and not state.state.busy and show_body
        if show_objects:
            can_send = can_send and self._checked_objects_count() > 0
        self._send_btn.setEnabled(can_send)

    def _refresh_account(self):
        busy = state.state.busy
        if state.is_logged_in():
            self._account_label.setText(f"Signed in as {state.user_name()}")
            self._login_btn.setVisible(False)
            self._logout_btn.setVisible(True)
        else:
            self._account_label.setText(state.state.status or "Not signed in")
            self._login_btn.setVisible(True)
            self._logout_btn.setVisible(False)
        self._login_btn.setEnabled(not busy)

    # --------------------------------------------------------- objects
    def _structure_signature(self, context) -> str:
        parts = [context.kind, context.workbench_name, context.document_name]
        parts += [f"{o.name}:{o.kind}" for o in context.objects]
        return "|".join(parts)

    def _populate_objects(self, context):
        # Seed defaults: prefer the viewport selection, else all visible objects.
        self._user_touched_selection = False
        selected = set(context.selected_names)
        default_checked = selected if selected else {
            o.name for o in context.objects if o.visible
        }
        if not default_checked:
            default_checked = {o.name for o in context.objects}

        self._object_list.blockSignals(True)
        self._object_list.clear()
        for o in context.objects:
            item = QtWidgets.QListWidgetItem(o.label)
            item.setData(QtCore.Qt.UserRole, o.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if o.name in default_checked else QtCore.Qt.Unchecked
            )
            tip = "Mesh" if o.kind == "mesh" else "Solid"
            item.setToolTip(f"{o.name} ({tip})")
            self._object_list.addItem(item)
        self._object_list.blockSignals(False)
        self._update_selection_summary()

    def _on_item_changed(self, *_):
        self._user_touched_selection = True
        self._update_selection_summary()
        self._update_preview()
        # Re-evaluate the Send button enablement.
        self._send_btn.setEnabled(
            state.is_logged_in() and not state.state.busy and self._checked_objects_count() > 0
        )

    def _set_all_checked(self, checked: bool):
        self._object_list.blockSignals(True)
        for i in range(self._object_list.count()):
            self._object_list.item(i).setCheckState(
                QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
            )
        self._object_list.blockSignals(False)
        self._user_touched_selection = True
        self._update_selection_summary()
        self._update_preview()
        self._send_btn.setEnabled(
            state.is_logged_in() and not state.state.busy and self._checked_objects_count() > 0
        )

    def _checked_names(self):
        names = []
        for i in range(self._object_list.count()):
            item = self._object_list.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                names.append(item.data(QtCore.Qt.UserRole))
        return names

    def _checked_objects_count(self) -> int:
        return len(self._checked_names())

    def _update_selection_summary(self):
        total = self._object_list.count()
        checked = self._checked_objects_count()
        self._sel_summary.setText(f"{checked} of {total} selected")

    def _objects_for_send(self):
        """Live FreeCAD objects to export for the current context."""
        if self._context.kind == "assembly":
            return [o.obj for o in self._context.objects]
        checked = set(self._checked_names())
        return [o.obj for o in self._context.objects if o.name in checked]

    # --------------------------------------------------------- preview
    def _update_preview(self):
        if not self._preview_group.isVisible():
            return
        objs = self._objects_for_send()
        if not objs:
            self._preview_label.setText("–")
            return
        try:
            info = export.measure(objs)
            x, y, z = info["bbox"]
            lines = []
            if max(x, y, z) > 0:
                lines.append(f"Bounding box: {x:.1f} × {y:.1f} × {z:.1f} mm")
            if info["has_volume"]:
                lines.append(f"Volume: {info['volume_cm3']:.2f} cm³")
            self._preview_label.setText("\n".join(lines) if lines else "–")
        except Exception as exc:
            self._preview_label.setText(f"(could not measure: {exc})")

    # --------------------------------------------------------- handlers
    def _on_login(self):
        actions.start_login()

    def _on_logout(self):
        actions.logout()

    def _on_open_panel(self):
        import webbrowser

        webbrowser.open(api.make_panel_url())

    def _set_status(self, text: str):
        self._status_label.setText(text)
        if not state.is_logged_in():
            self._account_label.setText(text or "Not signed in")

    def _on_progress(self, sent: int, total: int):
        if total > 0:
            self._progress.setVisible(True)
            self._progress.setRange(0, 100)
            self._progress.setValue(int(sent / total * 100))

    def _on_upload_done(self, success: bool, message: str):
        self._progress.setVisible(False)
        self._send_btn.setEnabled(state.is_logged_in() and self._can_send_now())
        if success:
            self._status_label.setText(state.state.status)
        else:
            self._status_label.setText(message)

    def _can_send_now(self) -> bool:
        if self._context.kind == "assembly":
            return bool(self._context.objects)
        return self._checked_objects_count() > 0

    def _on_send(self):
        if not state.is_logged_in():
            self._set_status("Please log in first")
            return
        if state.state.busy:
            return

        objs = self._objects_for_send()
        if not objs:
            self._set_status("Select at least one object to send")
            return

        fmt = self._format_combo.currentText()
        quality = self._quality_key()
        custom_linear = self._linear_spin.value()
        custom_angular = self._angular_spin.value()
        per_object = self._per_object.isChecked() and self._context.kind != "assembly"
        base_name = self._context.document_name or "model"

        state.state.busy = True
        self._send_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # indeterminate during export
        self._set_status("Exporting…")
        QtCore.QCoreApplication.processEvents()

        out_dir = tempfile.mkdtemp(prefix="simplyprint_")
        try:
            paths = export.export_objects(
                objs,
                fmt=fmt,
                out_dir=out_dir,
                base_name=base_name,
                quality=quality,
                custom_linear=custom_linear,
                custom_angular=custom_angular,
                per_object=per_object,
            )
        except Exception as exc:
            import shutil

            shutil.rmtree(out_dir, ignore_errors=True)
            state.state.busy = False
            self._progress.setVisible(False)
            self._send_btn.setEnabled(True)
            self._set_status(f"Export failed: {exc}")
            return

        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        actions.upload_paths_async(paths, cleanup_dir=out_dir)


# --------------------------------------------------------------- module API

def get_panel():
    return _panel


def ensure_panel():
    """Create the dock panel (once) and attach it to the FreeCAD main window.

    The panel is NOT forced open – it would otherwise pop up on the Start page.
    It starts hidden (or restores the user's last choice) and is toggled from the
    persistent SimplyPrint toolbar button or View > Panels.
    """
    global _panel
    if _panel is not None:
        return _panel

    import FreeCADGui

    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return None

    _panel = SimplyPrintPanel(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel)
    _panel.setVisible(_params().GetBool("PanelVisible", False))
    _panel.visibilityChanged.connect(lambda vis: _params().SetBool("PanelVisible", bool(vis)))

    _install_toolbar(mw, _panel)
    return _panel


def _install_toolbar(mw, panel):
    """Add an always-available toolbar button (in every workbench) that toggles
    the panel. Uses the dock's own toggleViewAction so the button stays in sync
    and also shows up under View > Panels."""
    existing = mw.findChild(QtWidgets.QToolBar, "SimplyPrintToolBar")
    if existing is not None:
        return existing

    action = panel.toggleViewAction()
    action.setText("SimplyPrint")
    action.setToolTip("Show or hide the SimplyPrint panel")
    action.setIcon(QtGui.QIcon(os.path.join(ICONPATH, "simplyprint.svg")))

    toolbar = QtWidgets.QToolBar("SimplyPrint", mw)
    toolbar.setObjectName("SimplyPrintToolBar")
    toolbar.addAction(action)
    mw.addToolBar(QtCore.Qt.TopToolBarArea, toolbar)
    toolbar.setVisible(True)

    # FreeCAD rebuilds the toolbar area on workbench switches; re-assert ours so
    # the button stays available in every workbench.
    try:
        mw.workbenchActivated.connect(lambda *_: _reassert_toolbar(mw, toolbar))
    except Exception:
        pass
    return toolbar


def _reassert_toolbar(mw, toolbar):
    if mw.findChild(QtWidgets.QToolBar, "SimplyPrintToolBar") is None:
        mw.addToolBar(QtCore.Qt.TopToolBarArea, toolbar)
    toolbar.setVisible(True)


def toggle_panel():
    p = ensure_panel()
    if p is not None:
        p.setVisible(not p.isVisible())
    return p
