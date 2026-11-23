"""Fixed demo inputs, display-field selection and honest completion status."""
import importlib
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.data_types.field_result import FieldResult
from sjtu_tpmshx.development.runs.demos import demo_3d_air_air as air


@pytest.fixture
def result():
    values = np.arange(8.).reshape(2, 2, 2)
    fields = {name + '_display': values + offset for name, offset in
              (('Ta', 300.), ('Tb', 290.), ('Ts', 295.))}
    fields.update({name: values + 900. for name in ('Ta', 'Tb', 'Ts')})
    fields.update(vmag_A=values + 1., vmag_B=values + 2.,
                  P_fA_display=100000. + 200. * values,
                  P_fB_display=90000. + 100. * values)
    return FieldResult('demo-result', 'demo-case', 'cpp', fields=fields,
        grid=dict(dx=np.array([.01, .02]), dy=np.array([.015, .025]),
                  dz=np.array([.01, .02])),
        run_status=dict(execution='completed', converged=True),
        metadata=dict(parameters=dict(prepared=dict(geometry=dict(epsilon=.8, D_h=.001))),
                      diagnostics=dict(Q_enthalpy_B=8., T_A_out=350., T_B_out=320.)))


@pytest.mark.parametrize('cube', [False, True])
def test_demo_preparation_keeps_original_workload(cube):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.development.runs.demos.demo_3d_cube_air_air import build_cube_cfg
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs

    config = build_cube_cfg() if cube else air.build_cfg()
    case = prepare_case(config, case_id='demo-inputs')
    actual_cfg, actual = build_execution_inputs(case)
    geometry, solver = config.geometry, config.solver
    # The grid covers the physical domain with the requested cell counts.
    for axis, count, length in zip('xyz', (solver.Nx, solver.Ny, solver.Nz),
                                   (geometry.L_dom_m, geometry.H_dom_m, geometry.Lz_m)):
        widths = np.asarray(actual['d' + axis])
        assert actual['N' + axis] == widths.size == count
        assert np.all(widths > 0.) and np.isclose(widths.sum(), length, rtol=1e-12)
    # Uniform demo geometry keeps the nominal L/t and a physical porosity.
    shape = (solver.Nx, solver.Ny, solver.Nz)
    np.testing.assert_allclose(actual['design']['L_field_m'], np.full(shape, geometry.L_cell_mm * 1e-3))
    np.testing.assert_allclose(actual['design']['t_field_m'], np.full(shape, geometry.t_wall_mm * 1e-3))
    assert np.all((actual['design']['eps_arr'] > 0.) & (actual['design']['eps_arr'] < 1.))
    for side in 'AB':
        for value in actual['openings'][side].values():
            assert np.all((np.asarray(value) >= 0.) & (np.asarray(value) <= 1.))
        assert all(np.isfinite(value) and value > 0. for value in actual['properties'][side].values())
    for key, value in (('u_A', config.fluid_A.u_mps), ('u_B', config.fluid_B.u_mps),
                       ('T_inA', config.fluid_A.T_in_K), ('T_inB', config.fluid_B.T_in_K),
                       ('P_inA', config.fluid_A.P_in_Pa), ('P_inB', config.fluid_B.P_in_Pa)):
        assert actual_cfg[key] == value


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
    from sjtu_tpmshx.development.runs.demos.demo_3d_cube_volume import make_grid

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
    module = importlib.import_module('sjtu_tpmshx.development.runs.' + module_name)
    prepared = object()
    events = []
    def prepare(config, *, case_id):
        assert config.bc_B.dir == 3 and config.geometry.Lz_m > 0
        events.append('prepare')
        return prepared
    def run(case, control):
        assert case is prepared and control.backend == 'cpp'
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
