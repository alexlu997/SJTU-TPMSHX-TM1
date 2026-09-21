"""Public true-h runs retain physical evidence, frozen selection and cancellation.

Full-chain comparison is fixed at rtol=atol=1e-10 (the existing assert_slots
contract), separately from native operator and physical convergence tolerances.
"""
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.python.thermal_native import NativeEnthalpySweeps
from sjtu_tpmshx.tests.integration_tm1.test_public_api import assert_slots
from sjtu_tpmshx.tests.native.test_enthalpy_sweeps import native_library as native_library


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


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('air_sco2', [False, True], ids=['sco2-water', 'air-sco2'])
def test_native_case_handoff_and_physical_evidence(native_library, monkeypatch, tmp_path,
                                                   dimension, air_sco2):
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

    solver = SIMPLESolver if dimension == 2 else SIMPLESolver3D
    original, flows = solver.solve, []

    def solve(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        flows.append((self.final_res_mom, self.final_res_mass_local,
                      self.final_res_mass_global, self.outlet_backflow_frac))
        return result

    monkeypatch.setattr(solver, 'solve', solve)
    cfg = _config(dimension, air_sco2)
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'numba')
    reference_case = prepare_case(cfg, case_id='numba-reference')
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'cpp_sweeps_v1')
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', native_library._name)
    case = prepare_case(cfg, case_id='native-candidate')
    save_case(case, tmp_path / 'case.h5')
    # Both choices belong to the prepared case, even after file handoff.
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'invalid-receiver-override')
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', '/missing-receiver-library')
    reference = run_case(reference_case)
    result = run_case(load_case(tmp_path / 'case.h5'))
    assert result.backend_id == reference.backend_id == 'python'
    assert result.run_status['converged'] and reference.run_status['converged']
    for name in ('fields', 'boundary_fluxes', 'pressure_evidence', 'run_status'):
        assert_slots(getattr(result, name), getattr(reference, name))
    assert_slots(result.metadata['model_metadata'], reference.metadata['model_metadata'])
    assert flows
    for momentum, local_mass, global_mass, backflow in flows:
        assert momentum < 1e-4 and local_mass < 1e-6 and global_mass < 1e-6
        assert backflow <= .01
    for current in (reference, result):
        balance = current.metadata['diagnostics']['true_h_balance']
        assert balance['converged']
        assert max(balance['enthalpy_clip_counts']['total']) == 0
        assert balance['coupled_energy_balance']['ratio'] <= .001
        assert balance['equation_energy_balance']['ratio'] <= .001
    settings = result.metadata['diagnostics']['true_h_balance']['effective_settings']
    assert settings['sweep_kernel'] == 'cpp_sweeps_v1'
    assert settings['thermal_abi'] == 1 and settings['energy_audit'] == 'python'
    assert settings['thermal_library'] == str(Path(native_library._name).resolve())
    actual_metrics, expected_metrics = evaluate(result).metrics, evaluate(reference).metrics
    for name in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B',
                 'mass_flow_A', 'mass_flow_B', 'energy_imbalance_rel'):
        assert actual_metrics[name].status == expected_metrics[name].status == 'available'
        np.testing.assert_allclose(actual_metrics[name].value, expected_metrics[name].value,
                                   rtol=1e-10, atol=1e-10)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('failure', ['cancel_before', 'cancel', 'invalid_native'])
def test_native_chunk_failure_never_finalizes(native_library, monkeypatch, dimension, failure):
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'cpp_sweeps_v1')
    monkeypatch.setenv('TPMSHX_THERMAL_LIBRARY', native_library._name)
    token, called = CancelToken(), []
    original = NativeEnthalpySweeps.__call__

    def chunk(self, *args, **kwargs):
        called.append(True)
        if failure == 'invalid_native':
            args = list(args)
            args[26] = 2.0  # The actual C++ physical-parameter guard must throw.
        value = original(self, *args, **kwargs)
        token.cancel()
        return value

    monkeypatch.setattr(NativeEnthalpySweeps, '__call__', chunk)
    pipeline = (Pipeline2D if dimension == 2 else Pipeline3D)(
        _config(dimension), cancel_token=token)
    if failure == 'cancel_before':
        token.cancel()
    monkeypatch.setattr(pipeline, 'finalize',
                        lambda *args: pytest.fail('failed native result was finalized'))
    with pytest.raises(ValueError if failure == 'invalid_native' else CancelledError,
                       match='omega' if failure == 'invalid_native' else 'cancel'):
        pipeline.run()
    assert called == ([] if failure == 'cancel_before' else [True])


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('selection', ['missing_library', 'unknown_kernel', 'model_h'])
def test_unsupported_native_requests_fail_before_simple(monkeypatch, dimension, selection):
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

    def forbidden(*args, **kwargs):
        pytest.fail('unsupported native request reached SIMPLE')

    monkeypatch.setattr(SIMPLESolver, 'solve', forbidden)
    monkeypatch.setattr(SIMPLESolver3D, 'solve', forbidden)
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL',
                       'unknown' if selection == 'unknown_kernel' else 'cpp_sweeps_v1')
    monkeypatch.delenv('TPMSHX_THERMAL_LIBRARY', raising=False)
    cfg = _config(dimension, air_sco2=True)
    if selection == 'model_h':
        cfg.fluid_B = FluidConfig(type='air', u_mps=2., T_in_K=300., P_in_Pa=1e5)
    case = prepare_case(cfg, case_id='unsupported-native')
    message = {'missing_library': 'TPMSHX_THERMAL_LIBRARY',
               'unknown_kernel': 'unsupported TPMSHX_TRUE_H_KERNEL',
               'model_h': 'full two-fluid true-h'}[selection]
    with pytest.raises(ValueError, match=message):
        run_case(case)
