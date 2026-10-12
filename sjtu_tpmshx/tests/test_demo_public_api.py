"""Fixed demo inputs, display-field selection and honest completion status."""
import importlib
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.runs.demos import demo_3d_air_air as air


@pytest.fixture
def result():
    values = np.arange(8.).reshape(2, 2, 2)
    fields = {name + '_display': values + offset for name, offset in
              (('Ta', 300.), ('Tb', 290.), ('Ts', 295.))}
    fields.update({name: values + 900. for name in ('Ta', 'Tb', 'Ts')})
    fields.update(vmag_A=values + 1., vmag_B=values + 2.,
                  P_fA_display=100000. + 200. * values,
                  P_fB_display=90000. + 100. * values)
    return FieldResult('demo-result', 'demo-case', 'python', fields=fields,
        grid=dict(dx=np.array([.01, .02]), dy=np.array([.015, .025]),
                  dz=np.array([.01, .02])),
        run_status=dict(execution='completed', converged=True),
        metadata=dict(parameters=dict(prepared=dict(geometry=dict(epsilon=.8, D_h=.001))),
                      diagnostics=dict(Q_enthalpy_B=8., T_A_out=350., T_B_out=320.)))


@pytest.mark.parametrize('cube', [False, True])
def test_demo_preparation_keeps_original_workload(cube):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.preprocess.three_d.preparation import _prepare_problem_data
    from sjtu_tpmshx.tests.cases_3d import demo_fixture_cfg as legacy_cfg
    from sjtu_tpmshx.runs.demos.demo_3d_cube_air_air import build_cube_cfg
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs

    config = build_cube_cfg() if cube else air.build_cfg()
    case = prepare_case(config, case_id='demo-inputs')
    actual_cfg, actual = build_execution_inputs(case)
    expected = _prepare_problem_data(legacy_cfg(**(
        dict(L=.05, H=.05, Lz=.05, Nx=20, Ny=20, Nz=20) if cube else {})))
    for key in ('dx', 'dy', 'dz', 'Nx', 'Ny', 'Nz'):
        np.testing.assert_array_equal(actual[key], expected[key])
    for key, value in expected['design'].items():
        np.testing.assert_allclose(actual['design'][key], value, rtol=1e-12)
    for side in 'AB':
        for key, value in expected['openings'][side].items():
            np.testing.assert_array_equal(actual['openings'][side][key], value)
        assert actual['axes'][side]['stream_real_axis'] == expected['axes'][side]['stream_real_axis']
        assert actual['axes'][side]['is_reverse'] == expected['axes'][side]['is_reverse']
        assert actual['properties'][side] == expected['properties'][side]
    for key in ('max_outer', 'ltne_max_iter', 'compact'):
        assert actual[key] == expected[key]
    for key in ('u_A', 'u_B', 'T_inA', 'T_inB', 'P_inA', 'P_inB', 'T_s_init'):
        assert actual_cfg[key] == expected['cfg'][key]


@pytest.mark.parametrize('converged,available', [(True, True), (False, True), (True, False)])
def test_report_keeps_signed_public_duty_and_metric_failure(result, capsys, converged, available):
    names = ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B',
             'mass_flow_A', 'mass_flow_B', 'mass_imbalance_rel_A',
             'mass_imbalance_rel_B', 'energy_imbalance_rel')
    metrics = {name: SimpleNamespace(value=-9. if name == 'Q_B' else 10.,
        status='available', reason='', spec=SimpleNamespace(unit='W')) for name in names}
    if not available:
        metrics['Q_B'] = SimpleNamespace(value=None, status='unsupported', reason='missing boundary ledger')
    result = replace(result, run_status=dict(execution='completed', converged=converged))
    assert air.print_metrics(result, SimpleNamespace(metrics=metrics), air.build_cfg()) is (converged and available)
    text = capsys.readouterr().out
    public, diagnostics = text.split('BACKEND DIAGNOSTICS', 1)
    assert 'signed native boundary heat losses' in public
    assert 'Q_enthalpy_B' in diagnostics and ': 8 W' in diagnostics
    if available:
        assert '-9 W' in public
    else:
        assert 'unsupported — missing boundary ledger' in public


def test_plots_keep_display_state_and_pressure_units(result, monkeypatch, tmp_path):
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from sjtu_tpmshx.runs.demos.demo_3d_cube_volume import make_grid

    calls = []
    contourf = Axes.contourf
    def observe(ax, x, y, values, *args, **kwargs):
        calls.append(np.array(values))
        return contourf(ax, x, y, values, *args, **kwargs)
    monkeypatch.setattr(Axes, 'contourf', observe)
    monkeypatch.setattr(Figure, 'savefig', lambda *a, **kw: None)
    air.plot_clouds(result, tmp_path)
    np.testing.assert_array_equal(calls[0], result.fields['Ta_display'][:, :, 1])
    np.testing.assert_array_equal(calls[5], result.fields['P_fA_display'][:, :, 1] / 1000.)
    calls.clear()
    air.plot_orthogonal_3d_slices(result, tmp_path)
    np.testing.assert_array_equal(calls[0], result.fields['Ta_display'][:, :, 1])
    np.testing.assert_array_equal(calls[12], result.fields['P_fA_display'][:, :, 1] / 1000.)
    grid = make_grid(result)
    np.testing.assert_allclose(grid.bounds, (0., 30., 0., 40., 0., 30.))
    np.testing.assert_allclose(grid['Ta'][[0, 2, -1]], (300., 304., 307.))
    np.testing.assert_allclose(grid['P_kPa'][[0, 2, -1]], (100., 100.8, 101.4))


@pytest.mark.parametrize('module_name', [
    'demos.demo_3d_air_air', 'demos.demo_3d_cube_air_air',
    'demos.demo_3d_cube_volume', 'tools.render_3d_styles',
])
def test_entries_use_public_api_and_preserve_failed_acceptance(module_name, result, monkeypatch):
    module = importlib.import_module('sjtu_tpmshx.runs.' + module_name)
    prepared = object()
    events = []
    def prepare(config, *, case_id):
        assert config.bc_B.dir == 3 and config.geometry.Lz_m > 0
        events.append('prepare')
        return prepared
    def run(case, control):
        assert case is prepared and control.backend == 'python'
        events.append('run')
        return result
    def evaluate(field):
        assert field is result
        events.append('evaluate')
        return object()
    monkeypatch.setattr(module, 'prepare_case', prepare)
    monkeypatch.setattr(module, 'run_case', run)
    monkeypatch.setattr(module, 'evaluate', evaluate)
    monkeypatch.setattr(module, 'print_metrics', lambda *args: False)
    monkeypatch.setattr(module.os, 'makedirs', lambda *a, **kw: None)
    for name in ('plot_clouds', 'plot_orthogonal_3d_slices'):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda *a, **kw: ('a', 'b', 'c'))
    if hasattr(module, 'make_grid'):
        monkeypatch.setattr(module, 'make_grid', lambda field: object())
    for name in ('render_volume', 'render_triple_slice', 'render_iso', 'render_publication_4panel',
                 'render_presentation_large', 'render_volume_tuned', 'render_iso_3level',
                 'render_rotation_mp4', 'render_html'):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda *a, **kw: True)
    assert module.main() == 2
    assert events == ['prepare', 'run', 'evaluate']
