"""SessionPresetsMixin — user presets, workspaces, session auto-persist.

Extracted verbatim from main.py (openspec arch-b-c-e batch E, 2026-07-02).
Mixed into Main_Menu; methods keep their exact names and behaviour.
closeEvent (which calls _save_session) stays in main.py — window lifecycle.
"""
from __future__ import annotations

# P2.1 lint (F821): QInputDialog was used at _save_current_as_preset but
# never imported — the "Save Preset" action raised NameError on first use.
from PySide6.QtWidgets import QInputDialog, QMessageBox, QTableWidgetItem


class SessionPresetsMixin:
    def _set_shanghai_grid(self, *, is_3d):
        from sjtu_tpmshx.models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
        counts = SHANGHAI_GRID_3D if is_3d else SHANGHAI_GRID_2D
        for axis, count in zip('xyz', counts):
            getattr(self, 'le_N' + axis).setText(str(count))
        self.chk_wall_refine_3d.setChecked(False)
        self.chk_port_wall_refine.setChecked(True)
        self._user_edited_grid = True

    # Canonical presets shipped with the app; user presets append after
    # these. Index 0 is the prompt placeholder managed by the combo itself.
    _BUILTIN_PRESETS = [
        "Shanghai (3D Gyroid)",
        "Shanghai (2D Gyroid)",
        "Shanghai (3D Diamond)",
    ]

    def _set_sco2_nu_parameters(self, payload):
        from dataclasses import asdict
        from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
        settings = Sco2NuConfig(**payload).validate()
        self._sco2_nu_parameters = asdict(settings) if payload else {}
        label = getattr(self, 'lbl_sco2_nu_parameters', None)
        if label is not None:
            label.setText(f"{settings.parameter_version} · {settings.source}"
                          if settings.parameter_version else "未导入标定参数")
            label.setToolTip(settings.applicability)

    def _load_user_presets(self):
        """Return the list of user-defined preset dicts (possibly empty).

        Delegates to SessionManager (Plan #4 P2.3).
        """
        return self.sm.load_user_presets()

    def _save_user_presets(self, presets):
        """Persist user preset list. Delegates to SessionManager (P2.3)."""
        self.sm.save_user_presets(presets)

    def _resync_undo_baseline(self):
        """Reset the undo baseline (`_undo_last`) to the CURRENT text of
        every session line-edit.

        2026-05-20 UI sweep (Tier 25). The global undo stack records a
        field edit by comparing `editingFinished` text against
        `_undo_last`. A programmatic batch-write (preset / Reset /
        workspace switch / Shanghai defaults / session restore) rewrites
        many fields via `setText` WITHOUT emitting `editingFinished`, so
        `_undo_last` stayed at the pre-write values. The next manual edit
        then pushed an undo command whose "old" value was the
        pre-programmatic text — Ctrl+Z would jump back across the entire
        preset load to a stale value. Treat these batch writes as undo
        checkpoints: after the write, snap the baseline to the new text
        so undo reverts to the post-preset state, not before it.
        """
        ul = getattr(self, '_undo_last', None)
        if ul is None:
            return
        for _nm in self._SESSION_LINE_EDITS:
            _le = getattr(self, _nm, None)
            if _le is not None:
                try:
                    ul[_nm] = _le.text()
                except Exception:
                    pass

    def _invalidate_results_for_preset_load(self):
        """Drop every cached compute artefact so a freshly-loaded preset
        cannot show the previous run's plots next to its new inputs.

        Added 2026-05-20 UI sweep (Tier 18). Called from
        ``_apply_user_preset`` — covers both the explicit Load Preset
        path and the Recent-run click path (which routes through the
        same helper).
        """
        # 2D-mode result flags + cached fields.
        self._has_results_2d = False
        self.T_fA = self.T_fB = self.T_s = None
        self._compute_results = None
        # 3D-mode result flags + cached fields.
        self._has_results_3d = False
        # U1 (2026-06-28): 3D View tab readiness (PyVista panel populated) is a
        # SEPARATE flag from result-presence (_has_results_3d). A soft viz-fail
        # keeps the result (exportable) but leaves this False (tab disabled).
        self._3d_view_ready = False
        self._result_3d = None
        self._tout_K_cache = None
        # Aggregate flag + draw tracker — keep in lock-step with the two
        # mode-specific flags above.
        self._has_results = False
        self._drawn_tabs = set()
        # Reset the outlet temperature display so a stale value can't be
        # mistaken for the post-preset result.
        for attr in ('_r_ToutA', '_r_ToutB', '_r_dP_A', '_r_dP_B', '_r_Q'):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.setText("—")  # em dash
                except Exception:
                    pass
        # Refresh tab visibility so the result tabs (Temp/Pres/Vel/3D)
        # disable now that there are no results to show.
        try:
            self._update_tab_visibility()
        except Exception:
            pass
        # Disable the export button — there is nothing to export.
        for _bname in ('btn_export',):
            _b = getattr(self, _bname, None)
            if _b is not None:
                try:
                    _b.setEnabled(False)
                except Exception:
                    pass

    def _apply_user_preset(self, preset):
        """Apply a saved preset payload (shape matches _save_session output).

        Widget names are filtered through the SESSION allow-lists so a tampered
        or malicious share-link cannot address arbitrary window attributes.

        2026-05-20 UI sweep (Tier 18): also invalidate compute-result
        caches up front. Prior to this, loading a preset (or clicking a
        Recent run via ``_load_recent_run`` which delegates here) only
        rewrote the input fields. The result flags / drawn tabs / cached
        3D result dict / 2D T_fA/T_fB/T_s arrays all survived, so the
        Temperature/Velocity/Pressure/3D tabs remained ENABLED and the
        canvas still showed the PREVIOUS compute's plots next to the
        freshly-loaded parameters. Easy to read as "preset applied",
        miss that the visible result is stale, then quote a number from
        the old compute as if it were the new design's.
        """
        self._validate_preset(preset)
        self._invalidate_results_for_preset_load()
        unit = preset.get('temp_unit', 'K')
        if unit in ('K', 'C'):
            self._temp_unit = unit
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        allowed_edits = set(self._SESSION_LINE_EDITS)
        allowed_checks = set(self._PRESET_CHECKS)
        for name, txt in (preset.get('line_edits') or {}).items():
            if name not in allowed_edits:
                continue
            w = getattr(self, name, None)
            if w is not None:
                try: w.setText(str(txt))
                except Exception: pass
        # Shape rebuilds polygon edge options: restore in canonical order,
        # independent of JSON object key order.
        self._set_sco2_nu_parameters(preset.get('sco2_nu_parameters', {}))
        combos = dict(preset.get('combos') or {})
        combos.setdefault('combo_df_mode', 0)  # legacy saved inputs used smooth CFD
        combos.setdefault('combo_sco2_nu_mode', 0)
        for name in self._PRESET_COMBOS:
            if name not in combos:
                continue
            idx = combos[name]
            c = getattr(self, name, None)
            if c is not None:
                try:
                    if 0 <= int(idx) < c.count():
                        # The preset's explicit line_edits (written just above)
                        # are the authoritative inlet conditions. Block the
                        # fluid combos' currentIndexChanged so _apply_fluid_
                        # defaults can't re-derive generic _FLUID_DEFAULTS and
                        # clobber them (same hole the 2026-06-24 audit fixed for
                        # _apply_shanghai_defaults). Audit: r2-ui-03.
                        if name in ('combo_fluidA', 'combo_fluidB'):
                            c.blockSignals(True)
                            c.setCurrentIndex(int(idx))
                            c.blockSignals(False)
                        else:
                            if (name == 'combo_shape' and int(idx) > 0
                                    and c.currentIndex() == int(idx)):
                                self._update_edge_combos()
                            c.setCurrentIndex(int(idx))
                except Exception: pass
        checks = dict(preset.get('checks') or {})
        checks.setdefault('chk_port_wall_refine', False)
        for side in ('A', 'B'):
            checks.setdefault(f'chk_uniform_inlet{side}_2d', False)
        for name, val in checks.items():
            if name not in allowed_checks:
                continue
            b = getattr(self, name, None)
            if b is not None:
                try: b.setChecked(bool(val))
                except Exception: pass

        zones = preset.get('zone_inputs')
        if zones is not None:
            self._grid_nx = zones['grid_nx']
            table = self.zone_table
            rows = zones['rows']
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    table.setItem(r, c, QTableWidgetItem(value))
            self._zone_grid = None  # derived by config_from_window, never persisted
            from sjtu_tpmshx.ui.zone_table import zone_resize
            zone_resize(self)
            self._pareto_x_decision = zones['pareto_x_decision']
            self._pareto_y_trans_inlet = zones['pareto_y_trans_inlet']
            self._pareto_y_trans_outlet = zones['pareto_y_trans_outlet']
        self._user_edited_grid = True
        self._resync_undo_baseline()
        # Fluid signals are blocked above to preserve the preset's inputs.
        from sjtu_tpmshx.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(self)
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()

    def _validate_preset(self, preset, *, complete=False):
        """Check the payload before touching widgets; old partial presets stay valid."""
        import math

        if not isinstance(preset, dict):
            raise ValueError('Preset must be a JSON object.')
        if complete and set(preset) - {'sco2_nu_parameters'} != {'name', 'temp_unit', 'line_edits',
                                       'combos', 'checks', 'zone_inputs'}:
            raise ValueError('Incomplete or unsupported preset fields.')
        from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
        from dataclasses import replace
        parameters = Sco2NuConfig(**preset.get('sco2_nu_parameters', {})).validate()
        if preset.get('temp_unit', 'K') not in ('K', 'C'):
            raise ValueError('Unsupported temperature unit.')
        combos = preset.get('combos', {})
        if not isinstance(combos, dict):
            raise ValueError('Invalid combos.')
        if combos.get('combo_sco2_nu_mode', 0) == 1:
            replace(parameters, mode='experimental').validate()
        shape = combos.get('combo_shape', self.combo_shape.currentIndex())
        for section, allowed in (('line_edits', self._SESSION_LINE_EDITS),
                                 ('combos', self._PRESET_COMBOS),
                                 ('checks', self._PRESET_CHECKS)):
            values = preset.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f'Invalid {section}.')
            required = {n for n in allowed if getattr(self, n, None) is not None}
            if section == 'combos' and shape == 0:
                required -= set(self._POLYGON_COMBOS)
            if section == 'combos' and 'combo_sco2_nu_mode' not in values:
                required.discard('combo_sco2_nu_mode')  # old saved configs default to CFD
            if section == 'checks' and 'chk_port_wall_refine' not in values:
                required.discard('chk_port_wall_refine')
            if complete and set(values) != required:
                raise ValueError(f'Incomplete or unsupported {section}: '
                                 f'{sorted(set(values) ^ required)}')
            for name, value in values.items():
                if name not in allowed:
                    continue  # retain the shared preset allow-list boundary
                if section == 'line_edits' and type(value) not in (str, int, float):
                    raise ValueError(f'Invalid text field: {name}')
                if (section == 'line_edits' and name != 'le_mesh_density'
                        and str(value).strip()):
                    try:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError()
                        if name in ('le_Nx', 'le_Ny', 'le_Nz'):
                            int(str(value))
                    except (TypeError, ValueError):
                        raise ValueError(f'Invalid numeric field: {name}') from None
                if section == 'combos':
                    widget = getattr(self, name, None)
                    count = ((6 if shape == 1 else 8) if name in self._POLYGON_COMBOS
                             and shape in (1, 2) else widget.count() if widget else 0)
                    if type(value) is not int or (widget is not None and
                                                not 0 <= value < count):
                        raise ValueError(f'Unsupported selection: {name}')
                if section == 'checks' and type(value) is not bool:
                    raise ValueError(f'Invalid checkbox: {name}')
        if any(n in combos for n in self._POLYGON_COMBOS):
            edits = preset.get('line_edits', {})
            if any(not str(edits.get(n, getattr(self, n).text())).strip()
                   for n in ('le_L', 'le_H')):
                raise ValueError('Polygon edge options require domain dimensions.')
        zones = preset.get('zone_inputs')
        if complete and ('temp_unit' not in preset or zones is None):
            raise ValueError('Incomplete configuration: missing unit or zone inputs.')
        if zones is None:
            return
        keys = {'rows', 'grid_nx', 'pareto_x_decision',
                'pareto_y_trans_inlet', 'pareto_y_trans_outlet'}
        if not isinstance(zones, dict) or set(zones) != keys:
            raise ValueError('Incomplete or unsupported zone inputs.')
        axis = preset.get('combos', {}).get('combo_zone_axis')
        if axis not in (0, 1, 2):
            raise ValueError('Zone inputs require an explicit axis.')
        rows, nx = zones['rows'], zones['grid_nx']
        if type(nx) is not int or nx < 1 or not isinstance(rows, list):
            raise ValueError('Invalid zone grid size.')
        if axis == 2 and len(rows) % nx:
            raise ValueError('Zone rows do not match grid size.')
        if any(not isinstance(row, list) or len(row) != (6 if axis == 2 else 4)
               or any(not isinstance(v, str) for v in row) for row in rows):
            raise ValueError('Invalid zone table.')
        if preset.get('checks', {}).get('chk_zones'):
            try:
                if not rows or any(not math.isfinite(float(v))
                                   for row in rows for v in row):
                    raise ValueError()
            except ValueError:
                raise ValueError('Enabled zones require complete numeric rows.') from None
        decision = zones['pareto_x_decision']
        numbers = [zones['pareto_y_trans_inlet'], zones['pareto_y_trans_outlet']]
        if decision is not None:
            if not isinstance(decision, list) or len(decision) != 36:
                raise ValueError('Pareto decision must contain 36 values.')
            numbers += decision
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in numbers):
            raise ValueError('Invalid Pareto input.')

    def _capture_current_preset(self, name):
        """Build a preset payload from the current field state."""
        payload = {'name': name,
                   'temp_unit': getattr(self, '_temp_unit', 'K'),
                   'line_edits': {}, 'combos': {}, 'checks': {},
                   'sco2_nu_parameters': dict(getattr(self, '_sco2_nu_parameters', {}))}
        for n in self._SESSION_LINE_EDITS:
            w = getattr(self, n, None)
            if w is not None:
                try: payload['line_edits'][n] = w.text()
                except Exception: pass
        for n in self._PRESET_COMBOS:
            if n in self._POLYGON_COMBOS and self.combo_shape.currentIndex() == 0:
                continue
            c = getattr(self, n, None)
            if c is not None:
                try: payload['combos'][n] = int(c.currentIndex())
                except Exception: pass
        for n in self._PRESET_CHECKS:
            b = getattr(self, n, None)
            if b is not None:
                try: payload['checks'][n] = bool(b.isChecked())
                except Exception: pass
        if hasattr(self, 'zone_table'):
            table = self.zone_table
            decision = getattr(self, '_pareto_x_decision', None)
            payload['zone_inputs'] = {
                'rows': [[table.item(r, c).text() if table.item(r, c) else ''
                          for c in range(table.columnCount())]
                         for r in range(table.rowCount())],
                'grid_nx': self._grid_nx,
                'pareto_x_decision': (list(map(float, decision))
                                      if decision is not None else None),
                'pareto_y_trans_inlet': getattr(self, '_pareto_y_trans_inlet', 0.2),
                'pareto_y_trans_outlet': getattr(self, '_pareto_y_trans_outlet', 0.2),
            }
        return payload

    def _load_named_preset(self, name):
        """Load a built-in canonical preset by name. Wired from the header
        载入 ▾ menu and the command palette (replaces the old index-based
        combo handler)."""
        if name not in self._BUILTIN_PRESETS:
            return
        self._active_preset_name = name
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
        # Builtin presets rewrite inputs via _apply_shanghai_defaults, which
        # does NOT route through _apply_user_preset (where the result-cache
        # invalidate lives). Invalidate here so stale result tabs/plots/export
        # from a prior compute don't survive a builtin-preset switch.
        self._invalidate_results_for_preset_load()
        self._apply_shanghai_defaults()
        if name == "Shanghai (2D Gyroid)":
            self.combo_dim.setCurrentIndex(0)
            self._set_shanghai_grid(is_3d=False)
        elif name == "Shanghai (3D Diamond)":
            self.combo_tpms.setCurrentIndex(0)
        self.statusBar().showMessage(f"Preset: {name}.", 5000)

    def _save_current_as_preset(self):
        """Prompt for a name and persist the full current field state as a
        user preset. Overwrites silently on duplicate name."""
        name, ok = QInputDialog.getText(
            self, "Save Preset",
            "Preset name:", text="my_preset")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._load_user_presets()
        presets = [p for p in presets if p.get('name') != name]  # overwrite
        presets.append(self._capture_current_preset(name))
        self._save_user_presets(presets)
        self._rebuild_recent_menu()
        self.statusBar().showMessage(
            f"Saved preset: {name}.", 5000)

    # ─────────────────────────────────────────────────────────
    #  Session auto-persist (restores last-used field state)
    # ─────────────────────────────────────────────────────────
    _SESSION_LINE_EDITS = (
        'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t', 'le_ks',
        'le_uA', 'le_TinA', 'le_PinA', 'le_uB', 'le_TinB', 'le_PinB',
        # le_TsInit removed 2026-04-29 (numerical seed only, not physical)
        'le_Nx', 'le_Ny', 'le_Nz',
        'le_rho_s',
        'le_pipeA_in_ctr', 'le_pipeA_in_w',
        'le_pipeA_out_ctr', 'le_pipeA_out_w',
        'le_pipeB_in_ctr', 'le_pipeB_in_w',
        'le_pipeB_out_ctr', 'le_pipeB_out_w',
        'le_pipeA_in_z_ctr', 'le_pipeA_in_z_w',
        'le_pipeA_out_z_ctr', 'le_pipeA_out_z_w',
        'le_pipeB_in_z_ctr', 'le_pipeB_in_z_w',
        'le_pipeB_out_z_ctr', 'le_pipeB_out_z_w',
        'le_mesh_density',
    )
    _SESSION_COMBOS = (
        'combo_shape', 'combo_dim', 'combo_tpms',
        'combo_df_mode', 'combo_sco2_nu_mode',
        'combo_fluidA', 'combo_fluidB',
        'combo_dirA', 'combo_dirB',
    )
    _SESSION_CHECKS = ('chk_zones', 'chk_wall_refine_3d', 'chk_port_wall_refine', 'chk_var_rhocp',
                       'chk_uniform_inletA_2d', 'chk_uniform_inletB_2d')
    # Explicit loads restore inputs; startup sessions retain their reset policy.
    _POLYGON_COMBOS = ('combo_edge_inA', 'combo_edge_outA',
                       'combo_edge_inB', 'combo_edge_outB')
    _PRESET_COMBOS = _SESSION_COMBOS + ('combo_zone_axis',) + _POLYGON_COMBOS
    _PRESET_CHECKS = _SESSION_CHECKS + ('chk_allow_extrap',)

    _WORKSPACES = ('A', 'B', 'C')

    def _switch_workspace(self, new):
        """Persist the current workspace, activate `new`, and reload it."""
        if new not in self._WORKSPACES:
            return
        cur = getattr(self, '_active_workspace', 'A')
        if cur == new:
            return
        try:
            self._save_session()  # saves to the current workspace path
        except Exception:
            pass
        self._active_workspace = new
        # Tier 25: a workspace switch reloads a completely different input
        # set, so the current compute result belongs to the OLD workspace.
        # Invalidate it before re-seeding so the new workspace doesn't open
        # showing the previous workspace's result tabs / plots / export.
        self._invalidate_results_for_preset_load()
        try:
            self._apply_shanghai_defaults()
            self._restore_session()
        except Exception as e:
            QMessageBox.warning(self, "Workspace switch", str(e))
        if hasattr(self, '_rebuild_workspace_menu'):
            self._rebuild_workspace_menu()
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
        # Persist the choice so the next launch re-opens the same workspace.
        # Delegates to SessionManager (P2.3).
        # 2026-05-20 UI sweep (Tier 18): SessionManager.set_active_workspace
        # returns False on IO failure. Previously this return was ignored,
        # so a marker-write failure silently reverted the next launch to
        # workspace 'A'. Surface the failure to the status bar so the
        # user knows to re-pick the workspace after restart.
        _wrote = False
        try:
            _wrote = bool(self.sm.set_active_workspace(new))
        except Exception:
            _wrote = False
        if _wrote:
            self.statusBar().showMessage(f"Workspace {new} loaded.", 4000)
        else:
            self.statusBar().showMessage(
                f"Workspace {new} loaded — but writing the active-workspace "
                f"marker failed; next launch may default to 'A'.", 8000)

    def _rebuild_workspace_menu(self):
        """Refresh the header Workspace ▾ menu to reflect the active tab."""
        from PySide6.QtWidgets import QMenu
        if not hasattr(self, 'btn_workspace'):
            return
        active = getattr(self, '_active_workspace', 'A')
        self.btn_workspace.setText(f"WS: {active} ▾")
        menu = QMenu(self)
        for ws in self._WORKSPACES:
            mark = "● " if ws == active else "   "
            act = menu.addAction(f"{mark}Workspace {ws}")
            act.triggered.connect(
                lambda _checked=False, name=ws: self._switch_workspace(name))
        self.btn_workspace.setMenu(menu)

    def _save_session(self):
        """Dump every input field's current value via SessionManager (P2.3).

        Best-effort: any attribute that is missing or that throws on read
        is silently skipped — partial sessions still reload cleanly
        (missing keys fall back to the Shanghai preset).
        """
        payload = {'temp_unit': getattr(self, '_temp_unit', 'K'),
                   'sco2_nu_parameters': dict(getattr(self, '_sco2_nu_parameters', {}))}
        lines = {}
        for name in self._SESSION_LINE_EDITS:
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                lines[name] = w.text()
            except Exception:
                continue
        payload['line_edits'] = lines
        combos = {}
        for name in self._SESSION_COMBOS:
            c = getattr(self, name, None)
            if c is None:
                continue
            try:
                combos[name] = int(c.currentIndex())
            except Exception:
                continue
        payload['combos'] = combos
        checks = {}
        for name in self._SESSION_CHECKS:
            b = getattr(self, name, None)
            if b is None:
                continue
            try:
                checks[name] = bool(b.isChecked())
            except Exception:
                continue
        payload['checks'] = checks
        # Workbench UI state (ui-shortcuts-persist): last tab (result-family
        # keys collapse to 'result' so restore re-resolves via _result_view),
        # left-panel collapse, 2D|3D result-view choice.
        _tab = getattr(self, '_active_tab', 'layout')
        if _tab in ('temp', 'pres', 'vel', '3d', '2d_view'):
            _tab = 'result'
        payload['ui_state'] = {
            'active_tab': _tab,
            'left_collapsed': bool(getattr(self, '_left_collapsed', False)),
            'result_view': getattr(self, '_result_view', '2d'),
        }
        # Window geometry + state (maximised, size, position). Store as
        # base64 so the JSON stays readable when the rest is inspected.
        try:
            import base64 as _b64
            geo = bytes(self.saveGeometry())
            st = bytes(self.saveState())
            payload['geometry'] = _b64.b64encode(geo).decode('ascii')
            payload['win_state'] = _b64.b64encode(st).decode('ascii')
        except Exception:
            pass
        # SessionManager handles IO failure silently + stamps schema_version.
        # 2026-05-20 UI sweep (Tier 18): return SessionManager's bool so
        # callers (notably _toggle_theme's restart path) can abort on a
        # silent IO failure instead of execv'ing into a process that has
        # lost the user's pending edits.
        return bool(self.sm.save_session(
            payload, getattr(self, '_active_workspace', 'A')))

    def _restore_session(self):
        """Load values saved by `_save_session` on top of the Shanghai
        defaults. Silently no-ops if the file doesn't exist or is malformed.

        Delegates IO to SessionManager (P2.3).
        """
        ws = getattr(self, '_active_workspace', 'A')
        payload = self.sm.load_session(ws)
        if payload is None:
            return
        self.combo_df_mode.setCurrentIndex(0)  # preserve legacy sessions without this field
        self._set_sco2_nu_parameters(payload.get('sco2_nu_parameters', {}))
        nu_combo = getattr(self, 'combo_sco2_nu_mode', None)
        if nu_combo is not None:
            nu_combo.setCurrentIndex(0)
        # Apply temp_unit first so we can interpret text correctly. The JSON
        # stores text as the user saw it, so matching units is the safe path.
        saved_unit = payload.get('temp_unit', 'K')
        if saved_unit in ('K', 'C'):
            self._temp_unit = saved_unit
            # Header button + row labels need to match the restored unit so
            # the restored text ("148.85") is not misread as Kelvin.
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        # User preference: app must open with temperature unit = K. If the
        # saved session was authored in °C, the line-edit text below is in
        # °C — restore it as-is, then convert + flip the unit to K so the
        # initial view is always Kelvin.
        _temp_field_names = {'le_TinA', 'le_TinB'}
        for name, txt in (payload.get('line_edits') or {}).items():
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                w.setText(str(txt))
            except Exception:
                continue
        if saved_unit == 'C':
            for name in _temp_field_names:
                w = getattr(self, name, None)
                if w is None:
                    continue
                try:
                    val = float(w.text())
                    w.setText(f"{val + 273.15:.2f}")
                except (ValueError, TypeError):
                    continue
            self._temp_unit = 'K'
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        for name, idx in (payload.get('combos') or {}).items():
            # The app must open in the canonical Shanghai topology regardless
            # of what the previous session stored: fluids A=Air / B=Water and
            # crossflow directions A:+x / B:-y. Skip restoring these four so
            # the construction + _apply_shanghai_defaults values stand — a
            # stale session must not rotate the case (A:+y B:-x) or swap the
            # cold fluid back to Air.
            if name in ('combo_fluidA', 'combo_fluidB',
                        'combo_dirA', 'combo_dirB'):
                continue
            c = getattr(self, name, None)
            if c is None:
                continue
            try:
                if 0 <= int(idx) < c.count():
                    c.setCurrentIndex(int(idx))
            except Exception:
                continue
        checks = dict(payload.get('checks') or {})
        for side in ('A', 'B'):
            checks.setdefault(f'chk_uniform_inlet{side}_2d', False)
        for name, val in checks.items():
            b = getattr(self, name, None)
            if b is None:
                continue
            try:
                b.setChecked(bool(val))
            except Exception:
                continue
        # Restore window geometry / dock state last so it doesn't fight the
        # `showMaximized()` the constructor already called. Pass-through:
        # if the payload is missing or corrupt, the explicit showMaximized
        # wins and the user sees the standard maximised window.
        import base64 as _b64
        from PySide6.QtCore import QByteArray
        geo_b64 = payload.get('geometry')
        if geo_b64:
            try:
                self.restoreGeometry(QByteArray(_b64.b64decode(geo_b64)))
            except Exception:
                pass
        st_b64 = payload.get('win_state')
        if st_b64:
            try:
                self.restoreState(QByteArray(_b64.b64decode(st_b64)))
            except Exception:
                pass
        # The restore loop above SKIPS the fluid combos, so each stays at its
        # construction-time index: A = 0 (Air), B = 1 (Water, pinned by
        # _apply_shanghai_defaults). The restored line-edits, however, are in
        # whatever fluid range the SAVED combo had. Push the LIVE fluid's
        # defaults only when the saved index DIFFERS from the held index — i.e.
        # the line-edits are in a different fluid's range than the live combo.
        # Gating on `!= 0` (the old code) was wrong for B (held=1): a saved
        # Air-B left Air velocities under a Water combo (r2-ui-01), and a saved
        # Water-B clobbered the user's custom Water inlet (r2-ui-02).
        _saved_combos = payload.get('combos') or {}
        for _side in ('A', 'B'):
            _held = 0 if _side == 'A' else 1
            try:
                _saved_idx = int(_saved_combos.get(f'combo_fluid{_side}', _held))
            except (ValueError, TypeError):
                _saved_idx = _held
            if _saved_idx != _held:
                try:
                    self._apply_fluid_defaults(_side)
                except Exception:
                    pass
        # Keep the existing startup-reset policy, using the current Shanghai
        # grid. Explicit preset loads and subsequent manual edits keep theirs.
        _saved_grid = (payload.get('line_edits') or {})
        self._set_shanghai_grid(is_3d=self.combo_dim.currentIndex() == 1)
        _grid_was_custom = any(
            str(_saved_grid.get(_n, '')).strip() not in ('', getattr(self, _n).text())
            for _n in ('le_Nx', 'le_Ny', 'le_Nz'))
        # Surface reset notices via deferred status bar — wait until the
        # window is shown so the message isn't eaten by subsequent renders.
        from PySide6.QtCore import QTimer as _QT_msg
        _msgs = []
        if _grid_was_custom:
            _msgs.append("Grid reset to Shanghai recommendation: " + "×".join(
                getattr(self, 'le_N' + axis).text() for axis in 'xyz'))
        _saved_combos2 = payload.get('combos') or {}
        if any(int(_saved_combos2.get(f'combo_fluid{_s}', 0) or 0) != 0
               for _s in ('A', 'B')):
            _msgs.append("Fluid type reset to Air (default; saved selection discarded)")
        if _msgs:
            def _flash():
                try:
                    self.statusBar().showMessage(" · ".join(_msgs), 8000)
                except Exception:
                    pass
            _QT_msg.singleShot(800, _flash)
        # Workbench UI state (ui-shortcuts-persist) — best-effort, mirrors
        # the save side. result_view first (so a restored 'result' tab
        # resolves to the saved side), then the left panel, then the tab.
        # A gated-off saved tab falls back through _switch_tab's own
        # button-disabled path (→ layout); no new fallback logic here.
        _ui = payload.get('ui_state') or {}
        try:
            _rvw = _ui.get('result_view')
            if _rvw in ('2d', '3d'):
                self._result_view = _rvw
                _paint = getattr(self, '_paint_result_seg', None)
                if _paint is not None:
                    _paint()
            if bool(_ui.get('left_collapsed')) != bool(
                    getattr(self, '_left_collapsed', False)):
                self._toggle_left_panel()
            _tab = _ui.get('active_tab')
            if _tab in ('layout', 'result', 'pareto') and \
                    _tab != getattr(self, '_active_tab', 'layout'):
                self._switch_tab(_tab)
        except Exception:
            pass
        # Tier 25: the restore above rewrote every field via setText with
        # no editingFinished — snap the undo baseline to the restored
        # state so the user's first manual edit undoes to what they see,
        # not to the construction-time defaults.
        self._resync_undo_baseline()
        from sjtu_tpmshx.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(self)
