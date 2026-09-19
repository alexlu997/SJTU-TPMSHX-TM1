"""Actual Qt Compute entry, numerical modules, rendering and CSV export."""
import csv
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import QTimer

from sjtu_tpmshx.tests.test_io_actions import win as win
from sjtu_tpmshx.tests.test_worker_result_handoff import _wait_for
from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config, AIR_PUBLIC_METRICS
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
from sjtu_tpmshx.ui.window_config import CONFIG_FIELDS
from sjtu_tpmshx.domain.compute_config import bc_to_dict


def apply_config(window, config):
    edits = {field.widget: str(getattr(getattr(config, field.section), field.name))
             for field in CONFIG_FIELDS
             if getattr(getattr(config, field.section), field.name) is not None}
    for side in ('A', 'B'):
        port = getattr(config, 'bc_' + side)
        cross = config.geometry.H_dom_m if port.dir in (0, 1) else config.geometry.L_dom_m
        normalized = bc_to_dict(port, config.geometry.L_dom_m, config.geometry.H_dom_m, with_z=True)
        for end in ('in', 'out'):
            for suffix, default in (('ctr', cross / 2), ('w', cross),
                                    ('z_ctr', (config.geometry.Lz_m or .042) / 2),
                                    ('z_w', config.geometry.Lz_m or .042)):
                value = normalized.get(end + '_' + suffix)
                edits[f'le_pipe{side}_{end}_{suffix}'] = str(default if value is None else value)
    window._apply_user_preset(dict(
        temp_unit='K', line_edits=edits, sco2_nu_parameters=asdict(config.sco2_nu),
        combos={'combo_shape': 0, 'combo_dim': int(config.is_3d),
                'combo_tpms': window.combo_tpms.findText(config.geometry.tpms),
                'combo_fluidA': ('air', 'water', 'sco2').index(config.fluid_A.type),
                'combo_fluidB': ('air', 'water', 'sco2').index(config.fluid_B.type),
                'combo_df_mode': window.combo_df_mode.findData(config.df_mode),
                'combo_sco2_nu_mode': window.combo_sco2_nu_mode.findData(config.sco2_nu.mode),
                'combo_dirA': config.bc_A.dir, 'combo_dirB': config.bc_B.dir},
        checks={'chk_zones': False, 'chk_wall_refine_3d': config.flags.wall_refine_3d,
                'chk_port_wall_refine': config.flags.port_wall_refine,
                'chk_uniform_inletA_2d': config.bc_A.uniform_inlet_2d,
                'chk_uniform_inletB_2d': config.bc_B.uniform_inlet_2d,
                'chk_var_rhocp': config.flags.variable_rho_cp, 'chk_allow_extrap': config.extrap.allow}))
    window.auto_fill_fluid_a()
    window.auto_fill_fluid_b()


def test_shanghai_uniform_inlet_is_explicit_and_preserved_by_preset(win):
    from sjtu_tpmshx.ui.window_config import config_from_window
    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(0)
    cfg = config_from_window(win)
    assert cfg.bc_B.uniform_inlet_2d and not cfg.bc_A.uniform_inlet_2d
    preset = win._capture_current_preset('Shanghai uniform inlet')
    win.chk_uniform_inletB_2d.setChecked(False)
    win._apply_user_preset(preset)
    assert config_from_window(win).bc_B.uniform_inlet_2d
    # Old explicitly loaded presets retain their original inlet distribution.
    preset['checks'].pop('chk_uniform_inletB_2d')
    win._apply_user_preset(preset)
    assert not config_from_window(win).bc_B.uniform_inlet_2d


