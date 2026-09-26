"""User configuration must reach actual prepared fields and exported geometry."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models.continuous_field import encode_decision_vector
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG, build_field
from sjtu_tpmshx.models.tpms_calc import compute
from sjtu_tpmshx.preprocess.api import prepare_screening_2d, prepare_screening_3d


def _prepare(dimension, x, cfg):
    cfg = {**DEFAULT_CONFIG, **cfg, 'Nx': 20, 'Ny': 6}
    if dimension == 2:
        return prepare_screening_2d(x, cfg, case_id='fidelity')
    return prepare_screening_3d(x, cfg, case_id='fidelity', Nx=20, Ny=6, Nz=2,
                                roughness_mode='baseline', roughness_eps_um=100., verbose=False)


def _decision(n=4):
    wall = np.repeat(np.linspace(.35, .45, n)[:, None], n, axis=1)
    if n == 4:
        wall[:] = np.array([.35, .35, .45, .45])[:, None]
    return encode_decision_vector(np.full((n, n), 6.), wall)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('order,n', [(1, 4), (3, 4), (3, 6)])
def test_prepared_field_uses_original_bounds_and_order(dimension, order, n):
    cfg = {**DEFAULT_CONFIG, 't_bounds': (.35, .45), 'spline_order': order,
           'n_ctrl_x': n, 'n_ctrl_y': n}
    x = _decision(n)
    expected = build_field(x, cfg).evaluate_grid(20, 6)[1]
    case = _prepare(dimension, x, cfg)
    actual = np.asarray(case.metadata['geometry_fields']['t_wall_m']) * 1000.
    if dimension == 3:
        actual = actual[:, :, 0]
    np.testing.assert_allclose(actual, expected, atol=1e-15, rtol=0)
    assert actual.min() >= .35 - 1e-15 and actual.max() <= .45 + 1e-15


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('pressure', [100000., 200000.])
def test_each_side_uses_its_own_pressure(dimension, pressure):
    x = np.r_[np.full(8, 6.), np.full(8, .4)]
    case = _prepare(dimension, x, {'P_inA': 100000., 'P_inB': pressure})
    for side, temperature, p in [('A', 350., 100000.), ('B', 300., pressure)]:
        expected = compute('Diamond', 6., .4, 10., temperature, p, 17.)
        np.testing.assert_allclose(case.design_fields[f'h_v{side}_arr'],
                                   expected['H_sf'] * expected['A_0'], rtol=1e-14)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('cfg,reason', [({'fluid_type_B': 'water'}, 'air only'),
                                      ({'fluid_type_A': 'sco2'}, 'air only'),
                                      ({'dir_B': 2}, 'flow mapping'),
                                      ({'P_inB': float('nan')}, 'finite and positive')])
def test_unsupported_or_invalid_requests_are_rejected(dimension, cfg, reason):
    with pytest.raises(ValueError, match=reason):
        _prepare(dimension, _decision(), cfg)


def test_current_upper_bound_reaches_preparation_and_export(tmp_path):
    from sjtu_tpmshx.optimization.export_ntop_csv import export_decision_vector
    from sjtu_tpmshx.domain.validator import geometry_extrapolation_warning
    x = np.r_[np.full(8, 7.), np.full(8, .6)]
    for dimension in (2, 3):
        case = _prepare(dimension, x, {})
        np.testing.assert_allclose(case.metadata['geometry_fields']['t_wall_m'], .0006, rtol=1e-14)
    summary = export_decision_vector(x, str(tmp_path))
    assert summary['t_min_mm'] == pytest.approx(.6)
    assert geometry_extrapolation_warning(7., .6) is None
    assert geometry_extrapolation_warning(6.5, .55) is None
    assert geometry_extrapolation_warning(7., .61) is not None


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_ordinary_zones_preserve_b_pressure(axis):
    from sjtu_tpmshx.domain.compute_config import (
        ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, ExtrapPolicy, ZoneInputConfig,
    )
    from sjtu_tpmshx.models.zone_config import ZoneConfig
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg
    zones = ZoneInputConfig(enabled=True, axis=axis,
        config=ZoneConfig.single_zone(6., .4, 'Diamond', 17.),
        grid=dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6., t=.4)],
                  tpms_type='Diamond', k_s=17.))
    cfg = ComputeConfig(geometry=GeometryConfig(tpms='Diamond', k_s_W_mK=17.),
        fluid_A=FluidConfig(u_mps=10., T_in_K=350., P_in_Pa=100000.),
        fluid_B=FluidConfig(u_mps=10., T_in_K=300., P_in_Pa=200000.),
        solver=SolverConfig(Nx=4, Ny=4), extrap=ExtrapPolicy(allow=True), zones=zones)
    props = _parse_inputs_cfg(cfg)['za']
    for side, temperature, pressure in [('A', 350., 100000.), ('B', 300., 200000.)]:
        expected = compute('Diamond', 6., .4, 10., temperature, pressure, 17.)
        np.testing.assert_allclose(props['h_v' + side + '_arr'],
                                   expected['H_sf'] * expected['A_0'], rtol=1e-14)


def test_legacy_pareto_export_keeps_original_geometry_config(tmp_path):
    from sjtu_tpmshx.optimization.export_ntop_csv import export_pareto_row
    cfg = {**DEFAULT_CONFIG, 't_bounds': (.35, .45), 'ports_A': (.01, .03, .01, .03)}
    restored = json.loads(json.dumps(cfg))
    x = _decision()
    expected = build_field(x, cfg).evaluate_grid(80, 40)[1]
    path = tmp_path / 'pareto_final.csv'
    header = ','.join([*(f'x{i}' for i in range(len(x))), 'Q_W_per_m', 'dP_Pa'])
    np.savetxt(path, np.r_[x, 100., 200.][None, :], delimiter=',', header=header, comments='')
    export_pareto_row(str(path), 0, str(tmp_path / 'export'), config=restored,
                      Nx_export=80, Ny_export=40)
    exported = np.loadtxt(tmp_path / 'export/tfield.csv', delimiter=',', skiprows=1)
    np.testing.assert_allclose(exported[:, 2].reshape(40, 80), expected.T, atol=5.1e-7, rtol=0)
    with pytest.raises(ValueError, match='original config.json'):
        export_pareto_row(str(path), 0, str(tmp_path / 'missing-config'))


def test_typed_configuration_preserves_fluid_and_direction():
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig, PartialBCConfig
    from sjtu_tpmshx.optimization.evaluator import _compute_cfg_to_evaluator_dict
    from sjtu_tpmshx.optimization.evaluator_3d import _compute_cfg_to_evaluator_dict_3d
    source = ComputeConfig(fluid_B=FluidConfig(type='water'), bc_A=PartialBCConfig(dir=1),
                           bc_B=PartialBCConfig(dir=2))
    for convert in (_compute_cfg_to_evaluator_dict, _compute_cfg_to_evaluator_dict_3d):
        cfg = convert(source)
        assert (cfg['dir_A'], cfg['dir_B']) == (1, 2)
        assert cfg['fluid_type_B'] == 'water'


@pytest.mark.parametrize('field', ['le_qd_rho', 'le_qd_ks', 'le_qd_height'])
@pytest.mark.parametrize('value', ['', 'oops', 'nan', 'inf'])
def test_bad_quick_design_input_does_not_launch(field, value, monkeypatch):
    from PySide6.QtWidgets import QLineEdit, QLabel, QCheckBox
    from sjtu_tpmshx.ui import quick_design_panel
    window = SimpleNamespace(**{field: QLineEdit(value)}, _qd_status=QLabel(), chk_qd_rect=QCheckBox())
    window.chk_qd_rect.setChecked(True)
    monkeypatch.setattr(quick_design_panel, '_make_worker_class', lambda: pytest.fail('invalid request launched'))
    quick_design_panel.run_quick_design(window)
    assert '输入解析失败' in window._qd_status.text()


@pytest.mark.parametrize('fluid', ['Water', 'sCO₂'])
def test_sensitivity_rejects_non_air_a_and_clears_previous_grid(monkeypatch, fluid):
    from PySide6.QtWidgets import QComboBox, QLineEdit, QMainWindow
    from sjtu_tpmshx.ui import sensitivity
    window = QMainWindow()
    window.combo_fluidA = QComboBox()
    window.combo_fluidA.addItems(['Air', 'Water', 'sCO₂'])
    window.combo_fluidB = QComboBox()
    window.combo_fluidB.addItem('Water')
    window.le_Lcell = QLineEdit('7')
    window.le_t = QLineEdit('.5')
    calls = []

    def compute(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(H_sf=2., A_0=3., dP_per_L=2., Re=10., Nu=5.)

    monkeypatch.setattr('sjtu_tpmshx.models.tpms_calc.compute', compute)
    dialog = sensitivity.SensitivityDialog(window)
    try:
        dialog._le_steps.setText('3')
        dialog._run_sweep()
        assert len(calls) == 9  # Air A / Water B remains a valid A-side estimate.
        np.testing.assert_array_equal(dialog._grid_params['grid'], np.full((3, 3), 3.))
        old_axes = dialog._grid_axes
        window.combo_fluidA.setCurrentText(fluid)
        dialog._run_sweep()
        assert len(calls) == 9
        assert dialog._grid_params is None
        assert 'Fluid A must be Air' in dialog._hint.text()
        assert dialog._btn_run.isEnabled()
        dialog._on_click(SimpleNamespace(inaxes=old_axes, xdata=4., ydata=.3))
        assert window.le_Lcell.text() == '7' and window.le_t.text() == '.5'
    finally:
        dialog.close()
        window.close()


def test_heatmap_only_loads_valid_plot_cells():
    from matplotlib.backend_bases import MouseEvent
    from PySide6.QtWidgets import QMainWindow, QLineEdit
    from sjtu_tpmshx.ui.sensitivity import SensitivityDialog
    from sjtu_tpmshx.ui.theme import FIELD_CMAP
    window = QMainWindow()
    window.le_Lcell = QLineEdit('8')
    window.le_t = QLineEdit('.6')
    dialog = SensitivityDialog(window)
    dialog._grid_params = dict(xs=np.array([5., 6.]), ys=np.array([.35, .45]),
                               grid=np.array([[10., np.nan], [20., 30.]]),
                               key_x='L_cell', key_y='t', key_m='ratio', fixed={})
    dialog._plot()
    assert dialog._grid_axes.collections[0].get_cmap().name == FIELD_CMAP

    def click(axes, x, y):
        px, py = axes.transData.transform((x, y))
        event = MouseEvent('button_press_event', dialog._canvas, px, py, button=1)
        dialog._canvas.callbacks.process('button_press_event', event)

    click(dialog._canvas.fig.axes[1], .5, 20.)
    click(dialog._grid_axes, 6., .35)
    assert window.le_Lcell.text() == '8' and window.le_t.text() == '.6'
    click(dialog._grid_axes, 5., .45)
    assert float(window.le_Lcell.text()) == 5. and float(window.le_t.text()) == .45
    dialog.close()
    window.close()
