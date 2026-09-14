"""B20 real prepared-only solve; baseline numbers are behavior, not Q accuracy."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, PartialBCConfig,
)
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.two_d.preparation import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d.execution import run_case
from sjtu_tpmshx.postprocess.metrics import evaluate

# 2026-09-13: inlet density now comes from the configured fluid model for
# every side. Previous values remain at 1a820521; tolerances are unchanged.
AIR_BASELINE_METRICS = [31086.937427058772, 1665.933909859572, 1212.4863954370883,
                        304.2432522135503, 334.6971842257337]
# Native main-grid A duty; the unchanged backend reference above retains
# the historical Richardson/max-side report for numerical regression.
AIR_NATIVE_Q = 31032.260073309655


def baseline_config():
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=600., P_in_Pa=101325.),
        fluid_B=FluidConfig(type='air', u_mps=10., T_in_K=300., P_in_Pa=101325.),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.4,
                                k_s_W_mK=16., L_dom_m=.182, H_dom_m=.042),
        solver=SolverConfig(Nx=20, Ny=40, Nz=1),
        bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3))


@pytest.mark.slow
def test_prepared_only_b20_air_baseline(monkeypatch):
    import sjtu_tpmshx.preprocess.two_d.preparation as preparation
    case = prepare_case(baseline_config(), case_id='B20-air')
    def forbidden(*args, **kwargs):
        raise AssertionError('execution called preprocessing')
    monkeypatch.setattr(preparation, '_parse_inputs_cfg', forbidden)
    monkeypatch.setattr(preparation, '_prepare_grid', forbidden)
    progress, iterations, residuals = [], [], []
    result = run_case(replace(case, config_snapshot={}), RunControl(
        progress=progress.append, iteration=iterations.append,
        residual=lambda side, index, value: residuals.append((side, index, value))))
    reference = result.metadata['reporting_reference']
    np.testing.assert_allclose(
        [reference[key] for key in ('Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')],
        AIR_BASELINE_METRICS, rtol=1e-10, atol=1e-10)
    assert result.run_status['converged'] is True
    assert result.fields['Ta'].shape == (36, 56)
    assert result.boundary_fluxes['mass_A'][0].shape == (37, 56)
    assert result.boundary_fluxes['model_h']['A']['h_faces_W_per_m']
    assert result.pressure_evidence['A']['inlet_gauge_Pa'].shape == (56,)
    assert progress
    assert iterations and all(isinstance(label, str) for label in iterations)
    assert {side for side, _, _ in residuals} == {'A', 'B'}
    assert all(isinstance(index, int) and np.isfinite(value) for _, index, value in residuals)
    _assert_postprocessing(result)


def _assert_postprocessing(result):
    reference = result.metadata['reporting_reference']
    metadata = dict(result.metadata)
    metadata.pop('reporting_reference')
    metrics = evaluate(replace(result, metadata=metadata)).metrics
    for name, raw_name in (('dP_A', 'dP_A'), ('dP_B', 'dP_B'),
                          ('T_out_A', 'T_out_A_K'), ('T_out_B', 'T_out_B_K')):
        assert metrics[name].status == 'available', metrics[name].reason
        np.testing.assert_allclose(metrics[name].value, reference[raw_name], rtol=1e-10, atol=1e-10)
    assert metrics['Q'].spec.unit == 'W/m'
    assert metrics['Q'].value == abs(metrics['Q_A'].value)
    assert metrics['Q'].spec.definition_version == 'native_boundary_v1'
    if result.metadata['thermal_mode'] == 'true_h':
        assert metrics['Q'].value == pytest.approx(reference['Q_total'], rel=1e-10)
    else:
        assert metrics['Q'].value == pytest.approx(AIR_NATIVE_Q, rel=1e-10)
        assert max(metrics[f'Q_richardson_{side}'].value for side in ('A', 'B')) == pytest.approx(reference['Q_total'], rel=1e-10)


@pytest.mark.slow
@pytest.mark.parametrize('fluid_A,u_A,P_A,fluid_B,P_B,expected_Q', [
    # Approved iteration-only BICUBIC reference; HEOS final state, same budgets.
    ('sco2', .3, 12e6, 'water', 2e6, 45645.89445485597),
    ('air', 3., 2e5, 'sco2', 12e6, 4419.516474200189),
])
def test_mixed_partial_native_and_postprocessing(fluid_A,u_A,P_A,fluid_B,P_B,expected_Q):
    from sjtu_tpmshx.domain.compute_config import ExtrapPolicy
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type=fluid_A, u_mps=u_A, T_in_K=500., P_in_Pa=P_A),
        fluid_B=FluidConfig(type=fluid_B, u_mps=.2, T_in_K=300., P_in_Pa=P_B),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6,
                                k_s_W_mK=16., L_dom_m=.06, H_dom_m=.03),
        solver=SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=3, max_iter_simple=500),
        bc_A=PartialBCConfig(dir=0, in_ctr=.015, in_w=.015, out_ctr=.015, out_w=.015),
        bc_B=PartialBCConfig(dir=3, in_ctr=.03, in_w=.03, out_ctr=.03, out_w=.03),
        extrap=ExtrapPolicy(allow=True))
    result = run_case(prepare_case(cfg, case_id='B20-mixed'))
    np.testing.assert_allclose(result.metadata['reporting_reference']['Q_total'], expected_Q,
                               rtol=1e-10, atol=1e-10)
    assert result.run_status['converged'] is False
    assert result.run_status['final_flow_after_last_thermal'] is True
    assert not np.array_equal(result.fields['Ta'], result.fields['Ta_display'])
    eos = result.metadata['model_metadata']['sco2_enthalpy_eos']
    assert list(eos['sides']) == (['A'] if fluid_A == 'sco2' else ['B'])
    assert eos['final_backend'] == 'HEOS'
    _assert_postprocessing(result)


@pytest.mark.slow
@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_zone_statistics_survive_result_handoff(tmp_path, axis):
    from sjtu_tpmshx.controllers.module_adapter import to_compute_result
    from sjtu_tpmshx.domain.compute_config import ZoneInputConfig
    from sjtu_tpmshx.io.result_io import load_result, save_result
    from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
    from sjtu_tpmshx.tests.integration_tm1.test_public_api import assert_slots

    cfg = baseline_config()
    cfg.solver = SolverConfig(Nx=8, Ny=6, Nz=1, max_outer_ltne=3, max_iter_simple=500)
    cfg.zones = ZoneInputConfig(enabled=True, axis=axis,
        config=ZoneConfig([Zone('first', 0., .5, 7., .4),
                           Zone('second', .5, 1., 6., .5)], 'Gyroid', 16.),
        grid=dict(tpms_type='Gyroid', k_s=16.,
                  cells=[dict(x0=0., x1=.5, y0=0., y1=1., L=7., t=.4),
                         dict(x0=.5, x1=1., y0=0., y1=1., L=6., t=.5)]))
    case = prepare_case(cfg, case_id=f'zone-handoff-{axis}')
    result = run_case(case)
    zones = result.metadata['application']['zones']
    assert zones['axis_dir'] == axis
    assert len(zones['stats']) == 2
    area = np.asarray(case.grid['dx'])[:, None] * np.asarray(case.grid['dy'])[None, :]
    for index, stats in enumerate(zones['stats']):
        mask = case.design_fields['zone_id'] == index
        assert stats['n_cells'] == np.count_nonzero(mask)
        for field in ('Ta', 'Tb', 'Ts'):
            assert stats[field + '_mean'] == pytest.approx(
                np.average(result.fields[field][mask], weights=area[mask]), rel=1e-12)
    path = tmp_path / 'results.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert_slots(loaded.metadata['application'], result.metadata['application'])
    display = to_compute_result(loaded, evaluate(loaded))
    assert_slots(display.zones, zones)
    assert display.converged == result.run_status['converged']
