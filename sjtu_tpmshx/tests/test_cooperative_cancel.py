"""Cancellation after real work starts; no timing-dependent sleeps."""
import threading

import pytest

from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken, ComputeOrchestrator
from sjtu_tpmshx.controllers.compute_pipeline import CancelledError, Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
)


def _cfg(nz=1, enthalpy=False):
    return ComputeConfig(
        fluid_A=FluidConfig(type='sco2' if enthalpy else 'air',
                            u_mps=0.8 if enthalpy else 5.0,
                            T_in_K=500.0 if enthalpy else 400.0,
                            P_in_Pa=12e6 if enthalpy else 101325.0),
        fluid_B=FluidConfig(type='water' if enthalpy else 'air',
                            u_mps=0.2 if enthalpy else 5.0, T_in_K=300.0,
                            P_in_Pa=2e6 if enthalpy else 101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                L_dom_m=0.06, H_dom_m=0.03, Lz_m=0.03),
        solver=SolverConfig(Nx=8, Ny=8, Nz=nz),
    )


def _no_finalize(monkeypatch, pipe):
    monkeypatch.setattr(pipe, 'finalize',
                        lambda *a: pytest.fail('cancelled result was finalized'))


@pytest.mark.parametrize('nz', [1, 3])
def test_real_simple_cancel_joins_both_sides(monkeypatch, nz):
    """Request only after momentum work; both real SIMPLE solves must exit."""
    token = CancelToken()
    if nz == 1:
        from sjtu_tpmshx.solvers import simple_solver as module
        cls = module.SIMPLESolver
        kernel = '_correct_jit'
    else:
        from sjtu_tpmshx.solvers import simple_solver_3d as module
        cls = module.SIMPLESolver3D
        kernel = '_correct_jit_3d'
    original_kernel = getattr(module, kernel)
    worked = []

    def request_after_work(*args, **kwargs):
        result = original_kernel(*args, **kwargs)
        worked.append(True)
        token.cancel()
        return result

    monkeypatch.setattr(module, kernel, request_after_work)
    threads, exited = [], []
    original_solve = cls.solve

    def solve(self, *args, **kwargs):
        threads.append(threading.current_thread())
        from sjtu_tpmshx.domain.run_warnings import current_warnings
        from sjtu_tpmshx.solvers.nu_correlations import nu_water_topo
        assert current_warnings() is not None
        nu_water_topo('Gyroid', 1, 3)
        try:
            return original_solve(self, *args, **kwargs)
        finally:
            exited.append(True)

    monkeypatch.setattr(cls, 'solve', solve)
    pipe = (Pipeline2D if nz == 1 else Pipeline3D)(_cfg(nz), cancel_token=token)
    _no_finalize(monkeypatch, pipe)
    with pytest.raises(CancelledError):
        pipe.run()
    assert worked and len(exited) == len(threads) == 2
    assert all(not thread.is_alive() for thread in threads)
    from sjtu_tpmshx.domain.run_warnings import current_warnings, warning_scope
    from sjtu_tpmshx.solvers.nu_correlations import nu_water_topo
    assert current_warnings() is None
    with warning_scope({}) as records:
        nu_water_topo('Gyroid', 1, 3)
    assert records


@pytest.mark.parametrize('nz', [1, 3])
@pytest.mark.parametrize('error_type', [ValueError, InterruptedError])
@pytest.mark.parametrize('error_side', [0, 1])
def test_real_error_wins_over_other_side_cancel(monkeypatch, nz, error_type, error_side):
    token = CancelToken()
    barrier = threading.Barrier(2, timeout=10)
    threads = []
    failure = error_type('real solver failure')

    def side(idx):
        threads.append(threading.current_thread())
        barrier.wait()
        token.cancel()
        if idx == error_side:
            raise failure
        raise CancelledError('explicit checkpoint')

    pipe = (Pipeline2D if nz == 1 else Pipeline3D)(_cfg(nz), cancel_token=token)
    _no_finalize(monkeypatch, pipe)
    if nz == 1:
        from sjtu_tpmshx.solvers.backends.python.two_d import execution
        original_build = execution.build_runtime

        def build(*args, **kwargs):
            fields = original_build(*args, **kwargs)
            fields['_run_simple'] = lambda *a, **k: side(0 if a[5] == 'Fluid A' else 1)
            return fields

        monkeypatch.setattr(execution, 'build_runtime', build)
    else:
        from sjtu_tpmshx.pipelines import run_stack_3d_stages as stages
        original_pair = stages._run_two_simple_parallel

        def pair(a, b, **kwargs):
            a.solve = lambda **k: side(0)
            b.solve = lambda **k: side(1)
            return original_pair(a, b, **kwargs)

        monkeypatch.setattr(stages, '_run_two_simple_parallel', pair)
    with pytest.raises(error_type) as caught:
        pipe.run()
    assert caught.value is failure
    assert len(threads) == 2 and all(not thread.is_alive() for thread in threads)


