"""Capture, validate, save and restore the desktop case and its workspace."""
from __future__ import annotations

import json

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QTableWidgetItem

from sjtu_tpmshx.applications.gui.controllers.session_manager import SessionManager
from sjtu_tpmshx.applications.gui.ui.window_config import DOMAIN_SHAPE_NOTICE, LINE_EDITS, validate_domain_shape
from sjtu_tpmshx.applications.gui.ui.ui_constants import TOAST_MS_MED
from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K


def shanghai_field_defaults(*, is_3d: bool) -> dict[str, str]:
    """Recorded April 1 case-8 inputs, with temperatures in K."""
    from sjtu_tpmshx.physical_models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
    values = {
        # Source: water-air_G7-t0p6_shanghai_experiment_20260401.xlsx,
        # Sheet1 row 10. Flow targets use F10*K10/I10 and H10*L10/J10.
        # Speeds are resolved for this uniform Gyroid and the 42 mm depth.
        # The 3D mass-flow mode resolves them again from the prepared inlet.
        'le_L':     '0.182',  # L domain [m]
        'le_H':     '0.042',
        'le_Lz':    '0.042',
        'le_Lcell': '7.0',
        'le_t':     '0.6',
        'le_ks':    '16.0',   # Shanghai SS solid k_s
        'le_mass_flowA': '0.02276073333333333',
        'le_mass_flowB': '0.0864722781',
        'le_uA':    '22.058558981502337',
        'le_TinA':  '422.0583382933427',  # AC10 + 273.15
        'le_PinA':  '192362.40144727775', # AE10 + assumed 101325 Pa
        'le_uB':    '0.13366189204916',
        'le_TinB':  '300.03908245097393', # Y10 + 273.15
        'le_PinB':  '101972.60139558925', # AA10 + assumed 101325 Pa
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


class CaseFiles:
    def __init__(self, window):
        self.window = window
        self.store = SessionManager(parent=window)
        self.active_workspace = self.store.get_active_workspace()
        self.active_preset_name = None

    def set_shanghai_grid(self, *, is_3d):
        window = self.window
        from sjtu_tpmshx.physical_models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
        counts = SHANGHAI_GRID_3D if is_3d else SHANGHAI_GRID_2D
        for axis, count in zip('xyz', counts):
            getattr(window, 'le_N' + axis).setText(str(count))
        window.combo_grid.setCurrentIndex(window.combo_grid.findData(True))
        window._user_edited_grid = True

    BUILTIN_PRESETS = [
        "Shanghai (3D Gyroid)",
        "Shanghai (2D Gyroid)",
    ]

    def use_current_sco2_nu_parameters(self):
        """Explicitly replace draft parameters with the current total amplitudes."""
        window = self.window
        from dataclasses import asdict
        from sjtu_tpmshx.physical_models.nu_correlations import sco2_effective_nu_config

        self.set_sco2_nu_parameters(asdict(sco2_effective_nu_config()))
        window.combo_sco2_nu_mode.setCurrentIndex(
            window.combo_sco2_nu_mode.findData('experimental'))

    def set_sco2_nu_parameters(self, payload):
        window = self.window
        from dataclasses import asdict
        from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
        settings = Sco2NuConfig(**payload).validate()
        window._sco2_nu_parameters = asdict(settings) if payload else {}
        label = getattr(window, 'lbl_sco2_nu_parameters', None)
        if label is not None:
            label.setText(f"Ceff: G={settings.alpha_G}, D={settings.alpha_D}\n{settings.parameter_version}"
                          if settings.parameter_version else "未导入标定参数")
            label.setToolTip(f"{settings.source}\n{settings.applicability}")
        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import refresh_stale_indicator
        refresh_stale_indicator(window)

    def resync_undo_baseline(self):
        """Start an undo checkpoint at the final restored/displayed values."""
        window = self.window
        stack = getattr(window, '_undo_stack', None)
        if stack is not None:
            stack.clear()
        ul = getattr(window, '_undo_last', None)
        if ul is None:
            return
        for _nm in self.SESSION_LINE_EDITS:
            _le = getattr(window, _nm, None)
            if _le is not None:
                try:
                    ul[_nm] = _le.text()
                except Exception:
                    pass

    def invalidate_results_for_preset_load(self):
        """Clear single-run results when a case or a selected design replaces its inputs."""
        window = self.window
        window.cache.clear()
        window.workbench.volume_ready = False
        window.results.refresh_summary()
        window.workbench.update_tab_visibility()
        # The separate optimization figure can remain available for export.
        window.result_export.refresh_export_button()

    def apply_user_preset(self, preset, *, show_notice=True, partial=False,
                           source_name=None):
        """Apply inputs from a saved preset or session.

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
        window = self.window
        if partial:
            # File patches own only the supplied fields. Full saved presets
            # and sessions retain their existing historical-default policy.
            if not isinstance(preset, dict):
                raise ValueError('Preset must be a JSON object.')
            for section in ('line_edits', 'combos', 'checks'):
                if not isinstance(preset.get(section, {}), dict):
                    raise ValueError(f'Invalid {section}.')
            merged = self.capture_current_preset('Imported parameters')
            unit = preset.get('temp_unit', window._temp_unit)
            if unit != window._temp_unit:
                for name in ('le_TinA', 'le_TinB'):
                    if name not in preset.get('line_edits', {}) and getattr(window, name).text().strip():
                        kelvin = window._temp_to_K(getattr(window, name))
                        merged['line_edits'][name] = str(kelvin - CELSIUS_ZERO_K if unit == 'C' else kelvin)
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
        self.validate_preset(preset)
        notice = self.solver_settings_notice(preset)
        if not partial and preset.get('zone_inputs') is None:
            # Historical full saves did not own a zone table. Never inherit
            # the previous window's table or Pareto decision in any load route.
            from copy import deepcopy
            preset = deepcopy(preset)
            checks = preset.setdefault('checks', {})
            if preset.get('continuous_field') is None:
                if checks.get('chk_zones'):
                    notice += ("\n" if notice else "") + (
                        "旧会话未保存分区数据，已关闭分区并清空分区表；"
                        "请重新载入完整分区配置或设置分区后再计算。")
                checks['chk_zones'] = False
            preset.setdefault('combos', {})['combo_zone_axis'] = 0
            preset['zone_inputs'] = {
                'rows': [], 'grid_nx': 2, 'pareto_x_decision': None,
                'pareto_y_trans_inlet': 0.2, 'pareto_y_trans_outlet': 0.2,
            }
        self.invalidate_results_for_preset_load()
        unit = preset.get('temp_unit', 'K')
        if unit in ('K', 'C'):
            if unit != window._temp_unit:
                window._discard_temperature_history()
            window._temp_unit = unit
            if hasattr(window, '_sync_temp_unit_labels'):
                window._sync_temp_unit_labels()
        allowed_edits = set(self.SESSION_LINE_EDITS)
        allowed_checks = set(self.PRESET_CHECKS)
        for name, txt in (preset.get('line_edits') or {}).items():
            if name not in allowed_edits:
                continue
            w = getattr(window, name, None)
            if w is not None:
                try: w.setText(str(txt))
                except Exception: pass
        self.set_sco2_nu_parameters(preset.get('sco2_nu_parameters', {}))
        combos = dict(preset.get('combos') or {})
        combos.setdefault('combo_df_mode', 0)  # legacy saved inputs used smooth CFD
        combos.setdefault('combo_sco2_nu_mode', 0)
        for side in 'AB':
            combos.setdefault('combo_inlet_mode' + side, 0)
        combos.setdefault('combo_grid', int((preset.get('checks') or {}).get('chk_port_wall_refine', False)))
        for name in self.PRESET_COMBOS:
            if name not in combos:
                continue
            idx = combos[name]
            c = getattr(window, name, None)
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
            b = getattr(window, name, None)
            if b is not None:
                try: b.setChecked(bool(val))
                except Exception: pass

        zones = preset.get('zone_inputs')
        if zones is not None:
            window._grid_nx = zones['grid_nx']
            table = window.zone_table
            rows = zones['rows']
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    table.setItem(r, c, QTableWidgetItem(value))
            from sjtu_tpmshx.applications.gui.ui.zone_table import zone_resize
            zone_resize(window)
            window._pareto_x_decision = zones['pareto_x_decision']
            window._pareto_y_trans_inlet = zones['pareto_y_trans_inlet']
            window._pareto_y_trans_outlet = zones['pareto_y_trans_outlet']
        from copy import deepcopy
        window._continuous_field_spec = deepcopy(preset.get('continuous_field'))
        window.optimization.restore_study(preset, partial=partial)
        window._user_edited_grid = True
        window._refresh_field_validation()
        self.resync_undo_baseline()
        self.active_preset_name = (source_name if source_name is not None
                                    else preset.get('name')) or None
        # Fluid signals are blocked above to preserve the preset's inputs.
        from sjtu_tpmshx.applications.gui.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(window)
        if hasattr(window, '_refresh_status_bar'):
            window._refresh_status_bar()
        if notice and show_notice:
            QMessageBox.information(window, "工况设置已更新", notice)
        return notice

    def solver_settings_notice(self, payload):
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

    def validate_preset(self, preset, *, complete=False):
        """Check the payload before touching widgets; old partial presets stay valid."""
        window = self.window
        import math

        if not isinstance(preset, dict):
            raise ValueError('Preset must be a JSON object.')
        if 'ui_state' in preset:
            from sjtu_tpmshx.applications.gui.ui.vis3d_constants import validate_color_range_state
            if not isinstance(preset['ui_state'], dict):
                raise ValueError('Invalid saved UI state')
            views = preset['ui_state'].get('volume_color_ranges', {})
            if not isinstance(views, dict) or set(views) - {'results', 'optimization'}:
                raise ValueError('Invalid saved 3D views')
            for state in views.values():
                validate_color_range_state(state)
        if complete and set(preset) - {'sco2_nu_parameters', 'continuous_field', 'optimization_conditions', 'optimization_controls',
                                      'optimization_mass_requirements', 'optimization_bounds'} != {'name', 'temp_unit', 'line_edits',
                                       'combos', 'checks', 'zone_inputs'}:
            raise ValueError('Incomplete or unsupported preset fields.')
        from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
        from dataclasses import replace
        parameters = Sco2NuConfig(**preset.get('sco2_nu_parameters', {})).validate()
        temp_unit = preset.get('temp_unit', 'K')
        if temp_unit not in ('K', 'C'):
            raise ValueError('Unsupported temperature unit.')
        combos = preset.get('combos', {})
        if not isinstance(combos, dict):
            raise ValueError('Invalid combos.')
        conditions = preset.get('optimization_conditions')
        requirements = preset.get('optimization_mass_requirements')
        if conditions is not None or requirements is not None:
            from sjtu_tpmshx.applications.optimization.optimization_job import validate_condition_table
            table = {'conditions': conditions}
            if requirements is not None:
                table['mass_requirements'] = requirements
            validate_condition_table(table)
        if 'optimization_bounds' in preset:
            from sjtu_tpmshx.data_types.compute_config import ZoneInputConfig
            bounds = preset['optimization_bounds']
            if (not isinstance(bounds, dict) or set(bounds) != {'L', 't'}
                    or any(not isinstance(pair, list) or len(pair) != 2 for pair in bounds.values())):
                raise ValueError('Optimization bounds need L and t pairs')
            ZoneInputConfig(enabled=True, axis='continuous', config=dict(
                n_ctrl_x=1, n_ctrl_y=1, symmetric_y=False, spline_order=1,
                L_bounds=bounds['L'], t_bounds=bounds['t'],
                x_decision=[bounds['L'][0], bounds['t'][0]])).validate()
        if 'optimization_controls' in preset:
            controls = preset['optimization_controls']
            if (not isinstance(controls, dict) or set(controls) != set('xyz')
                    or any(type(value) is not int or not 1 <= value <= 99 for value in controls.values())):
                raise ValueError('Optimization control counts must be integers in 1..99 for X/Y/Z')
        if combos.get('combo_sco2_nu_mode', 0) == 1:
            replace(parameters, mode='experimental').validate()
        validate_domain_shape(combos.get('combo_shape', 0))
        if any(name.startswith('combo_edge_') for name in combos):
            raise ValueError(DOMAIN_SHAPE_NOTICE)
        for section, allowed in (('line_edits', self.SESSION_LINE_EDITS),
                                 ('combos', self.PRESET_COMBOS + ('combo_shape',)),
                                 ('checks', self.PRESET_CHECKS + tuple(self.FIXED_SOLVER_CHECKS)
                                  + ('chk_port_wall_refine', 'chk_wall_refine_3d'))):
            values = preset.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f'Invalid {section}.')
            if section == 'line_edits':
                # Older files can contain unused polygon and solid-density inputs.
                values = {name: value for name, value in values.items()
                          if name not in ('le_mesh_density', 'le_rho_s')}
            required = {n for n in allowed if getattr(window, n, None) is not None}
            if section == 'combos':
                required.add('combo_shape')
            if section == 'combos' and 'combo_sco2_nu_mode' not in values:
                required.discard('combo_sco2_nu_mode')  # old saved configs default to CFD
            if section == 'combos' and 'combo_grid' not in values:
                required.discard('combo_grid')
            for side in 'AB':
                optional = ('combo_inlet_mode' if section == 'combos' else 'le_mass_flow') + side
                if optional not in values:
                    required.discard(optional)
            if section == 'checks':
                # Old complete files may omit newly fixed settings or use the
                # former port-refinement checkbox instead of the mesh combo.
                required |= set(values) & (set(self.FIXED_SOLVER_CHECKS)
                                           | {'chk_port_wall_refine', 'chk_wall_refine_3d'})
            if complete and set(values) != required:
                raise ValueError(f'Incomplete or unsupported {section}: '
                                 f'{sorted(set(values) ^ required)}')
            for name, value in values.items():
                if name not in allowed:
                    continue  # retain the shared preset allow-list boundary
                if section == 'line_edits':
                    if type(value) not in (str, int, float):
                        raise ValueError(f'Invalid text field: {name}')
                    spec = LINE_EDITS[name]
                    mass_mode = combos.get('combo_dim') == 1 and combos.get('combo_inlet_mode' + name[-1]) == 1
                    if (not str(value).strip() or spec.when == 'velocity' and mass_mode
                            or spec.when == 'mass_flow' and not mass_mode):
                        continue
                    try:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError()
                        if spec.family == 'count':
                            int(str(value))
                    except (TypeError, ValueError):
                        raise ValueError(f'Invalid numeric field: {name}') from None
                    if spec.family == 'temp':
                        kelvin = number + CELSIUS_ZERO_K if temp_unit == 'C' else number
                        if kelvin <= 0:
                            raise ValueError(f'{name}: Must be above 0 K')
                if section == 'combos':
                    widget = getattr(window, name, None)
                    if name in ('combo_dirA', 'combo_dirB'):
                        target_dim = combos.get(
                            'combo_dim',
                            window.combo_dim.currentIndex() if hasattr(window, 'combo_dim') else 0,
                        )
                        count = 6 if target_dim == 1 else 4
                    else:
                        count = widget.count() if widget else 0
                    if type(value) is not int or (widget is not None and
                                                not 0 <= value < count):
                        raise ValueError(f'Unsupported selection: {name}')
                if section == 'checks' and type(value) is not bool:
                    raise ValueError(f'Invalid checkbox: {name}')
        continuous = preset.get('continuous_field')
        if continuous is not None:
            from sjtu_tpmshx.data_types.compute_config import ZoneInputConfig
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

    def capture_current_preset(self, name):
        """Build a preset payload from the current field state."""
        window = self.window
        payload = {'name': name,
                   'temp_unit': getattr(window, '_temp_unit', 'K'),
                   'line_edits': {}, 'combos': {'combo_shape': 0}, 'checks': {},
                   'sco2_nu_parameters': dict(getattr(window, '_sco2_nu_parameters', {}))}
        from copy import deepcopy
        if getattr(window, '_continuous_field_spec', None) is not None and window.chk_zones.isChecked():
            payload['continuous_field'] = deepcopy(window._continuous_field_spec)
        payload.update(window.optimization.capture_study())
        for n in self.SESSION_LINE_EDITS:
            w = getattr(window, n, None)
            if w is not None:
                try: payload['line_edits'][n] = w.text()
                except Exception: pass
        for n in self.PRESET_COMBOS:
            c = getattr(window, n, None)
            if c is not None:
                try: payload['combos'][n] = int(c.currentIndex())
                except Exception: pass
        for n in self.PRESET_CHECKS:
            b = getattr(window, n, None)
            if b is not None:
                try: payload['checks'][n] = bool(b.isChecked())
                except Exception: pass
        payload['checks'].update(self.FIXED_SOLVER_CHECKS)
        if hasattr(window, 'zone_table'):
            table = window.zone_table
            decision = getattr(window, '_pareto_x_decision', None)
            payload['zone_inputs'] = {
                'rows': [[table.item(r, c).text() if table.item(r, c) else ''
                          for c in range(table.columnCount())]
                         for r in range(table.rowCount())],
                'grid_nx': window._grid_nx,
                'pareto_x_decision': (list(map(float, decision))
                                      if decision is not None else None),
                'pareto_y_trans_inlet': getattr(window, '_pareto_y_trans_inlet', 0.2),
                'pareto_y_trans_outlet': getattr(window, '_pareto_y_trans_outlet', 0.2),
            }
        return payload

    def load_named_preset(self, name):
        """Load a built-in canonical preset by name. Wired from the header
        载入 ▾ menu and the command palette (replaces the old index-based
        combo handler)."""
        window = self.window
        if name not in self.BUILTIN_PRESETS:
            return
        self.invalidate_results_for_preset_load()
        window._apply_shanghai_defaults()
        if name == "Shanghai (2D Gyroid)":
            window.combo_dim.setCurrentIndex(0)
            self.set_shanghai_grid(is_3d=False)
        self.active_preset_name = name
        self.resync_undo_baseline()
        if hasattr(window, '_refresh_status_bar'):
            window._refresh_status_bar()
        window.statusBar().showMessage(f"Preset: {name}.", 5000)

    def save_current_as_preset(self):
        """Prompt for a name and persist the full current field state as a
        user preset. Overwrites silently on duplicate name."""
        window = self.window
        name, ok = QInputDialog.getText(
            window, "Save Preset",
            "Preset name:", text="my_preset")
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            window._refresh_field_validation()
            preset = self.capture_current_preset(name)
            for field in self.SESSION_LINE_EDITS:
                if getattr(window, field).property('inpError') == 'true':
                    raise ValueError(f'Invalid numeric field: {field}')
            self.validate_preset(preset, complete=True)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(window, "预设未保存", str(exc))
            return
        presets = self.store.load_user_presets()
        presets = [p for p in presets if p.get('name') != name]  # overwrite
        presets.append(preset)
        if not self.store.save_user_presets(presets):
            QMessageBox.warning(window, "预设未保存", "无法写入用户预设，当前输入保持不变。请检查用户数据目录。")
            return
        window.history.rebuild_recent_menu()
        window.statusBar().showMessage(
            f"Saved preset: {name}.", 5000)

    SESSION_LINE_EDITS = tuple(LINE_EDITS)

    SESSION_COMBOS = (
        'combo_dim', 'combo_tpms', 'combo_grid',
        'combo_df_mode', 'combo_sco2_nu_mode',
        'combo_fluidA', 'combo_fluidB',
        'combo_inlet_modeA', 'combo_inlet_modeB',
        'combo_dirA', 'combo_dirB',
    )

    SESSION_CHECKS = ('chk_zones',)

    FIXED_SOLVER_CHECKS = {
        'chk_var_rhocp': True,
        'chk_uniform_inletA_2d': True, 'chk_uniform_inletB_2d': True,
    }

    PRESET_COMBOS = SESSION_COMBOS + ('combo_zone_axis',)

    PRESET_CHECKS = SESSION_CHECKS + ('chk_allow_extrap',)

    WORKSPACES = ('A', 'B', 'C')

    def switch_workspace(self, new):
        """Persist the current workspace, activate `new`, and reload it."""
        window = self.window
        if new not in self.WORKSPACES:
            return
        cur = self.active_workspace
        if cur == new:
            return
        from sjtu_tpmshx.applications.gui.ui.background_tasks import has_active_tasks
        if has_active_tasks(window):
            QMessageBox.information(
                window, "任务仍在运行", "请等待当前任务结束后再切换工作区。")
            return
        try:
            saved = bool(self.save_session())
        except Exception:
            saved = False
        if not saved:
            QMessageBox.warning(window, "会话未保存", "当前输入保存失败，已取消切换工作区。请先保存当前配置。")
            return
        self.active_workspace = new
        # Tier 25: a workspace switch reloads a completely different input
        # set, so the current compute result belongs to the OLD workspace.
        # Invalidate it before re-seeding so the new workspace doesn't open
        # showing the previous workspace's result tabs / plots / export.
        self.invalidate_results_for_preset_load()
        try:
            window._apply_shanghai_defaults()
            self.restore_session()
        except Exception as e:
            QMessageBox.warning(window, "Workspace switch", str(e))
        self.rebuild_workspace_menu()
        window.history.rebuild_recent_menu()
        if hasattr(window, '_refresh_workbench_navigation'):
            window._refresh_workbench_navigation()
        if hasattr(window, '_refresh_status_bar'):
            window._refresh_status_bar()
        # Persist the choice so the next launch re-opens the same workspace.
        # Delegates to SessionManager (P2.3).
        # 2026-05-20 UI sweep (Tier 18): SessionManager.set_active_workspace
        # returns False on IO failure. Previously this return was ignored,
        # so a marker-write failure silently reverted the next launch to
        # workspace 'A'. Surface the failure to the status bar so the
        # user knows to re-pick the workspace after restart.
        _wrote = False
        try:
            _wrote = bool(self.store.set_active_workspace(new))
        except Exception:
            _wrote = False
        if _wrote:
            window.statusBar().showMessage(f"Workspace {new} loaded.", 4000)
        else:
            window.statusBar().showMessage(
                f"Workspace {new} loaded — but writing the active-workspace "
                f"marker failed; next launch may default to 'A'.", 8000)

    def rebuild_workspace_menu(self):
        """Refresh the workspace choices shown from the More menu."""
        window = self.window
        menu = getattr(window, '_workspace_menu', None)
        if menu is None:
            return
        active = self.active_workspace
        menu.clear()
        for ws in self.WORKSPACES:
            mark = "● " if ws == active else "   "
            act = menu.addAction(f"{mark}Workspace {ws}")
            act.triggered.connect(
                lambda _checked=False, name=ws: self.switch_workspace(name))

    def save_session(self):
        """Save the complete preset inputs plus window state for this workspace."""
        window = self.window
        # Closing need not blur the focused line edit before this callback.
        # Keep capture pure: partial-import validation also reads that snapshot.
        window._refresh_field_validation()
        payload = self.capture_current_preset('Last session')
        from sjtu_tpmshx.applications.gui.ui.window_config import inlet_input_active
        if any(getattr(window, name).property('inpError') == 'true'
               for name in self.SESSION_LINE_EDITS if inlet_input_active(window, name)):
            return False
        try:
            self.validate_preset(payload)
        except (TypeError, ValueError):
            return False
        payload['preset_source'] = self.active_preset_name
        # Workbench UI state (ui-shortcuts-persist): last tab (result-family
        # keys collapse to 'result' so restore uses the saved result view),
        # left-panel collapse, 2D|3D result-view choice.
        _tab = window.workbench.active_tab
        if _tab in ('temp', 'pres', 'vel', '3d', '2d_view'):
            _tab = 'result'
        _collapsed = not window.appearance.is_drawer_open()
        _parameter_width = getattr(window, '_param_width', 376)
        payload['ui_state'] = {
            'active_tab': _tab,
            'left_collapsed': _collapsed,
            'result_view': window.workbench.result_view,
            'parameter_width': max(320, min(520, _parameter_width)),
            'parameter_page': getattr(window, '_param_page', 0),
            'result_summary_visible': window.btn_result_summary.isChecked(),
        }
        ranges = dict(getattr(window, '_volume_color_ranges', {}))
        for key, panel in (('results', window.canvas_3d), ('optimization', window.optimization.volume_panel)):
            if panel is not None:
                ranges[key] = panel.color_range_state()
        payload['ui_state']['volume_color_ranges'] = ranges
        # Window geometry + state (maximised, size, position). Store as
        # base64 so the JSON stays readable when the rest is inspected.
        try:
            import base64 as _b64
            geo = bytes(window.saveGeometry())
            st = bytes(window.saveState())
            payload['geometry'] = _b64.b64encode(geo).decode('ascii')
            payload['win_state'] = _b64.b64encode(st).decode('ascii')
        except Exception:
            pass
        # SessionManager handles IO failure silently + stamps schema_version.
        # 2026-05-20 UI sweep (Tier 18): return SessionManager's bool so
        # callers (notably _toggle_theme's restart path) can abort on a
        # silent IO failure instead of execv'ing into a process that has
        # lost the user's pending edits.
        return bool(self.store.save_session(
            payload, self.active_workspace))

    def restore_session(self):
        """Restore one saved case; Shanghai defaults only fill absent old fields."""
        window = self.window
        from copy import deepcopy
        from PySide6.QtCore import QTimer

        ws = self.active_workspace
        payload = self.store.load_session(ws)
        if payload is None:
            return
        # Use the same validation as explicit configuration loads, before
        # changing any widgets or invalidating the current result.
        try:
            self.validate_preset(payload)
        except (TypeError, ValueError) as error:
            backup = self.store.quarantine_session(ws)
            message = f"{error}\n已保留当前工况。"
            if backup is not None:
                message += f"\n原会话已保存在：{backup}"
            elif self.store.session_path(ws).exists():
                message += ("\n原会话备份失败，已阻止覆盖。"
                            "请检查用户数据目录的写入权限后重试保存。")
            QTimer.singleShot(0, window, lambda: QMessageBox.warning(
                window, "会话未恢复", message))
            return

        restored = deepcopy(payload)
        # Open in Kelvin without changing either inlet's physical temperature.
        # Convert only saved C values; missing fields already have a known
        # physical value in the seeded defaults/current display unit.
        saved_unit = payload.get('temp_unit', 'K')
        edits = restored.setdefault('line_edits', {})
        for name in ('le_TinA', 'le_TinB'):
            if name not in edits:
                edits[name] = str(window._temp_to_K(getattr(window, name)))
            elif saved_unit == 'C' and str(edits[name]).strip():
                edits[name] = str(float(edits[name]) + CELSIUS_ZERO_K)
        restored['temp_unit'] = 'K'
        notice = self.apply_user_preset(
            restored, show_notice=False, source_name=payload.get('preset_source') or '')
        if notice:
            QTimer.singleShot(0, window, lambda: QMessageBox.information(
                window, "工况设置已更新", notice))
        # Restore window geometry / dock state last so it doesn't fight the
        # `showMaximized()` the constructor already called. Pass-through:
        # if the payload is missing or corrupt, the explicit showMaximized
        # wins and the user sees the standard maximised window.
        import base64 as _b64
        from PySide6.QtCore import QByteArray
        geo_b64 = payload.get('geometry')
        if geo_b64:
            try:
                window.restoreGeometry(QByteArray(_b64.b64decode(geo_b64)))
            except Exception:
                pass
        st_b64 = payload.get('win_state')
        if st_b64:
            try:
                window.restoreState(QByteArray(_b64.b64decode(st_b64)))
            except Exception:
                pass
        # Workbench UI state (ui-shortcuts-persist) — best-effort, mirrors
        # the save side. result_view first (so a restored 'result' tab
        # resolves to the saved side), then the left panel, then the tab.
        # Workbench.switch_tab selects the layout if that tab is unavailable.
        _ui = payload.get('ui_state') or {}
        window._volume_color_ranges = deepcopy(_ui.get('volume_color_ranges', {}))
        if window.canvas_3d is not None:
            window.canvas_3d.restore_color_ranges(window._volume_color_ranges.get('results', {}))
        window.optimization.restore_volume_ranges(window._volume_color_ranges.get('optimization', {}))
        try:
            if window.appearance.is_focused():
                window.appearance.toggle_focus()
            _rvw = _ui.get('result_view')
            if _rvw in ('2d', '3d'):
                window.workbench.result_view = _rvw
                _paint = getattr(window, '_paint_result_seg', None)
                if _paint is not None:
                    _paint()
            _width = _ui.get('parameter_width', 376)
            if isinstance(_width, (int, float)):
                window._param_width = max(320, min(520, int(_width)))
            window.appearance.set_drawer_open(not bool(_ui.get('left_collapsed', False)))
            _page = _ui.get('parameter_page', 0)
            if _page in (0, 1, 2):
                window._select_param_page(_page)
            window.btn_result_summary.setChecked(bool(_ui.get('result_summary_visible', True)))
            _tab = _ui.get('active_tab')
            if _tab in ('layout', 'result', 'pareto') and \
                    _tab != window.workbench.active_tab:
                window.workbench.switch_tab(_tab)
        except Exception:
            pass

    def load_sco2_nu_parameters(self):
        """Resolve a local parameter file now; snapshots never reread its path."""
        window = self.window
        path, _ = QFileDialog.getOpenFileName(window, "导入 sCO₂ Nu 标定参数", "", "JSON (*.json)")
        if not path:
            return False
        try:
            from pathlib import Path
            from dataclasses import asdict, replace
            from sjtu_tpmshx.data_types.compute_config import Sco2NuConfig
            settings = Sco2NuConfig(**json.loads(Path(path).read_text(encoding='utf-8')))
            replace(settings, mode='experimental').validate()
            self.set_sco2_nu_parameters(asdict(settings))
            return True
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(window, "标定参数无法加载", str(exc))
            return False

    def save_config(self):
        window = self.window
        path, _ = QFileDialog.getSaveFileName(
            window, "Save Config", "SJTU-TPMSHX_config.json",
            "JSON Files (*.json)")
        if not path:
            return False
        try:
            from pathlib import Path
            preset = self.capture_current_preset(Path(path).stem)
            self.validate_preset(preset, complete=True)
            payload = {'config_format': 1, 'preset': preset}
            if not self.store._atomic_write_json(Path(path), payload):
                raise OSError(f"Cannot save configuration: {path}")
        except Exception as e:
            QMessageBox.critical(window, "Save Error", str(e))
            return False
        window.statusBar().showMessage(f"Saved configuration: {path}", TOAST_MS_MED)
        return True

    def load_config(self):
        window = self.window
        path, _ = QFileDialog.getOpenFileName(
            window, "Load Config", "", "JSON Files (*.json)")
        if not path:
            return False
        return self.load_config_path(path)

    def load_config_path(self, path):
        """Apply one configuration file through the same menu/drop validation."""
        window = self.window
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Configuration must be a JSON object.")
            legacy = False
            partial = False
            if 'config_format' in payload:
                if (type(payload['config_format']) is not int or
                        payload['config_format'] != 1 or
                        set(payload) != {'config_format', 'preset'}):
                    raise ValueError("Unsupported configuration format.")
                preset = payload['preset']
                self.validate_preset(preset, complete=True)
            elif 'line_edits' in payload:
                preset = payload
                partial = True
            elif 'presets' in payload:
                presets = payload['presets']
                if not isinstance(presets, list) or not presets:
                    raise ValueError("Preset library must contain at least one preset.")
                preset = presets[0]
                self.validate_preset(preset)
            else:
                legacy = True
                partial = True
                preset = self.legacy_config_preset(payload)
            self.apply_user_preset(preset, partial=partial)
        except Exception as e:
            QMessageBox.critical(window, "Load Error", str(e))
            return False
        if legacy:
            message = ("已导入旧文件中保存的字段；这不是完整工况恢复。旧格式没有"
                       "保存流体、温度单位、维度/Lz/Nz、第二横向端口、外推、"
                       "flags 和分区；这些输入保持当前值，请核对后计算。")
            QMessageBox.warning(window, "旧配置不完整", message)
        else:
            message = f"Loaded configuration: {path}"
        window.statusBar().showMessage(message, TOAST_MS_MED)
        return True

    def legacy_config_preset(self, payload):
        """Import only fields the former flat writer actually saved."""
        window = self.window
        edits = {
            'L': 'le_L', 'H': 'le_H',
            'Nx': 'le_Nx', 'Ny': 'le_Ny', 'L_cell': 'le_Lcell',
            't': 'le_t', 'k_s': 'le_ks',
            'u_A': 'le_uA', 'T_inA': 'le_TinA', 'P_inA': 'le_PinA',
            'u_B': 'le_uB', 'T_inB': 'le_TinB', 'P_inB': 'le_PinB',
        }
        for side in ('A', 'B'):
            for port in ('in', 'out'):
                for field in ('ctr', 'w'):
                    key = f'pipe{side}_{port}_{field}'
                    edits[key] = f'le_{key}'
        known = set(edits) | {'tpms_type', 'df_mode', 'dir_A', 'dir_B', 'T_s_init', 'rho_s'}
        if not payload or set(payload) - known:
            raise ValueError("Incomplete or unsupported configuration payload.")
        if payload.get('T_s_init', '') != '':
            raise ValueError("T_s_init is no longer a GUI input; cannot restore it.")
        preset = {'temp_unit': window._temp_unit,
                  'line_edits': {name: payload[key] for key, name in edits.items()
                                 if key in payload},
                  'combos': {}, 'checks': {}}
        for key, name, by_data in (
                ('tpms_type', 'combo_tpms', False),
                ('df_mode', 'combo_df_mode', True)):
            if key in payload:
                combo = getattr(window, name)
                idx = (combo.findData(payload[key]) if by_data else
                       combo.findText(payload[key]))
                if idx < 0:
                    raise ValueError(f"Unsupported {key}: {payload[key]}")
                preset['combos'][name] = idx
        for side in ('A', 'B'):
            if f'dir_{side}' in payload:
                preset['combos'][f'combo_dir{side}'] = payload[f'dir_{side}']
            if f'u_{side}' in payload:
                # The former flat format specifies inlet speed.
                preset['combos'][f'combo_inlet_mode{side}'] = 0
        self.validate_preset(preset)
        return preset
