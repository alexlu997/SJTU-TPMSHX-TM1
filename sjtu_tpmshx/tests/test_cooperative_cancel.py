"""Cancellation after real work starts; no timing-dependent sleeps."""

import pytest

from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
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














@pytest.mark.parametrize('error_type', [CancelledError, InterruptedError, ValueError])
@pytest.mark.parametrize('requested', [False, True])
def test_ui_adapter_only_classifies_explicit_cancellation(monkeypatch, error_type, requested):
    from sjtu_tpmshx.ui.mixins import run_controller
    token = CancelToken()
    failure = error_type('solver stopped')

    def run(config, *, control, progress_cb):
        if requested:
            token.cancel()
        raise failure

    monkeypatch.setattr('sjtu_tpmshx.controllers.module_adapter.compute_result', run)
    with pytest.raises(error_type) as caught:
        run_controller._run_compute(_cfg(3), token, lambda *a: None, ui_hooks={})
    assert caught.value is failure




def test_cancel_during_finalize_does_not_return_result(monkeypatch):
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    token = CancelToken()
    progress = []
    from sjtu_tpmshx.workflows.compute import compute

    def finalize(*args):
        token.cancel()
        return ComputeResult(Q_W=1.0)

    with pytest.raises(CancelledError):
        compute(_cfg(), control=RunControl(cancel_check=token.is_set), progress_cb=progress.append,
                prepare=lambda *a, **k: {}, solve=lambda *a: {}, evaluate=finalize)
    assert 100 not in progress
