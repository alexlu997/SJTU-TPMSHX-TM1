"""SessionPresetsMixin — user presets, workspaces, session auto-persist.

Extracted verbatim from main.py (openspec arch-b-c-e batch E, 2026-07-02).
Mixed into Main_Menu; methods keep their exact names and behaviour.
closeEvent (which calls _save_session) stays in main.py — window lifecycle.
"""
from __future__ import annotations

# P2.1 lint (F821): QInputDialog was used at _save_current_as_preset but
# never imported — the "Save Preset" action raised NameError on first use.
from PySide6.QtWidgets import QInputDialog, QMessageBox, QTableWidgetItem

from sjtu_tpmshx.ui.window_config import DOMAIN_SHAPE_NOTICE, validate_domain_shape


def shanghai_field_defaults(*, is_3d: bool) -> dict[str, str]:
    """Canonical input-field values for the shipped case, authored in K."""
    from sjtu_tpmshx.models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
    values = {
        # Shanghai Electric gas-heater experimental log (工况8, Re_air=5000,
        # Re_water=400) — raw values from `data/raw_data/
        # 20260401-上海电气天然气加热器实验工况.xlsx` Sheet1 row 9:
        #   col 24 water_in  = 26.89 °C   → 300.04 K
        #   col 26 water_P   = 647.60 Pa (gauge)  → 101972.60 abs
        #   col 28 air_in    = 148.908 °C → 422.06 K
        #   col 30 air_P     = 91037.40 Pa (gauge) → 192362.40 abs
        #   col 10 air_SLM   = 1057  → u_A ~20 m/s interstitial (Gyroid L7/t0.6)
        #   col 11 water_flow= 5193 ml/min → u_B ~0.133 m/s interstitial
        'le_L':     '0.182',  # L domain [m]
        'le_H':     '0.042',
        'le_Lz':    '0.042',
        'le_Lcell': '7.0',
        'le_t':     '0.6',
        'le_ks':    '16.0',   # Shanghai SS solid k_s
        'le_rho_s': '7900',
        'le_uA':    '20.0',   # Fluid A (air) interstitial, back-calc Re=5000
        'le_TinA':  '422.0',  # Fluid A inlet (Excel col 28: 148.908 °C)
        'le_PinA':  '192362', # Fluid A inlet absolute (Excel 91037 Pa gauge + atm)
        'le_uB':    '0.133',  # Fluid B (water) — Shanghai case 8 Re_water=400
        'le_TinB':  '300.0',  # Fluid B inlet (Excel col 24: 26.89 °C)
        'le_PinB':  '101973', # Fluid B inlet absolute (Excel 647.6 Pa gauge + atm)
        # Shanghai pipe inlet/outlet: A full-width (42 mm strip), B
        # staggered cross-flow (water enters top-right +x end, exits
        # bottom-left -x end; inlet/outlet 42 mm strips along real x).
        # A flows +x: full H=42mm face inlet/outlet.
        # B flows -y: staggered cross-flow, inlet at x=154mm (w=42mm),
        # outlet at x=28mm (w=42mm).
        'le_pipeA_in_ctr':  '0.021', 'le_pipeA_in_w':  '0.042',
        'le_pipeA_out_ctr': '0.021', 'le_pipeA_out_w': '0.042',
        'le_pipeB_in_ctr':  '0.154', 'le_pipeB_in_w':  '0.042',
        'le_pipeB_out_ctr': '0.028', 'le_pipeB_out_w': '0.042',
        # Both networks span the full thickness; reset prior-case Z ports.
        'le_pipeA_in_z_ctr':  '0.021', 'le_pipeA_in_z_w':  '0.042',
        'le_pipeA_out_z_ctr': '0.021', 'le_pipeA_out_z_w': '0.042',
        'le_pipeB_in_z_ctr':  '0.021', 'le_pipeB_in_z_w':  '0.042',
        'le_pipeB_out_z_ctr': '0.021', 'le_pipeB_out_z_w': '0.042',
    }
    counts = SHANGHAI_GRID_3D if is_3d else SHANGHAI_GRID_2D
    values.update({f'le_N{axis}': str(count) for axis, count in zip('xyz', counts)})
    return values


