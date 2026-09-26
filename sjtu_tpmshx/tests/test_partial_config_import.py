"""A partial import changes supplied inputs without reinterpreting the rest."""
import json

import pytest

from sjtu_tpmshx.tests.test_io_actions import win as win  # shared real Main_Menu fixture


@pytest.mark.parametrize('payload', [
    {'line_edits': {'le_L': '0.15'}},
    {'L': .15},
    {'temp_unit': 'K', 'line_edits': {'le_TinA': '410'}},
])
def test_partial_import_preserves_unsupplied_physical_inputs(win, tmp_path, monkeypatch, payload):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window

    for method in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, method, lambda *a: None)
    win._apply_shanghai_defaults()
    win._temp_unit = 'C'
    win._sync_temp_unit_labels()
    win.le_TinA.setText('148.85')
    win.le_TinB.setText('26.85')
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('experimental'))
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(True))
    before = win._capture_current_preset('before')
    path = tmp_path / 'partial.json'
    path.write_text(json.dumps(payload))
    assert win._load_config_path(str(path))
    config = config_from_window(win)
    assert config.fluid_A.T_in_K == pytest.approx(410 if 'temp_unit' in payload else 422)
    assert config.fluid_B.T_in_K == pytest.approx(300)
    assert win.combo_df_mode.currentData() == 'experimental'
    assert win.combo_grid.currentData() is True
    assert win._temp_unit == payload.get('temp_unit', 'C')
    after = win._capture_current_preset('before')
    for section in ('combos', 'checks', 'sco2_nu_parameters', 'zone_inputs',
                    'continuous_field', 'optimization_conditions'):
        assert after.get(section) == before.get(section)
    assert win.le_L.text() == ('0.15' if 'temp_unit' not in payload else before['line_edits']['le_L'])


@pytest.mark.parametrize('dimension', [0, 1])
def test_partial_import_keeps_full_continuous_field_and_conditions(win, tmp_path, monkeypatch, dimension):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.tests.test_optimize_panel_wiring import condition, report

    for method in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, method, lambda *a: None)
    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(dimension)
    study = report(win)
    preset = win._capture_current_preset('continuous')
    preset['checks']['chk_zones'] = True
    preset['continuous_field'] = {**study['field_spec'],
                                  'x_decision': study['history'][0]['x_decision']}
    preset['optimization_conditions'] = [condition()]
    win._apply_user_preset(preset)
    before = win._capture_current_preset('before')
    path = tmp_path / 'partial.json'
    path.write_text(json.dumps({'line_edits': {'le_rho_s': '7950'}}))
    assert win._load_config_path(str(path))
    after = win._capture_current_preset('before')
    before['line_edits']['le_rho_s'] = '7950'
    assert after == before


@pytest.mark.parametrize('kind', ['continuous', 'zones'])
def test_partial_import_rejects_conflicting_context_without_mutation(
        win, tmp_path, monkeypatch, kind):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    from sjtu_tpmshx.tests.test_optimize_panel_wiring import report

    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a[-1]))
    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(1)
    win.combo_zone_axis.setCurrentIndex(0)
    if kind == 'continuous':
        study = report(win)
        win._continuous_field_spec = {
            **study['field_spec'], 'x_decision': study['history'][0]['x_decision']}
    win.chk_zones.setChecked(True)
    before = win._capture_current_preset('before')
    previous_result = ComputeResult(Q_W=123.)
    win.cache.set_result('3d', previous_result)
    patch = {'line_edits': {}, 'combos': {
        'combo_dim' if kind == 'continuous' else 'combo_zone_axis':
        0 if kind == 'continuous' else 2}}
    path = tmp_path / 'conflicting-partial.json'
    path.write_text(json.dumps(patch))

    assert not win._load_config_path(str(path))
    assert errors
    assert win._capture_current_preset('before') == before
    assert win.cache.get_result('3d') is previous_result


@pytest.mark.parametrize('kind', ['continuous', 'zones'])
def test_partial_field_update_uses_current_dimension_and_axis(
        win, tmp_path, monkeypatch, kind):
    from copy import deepcopy
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.tests.test_optimize_panel_wiring import report

    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a[-1]))
    win._apply_shanghai_defaults()
    win.combo_dim.setCurrentIndex(1)
    win.combo_zone_axis.setCurrentIndex(0)
    if kind == 'continuous':
        study = report(win)
        win._continuous_field_spec = {
            **study['field_spec'], 'x_decision': study['history'][0]['x_decision']}
    win.chk_zones.setChecked(True)
    expected = win._capture_current_preset('before')
    name = 'continuous_field' if kind == 'continuous' else 'zone_inputs'
    updated = deepcopy(expected[name])
    if kind == 'continuous':
        updated['x_decision'][0] = 5.1
    else:
        updated['rows'][0][2] = '6.5'
    path = tmp_path / 'field-update.json'
    path.write_text(json.dumps({'line_edits': {}, name: updated}))

    assert win._load_config_path(str(path)), errors
    expected[name] = updated
    assert win._capture_current_preset('before') == expected


@pytest.mark.parametrize('section,value', [
    ('line_edits', [['le_L', '0.333']]),
    ('combos', [['combo_dim', 0]]),
    ('checks', [['chk_zones', False]]),
])
def test_partial_import_does_not_coerce_invalid_section_containers(
        win, tmp_path, monkeypatch, section, value):
    from PySide6.QtWidgets import QMessageBox

    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a[-1]))
    before = win._capture_current_preset('before')
    patch = {'line_edits': {}}
    patch[section] = value
    path = tmp_path / 'invalid-section.json'
    path.write_text(json.dumps(patch))
    assert not win._load_config_path(str(path))
    assert errors
    assert win._capture_current_preset('before') == before