def test_shanghai_recommended_grid_and_manual_preset_roundtrip(win):
    from sjtu_tpmshx.models.grid import SHANGHAI_GRID_2D, SHANGHAI_GRID_3D
    from sjtu_tpmshx.ui.window_config import config_from_window
    for name, counts in (('Shanghai (2D Gyroid)', SHANGHAI_GRID_2D),
                         ('Shanghai (3D Gyroid)', SHANGHAI_GRID_3D)):
        win._load_named_preset(name)
        cfg = config_from_window(win)
        assert (cfg.solver.Nx, cfg.solver.Ny, cfg.solver.Nz) == counts
        assert cfg.flags.port_wall_refine and not cfg.flags.wall_refine_3d
    win.le_Nx.setText('100')
    win.compute_tpms()
    assert win.le_Nx.text() == '100'
    saved = win._capture_current_preset('manual grid')
    win._load_named_preset('Shanghai (2D Gyroid)')
    win._apply_user_preset(saved)
    assert win.le_Nx.text() == '100' and win.chk_port_wall_refine.isChecked()
    saved['checks'].pop('chk_port_wall_refine')
    win._apply_user_preset(saved)
    assert not win.chk_port_wall_refine.isChecked()  # legacy files keep their mesh


@pytest.mark.parametrize('shape', [1, 2], ids=['hexagon', 'octagon'])
@pytest.mark.parametrize('dimension', [2, 3])
def test_saved_polygon_cannot_start_compute(win, monkeypatch, shape, dimension):
    from sjtu_tpmshx.ui.window_config import config_from_window, DOMAIN_SHAPE_NOTICE

    apply_config(win, baseline_config() if dimension == 2 else _small_air_cfg())
    assert win.combo_shape.model().item(0).isEnabled()
    assert all(not win.combo_shape.model().item(index).isEnabled() for index in (1, 2))
    # Saved presets can restore a disabled item; keep it visible and reject compute.
    win._apply_user_preset({'combos': {'combo_shape': shape}})
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, text: messages.append(text))
    def forbidden(*args, **kwargs):
        pytest.fail('polygon selection reached grid preparation or numerical execution')
    monkeypatch.setattr(win, '_preflight_grid', forbidden)
    monkeypatch.setattr(win.compute, 'start', forbidden)
    try:
        for strict in (False, True):
            with pytest.raises(ValueError, match='Rectangle'):
                config_from_window(win, strict=strict)
        win.run_calculation()
        assert messages == [DOMAIN_SHAPE_NOTICE]
        assert win.combo_shape.currentIndex() == shape
        assert win.compute.is_idle()
    finally:
        win.combo_shape.setCurrentIndex(0)


