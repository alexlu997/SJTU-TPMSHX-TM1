"""IOActionsMixin locks (openspec maintainability-closeout, 2026-07-03).

save_config/load_config JSON round-trip was 0%-tested despite being the
user's config persistence path — a broken key silently loses a field.
Offscreen Main_Menu fixture mirrors test_ui_layout_hygiene.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

@pytest.fixture(scope="module")
def win(tmp_path_factory):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(
        ['pytest', '-platform', 'offscreen'])
    # Redirect SessionManager's default base_dir before Main_Menu is built:
    # closeEvent auto-saves the session, and without this the teardown
    # w.close() writes the REAL sjtu_tpmshx/.last_session.json (bug found
    # 2026-07-13). Module-scoped fixture, so patch manually (monkeypatch
    # fixture is function-scoped) and undo after close.
    from _pytest.monkeypatch import MonkeyPatch
    import sjtu_tpmshx.controllers.session_manager as sm_mod
    mp = MonkeyPatch()
    session_dir = tmp_path_factory.mktemp('session')
    orig_init = sm_mod.SessionManager.__init__

    def _init(self, base_dir=None, parent=None):
        orig_init(self, base_dir=base_dir if base_dir is not None else session_dir,
                  parent=parent)

    mp.setattr(sm_mod.SessionManager, '__init__', _init)
    import sjtu_tpmshx.main as main_mod
    w = main_mod.Main_Menu()
    yield w
    w.close()
    w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    mp.undo()


def test_figure_export_records_current_source_and_version(tmp_path, monkeypatch, win):
    from PIL import Image
    from sjtu_tpmshx._version import __version__
    from sjtu_tpmshx.ui.mixins import io_actions

    path = tmp_path / 'figure.png'
    choices = iter([('温度', True), ('150 (screen)', True)])
    monkeypatch.setattr(io_actions.QInputDialog, 'getItem', lambda *a, **kw: next(choices))
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *a, **kw: (str(path), 'PNG (*.png)'))
    roots = []
    def revision(root):
        roots.append(root)
        return {'revision': 'example-revision'}
    monkeypatch.setattr(io_actions, 'repository_revision', revision)
    win.cache.replace_drawn_tabs({'temp'})
    monkeypatch.chdir(tmp_path)
    win._export_figure()
    with Image.open(path) as figure:
        assert figure.info['Source'] == 'https://github.com/alexlu997/SJTU-TPMSHX-TM1'
        assert figure.info['Software'] == f'SJTU-TPMSHX v{__version__}'
        assert figure.info['Keywords'] == 'commit=example'
    assert roots == [io_actions.SOURCE_ROOT]


@pytest.mark.parametrize('side', ['A', 'B'])
def test_sco2_switch_default_and_explicit_pressure_preserved(win, side):
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    combo = getattr(win, f'combo_fluid{side}')
    pressure = getattr(win, f'le_Pin{side}')
    combo.setCurrentIndex(0)
    combo.setCurrentIndex(2)
    fluid = getattr(config_from_window(win), f'fluid_{side}')
    assert (fluid.type, fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa) == (
        'sco2', 2., 350., 12e6)
    assert 'absolute' in pressure.toolTip() and '7.9–16 MPa' in pressure.toolTip()
    pressure.setText('11000000')
    assert getattr(config_from_window(win), f'fluid_{side}').P_in_Pa == 11e6
    assert pressure.text() == '11000000'
    for endpoint in ('7900000', '8000000', '16000000'):
        for previous_type in (0, 2):
            combo.setCurrentIndex(previous_type)
            win._apply_user_preset({
                'line_edits': {f'le_Pin{side}': endpoint},
                'combos': {f'combo_fluid{side}': 2},
            })
            assert pressure.text() == endpoint
            assert getattr(config_from_window(win), f'fluid_{side}').P_in_Pa == float(endpoint)


@pytest.mark.parametrize('dim,unit,fluids,axis,df', [
    (0, 'K', (0, 1), 0, 0),
    (1, 'C', (1, 0), 1, 0),
    (1, 'K', (2, 0), None, 1),
    (0, 'C', (0, 0), 2, 0),
])
def test_complete_config_menu_roundtrip(tmp_path, monkeypatch, win,
                                        dim, unit, fluids, axis, df):
    from dataclasses import asdict
    from PySide6.QtWidgets import QFileDialog, QTableWidgetItem, QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(dim)
    win._temp_unit = unit
    win._sync_temp_unit_labels()
    win.combo_fluidA.setCurrentIndex(fluids[0])
    win.combo_fluidB.setCurrentIndex(fluids[1])
    win.combo_df_mode.setCurrentIndex(df)
    win.combo_tpms.setCurrentIndex(0)
    win.le_L.setText('0.182')
    win.le_H.setText('0.042' if df else '0.052')
    win.le_Lz.setText('0.042' if df else '0.063')
    win.le_Nx.setText('24')
    win.le_Ny.setText('18')
    win.le_Nz.setText('13')
    win.le_TinA.setText('126.85' if unit == 'C' else '400')
    win.le_TinB.setText('46.85' if unit == 'C' else '320')
    win.le_uA.setText('1.7')
    win.le_uB.setText('12' if df else '0.17')
    win.le_PinA.setText('8200000')
    win.le_PinB.setText('230000')
    win.le_Lcell.setText('7.0')
    win.le_t.setText('0.6')
    win.le_ks.setText('18.5')
    win.combo_dirA.setCurrentIndex(4 if dim else 1)
    win.combo_dirB.setCurrentIndex(2)
    for side in ('A', 'B'):
        for port, ctr in (('in', '0.018'), ('out', '0.029')):
            for suffix, value in (('ctr', ctr), ('w', '0.012'),
                                  ('z_ctr', '0.022'), ('z_w', '0.016')):
                getattr(win, f'le_pipe{side}_{port}_{suffix}').setText(value)
    win.chk_allow_extrap.setChecked(True)
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    win.chk_zones.setChecked(axis is not None)
    win.combo_zone_axis.setCurrentIndex(axis or 0)
    win._pareto_x_decision = None
    win._pareto_y_trans_inlet = 0.15
    win._pareto_y_trans_outlet = 0.18
    if axis is not None:
        rows = ([['0', '40', '6', '0.4'], ['40', '100', '7', '0.5']]
                if axis != 2 else
                [[str(y0), str(y1), str(x0), str(x1), '6.5', '0.45']
                 for y0, y1 in ((0, 35), (35, 100))
                 for x0, x1 in ((0, 60), (60, 100))])
        win._grid_nx = 2
        win.zone_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                win.zone_table.setItem(r, c, QTableWidgetItem(value))
        if axis == 2:
            win._pareto_x_decision = np.array([6.5, 0.45] * 18)
    saved = win._capture_current_preset('test')
    captured = config_from_window(win)
    # Verify representative inputs pass existing physical validation; the
    # persistence layer itself does not impose a new physical gate.
    from copy import deepcopy
    deepcopy(captured).validate()
    before = asdict(captured)
    if before['zones']['pareto_x_decision'] is not None:
        before['zones']['pareto_x_decision'] = list(before['zones']['pareto_x_decision'])
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
    path = str(tmp_path / 'complete.json')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (path, ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (path, ''))
    actions = {a.text(): a for a in win.btn_recent.menu().actions()}
    assert '保存配置文件…' in actions
    assert '加载配置文件…' in actions
    actions['保存配置文件…'].trigger()
    for name in win._SESSION_LINE_EDITS:
        getattr(win, name).setText('1')
    for name in win._PRESET_COMBOS:
        combo = getattr(win, name)
        if combo.count():
            combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    for name in win._PRESET_CHECKS:
        getattr(win, name).toggle()
    win._grid_nx = 3
    win.zone_table.setRowCount(1)
    win._pareto_x_decision = [8.0, 0.6] * 18
    win.cache.set_result('2d', {'stale': True})
    win._undo_last = {'le_L': 'old'}
    actions['加载配置文件…'].trigger()
    assert not errors
    assert win.combo_dim.currentIndex() == dim
    assert win.le_pipeA_in_z_ctr.isHidden() == (dim == 0)
    assert asdict(config_from_window(win)) == before
    assert win._capture_current_preset('test') == saved
    assert not win.cache.get_result('2d')
    assert not win.cache.has_results('2d') and not win.cache.has_results('3d')
    assert win._undo_last['le_L'] == '0.182'
    assert win._user_edited_grid
    # Exercise the real Compute entry point without starting numerical work.
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
    calls = []
    monkeypatch.setattr(win, '_validate_inputs_preflight', lambda: True)
    monkeypatch.setattr(win, '_preflight_grid', lambda: True)
    monkeypatch.setattr(win, '_preflight_3d', lambda: (True, 8, 'test'))

    def capture_start(mode, worker, *, cfg):
        calls.append((mode, worker.keywords['pipeline_cls'], asdict(cfg)))
        return True

    monkeypatch.setattr(win.compute, 'start', capture_start)
    win.run_calculation()
    assert calls == [('3d' if dim else '2d', Pipeline3D if dim else Pipeline2D, before)]
    if dim:
        win._compute_3d_watchdog.stop()


@pytest.mark.parametrize('shape', [1, 2])
def test_polygon_file_is_rejected_without_changing_inputs_or_results(
        tmp_path, monkeypatch, win, shape):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from sjtu_tpmshx.ui.window_config import DOMAIN_SHAPE_NOTICE

    win._apply_shanghai_defaults()
    before = win._capture_current_preset('current')
    old = win._capture_current_preset('polygon')
    old['combos'].update(combo_shape=shape, combo_edge_inA=2)
    old['line_edits'].update(le_L='0.333', le_mesh_density='1200')
    path = tmp_path / 'polygon.json'
    original = json.dumps({'config_format': 1, 'preset': old})
    path.write_text(original)
    result = {'already computed': True}
    win.cache.set_result('2d', result)
    errors = []
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[2]))
    assert not win.load_config()
    assert errors == [DOMAIN_SHAPE_NOTICE]
    assert win._capture_current_preset('current') == before
    assert win.cache.get_result('2d') is result
    assert path.read_text() == original


@pytest.mark.parametrize('shape', [1, 2])
def test_polygon_session_does_not_partially_restore(win, monkeypatch, shape):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.ui.window_config import DOMAIN_SHAPE_NOTICE

    win._apply_shanghai_defaults()
    before = win._capture_current_preset('current')
    old = win._capture_current_preset('polygon session')
    old['combos']['combo_shape'] = shape
    old['line_edits']['le_L'] = '0.333'
    monkeypatch.setattr(win.sm, 'load_session', lambda *args: old)
    callbacks, notices = [], []
    monkeypatch.setattr(QTimer, 'singleShot', lambda interval, owner, callback: callbacks.append(callback))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: notices.append(args[2]))
    win._restore_session()
    assert win._capture_current_preset('current') == before
    assert len(callbacks) == 1
    callbacks[0]()
    assert len(notices) == 1 and DOMAIN_SHAPE_NOTICE in notices[0]
    assert '保留当前' in notices[0]


@pytest.mark.parametrize('notice', ['information', 'warning'])
@pytest.mark.parametrize('delete_before_delivery', [False, True])
def test_deferred_session_notice_follows_window_lifetime(
        tmp_path, monkeypatch, notice, delete_before_delivery):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
    from shiboken6 import isValid
    from sjtu_tpmshx.controllers import session_manager
    from sjtu_tpmshx.main import Main_Menu

    original_init = session_manager.SessionManager.__init__
    monkeypatch.setattr(session_manager.SessionManager, '__init__',
                        lambda self, parent=None: original_init(
                            self, base_dir=tmp_path, parent=parent))
    window = Main_Menu()
    assert window.sm.base_dir == tmp_path
    payload = {'checks': {'chk_var_rhocp': False}}
    if notice == 'warning':
        payload = {'combos': {'combo_shape': 1}}
    monkeypatch.setattr(window.sm, 'load_session', lambda *_: payload)
    messages = []
    monkeypatch.setattr(QMessageBox, notice, lambda *args: messages.append(args[1:]))
    try:
        window._restore_session()
        assert not messages  # The notification is deferred, not synchronous.
        if delete_before_delivery:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not isValid(window)
        QApplication.processEvents()
        assert len(messages) == (0 if delete_before_delivery else 1)
    finally:
        if isValid(window):
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_old_rectangular_file_with_unused_mesh_field_remains_loadable(
        tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    win._apply_shanghai_defaults()
    old = win._capture_current_preset('rectangle')
    old['line_edits'].update(le_L='0.195', le_mesh_density='auto')
    path = tmp_path / 'rectangle.json'
    original = json.dumps({'config_format': 1, 'preset': old})
    path.write_text(original)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[2]))
    assert win.load_config() and not errors
    assert win.le_L.text() == '0.195'
    current = win._capture_current_preset('current')
    assert current['combos']['combo_shape'] == 0
    assert 'le_mesh_density' not in current['line_edits']
    assert not any(name.startswith('combo_edge_') for name in current['combos'])
    assert path.read_text() == original


def test_save_load_config_roundtrip(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog
    cfg_path = str(tmp_path / 'cfg.json')

    win.le_Lcell.setText('6.5')
    win.le_t.setText('0.45')
    assert win.combo_df_mode.count() == 2
    win.combo_df_mode.setCurrentIndex(0)
    assert win.combo_df_mode.model().item(1).isEnabled()
    win.combo_fluidB.setCurrentText('Air')
    assert win.combo_df_mode.model().item(1).isEnabled()
    win.combo_df_mode.setCurrentIndex(1)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: (cfg_path, 'json')))
    win.save_config()

    data = json.loads(Path(cfg_path).read_text(encoding='utf-8'))
    assert data['preset']['line_edits']['le_Lcell'] == '6.5'
    assert data['preset']['line_edits']['le_t'] == '0.45'
    assert data['preset']['combos']['combo_df_mode'] == 1

    # Perturb, then load back — fields must restore.
    win.le_Lcell.setText('9.9')
    win.le_t.setText('0.9')
    win.combo_df_mode.setCurrentIndex(0)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        staticmethod(lambda *a, **k: (cfg_path, 'json')))
    win.load_config()
    assert win.le_Lcell.text() == '6.5'
    assert win.le_t.text() == '0.45'
    assert win.combo_df_mode.currentData() == 'experimental'


def test_load_config_cancel_is_noop(monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog
    win.le_Lcell.setText('7.0')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        staticmethod(lambda *a, **k: ('', '')))
    win.load_config()
    assert win.le_Lcell.text() == '7.0'


@pytest.mark.parametrize('damage', ['missing', 'unknown', 'combo', 'unit',
                                    'rows', 'pareto', 'numeric', 'boolean', 'version'])
def test_bad_config_does_not_partially_apply(tmp_path, monkeypatch, win, damage):
    from copy import deepcopy
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    before = win._capture_current_preset('test')
    preset = deepcopy(before)
    preset['line_edits']['le_L'] = '0.333'
    payload = {'config_format': 1, 'preset': preset}
    if damage == 'missing':
        del preset['checks']['chk_allow_extrap']
    elif damage == 'unknown':
        preset['line_edits']['statusBar'] = '42'
    elif damage == 'combo':
        preset['combos']['combo_fluidA'] = 999
    elif damage == 'unit':
        preset['temp_unit'] = 'F'
    elif damage == 'rows':
        preset['zone_inputs']['rows'] = [['0']]
    elif damage == 'pareto':
        preset['zone_inputs']['pareto_x_decision'] = {'__class__': 'bad'}
    elif damage == 'numeric':
        preset['line_edits']['le_PinA'] = 'NaN'
    elif damage == 'boolean':
        preset['line_edits']['le_PinA'] = True
    else:
        payload['config_format'] = 2
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
    win.cache.set_result('2d', {'old': 123})
    assert win.load_config() is False
    assert errors
    assert win._capture_current_preset('test') == before
    assert win.cache.get_result('2d') == {'old': 123}
    win.cache.clear('2d')


def test_config_io_failures_and_cancel(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    import sjtu_tpmshx.controllers.session_manager as sm_mod

    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: ('', ''))
    assert win.save_config() is False
    assert not errors
    path = tmp_path / 'existing.json'
    path.write_text('original file')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))

    def fail_replace(*args):
        raise OSError('replace denied')

    monkeypatch.setattr(sm_mod.os, 'replace', fail_replace)
    assert win.save_config() is False
    assert errors and path.read_text() == 'original file'
    assert not path.with_suffix('.json.tmp').exists()
    before = win._capture_current_preset('test')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    assert win.load_config() is False  # malformed JSON
    assert win._capture_current_preset('test') == before
    path.unlink()
    assert win.load_config() is False  # missing file
    assert win._capture_current_preset('test') == before


def test_legacy_file_preserves_fields_and_reports_missing_inputs(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    payload = {'L': '0.231', 'H': '0.051', 'rho_s': '8123', 'Nx': '22',
               'Ny': '17', 'L_cell': '6.5', 't': '0.45', 'k_s': '17',
               'u_A': '2.3', 'u_B': '0.21', 'T_inA': '130', 'T_inB': '42',
               'P_inA': '120000', 'P_inB': '240000', 'tpms_type': 'Diamond',
               'df_mode': 'experimental', 'dir_A': 1, 'dir_B': 2, 'T_s_init': ''}
    for side in ('A', 'B'):
        for port in ('in', 'out'):
            payload[f'pipe{side}_{port}_ctr'] = '0.024'
            payload[f'pipe{side}_{port}_w'] = '0.012'
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(a))
    win._temp_unit = 'C'
    win.combo_fluidA.setCurrentIndex(2)
    untouched = (win.le_Nz.text(), win.combo_dim.currentIndex(),
                 win.le_pipeA_in_z_w.text())
    expected = win._legacy_config_preset(payload)
    assert win.load_config()
    assert warnings and '不是完整工况恢复' in warnings[0][2]
    for name, value in expected['line_edits'].items():
        assert getattr(win, name).text() == value
    for name, value in expected['combos'].items():
        assert getattr(win, name).currentIndex() == value
    assert win.combo_fluidA.currentIndex() == 2 and win._temp_unit == 'C'
    assert (win.le_Nz.text(), win.combo_dim.currentIndex(),
            win.le_pipeA_in_z_w.text()) == untouched


@pytest.mark.parametrize('name', [
    'Shanghai (3D Gyroid)', 'Shanghai (2D Gyroid)', 'Shanghai (3D Diamond)',
])
@pytest.mark.parametrize('unit', ['K', 'C'])
def test_shanghai_preset_restores_ports_and_valid_grid(win, name, unit):
    from dataclasses import asdict
    from sjtu_tpmshx.domain.compute_config import bc_to_dict
    from sjtu_tpmshx.models.grid import build_port_wall_grid
    from sjtu_tpmshx.tests.test_sco2_nu_modes import SYNTHETIC
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._temp_unit = unit
    win._sync_temp_unit_labels()
    win.combo_fluidA.setCurrentIndex(2)
    win.combo_fluidB.setCurrentIndex(0)
    win.combo_dirA.setCurrentIndex(1)
    win.combo_dirB.setCurrentIndex(2)
    win.chk_zones.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(2)
    win._zone_grid = {'stale': True}
    win._pareto_x_decision = [6.0, 0.4] * 18
    win._set_sco2_nu_parameters(asdict(SYNTHETIC))
    win.combo_sco2_nu_mode.setCurrentIndex(1)
    win.le_rho_s.setText('1234')
    win.chk_allow_extrap.setChecked(False)
    # Loading after a smaller case must not retain its 30 mm Z openings.
    win.le_Lz.setText('0.03')
    for side in ('A', 'B'):
        for end in ('in', 'out'):
            getattr(win, f'le_pipe{side}_{end}_z_ctr').setText('0.015')
            getattr(win, f'le_pipe{side}_{end}_z_w').setText('0.03')
    win.combo_df_mode.setCurrentIndex(0)
    win._load_named_preset(name)
    cfg = config_from_window(win)
    assert cfg.df_mode == 'experimental'
    assert (cfg.fluid_A.type, cfg.fluid_B.type) == ('air', 'water')
    assert (cfg.bc_A.dir, cfg.bc_B.dir) == (0, 3)
    assert (cfg.fluid_A.u_mps, cfg.fluid_A.T_in_K, cfg.fluid_A.P_in_Pa) == (20.0, 422.0, 192362.0)
    assert (cfg.fluid_B.u_mps, cfg.fluid_B.T_in_K, cfg.fluid_B.P_in_Pa) == (0.133, 300.0, 101973.0)
    assert win._temp_unit == unit
    assert cfg.sco2_nu.mode == 'cfd_smooth' and win._sco2_nu_parameters == {}
    assert not cfg.zones.enabled and win._zone_grid is None
    assert win._pareto_x_decision is None and win.combo_zone_axis.currentIndex() == 0
    assert float(win.le_rho_s.text()) == 7900 and cfg.extrap.allow
    assert win._active_preset_name == name
    for side in ('A', 'B'):
        for end in ('in', 'out'):
            assert getattr(win, f'le_pipe{side}_{end}_z_ctr').text() == '0.021'
            assert getattr(win, f'le_pipe{side}_{end}_z_w').text() == '0.042'
    geom, solver = cfg.geometry, cfg.solver
    lengths = (geom.L_dom_m, geom.H_dom_m)
    counts = (solver.Nx, solver.Ny)
    if cfg.is_3d:
        lengths += (geom.Lz_m,)
        counts += (solver.Nz,)
    ports = [bc_to_dict(getattr(cfg, f'bc_{side}'), *lengths[:2],
                        side=side, with_z=cfg.is_3d)
             for side in ('A', 'B')]
    grid = build_port_wall_grid(lengths, counts, ports)
    assert tuple(len(widths) for widths in grid) == counts


@pytest.mark.parametrize('route', ['preset', 'session'])
@pytest.mark.parametrize('saved_mode', [None, 0, 1])
def test_saved_df_choice_is_preserved(win, monkeypatch, route, saved_mode):
    payload = {'combos': {} if saved_mode is None else {'combo_df_mode': saved_mode}}
    win.combo_df_mode.setCurrentIndex(1)
    if route == 'preset':
        win._apply_user_preset(payload)
    else:
        monkeypatch.setattr(win.sm, 'load_session', lambda *args: payload)
        win._restore_session()
    assert win.combo_df_mode.currentIndex() == (saved_mode or 0)


def test_partial_preset_allowlist_and_session_preserves_saved_case(win):
    win._apply_user_preset({'line_edits': {'le_L': '0.22', 'statusBar': 'evil'},
                            'combos': {'combo_fluidA': 1}, 'temp_unit': 'C'})
    assert win.le_L.text() == '0.22' and callable(win.statusBar)
    win.le_Nx.setText('31')
    win.le_TinA.setText('70')
    assert win._save_session()
    win.combo_fluidA.setCurrentIndex(0)  # construction-time Air default
    win._apply_shanghai_defaults()
    win._restore_session()
    assert win._temp_unit == 'K'
    assert win.le_Nx.text() == '31'
    assert float(win.le_TinA.text()) == pytest.approx(343.15)
    assert win.combo_grid.currentData() is False
    assert win.combo_fluidA.currentIndex() == 1
    assert win.combo_fluidB.currentIndex() == 1


@pytest.mark.parametrize('unit', ['K', 'C'])
def test_session_restores_complete_physical_case_in_kelvin(win, monkeypatch, unit):
    from dataclasses import asdict
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    win._temp_unit = unit
    win._sync_temp_unit_labels()
    win.combo_fluidA.setCurrentIndex(2)
    win.combo_fluidB.setCurrentIndex(0)
    win.combo_dirA.setCurrentIndex(1)
    win.combo_dirB.setCurrentIndex(2)
    win.combo_df_mode.setCurrentIndex(0)
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    edits = {'le_L': '.06', 'le_H': '.03', 'le_Lz': '.03',
             'le_Nx': '30', 'le_Ny': '18', 'le_Nz': '10',
             'le_uA': '1.7', 'le_PinA': '12000000',
             'le_uB': '7.5', 'le_PinB': '201325',
             'le_TinA': '86.85' if unit == 'C' else '360',
             'le_TinB': '26.85' if unit == 'C' else '300'}
    for side, centre, width in (('A', '.015', '.020'), ('B', '.030', '.030')):
        for end in ('in', 'out'):
            for suffix, value in (('ctr', centre), ('w', width),
                                  ('z_ctr', '.01'), ('z_w', '.02')):
                edits[f'le_pipe{side}_{end}_{suffix}'] = value
    for name, value in edits.items():
        getattr(win, name).setText(value)
    before = asdict(config_from_window(win))
    before['flags']['temp_unit'] = 'K'
    saved = {}
    monkeypatch.setattr(win.sm, 'save_session', lambda payload, ws: saved.update(payload) or True)
    assert win._save_session()
    win._apply_shanghai_defaults()
    win.cache.set_result('2d', {'stale': True})
    monkeypatch.setattr(win.sm, 'load_session', lambda ws: saved)
    win._restore_session()
    assert win._temp_unit == 'K'
    assert asdict(config_from_window(win)) == before
    assert not win.cache.get_result('2d')
    assert saved['temp_unit'] == unit  # loading did not rewrite the source payload


def test_partial_celsius_session_does_not_convert_missing_kelvin_field(win, monkeypatch):
    win._temp_unit = 'K'
    win._apply_shanghai_defaults()
    old = {'temp_unit': 'C', 'line_edits': {'le_TinA': '70'}, 'combos': {}}
    monkeypatch.setattr(win.sm, 'load_session', lambda ws: old)
    win._restore_session()
    assert float(win.le_TinA.text()) == pytest.approx(343.15)
    assert float(win.le_TinB.text()) == 300.0


def test_workspaces_restore_their_own_zone_table_and_pareto_state(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QTableWidgetItem

    monkeypatch.setattr(win.sm, '_base', tmp_path)
    monkeypatch.setattr(win, '_active_workspace', 'A')
    win._temp_unit = 'K'
    win._apply_shanghai_defaults()
    win.combo_df_mode.setCurrentIndex(0)
    win.combo_zone_axis.setCurrentIndex(2)
    win.chk_zones.setChecked(True)
    win._grid_nx = 2
    rows_a = [[str(y0), str(y1), str(x0), str(x1), '6.5', '0.45']
              for y0, y1 in ((0, 40), (40, 100))
              for x0, x1 in ((0, 60), (60, 100))]
    win.zone_table.setRowCount(len(rows_a))
    for r, row in enumerate(rows_a):
        for c, value in enumerate(row):
            win.zone_table.setItem(r, c, QTableWidgetItem(value))
    win._pareto_x_decision = [6.5, .45] * 18
    win._pareto_y_trans_inlet, win._pareto_y_trans_outlet = .15, .18
    saved_a = win._capture_current_preset('A')
    win._switch_workspace('B')
    win.combo_df_mode.setCurrentIndex(0)
    win.combo_dim.setCurrentIndex(0)
    win.combo_zone_axis.setCurrentIndex(1)
    win.chk_zones.setChecked(True)
    win._zone_init_1d(2)
    win.zone_table.item(0, 2).setText('8.0')
    saved_b = win._capture_current_preset('B')

    win._switch_workspace('A')
    restored_a = win._capture_current_preset('A')
    assert restored_a['zone_inputs'] == saved_a['zone_inputs']
    assert restored_a['combos']['combo_zone_axis'] == 2
    assert restored_a['checks']['chk_zones']
    on_disk = json.loads(win.sm.session_path('A').read_text())
    assert on_disk['zone_inputs'] == saved_a['zone_inputs']
    win._switch_workspace('B')
    restored_b = win._capture_current_preset('B')
    assert restored_b['zone_inputs'] == saved_b['zone_inputs']
    assert restored_b['combos']['combo_zone_axis'] == 1
    assert restored_b['checks']['chk_zones']


def test_legacy_session_without_zone_data_disables_and_clears_stale_zones(win, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    win._apply_shanghai_defaults()
    win.combo_zone_axis.setCurrentIndex(2)
    win.chk_zones.setChecked(True)
    win._pareto_x_decision = [8.0, .5] * 18
    old = win._capture_current_preset('old session')
    old.pop('zone_inputs')
    old['combos'].pop('combo_zone_axis')
    callbacks, messages = [], []
    monkeypatch.setattr(win.sm, 'load_session', lambda ws: old)
    monkeypatch.setattr(QTimer, 'singleShot', lambda interval, owner, callback: callbacks.append(callback))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[2]))
    win._restore_session()
    assert not win.chk_zones.isChecked() and win.zone_table.rowCount() == 0
    assert win._zone_grid is None and win._pareto_x_decision is None
    assert win.combo_zone_axis.currentIndex() == 0 and win._grid_nx == 2
    assert old['checks']['chk_zones'] and 'zone_inputs' not in old
    for callback in callbacks:
        callback()
    assert len(messages) == 1 and '旧会话未保存分区数据' in messages[0]


@pytest.mark.parametrize('route', ['preset', 'recent', 'link'])
def test_shared_preset_callers_restore_new_inputs(monkeypatch, win, route):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QInputDialog
    import sjtu_tpmshx.ui.mixins.run_history as history

    win.chk_allow_extrap.setChecked(True)
    win.combo_zone_axis.setCurrentIndex(1)
    win.chk_zones.setChecked(True)
    win._zone_init_1d(2)
    saved = win._capture_current_preset('test')
    tokens = []
    monkeypatch.setattr(history, 'QApplication', SimpleNamespace(
        clipboard=lambda: SimpleNamespace(setText=tokens.append)))
    win._copy_reproducible_link()
    win.chk_allow_extrap.setChecked(False)
    win.combo_zone_axis.setCurrentIndex(2)
    if route == 'preset':
        win._load_user_preset(saved)
    elif route == 'recent':
        win._load_recent_run({'preset': saved, 'ts': 'test'})
    else:
        monkeypatch.setattr(QInputDialog, 'getText', lambda *a: (tokens[0], True))
        win._load_reproducible_link()
    assert win._capture_current_preset('test') == saved


def test_export_results_no_data_shows_dialog(monkeypatch, win):
    """Without results the export path must short-circuit on the info
    dialog — not crash, not write a file."""
    from PySide6.QtWidgets import QMessageBox
    hits = []
    monkeypatch.setattr(QMessageBox, 'information',
                        staticmethod(lambda *a, **k: hits.append(a)))
    # Fresh module-scoped window: no compute has run, so both the 2D
    # cache and _result_3d are empty by construction.
    win._export_results()
    assert hits, 'expected the No Results dialog'


def test_export_results_writes_2d_values(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog

    out = tmp_path / 'results.csv'
    win.cache.set_result('2d', {'Q_total': 123.5, 'dP_A': 45.0, 'dP_B': 6.0, 'Ta': np.array([[300.0, 301.0], [302.0, 303.0]]), 'L': 0.2, 'H': 0.1})
    monkeypatch.setattr(
        QFileDialog, 'getSaveFileName',
        staticmethod(lambda *a, **k: (str(out), 'CSV')),
    )

    win._export_results()

    text = out.read_text()
    assert 'Q [W/m],123.5000' in text
    assert 'Grid Nx,2' in text
    import csv
    with out.open(encoding='utf-8', newline='') as stream:
        rows = dict(csv.reader(stream))
    for key in ('converged', 'envelope_valid', 'outer_converged',
                'warnings', 'extrap_reasons'):
        assert rows[key] == 'unknown'


def test_export_results_writes_3d_values_and_fields(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog
    from sjtu_tpmshx.domain.compute_result import ComputeResult

    out = tmp_path / 'results.csv'
    field = np.arange(24.0).reshape(2, 3, 4)
    expected = {name: field + offset for offset, name in enumerate(
        ('Ta', 'Tb', 'Ts', 'ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB', 'vmag_A', 'vmag_B'))}
    expected.update(P_fA=101325. + field, P_fB=202650. + field,
                    L_mm=4. + field / 10., t_mm=.3 + field / 100.,
                    dx=np.array([.05, .15]), dy=np.array([.01, .03, .06]),
                    dz=np.array([.005, .01, .015, .02]))
    win.cache.set_result('3d', ComputeResult(Q_W=321.0, dP_A_Pa=54.0, dP_B_Pa=7.0,
        fields={**expected, 'Lx': .2, 'Ly': .1, 'Lz': .05}))
    monkeypatch.setattr(
        QFileDialog, 'getSaveFileName',
        staticmethod(lambda *a, **k: (str(out), 'CSV')),
    )

    win._export_results()

    assert 'Q [W],321.0000' in out.read_text()
    with np.load(tmp_path / 'results_fields.npz', allow_pickle=False) as fields:
        for name, values in expected.items():
            np.testing.assert_array_equal(fields[name], values, err_msg=name)
        np.testing.assert_array_equal(fields['vmag'], expected['vmag_A'])
        np.testing.assert_array_equal(fields['P_kPa'], expected['P_fA'] / 1000.)
        assert all(fields[name].dtype.kind != 'O' for name in fields.files)
        assert fields['converged'].item() == 'true'
        assert fields['warnings'].item() == '[]'
        assert fields['extrap_reasons'].item() == '[]'
        assert fields['envelope_valid'].item() == 'unknown'
        assert fields['outer_converged'].item() == 'unknown'


def test_export_failure_preserves_old_pair_and_memory_then_retries(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    csv_path = tmp_path / 'result.csv'
    npz_path = tmp_path / 'result_fields.npz'
    csv_path.write_text('previous successful CSV')
    npz_path.write_bytes(b'previous successful NPZ')
    result = ComputeResult(Q_W=321., fields={'Ta': np.ones((2, 2, 2))},
                           metadata={'source_result_id': 'next-run'})
    win.cache.set_result('3d', result)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(csv_path), 'CSV'))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a[-1]))
    original = np.savez_compressed

    def fail(path, **kwargs):
        from pathlib import Path
        Path(path).write_bytes(b'partial NPZ')
        raise OSError('simulated full disk at NPZ write')

    monkeypatch.setattr(np, 'savez_compressed', fail)
    win._export_results()
    assert errors and 'full disk' in errors[-1]
    assert csv_path.read_text() == 'previous successful CSV'
    assert npz_path.read_bytes() == b'previous successful NPZ'
    assert win.cache.get_result('3d') is result
    monkeypatch.setattr(np, 'savez_compressed', original)
    win._export_results()
    assert 'next-run' in csv_path.read_text()
    with np.load(npz_path, allow_pickle=False) as fields:
        assert 'next-run' in fields['metadata'].item()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['result.csv', 'result_fields.npz']


@pytest.mark.parametrize('converged,envelope,outer', [
    (True, True, True), (False, True, True), (True, False, True),
    (True, True, False),
])
def test_result_status_survives_notification_and_mode_switch(
        tmp_path, monkeypatch, win, converged, envelope, outer):
    import csv
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    from sjtu_tpmshx.ui.plot_2d_results import finalize_plots

    notices, errors = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: notices.append(a))
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
    # These are existing-carrier messages, not proof of Nu source collection.
    warnings = ['经验外推, "边界"\n第二行', '另一条警告']
    reasons = ['L 超出范围,\n请核对', 'Re 外推']
    for index, mode in enumerate(('2d', '3d', '2d')):
        field = np.arange(8.0).reshape((2, 4) if mode == '2d' else (2, 2, 2)) + 300
        result = ComputeResult(
            Q_W=123 + index, dP_A_Pa=45, dP_B_Pa=6,
            converged=converged, warnings=warnings.copy(),
            extrap_reasons=reasons.copy(),
            diagnostics={'mode': mode, 'envelope_valid': envelope,
                         'convergence_detail': {'outer_converged': outer}},
            fields={key: field for key in
                    ('Ta', 'Tb', 'Ts', 'ucA', 'vcA', 'ucB', 'vcB', 'P_fA',
                     'P_fB', 'vmag_A')},
        )
        result.fields.update(N_x=2, N_y=4, L=0.2, H=0.1, dir_A=0, dir_B=2,
                             dx_arr=np.full(2, 0.1), dy_arr=np.full(4, 0.025))
        win.write_result(result)
        expected_warnings = result.warnings.copy()
        if mode == '2d':
            finalize_plots(win)
            assert win._compute_warnings == expected_warnings
            assert not notices, 'completed solves must not wait for a warning popup'
            assert win._diag_summary['converged'] == converged
            assert win.cache.get_result('2d')['warnings'] == expected_warnings
            # Result owns copies; a later notification/draft must not replace it.
            result.warnings.clear()
            result.extrap_reasons.clear()
        win._compute_warnings = ['下一工况通知']
        win._extrap_reasons = ['下一工况外推']
        out = tmp_path / f'{index}.csv'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(out), ''))
        win._export_results()
        assert not errors
        with out.open(encoding='utf-8', newline='') as stream:
            rows = dict(csv.reader(stream))
        q_unit = 'W' if mode == '3d' else 'W/m'
        assert rows[f'Q [{q_unit}]'] == f'{123 + index:.4f}'
        for key, value in (('converged', converged), ('envelope_valid', envelope),
                           ('outer_converged', outer), ('warnings', expected_warnings),
                           ('extrap_reasons', reasons)):
            assert json.loads(rows[key]) == value
        npz = tmp_path / f'{index}_fields.npz'
        if mode == '3d':
            with np.load(npz, allow_pickle=False) as saved:
                for key in saved.files:
                    assert saved[key].dtype.kind != 'O'
                for key in ('converged', 'envelope_valid', 'outer_converged',
                            'warnings', 'extrap_reasons'):
                    assert saved[key].item() == rows[key]
                np.testing.assert_array_equal(saved['vmag'], field)
                np.testing.assert_array_equal(saved['P_kPa'], field / 1000)
        else:
            assert not npz.exists()


def test_current_nu_button_explicit_selection_and_saved_parameter_restore(win):
    from dataclasses import asdict
    from sjtu_tpmshx.models.nu_correlations import sco2_effective_nu_config
    from sjtu_tpmshx.tests.test_sco2_nu_modes import SYNTHETIC
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    assert config_from_window(win).sco2_nu.mode == 'cfd_smooth'
    win._set_sco2_nu_parameters(asdict(SYNTHETIC))
    win.combo_sco2_nu_mode.setCurrentIndex(1)
    previous = win._capture_current_preset('explicit previous parameters')
    df_mode = win.combo_df_mode.currentData()
    win.btn_sco2_nu_current.click()
    assert config_from_window(win).sco2_nu == sco2_effective_nu_config()
    assert win.combo_df_mode.currentData() == df_mode
    assert '2.4824' in win.lbl_sco2_nu_parameters.text()
    assert '4.1064' in win.lbl_sco2_nu_parameters.text()
    current = win._capture_current_preset('current parameters')
    win._apply_user_preset(previous)
    assert config_from_window(win).sco2_nu == SYNTHETIC
    win._apply_user_preset(current)
    assert config_from_window(win).sco2_nu == sco2_effective_nu_config()


@pytest.mark.parametrize('nu_mode,df_mode', [(0,0),(0,1),(1,0),(1,1)])
def test_nu_parameters_import_save_load_snapshot(win, monkeypatch, tmp_path, nu_mode, df_mode):
    from dataclasses import asdict
    from PySide6.QtWidgets import QFileDialog
    from sjtu_tpmshx.tests.test_sco2_nu_modes import SYNTHETIC
    from sjtu_tpmshx.ui.window_config import config_from_window
    win._apply_shanghai_defaults()
    parameter_file = tmp_path / 'synthetic.json'
    parameter_file.write_text(json.dumps(asdict(SYNTHETIC)))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(parameter_file), ''))
    assert win._load_sco2_nu_parameters()
    parameter_file.unlink()  # Resolved contents, not an external-file dependency.
    win.combo_sco2_nu_mode.setCurrentIndex(nu_mode)
    win.combo_df_mode.setCurrentIndex(df_mode)
    original = config_from_window(win)
    output = tmp_path / 'saved.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), ''))
    assert win.save_config()
    win._set_sco2_nu_parameters({})
    win.combo_sco2_nu_mode.setCurrentIndex(0)
    win.combo_df_mode.setCurrentIndex(0)
    assert original.sco2_nu.alpha_D == .8
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(output), ''))
    assert win.load_config()
    assert config_from_window(win) == original
    old = win._capture_current_preset('old')
    del old['sco2_nu_parameters']
    del old['combos']['combo_sco2_nu_mode']
    win._apply_user_preset(old)
    assert config_from_window(win).sco2_nu.mode == 'cfd_smooth'
    assert config_from_window(win).sco2_nu.alpha_D is None


@pytest.mark.parametrize('missing_inlet_flags', [False, True])
def test_saved_older_solver_settings_upgrade_once_and_save_current_values(
        win, tmp_path, monkeypatch, missing_inlet_flags):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(0)
    old = win._capture_current_preset('older inlet settings')
    old['combos'].pop('combo_grid')
    old['checks'].update(chk_port_wall_refine=False, chk_wall_refine_3d=True,
                         chk_var_rhocp=False)
    for side in ('A', 'B'):
        key = f'chk_uniform_inlet{side}_2d'
        if missing_inlet_flags:
            old['checks'].pop(key)
        else:
            old['checks'][key] = False
    path = tmp_path / 'input.json'
    original = json.dumps({'config_format': 1, 'preset': old})
    path.write_text(original)
    notices, errors = [], []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: notices.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    assert win.load_config()
    assert not errors and len(notices) == 1
    assert all(part in notices[0] for part in ('流体 A', '流体 B', '六壁面', '局部密度'))
    assert path.read_text() == original
    config = config_from_window(win)
    assert config.bc_A.uniform_inlet_2d and config.bc_B.uniform_inlet_2d
    assert not config.flags.wall_refine_3d and config.flags.variable_rho_cp
    assert not config.flags.port_wall_refine
    new_path = tmp_path / 'current.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(new_path), ''))
    assert win.save_config()
    current = json.loads(new_path.read_text())['preset']
    assert all(current['checks'][key] == value for key, value in win._FIXED_SOLVER_CHECKS.items())
    assert 'chk_port_wall_refine' not in current['checks']
    assert current['combos']['combo_grid'] == win.combo_grid.findData(False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(new_path), ''))
    assert win.load_config()
    assert len(notices) == 1


def test_session_restore_reports_solver_update_and_resave_removes_repeat(win, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_shanghai_defaults()
    old = win._capture_current_preset('previous session')
    old['checks']['chk_var_rhocp'] = False
    old['checks']['chk_uniform_inletB_2d'] = False
    monkeypatch.setattr(win.sm, 'load_session', lambda *args: old)
    callbacks = []
    monkeypatch.setattr(QTimer, 'singleShot', lambda interval, owner, callback: callbacks.append((interval, callback)))
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[2]))
    win._restore_session()
    for interval, callback in callbacks:
        if interval == 0:
            callback()
    assert len(messages) == 1 and '局部密度热输运' in messages[0]
    assert '流体 B' in messages[0]
    config = config_from_window(win)
    assert config.flags.variable_rho_cp and config.bc_B.uniform_inlet_2d
    saved = []
    monkeypatch.setattr(win.sm, 'save_session', lambda payload, *args: saved.append(payload) or True)
    assert win._save_session()
    assert win._solver_settings_notice(saved[0]) == ''


def _drop_json(window, path):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(0, 0), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(event)
    return event.isAccepted()


@pytest.mark.parametrize('file_format', ['current', 'preset', 'library', 'flat'])
@pytest.mark.parametrize('entry', ['menu', 'drop'])
def test_current_and_old_configs_use_the_same_import_path(
        tmp_path, monkeypatch, win, file_format, entry):
    from sjtu_tpmshx.ui.mixins import io_actions
    win._apply_shanghai_defaults()
    win.le_uA.setText('20.0')
    path = tmp_path / 'config.json'
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *a: (str(path), ''))
    assert win.save_config()
    payload = json.loads(path.read_text())
    if file_format == 'preset':
        payload = payload['preset']
    elif file_format == 'library':
        payload = {'presets': [payload['preset']]}
    elif file_format == 'flat':
        payload = {'u_A': '20.0'}
    path.write_text(json.dumps(payload))
    win.le_uA.setText('99')
    warnings = []
    monkeypatch.setattr(io_actions.QMessageBox, 'warning',
                        lambda *a: warnings.append(a))
    monkeypatch.setattr(io_actions.QMessageBox, 'critical',
                        lambda *a: pytest.fail(str(a)))
    monkeypatch.setattr(io_actions.QFileDialog, 'getOpenFileName',
                        lambda *a: (str(path), ''))
    assert win.load_config() if entry == 'menu' else _drop_json(win, path)
    assert win.le_uA.text() == '20.0'
    assert bool(warnings) == (file_format == 'flat')


@pytest.mark.parametrize('entry', ['menu', 'drop'])
def test_both_import_entries_reject_unknown_format_without_changing_input(
        tmp_path, monkeypatch, win, entry):
    from sjtu_tpmshx.ui.mixins import io_actions
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps({'config_format': 999, 'preset':
                                {'line_edits': {'le_uA': '1'}}}))
    win.le_uA.setText('99')
    errors = []
    monkeypatch.setattr(io_actions.QMessageBox, 'critical', lambda *a: errors.append(a))
    monkeypatch.setattr(io_actions.QFileDialog, 'getOpenFileName',
                        lambda *a: (str(path), ''))
    result = win.load_config() if entry == 'menu' else _drop_json(win, path)
    assert not result and win.le_uA.text() == '99'
    assert len(errors) == 1 and 'Unsupported configuration format' in errors[0][2]


def _study_front(X, F):
    return dict(status='completed', reason=None, method='qlognehvi',
        history=[dict(x_decision=list(x), status='completed',
                      objectives=dict(heat_gain_percent=-f[0], pressure_ratio=f[1]))
                 for x, f in zip(X, F)], pareto_indices=list(range(len(X))),
        n_evaluated=len(X), n_usable=len(X))


def test_pareto_figure_copy_export_survives_field_result_then_clears_on_empty(
        tmp_path, monkeypatch, win):
    from PySide6.QtGui import QGuiApplication
    from sjtu_tpmshx.ui import optimize_panel
    from sjtu_tpmshx.ui.mixins import io_actions
    front = _study_front([[.5, .6], [.3, .7]], [[-8., .8], [-9., 1.1]])
    win.cache.clear()
    win.btn_export.setEnabled(False)
    optimize_panel.show_pareto(win, front)
    monkeypatch.setattr(win, '_active_tab', 'pareto')
    menu_actions = {action.text(): action for action in win.btn_export.menu().actions()}
    try:
        for state in ('pareto', 'preset-load', 'later-field-result'):
            if state == 'preset-load':
                win._invalidate_results_for_preset_load()
            if state == 'later-field-result':
                # Publishing a field snapshot clears its own rendered-tab flags.
                win.cache.set_result('2d', {'Q_total': 1.})
            QGuiApplication.clipboard().clear()
            assert win.btn_export.isEnabled()
            menu_actions['复制当前图像'].trigger()
            assert not QGuiApplication.clipboard().image().isNull()
            assert '已复制 pareto' in win.statusBar().currentMessage()
            calls = []
            def choose(*args):
                calls.append(args[3])
                return ('Pareto / 优化', True) if len(calls) == 1 else ('150 (screen)', True)
            monkeypatch.setattr(io_actions.QInputDialog, 'getItem', choose)
            path = tmp_path / f'{state}.png'
            monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                                lambda *a, **kw: (str(path), 'PNG (*.png)'))
            menu_actions['导出图像 — PNG / SVG / PDF'].trigger()
            assert 'Pareto / 优化' in calls[0] and path.is_file()
        optimize_panel.show_pareto(win, dict(front, pareto_indices=[]))
        win._copy_figure_clipboard()
        assert '当前无可复制' in win.statusBar().currentMessage()
        choices = []
        monkeypatch.setattr(io_actions.QInputDialog, 'getItem',
                            lambda *a: (choices.append(a[3]) or ('', False)))
        win._export_figure()
        assert choices and 'Pareto / 优化' not in choices[0]
        assert win.btn_export.isEnabled()  # Field results remain exportable.
        win.cache.clear()
        optimize_panel.show_pareto(win, dict(front, pareto_indices=[]))
        assert not win.btn_export.isEnabled()
    finally:
        win.cache.clear()
        win._pareto_X = win._pareto_F = None


def test_continuous_field_preview_button_shows_and_exports_after_preset_load(
        win, monkeypatch, tmp_path):
    from PIL import Image
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtGui import QGuiApplication
    from sjtu_tpmshx.ui.mixins import io_actions
    win._load_named_preset('Shanghai (2D Gyroid)')
    win.cache.clear()
    win._pareto_X = win._pareto_F = None
    win.canvas_opt_field.figure.clear()
    geometry_axes = tuple(win.canvas_layout.figure.axes)
    win.show()
    try:
        win._switch_tab('pareto')
        preview = next(button for button in win.findChildren(QPushButton)
                       if '预览连续场' in button.text())
        preview.click()
        assert win._active_tab == 'pareto'
        assert win._opt_result_tabs.currentWidget() is win.canvas_opt_field
        assert win.canvas_opt_field.isVisible()
        assert not win.cache.is_drawn('layout') and win.btn_export.isEnabled()
        assert tuple(win.canvas_layout.figure.axes) == geometry_axes
        assert not win._pareto_figure_ready() and win._opt_field_figure_ready()
        images = [image for axis in win.canvas_opt_field.figure.axes for image in axis.images]
        assert len(images) == 2 and all(np.isfinite(im.get_array()).all() for im in images)
        QGuiApplication.clipboard().clear()
        win._copy_figure_clipboard()
        assert not QGuiApplication.clipboard().image().isNull()
        assert '已复制 opt_field' in win.statusBar().currentMessage()
        # A later Compute preset is not the source of this retained field figure.
        win._load_named_preset('Shanghai (3D Diamond)')
        assert win._opt_field_figure_ready()
        path = tmp_path / 'continuous-field-preview.png'
        options = []
        def choose(*args):
            options.append(args[3])
            return ('优化尺寸/壁厚场', True) if len(options) == 1 else ('150 (screen)', True)
        monkeypatch.setattr(io_actions.QInputDialog, 'getItem', choose)
        monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                            lambda *a: (str(path), 'PNG (*.png)'))
        win._export_figure()
        assert path.is_file()
        assert options[0] == ['优化尺寸/壁厚场']
        with Image.open(path) as picture:
            assert picture.info['Title'] == 'SJTU-TPMSHX opt_field'
            assert 'Subject' not in picture.info
    finally:
        win.canvas_opt_field.figure.clear()
        win.cache.clear()
        win._refresh_export_button()
        win.hide()


def test_optimization_copy_uses_selected_result_tab_and_rejects_empty_field(win, monkeypatch):
    from PySide6.QtGui import QColor, QGuiApplication, QPixmap
    from sjtu_tpmshx.ui import optimize_panel
    from sjtu_tpmshx.ui.mixins import io_actions
    win._load_named_preset('Shanghai (2D Gyroid)')
    win.cache.clear()
    front = _study_front([[.5, .6]], [[-1., .8]])
    optimize_panel.show_pareto(win, front)
    optimize_panel.show_field_preview(win)
    monkeypatch.setattr(win, '_active_tab', 'pareto')
    clipboard = QGuiApplication.clipboard()
    try:
        for canvas, color in ((win.canvas_pareto, '#4488cc'), (win.canvas_opt_field, '#dd6633')):
            pixmap = QPixmap(8, 8)
            pixmap.fill(QColor(color))
            monkeypatch.setattr(canvas, 'grab', lambda p=pixmap: p)
            win._opt_result_tabs.setCurrentWidget(canvas)
            clipboard.clear()
            win._copy_figure_clipboard()
            assert clipboard.image().pixelColor(0, 0).name() == color
        win.canvas_opt_field.figure.clear()
        clipboard.clear()
        win._copy_figure_clipboard()
        assert clipboard.image().isNull()
        assert '当前无可复制' in win.statusBar().currentMessage()
        choices = []
        monkeypatch.setattr(io_actions.QInputDialog, 'getItem',
                            lambda *a: (choices.append(a[3]) or ('', False)))
        win._export_figure()
        assert choices == [['Pareto / 优化']]
        win._pareto_X = win._pareto_F = None
        win._refresh_export_button()
        assert not win.btn_export.isEnabled()
    finally:
        win._pareto_X = win._pareto_F = None
        win.canvas_opt_field.figure.clear()
        win._opt_result_tabs.setCurrentWidget(win.canvas_pareto)
        win._refresh_export_button()


@pytest.mark.parametrize('depth', ['invalid', '0', '-0.01'])
def test_optimization_validates_explicit_2d_flow_conversion_depth(win, depth):
    from sjtu_tpmshx.ui.optimize_panel import _gather_cfg
    win._load_named_preset('Shanghai (2D Gyroid)')
    win.le_Lz.setText(depth)
    assert win.le_Lz.isHidden()
    assert win._opt_depth.text() == depth
    with pytest.raises(ValueError, match='2D total-flow depth'):
        _gather_cfg(win)
    win.le_Lz.setText('0.042')
    assert _gather_cfg(win).geometry.Lz_m == .042


def test_retained_pareto_export_does_not_take_new_compute_preset_name(
        win, monkeypatch, tmp_path):
    from PIL import Image
    from sjtu_tpmshx.ui import optimize_panel
    from sjtu_tpmshx.ui.mixins import io_actions
    win._load_named_preset('Shanghai (2D Gyroid)')
    front = _study_front(np.ones((2, 18)), [[-1., .8], [-2., 1.1]])
    optimize_panel.show_pareto(win, front)
    win._load_named_preset('Shanghai (3D Diamond)')
    np.testing.assert_array_equal(win._pareto_F, [[-1., .8], [-2., 1.1]])
    path = tmp_path / 'retained-pareto.png'
    choices = iter([('Pareto / 优化', True), ('150 (screen)', True)])
    monkeypatch.setattr(io_actions.QInputDialog, 'getItem', lambda *a: next(choices))
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *a: (str(path), 'PNG (*.png)'))
    win._export_figure()
    with Image.open(path) as picture:
        assert 'Subject' not in picture.info
        assert picture.info['Title'] == 'SJTU-TPMSHX pareto'
    optimize_panel.show_pareto(win, dict(front, pareto_indices=[]))


@pytest.mark.parametrize('channels', [3, 4])
def test_optimization_volume_copy_and_export_require_current_render(
        win, monkeypatch, tmp_path, channels):
    from types import MethodType, SimpleNamespace
    from unittest.mock import Mock
    from PySide6.QtGui import QGuiApplication
    from sjtu_tpmshx.ui.mixins import io_actions
    from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel

    win.cache.clear()
    win._pareto_X = win._pareto_F = None
    win.canvas_opt_field.figure.clear()
    monkeypatch.setattr(win, '_active_tab', 'pareto')
    monkeypatch.setattr(win, '_opt_3d_data', None)
    win._opt_result_tabs.setCurrentWidget(win._opt_3d_host)
    pixels = np.array([[[17, 119, 68, 255], [230, 40, 10, 128], [5, 60, 180, 255]],
                       [[25, 70, 130, 64], [90, 40, 220, 255], [240, 210, 20, 255]]],
                      dtype=np.uint8)[:, :, :channels].copy()
    expected = pixels.copy()
    panel = SimpleNamespace(_grid=object(), _field='L_mm', _volume_actor=object(), _scale_mode='global',
                            plotter=Mock(), status=Mock(), grab=Mock())
    panel.plotter.screenshot.return_value = pixels
    panel._on_screenshot = MethodType(ThreeDVisPanel._on_screenshot, panel)
    monkeypatch.setattr(win, 'canvas_opt_3d', panel)
    monkeypatch.setattr(win, '_opt_3d_data', {'new-design': True})
    monkeypatch.setattr(win, '_opt_3d_ready', False)
    clipboard = QGuiApplication.clipboard()
    try:
        # A previous grid must not count as the newly requested design.
        win._refresh_export_button()
        assert not win.btn_export.isEnabled()
        clipboard.clear()
        win._copy_figure_clipboard()
        assert clipboard.image().isNull()
        panel.grab.assert_not_called()
        picker = Mock(return_value=('优化三维场', True))
        monkeypatch.setattr(io_actions.QInputDialog, 'getItem', picker)
        win._export_figure()
        picker.assert_not_called()

        win._opt_3d_ready = True
        win._refresh_export_button()
        assert win.btn_export.isEnabled()
        win._copy_figure_clipboard()
        panel.grab.assert_not_called()
        panel.plotter.screenshot.assert_called_once_with(return_img=True)
        pixels[:] = 0
        image = clipboard.image()
        assert (image.width(), image.height()) == (3, 2)
        for y in range(2):
            for x in range(3):
                assert image.pixelColor(x, y).getRgb()[:channels] == tuple(expected[y, x])
        panel.plotter.screenshot.reset_mock()
        path = tmp_path / 'optimization-volume.png'
        save_dialog = Mock(return_value=(str(path), 'PNG images (*.png)'))
        monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName', save_dialog)
        win._export_figure()
        picker.assert_called_once()
        assert picker.call_args.args[3] == ['优化三维场']
        assert save_dialog.call_args.args[3] == 'PNG images (*.png)'
        panel.plotter.screenshot.assert_called_once_with(str(path))
        panel.plotter.screenshot.side_effect = RuntimeError('screenshot failed')
        warning = Mock()
        monkeypatch.setattr(io_actions.QMessageBox, 'warning', warning)
        win._export_figure()
        assert warning.call_args.args[1:] == ('Export failed', 'screenshot failed')

        # The real L/t callback clears its actor if the next VTK volume fails,
        # even though the study's initial set_fields call already succeeded.
        panel.combo_field = SimpleNamespace(itemData=lambda index: 't_mm')
        panel._arrays = {'L_mm': object(), 't_mm': object()}
        panel._slice_info = None
        panel._clim_for = lambda field: (.3, .6)
        panel._opacity_ramp = lambda: (.2, .5)
        panel._build_volume_grid = lambda: (panel._grid, 1.)
        panel._update_status = Mock()
        panel._rebuild_volume = MethodType(ThreeDVisPanel._rebuild_volume, panel)
        panel.plotter.add_volume.side_effect = RuntimeError('field switch failed')
        ThreeDVisPanel._on_field_changed(panel, 1)
        assert panel._field == 't_mm' and panel._volume_actor is None
        assert win._opt_3d_ready  # This flag describes the earlier successful load.
        assert not win._opt_3d_figure_ready()
        win._refresh_export_button()
        assert not win.btn_export.isEnabled()
        panel.plotter.screenshot.reset_mock()
        picker.reset_mock()
        clipboard.clear()
        win._copy_figure_clipboard()
        win._export_figure()
        assert clipboard.image().isNull()
        panel.plotter.screenshot.assert_not_called()
        picker.assert_not_called()
    finally:
        win._opt_result_tabs.setCurrentWidget(win.canvas_pareto)
        win._opt_3d_ready = False
        win._refresh_export_button()
