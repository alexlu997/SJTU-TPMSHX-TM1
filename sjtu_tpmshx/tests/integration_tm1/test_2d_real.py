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
    progress = []
    result = run_case(replace(case, config_snapshot={}), RunControl(progress=progress.append))
    reference = result.metadata['reporting_reference']
    np.testing.assert_allclose(
        [reference[key] for key in ('Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')],
        [31084.383039293898, 1665.684133288371, 1212.2971501411819,
         304.2430037398466, 334.69721144655796], rtol=1e-10, atol=1e-10)
    assert result.run_status['converged'] is True
    assert result.fields['Ta'].shape == (36, 56)
    assert result.boundary_fluxes['mass_A'][0].shape == (37, 56)
    assert result.boundary_fluxes['model_h']['A']['h_faces_W_per_m']
    assert result.pressure_evidence['A']['inlet_gauge_Pa'].shape == (56,)
    assert progress
    _assert_postprocessing(result)


def _assert_postprocessing(result):
    reference = result.metadata['reporting_reference']
    metadata = dict(result.metadata)
    metadata.pop('reporting_reference')
    metrics = evaluate(replace(result, metadata=metadata)).metrics
    for name, raw_name in (('Q', 'Q_total'), ('dP_A', 'dP_A'), ('dP_B', 'dP_B'),
                          ('T_out_A', 'T_out_A_K'), ('T_out_B', 'T_out_B_K')):
        assert metrics[name].status == 'available', metrics[name].reason
        np.testing.assert_allclose(metrics[name].value, reference[raw_name], rtol=1e-10, atol=1e-10)
    assert metrics['Q'].spec.unit == 'W/m'


@pytest.mark.slow
@pytest.mark.parametrize('fluid_A,u_A,P_A,fluid_B,P_B,expected_Q', [
    ('sco2', .3, 12e6, 'water', 2e6, 45645.686638674175),
    ('air', 3., 2e5, 'sco2', 12e6, 4419.163268961036),
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
    _assert_postprocessing(result)