@pytest.mark.slow
@pytest.mark.parametrize('dimension', [2, 3])
def test_real_gui_compute_drafts_units_and_export(win, monkeypatch, tmp_path, dimension):
    monkeypatch.setenv('SJTU_TPMSHX_DISABLE_3D_PANEL', '1')
    monkeypatch.delenv('TPMSHX_EAGER_3D_SLICES', raising=False)
    monkeypatch.setattr('sjtu_tpmshx.ui.mixins.run_history._TIMELINE_FILE', tmp_path / 'timeline.jsonl')
    errors = []
    dialogs = []
    solver_warnings = []
    original_exec = QMessageBox.exec
    def accept_grid_warning(dialog):
        assert 'Grid preflight' in dialog.text(), dialog.text()
        assert dialog.icon() == QMessageBox.Icon.Warning, dialog.text()
        dialogs.append(dialog.text())
        QTimer.singleShot(0, lambda: dialog.button(QMessageBox.StandardButton.Yes).click())
        return original_exec(dialog)
    monkeypatch.setattr(QMessageBox, 'exec', accept_grid_warning)
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[1:]))
    def record_warning(parent, title, message, *args):
        if title == 'Solver Warnings':
            solver_warnings.append(message)
        else:
            errors.append((title, message))
    monkeypatch.setattr(QMessageBox, 'warning', record_warning)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: pytest.fail(f'unexpected preflight prompt: {args[1:3]}'))
    config = baseline_config() if dimension == 2 else _small_air_cfg()
    apply_config(win, config)
    finished, started = [], []
    win.compute.finished.connect(finished.append)
    win.compute.started.connect(started.append)
    try:
        win.run_calculation()
        assert started, errors
        # Edit a new draft while the actual accepted run is in its worker.
        win.combo_dim.setCurrentIndex(0 if dimension == 3 else 1)
        win.combo_dirA.setCurrentIndex(1)
        win.le_Nx.setText('99')
        win._toggle_temp_unit()
        _wait_for(win.compute.is_idle, timeout=180)
    finally:
        win.compute.finished.disconnect(finished.append)
        win.compute.started.disconnect(started.append)
        if not win.compute.is_idle():
            win.compute.cancel()
            _wait_for(win.compute.is_idle, timeout=30)
    assert not errors
    assert len(finished) == 1
    result = finished[0]
    assert bool(solver_warnings) == bool(result.warnings)
    assert all(warning in '\n'.join(solver_warnings) for warning in result.warnings)
    unit = 'W/m' if dimension == 2 else 'W'
    assert result.metadata['source_result_id']
    assert result.metadata['units']['Q'] == win._result_Q_unit == unit
    assert f'[{unit}]' in win._lbl_Q_unit.text()
    assert win._tout_K_cache == (result.T_out_A_K, result.T_out_B_K)
    assert float(win._r_ToutA.text()) == pytest.approx(result.T_out_A_K - 273.15, abs=.051)
    assert result.fields['dir_A'] == config.bc_A.dir
    assert result.fields['Ta'].shape[0] != 99
    np.testing.assert_allclose(
        [result.Q_W, result.dP_A_Pa, result.dP_B_Pa, result.T_out_A_K, result.T_out_B_K],
        (AIR_PUBLIC_METRICS
         if dimension == 2 else
         # Physical inlet-pressure reference; previous values and native
         # evidence: docs/history/README.md.
         [338.325949393, 1944.010935833327, 3038.067091602703, 359.22541117456143, 344.9327731893514]),
        rtol=1e-10, atol=1e-10)
    output = tmp_path / 'results.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), 'CSV'))
    win._export_results()
    assert not errors
    with output.open() as stream:
        rows = dict(list(csv.reader(stream))[1:])
    assert float(rows[f'Q [{unit}]']) == pytest.approx(result.Q_W, abs=.0001)
    assert json.loads(rows['metadata'])['metric_definitions']['Q']['definition_version'] == 'native_boundary_v1'
    assert '主网格 A 侧' in win._diag_summary_text()
    assert unit in win._diag_summary_text()
    win.show()
    assert win._canvas_tab_availability()['temp']
    win._switch_tab('temp')
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert win._active_tab == 'temp'
    assert unit in win._sb_labels['q'].text()
    assert f'{dimension}D' in win._sb_result_heading.text()
    assert '[°C]' in win._lbl_sidebar_tout_unit.text()
    if dimension == 3:
        assert win._resid_spark._data == []
    for width in (900, 1440):
        win.resize(width, 720 if width == 900 else 900)
        _wait_for(lambda: win._canvas_scroll.verticalScrollBar().maximum() == 0,
                  timeout=2)
        QApplication.processEvents()
        canvas = win.canvas_temp
        canvas.draw()
        axis = canvas.axes[0][0]
        assert axis.xaxis.label.get_window_extent(canvas.renderer).y0 >= 0
        assert axis.title.get_window_extent(canvas.renderer).y1 <= canvas.fig.bbox.height
    screenshot = Path(f'.cache/tm1-apps/gui-{dimension}d.png')
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    assert win.grab().save(str(screenshot))
    Path(f'.cache/tm1-apps/gui-{dimension}d-preflight.txt').write_text('\n'.join(dialogs))
    Path(f'.cache/tm1-apps/gui-{dimension}d-warnings.txt').write_text('\n'.join(solver_warnings))