@pytest.mark.parametrize('nz,enthalpy', [(1, False), (3, False), (1, True), (3, True)])
def test_pipeline_energy_cancel_after_native_chunk(monkeypatch, nz, enthalpy):
    token = CancelToken()
    if enthalpy:
        from sjtu_tpmshx.solvers import ltne_enthalpy_3d as energy
        kernel = '_gs_enthalpy_sweeps_3d'
    elif nz == 1:
        from sjtu_tpmshx.solvers import ltne_energy as energy
        kernel = '_gs_full_chunk'
    else:
        from sjtu_tpmshx.solvers import ltne_energy_3d as energy
        kernel = '_gs_full_chunk_3d_stag'
    original = getattr(energy, kernel)
    worked = []

    def chunk(*args, **kwargs):
        result = original(*args, **kwargs)
        worked.append(True)
        token.cancel()
        return result

    monkeypatch.setattr(energy, kernel, chunk)
    pipe = (Pipeline2D if nz == 1 else Pipeline3D)(
        _cfg(nz, enthalpy), cancel_token=token)
    _no_finalize(monkeypatch, pipe)
    with pytest.raises(CancelledError):
        pipe.run()
    assert worked == [True]


def test_richardson_cancel_after_refined_chunk(monkeypatch):
    from sjtu_tpmshx.pipelines import solve_2d
    from sjtu_tpmshx.solvers import ltne_energy
    token = CancelToken()
    original = solve_2d._compute_Q_richardson
    original_chunk = ltne_energy._gs_full_chunk
    refined = []

    def chunk(*args, **kwargs):
        result = original_chunk(*args, **kwargs)
        refined.append(True)
        token.cancel()
        return result

    def richardson(*args, **kwargs):
        monkeypatch.setattr(ltne_energy, '_gs_full_chunk', chunk)
        return original(*args, **kwargs)

    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', richardson)
    pipe = Pipeline2D(_cfg(), cancel_token=token)
    _no_finalize(monkeypatch, pipe)
    with pytest.raises(CancelledError):
        pipe.run()
    assert refined == [True]


@pytest.mark.parametrize('error_type', [CancelledError, InterruptedError, ValueError])
@pytest.mark.parametrize('requested', [False, True])
def test_ui_adapter_only_classifies_explicit_cancellation(monkeypatch, error_type, requested):
    from sjtu_tpmshx.ui.mixins import run_controller
    token = CancelToken()
    failure = error_type('solver stopped')
    pipe = Pipeline3D(_cfg(3), cancel_token=token)

    def run():
        if requested:
            token.cancel()
        raise failure

    monkeypatch.setattr(pipe, 'run', run)
    expected = ComputeOrchestrator.CancelledError if error_type is CancelledError else error_type
    with pytest.raises(expected) as caught:
        run_controller._run_pipeline(_cfg(3), token, lambda *a: None,
                                     pipeline_cls=lambda *a, **k: pipe, ui_hooks={})
    if error_type is not CancelledError:
        assert caught.value is failure


@pytest.mark.parametrize('nz', [1, 2])
def test_ltne_cell_centered_and_nz1_delegate_cancel(nz):
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    from sjtu_tpmshx.tests.test_ltne_energy_3d import _toy_case
    token = CancelToken()
    chunks = []

    def progress(done, total):
        chunks.append(done)
        token.cancel()

    with pytest.raises(CancelledError):
        solve_full_domain_3d(**_toy_case(Nx=4, Ny=4, Nz=nz),
                             progress_cb=progress, cancel_check=token.is_set)
    assert len(chunks) == 1 and chunks[0] > 0


def test_cancel_during_finalize_does_not_return_result(monkeypatch):
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    token = CancelToken()
    progress = []
    pipe = Pipeline2D(_cfg(), cancel_token=token, progress_cb=progress.append)
    monkeypatch.setattr(pipe, 'build_fields', lambda: {})
    monkeypatch.setattr(pipe, 'run_solvers', lambda fields: {})

    def finalize(*args):
        token.cancel()
        return ComputeResult(Q_W=1.0)

    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises(CancelledError):
        pipe.run()
    assert 100 not in progress
