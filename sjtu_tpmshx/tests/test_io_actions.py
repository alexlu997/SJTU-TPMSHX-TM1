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
    win.combo_shape.setCurrentIndex(0)
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
    win.chk_var_rhocp.setChecked(False)
    win.chk_wall_refine_3d.setChecked(True)
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
    win._compute_results = {'stale': True}
    win._has_results_2d = win._has_results_3d = True
    win._undo_last = {'le_L': 'old'}
    actions['加载配置文件…'].trigger()
    assert not errors
    assert win.combo_dim.currentIndex() == dim
    assert win.le_pipeA_in_z_ctr.isHidden() == (dim == 0)
    assert asdict(config_from_window(win)) == before
    assert win._capture_current_preset('test') == saved
    assert not win._compute_results
    assert not win._has_results_2d and not win._has_results_3d
    assert win._undo_last['le_L'] == '0.182'
    assert win._user_edited_grid
    # Exercise the real Compute entry point without starting numerical work.
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
    calls = []
    monkeypatch.setattr(win, '_validate_inputs_preflight', lambda: True)
    monkeypatch.setattr(win, '_preflight_grid', lambda: True)
    monkeypatch.setattr(win, '_preflight_3d', lambda: (True, 8, 'test'))
    win._K_ffA = win._K_ffB = 1e-8

    def capture_start(mode, worker, *, cfg):
        calls.append((mode, worker.keywords['pipeline_cls'], asdict(cfg)))
        return True

    monkeypatch.setattr(win.compute, 'start', capture_start)
    win.run_calculation()
    assert calls == [('3d' if dim else '2d', Pipeline3D if dim else Pipeline2D, before)]
    if dim:
        win._compute_3d_watchdog.stop()


@pytest.mark.parametrize('shape,perturb_shape,edges', [
    (1, 0, [1, 4, 2, 5]), (2, 1, [7, 5, 1, 3]), (2, 2, [7, 5, 1, 3]),
])
def test_polygon_edges_menu_roundtrip(tmp_path, monkeypatch, win,
                                      shape, perturb_shape, edges):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    win._apply_shanghai_defaults()
    win.combo_shape.setCurrentIndex(shape)
    win.le_mesh_density.setText('1200')
    for name, index in zip(win._POLYGON_COMBOS, edges):
        getattr(win, name).setCurrentIndex(index)
    before = win._capture_current_preset('test')
    labels = [getattr(win, n).currentText() for n in win._POLYGON_COMBOS]
    path = tmp_path / 'polygon.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
    actions = {a.text(): a for a in win.btn_recent.menu().actions()}
    actions['保存配置文件…'].trigger()
    assert not errors
    payload = json.loads(path.read_text())
    payload['preset']['combos'] = dict(reversed(list(payload['preset']['combos'].items())))
    path.write_text(json.dumps(payload))  # JSON key order must not govern restore order
    win.combo_shape.setCurrentIndex(perturb_shape)
    win.le_L.setText('0.333')
    win.le_mesh_density.setText('auto')
    for name in win._POLYGON_COMBOS:
        getattr(win, name).setCurrentIndex(0)
    actions['加载配置文件…'].trigger()
    assert not errors
    assert win._capture_current_preset('test') == before
    assert [getattr(win, n).currentText() for n in win._POLYGON_COMBOS] == labels
    win.combo_shape.setCurrentIndex(0)


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
    win._compute_results = {'old': 123}
    assert win.load_config() is False
    assert errors
    assert win._capture_current_preset('test') == before
    assert win._compute_results == {'old': 123}
    win._compute_results = None


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


def test_partial_preset_allowlist_and_startup_reset_policy(win):
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
    assert [getattr(win, n).text() for n in ('le_Nx', 'le_Ny', 'le_Nz')] == ['20'] * 3
    assert win.combo_fluidA.currentIndex() == 0
    assert win.combo_fluidB.currentIndex() == 1


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
    win._compute_results = {
        'Q_total': 123.5, 'dP_A': 45.0, 'dP_B': 6.0,
        'Ta': np.array([[300.0, 301.0], [302.0, 303.0]]),
        'L': 0.2, 'H': 0.1,
    }
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
    field = np.arange(8.0).reshape(2, 2, 2)
    win._result_3d = ComputeResult(
        Q_W=321.0,
        dP_A_Pa=54.0,
        dP_B_Pa=7.0,
        fields={'Ta': field, 'Tb': field, 'Ts': field, 'vmag_A': field,
                'P_fA': field, 'Lx': 0.2, 'Ly': 0.1, 'Lz': 0.05},
    )
    monkeypatch.setattr(
        QFileDialog, 'getSaveFileName',
        staticmethod(lambda *a, **k: (str(out), 'CSV')),
    )

    win._export_results()

    assert 'Q [W],321.0000' in out.read_text()
    with np.load(tmp_path / 'results_fields.npz', allow_pickle=False) as fields:
        assert fields['Ta'].shape == (2, 2, 2)
        assert fields['converged'].item() == 'true'
        assert fields['warnings'].item() == '[]'
        assert fields['extrap_reasons'].item() == '[]'
        assert fields['envelope_valid'].item() == 'unknown'
        assert fields['outer_converged'].item() == 'unknown'


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
            assert win._compute_warnings is None
            assert notices
            assert win._diag_summary['converged'] == converged
            assert win._compute_results['warnings'] == expected_warnings
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