class SessionPresetsMixin:
    def _set_shanghai_grid(self, *, is_3d):
        from sjtu_tpmshx.models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
        counts = SHANGHAI_GRID_3D if is_3d else SHANGHAI_GRID_2D
        for axis, count in zip('xyz', counts):
            getattr(self, 'le_N' + axis).setText(str(count))
        self.combo_grid.setCurrentIndex(self.combo_grid.findData(True))
        self._user_edited_grid = True

    # Canonical presets shipped with the app; user presets append after
    # these. Index 0 is the prompt placeholder managed by the combo itself.
    _BUILTIN_PRESETS = [
        "Shanghai (3D Gyroid)",
        "Shanghai (2D Gyroid)",
        "Shanghai (3D Diamond)",
    ]

    def _use_current_sco2_nu_parameters(self):
        """Explicitly replace draft parameters with the current total amplitudes."""
        from dataclasses import asdict
        from sjtu_tpmshx.models.nu_correlations import sco2_effective_nu_config

        self._set_sco2_nu_parameters(asdict(sco2_effective_nu_config()))
        self.combo_sco2_nu_mode.setCurrentIndex(
            self.combo_sco2_nu_mode.findData('experimental'))

    def _set_sco2_nu_parameters(self, payload):
        from dataclasses import asdict
        from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
        settings = Sco2NuConfig(**payload).validate()
        self._sco2_nu_parameters = asdict(settings) if payload else {}
        label = getattr(self, 'lbl_sco2_nu_parameters', None)
        if label is not None:
            label.setText(f"Ceff: G={settings.alpha_G}, D={settings.alpha_D}\n{settings.parameter_version}"
                          if settings.parameter_version else "未导入标定参数")
            label.setToolTip(f"{settings.source}\n{settings.applicability}")

    def _load_user_presets(self):
        """Return the list of user-defined preset dicts (possibly empty).

        Delegates to SessionManager (Plan #4 P2.3).
        """
        return self.sm.load_user_presets()

    def _save_user_presets(self, presets):
        """Persist user preset list. Delegates to SessionManager (P2.3)."""
        return self.sm.save_user_presets(presets)

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
        self.cache.clear()
        self._3d_view_ready = False
        self._tout_K_cache = None
        self._diag_summary = {}
        self._update_result_summary()
        # Refresh tab visibility so the result tabs (Temp/Pres/Vel/3D)
        # disable now that there are no results to show.
        try:
            self._update_tab_visibility()
        except Exception:
            pass
        # The separate optimization figure can remain available for export.
        self._refresh_export_button()

    def _apply_user_preset(self, preset, *, show_notice=True, partial=False):
        """Apply a saved preset payload (shape matches _save_session output).

        Widget names are filtered through the SESSION allow-lists so a tampered
        or malicious share-link cannot address arbitrary window attributes.

        2026-05-20 UI sweep (Tier 18): also invalidate compute-result
        caches up front. Prior to this, loading a preset (or clicking a
        Recent run via ``_load_recent_run`` which delegates here) only
        rewrote the input fields. The result flags / drawn tabs / cached
        3D result / 2D field caches all survived, so the
        Temperature/Velocity/Pressure/3D tabs remained ENABLED and the
        canvas still showed the PREVIOUS compute's plots next to the
        freshly-loaded parameters. Easy to read as "preset applied",
        miss that the visible result is stale, then quote a number from
        the old compute as if it were the new design's.
        """
        if partial:
            # File patches own only the supplied fields. Full saved presets
            # and sessions retain their existing historical-default policy.
            if not isinstance(preset, dict):
                raise ValueError('Preset must be a JSON object.')
            for section in ('line_edits', 'combos', 'checks'):
                if not isinstance(preset.get(section, {}), dict):
                    raise ValueError(f'Invalid {section}.')
            merged = self._capture_current_preset('Imported parameters')
            unit = preset.get('temp_unit', self._temp_unit)
            if unit != self._temp_unit:
                for name in ('le_TinA', 'le_TinB'):
                    if name not in preset.get('line_edits', {}) and getattr(self, name).text().strip():
                        kelvin = self._temp_to_K(getattr(self, name))
                        merged['line_edits'][name] = str(kelvin - 273.15 if unit == 'C' else kelvin)
            for name, value in preset.items():
                if name in ('line_edits', 'combos', 'checks'):
                    merged[name].update(value)
                else:
                    merged[name] = value
            if ('chk_port_wall_refine' in preset.get('checks', {})
                    and 'combo_grid' not in preset.get('combos', {})):
                merged['combos']['combo_grid'] = int(preset['checks']['chk_port_wall_refine'])
            preset = merged
        # Cross-field requirements belong to the effective input, before any
        # widget signal or result invalidation can change the current state.
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
        self._set_sco2_nu_parameters(preset.get('sco2_nu_parameters', {}))
        combos = dict(preset.get('combos') or {})
        combos.setdefault('combo_df_mode', 0)  # legacy saved inputs used smooth CFD
        combos.setdefault('combo_sco2_nu_mode', 0)
        combos.setdefault('combo_grid', int((preset.get('checks') or {}).get('chk_port_wall_refine', False)))
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
                            c.setCurrentIndex(int(idx))
                except Exception: pass
        checks = dict(preset.get('checks') or {})
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
        from copy import deepcopy
        self._continuous_field_spec = deepcopy(preset.get('continuous_field'))
        self._selected_pareto_x = None
        self._opt_conditions = deepcopy(preset.get('optimization_conditions'))
        from sjtu_tpmshx.ui.optimize_panel import refresh_setup
        refresh_setup(self)
        self._user_edited_grid = True
        self._resync_undo_baseline()
        # Fluid signals are blocked above to preserve the preset's inputs.
        from sjtu_tpmshx.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(self)
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
        notice = self._solver_settings_notice(preset)
        if notice and show_notice:
            QMessageBox.information(self, "工况设置已更新", notice)

    def _solver_settings_notice(self, payload):
        """Explain changed historical settings without restoring retired controls."""
        checks = payload.get('checks') or {}
        combos = payload.get('combos') or {}
        edits = payload.get('line_edits') or {}
        updates = []
        for side in ('A', 'B'):
            key = f'chk_uniform_inlet{side}_2d'
            implicit_old_inlet = (key not in checks and combos.get('combo_dim') == 0
                                  and f'le_pipe{side}_in_w' in edits)
            if checks.get(key) is False or implicit_old_inlet:
                updates.append(f"流体 {side} 的二维入口采用开口内均匀速度")
        if checks.get('chk_wall_refine_3d') is True:
            updates.append("三维网格不再额外增加六壁面细化层")
        if checks.get('chk_var_rhocp') is False:
            updates.append("启用局部密度热输运")
        if not updates:
            return ''
        return ("已按当前求解设置载入：\n" + "\n".join(updates)
                + "\n这些设置与原文件不同，重新计算的结果可能变化；原文件和已保存结果未修改。")

    def _validate_preset(self, preset, *, complete=False):
        """Check the payload before touching widgets; old partial presets stay valid."""
        import math

        if not isinstance(preset, dict):
            raise ValueError('Preset must be a JSON object.')
        if complete and set(preset) - {'sco2_nu_parameters', 'continuous_field', 'optimization_conditions'} != {'name', 'temp_unit', 'line_edits',
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
        conditions = preset.get('optimization_conditions')
        if conditions is not None:
            from sjtu_tpmshx.ui.optimize_panel import validate_condition_table
            validate_condition_table({'conditions': conditions})
        if combos.get('combo_sco2_nu_mode', 0) == 1:
            replace(parameters, mode='experimental').validate()
        validate_domain_shape(combos.get('combo_shape', 0))
        if any(name.startswith('combo_edge_') for name in combos):
            raise ValueError(DOMAIN_SHAPE_NOTICE)
        for section, allowed in (('line_edits', self._SESSION_LINE_EDITS),
                                 ('combos', self._PRESET_COMBOS + ('combo_shape',)),
                                 ('checks', self._PRESET_CHECKS + tuple(self._FIXED_SOLVER_CHECKS)
                                  + ('chk_port_wall_refine',))):
            values = preset.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f'Invalid {section}.')
            if section == 'line_edits':
                # Former rectangular files also stored this unused polygon field.
                values = {name: value for name, value in values.items()
                          if name != 'le_mesh_density'}
            required = {n for n in allowed if getattr(self, n, None) is not None}
            if section == 'combos':
                required.add('combo_shape')
            if section == 'combos' and 'combo_sco2_nu_mode' not in values:
                required.discard('combo_sco2_nu_mode')  # old saved configs default to CFD
            if section == 'combos' and 'combo_grid' not in values:
                required.discard('combo_grid')
            if section == 'checks':
                # Old complete files may omit newly fixed settings or use the
                # former port-refinement checkbox instead of the mesh combo.
                required |= set(values) & (set(self._FIXED_SOLVER_CHECKS) | {'chk_port_wall_refine'})
            if complete and set(values) != required:
                raise ValueError(f'Incomplete or unsupported {section}: '
                                 f'{sorted(set(values) ^ required)}')
            for name, value in values.items():
                if name not in allowed:
                    continue  # retain the shared preset allow-list boundary
                if section == 'line_edits' and type(value) not in (str, int, float):
                    raise ValueError(f'Invalid text field: {name}')
                if section == 'line_edits' and str(value).strip():
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
                    count = widget.count() if widget else 0
                    if type(value) is not int or (widget is not None and
                                                not 0 <= value < count):
                        raise ValueError(f'Unsupported selection: {name}')
                if section == 'checks' and type(value) is not bool:
                    raise ValueError(f'Invalid checkbox: {name}')
        continuous = preset.get('continuous_field')
        if continuous is not None:
            from sjtu_tpmshx.domain.compute_config import ZoneInputConfig
            ZoneInputConfig(enabled=True, axis='continuous', config=continuous).validate()
            if ('n_ctrl_z' in continuous) != (combos.get('combo_dim') == 1):
                raise ValueError('Continuous field dimension must match the saved case')
            if not preset.get('checks', {}).get('chk_zones'):
                raise ValueError('Continuous field requires enabled spatial design')
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
        if preset.get('checks', {}).get('chk_zones') and continuous is None:
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
                   'line_edits': {}, 'combos': {'combo_shape': 0}, 'checks': {},
                   'sco2_nu_parameters': dict(getattr(self, '_sco2_nu_parameters', {}))}
        from copy import deepcopy
        if getattr(self, '_continuous_field_spec', None) is not None and self.chk_zones.isChecked():
            payload['continuous_field'] = deepcopy(self._continuous_field_spec)
        if getattr(self, '_opt_conditions', None) is not None:
            payload['optimization_conditions'] = deepcopy(self._opt_conditions)
        for n in self._SESSION_LINE_EDITS:
            w = getattr(self, n, None)
            if w is not None:
                try: payload['line_edits'][n] = w.text()
                except Exception: pass
        for n in self._PRESET_COMBOS:
            c = getattr(self, n, None)
            if c is not None:
                try: payload['combos'][n] = int(c.currentIndex())
                except Exception: pass
        for n in self._PRESET_CHECKS:
            b = getattr(self, n, None)
            if b is not None:
                try: payload['checks'][n] = bool(b.isChecked())
                except Exception: pass
        payload['checks'].update(self._FIXED_SOLVER_CHECKS)
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
        self._active_preset_name = name
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
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
        if not self._save_user_presets(presets):
            QMessageBox.warning(self, "预设未保存", "无法写入用户预设，当前输入保持不变。请检查用户数据目录。")
            return
        self._rebuild_recent_menu()
        self.statusBar().showMessage(
            f"Saved preset: {name}.", 5000)

    # ─────────────────────────────────────────────────────────
    #  Session auto-persist (restores last-used field state)
    # ─────────────────────────────────────────────────────────
    _SESSION_LINE_EDITS = (
        'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t', 'le_ks',
        'le_uA', 'le_TinA', 'le_PinA', 'le_uB', 'le_TinB', 'le_PinB',
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
    )
    _SESSION_COMBOS = (
        'combo_dim', 'combo_tpms', 'combo_grid',
        'combo_df_mode', 'combo_sco2_nu_mode',
        'combo_fluidA', 'combo_fluidB',
        'combo_dirA', 'combo_dirB',
    )
    _SESSION_CHECKS = ('chk_zones',)
    # Keep the physical choices explicit in saved files, without GUI toggles.
    _FIXED_SOLVER_CHECKS = {
        'chk_wall_refine_3d': False, 'chk_var_rhocp': True,
        'chk_uniform_inletA_2d': True, 'chk_uniform_inletB_2d': True,
    }
    # Presets and sessions share the complete physical-input snapshot.
    _PRESET_COMBOS = _SESSION_COMBOS + ('combo_zone_axis',)
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
            saved = bool(self._save_session())
        except Exception:
            saved = False
        if not saved:
            QMessageBox.warning(self, "会话未保存", "当前输入保存失败，已取消切换工作区。请先保存当前配置。")
            return
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
        """Refresh the workspace choices shown from the More menu."""
        menu = getattr(self, '_workspace_menu', None)
        if menu is None:
            return
        active = getattr(self, '_active_workspace', 'A')
        menu.clear()
        for ws in self._WORKSPACES:
            mark = "● " if ws == active else "   "
            act = menu.addAction(f"{mark}Workspace {ws}")
            act.triggered.connect(
                lambda _checked=False, name=ws: self._switch_workspace(name))

    def _save_session(self):
        """Save the complete preset inputs plus window state for this workspace."""
        payload = self._capture_current_preset('Last session')
        # Workbench UI state (ui-shortcuts-persist): last tab (result-family
        # keys collapse to 'result' so restore re-resolves via _result_view),
        # left-panel collapse, 2D|3D result-view choice.
        _tab = getattr(self, '_active_tab', 'layout')
        if _tab in ('temp', 'pres', 'vel', '3d', '2d_view'):
            _tab = 'result'
        _collapsed = bool(getattr(self, '_left_collapsed', False))
        _parameter_width = (getattr(self, '_param_width', 360) if _collapsed
                            else self._parameter_host.width())
        payload['ui_state'] = {
            'active_tab': _tab,
            'left_collapsed': _collapsed,
            'result_view': getattr(self, '_result_view', '2d'),
            'parameter_width': max(320, min(520, _parameter_width)),
            'parameter_page': getattr(self, '_param_page', 0),
            'result_summary_visible': self.btn_result_summary.isChecked(),
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
        """Restore one saved case; Shanghai defaults only fill absent old fields."""
        from copy import deepcopy
        from PySide6.QtCore import QTimer

        ws = getattr(self, '_active_workspace', 'A')
        payload = self.sm.load_session(ws)
        if payload is None:
            return
        # Use the same validation as explicit configuration loads, before
        # changing any widgets or invalidating the current result.
        try:
            self._validate_preset(payload)
        except (TypeError, ValueError) as error:
            message = f"{error}\n已保留当前工况。"
            QTimer.singleShot(0, self, lambda: QMessageBox.warning(
                self, "会话未恢复", message))
            return

        restored = deepcopy(payload)
        notice = self._solver_settings_notice(payload)
        if restored.get('zone_inputs') is None:
            # Older sessions saved the enabled flag without the table. Never
            # apply it to a table/Pareto field left over from another workspace.
            checks = restored.setdefault('checks', {})
            if checks.get('chk_zones'):
                notice += ("\n" if notice else "") + (
                    "旧会话未保存分区数据，已关闭分区并清空分区表；"
                    "请重新载入完整分区配置或设置分区后再计算。")
            checks['chk_zones'] = False
            restored.setdefault('combos', {})['combo_zone_axis'] = 0
            restored['zone_inputs'] = {
                'rows': [], 'grid_nx': 2, 'pareto_x_decision': None,
                'pareto_y_trans_inlet': 0.2, 'pareto_y_trans_outlet': 0.2,
            }

        # Open in Kelvin without changing either inlet's physical temperature.
        # Convert only saved C values; missing fields already have a known
        # physical value in the seeded defaults/current display unit.
        saved_unit = payload.get('temp_unit', 'K')
        edits = restored.setdefault('line_edits', {})
        for name in ('le_TinA', 'le_TinB'):
            if name not in edits:
                edits[name] = str(self._temp_to_K(getattr(self, name)))
            elif saved_unit == 'C' and str(edits[name]).strip():
                edits[name] = str(float(edits[name]) + 273.15)
        restored['temp_unit'] = 'K'
        self._apply_user_preset(restored, show_notice=False)
        if notice:
            QTimer.singleShot(0, self, lambda: QMessageBox.information(
                self, "工况设置已更新", notice))
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
        # Workbench UI state (ui-shortcuts-persist) — best-effort, mirrors
        # the save side. result_view first (so a restored 'result' tab
        # resolves to the saved side), then the left panel, then the tab.
        # A gated-off saved tab falls back through _switch_tab's own
        # button-disabled path (→ layout); no new fallback logic here.
        _ui = payload.get('ui_state') or {}
        try:
            if getattr(self, '_3d_immersive', False):
                self._toggle_3d_immersive()
            _rvw = _ui.get('result_view')
            if _rvw in ('2d', '3d'):
                self._result_view = _rvw
                _paint = getattr(self, '_paint_result_seg', None)
                if _paint is not None:
                    _paint()
            _width = _ui.get('parameter_width', 360)
            if isinstance(_width, (int, float)):
                self._param_width = max(320, min(520, int(_width)))
            # Apply the saved width before collapsing, so a current expanded
            # panel cannot overwrite it with its construction-time width.
            self._set_parameter_panel_collapsed(False)
            self._set_parameter_panel_collapsed(bool(_ui.get('left_collapsed', False)))
            _page = _ui.get('parameter_page', 0)
            if _page in (0, 1, 2):
                self._select_param_page(_page)
            self.btn_result_summary.setChecked(bool(_ui.get('result_summary_visible', True)))
            _tab = _ui.get('active_tab')
            if _tab in ('layout', 'result', 'pareto') and \
                    _tab != getattr(self, '_active_tab', 'layout'):
                self._switch_tab(_tab)
        except Exception:
            pass
