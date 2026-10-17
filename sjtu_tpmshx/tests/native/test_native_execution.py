"""Native runs retain physical evidence, saved-case handoff, and cancellation."""
import numpy as np
import pytest

from sjtu_tpmshx.controllers.module_adapter import compute_result
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.integration_tm1.test_public_api import assert_slots


def _config(dimension, air_sco2=False):
    def port(direction, centre=.015, width=.015):
        return PartialBCConfig(dir=direction, in_ctr=centre, in_w=width,
            out_ctr=centre, out_w=width, **(dict(in_z_ctr=.015, in_z_w=.015,
                out_z_ctr=.015, out_z_w=.015) if dimension == 3 else {}))

    return ComputeConfig(
        fluid_A=FluidConfig(type='air' if air_sco2 else 'sco2',
            u_mps=3. if air_sco2 else .3, T_in_K=500., P_in_Pa=2e5 if air_sco2 else 12e6),
        fluid_B=FluidConfig(type='sco2' if air_sco2 else 'water', u_mps=.2,
            T_in_K=300., P_in_Pa=12e6 if air_sco2 else 2e6),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6,
            k_s_W_mK=16., L_dom_m=.03 if dimension == 3 else .06, H_dom_m=.03,
            Lz_m=.03 if dimension == 3 else None),
        solver=SolverConfig(Nx=4 if dimension == 3 else 8, Ny=4 if dimension == 3 else 6,
            Nz=4 if dimension == 3 else 1, max_outer_ltne=30, max_iter_simple=5000),
        bc_A=port(4 if dimension == 3 else 0),
        bc_B=port(1) if dimension == 3 else port(3, .03, .03),
        extrap=ExtrapPolicy(allow=True))


@pytest.fixture(scope='module')
def native_path():
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import native_path as fixture
    return fixture.__wrapped__()


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('air_sco2', [False, True], ids=['sco2-water', 'air-sco2'])
def test_native_case_handoff_and_physical_evidence(monkeypatch, tmp_path, native_path, dimension, air_sco2):
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import control
    from sjtu_tpmshx.tests.native.full_result_audit import physical_gates
    cfg = _config(dimension, air_sco2)
    case = prepare_case(cfg, case_id='native-replay')
    assert 'TPMSHX_THERMAL_LIBRARY' not in case.parameters['_environment']
    save_case(case, tmp_path/'case.h5')
    reference = run_case(case, control(native_path))
    # A saved environment owns the execution; receiving-host overrides do not.
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'invalid-receiver-override')
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', '/missing-receiver-library')
    result = run_case(load_case(tmp_path/'case.h5'), control(native_path))
    assert result.backend_id == reference.backend_id == 'cpp'
    for name in ('fields', 'boundary_fluxes', 'pressure_evidence', 'run_status'):
        assert_slots(getattr(result, name), getattr(reference, name))
    assert_slots(result.metadata['model_metadata'], reference.metadata['model_metadata'])
    for current in (reference, result):
        physical_gates(current)
    settings = result.metadata['diagnostics']['true_h_balance']['effective_settings']
    assert 'numba' not in str(settings) and 'python' not in str(settings)
    actual_metrics, expected_metrics = evaluate(result).metrics, evaluate(reference).metrics
    for name in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B',
                 'mass_flow_A', 'mass_flow_B', 'energy_imbalance_rel'):
        assert actual_metrics[name].status == expected_metrics[name].status == 'available'
        np.testing.assert_allclose(actual_metrics[name].value, expected_metrics[name].value, rtol=1e-10, atol=1e-10)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('before', [False, True])
def test_native_cancellation_never_finalizes(monkeypatch, native_path, dimension, before):
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import control
    calls = []
    def cancelled():
        calls.append(True)
        return len(calls) >= (1 if before else 100)
    monkeypatch.setattr('sjtu_tpmshx.postprocess.api.evaluate',
                        lambda *args: pytest.fail('cancelled result was finalized'))
    with pytest.raises(CancelledError, match='cancel'):
        compute_result(_config(dimension), control=control(native_path, cancel_check=cancelled))
    assert len(calls) == 1 if before else len(calls) >= 100


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('selection', ['cpp_sweeps_v1', 'unknown_kernel', 'numba'])
def test_retired_kernel_requests_fail_before_library_load(monkeypatch, tmp_path, dimension, selection):
    from sjtu_tpmshx.solvers.backends.cpp import full_2d, full_3d
    def forbidden(*args, **kwargs):
        pytest.fail('retired kernel request reached native loading')
    monkeypatch.setattr(full_2d.ct, 'CDLL', forbidden)
    monkeypatch.setattr(full_3d.ct, 'CDLL', forbidden)
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', selection)
    case = prepare_case(_config(dimension, air_sco2=True), case_id='retired-kernel')
    path = save_case(case, tmp_path/'retired-case.h5')
    monkeypatch.delenv('TPMSHX_TRUE_H_KERNEL')
    with pytest.raises(ValueError, match='TPMSHX_TRUE_H_KERNEL has been retired'):
        run_case(load_case(path))
