"""Real production runs, including cached initial and iterative Nu calls."""
from contextlib import nullcontext
from dataclasses import replace
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.controllers import compute_pipeline as pipelines
from sjtu_tpmshx.models import nu_correlations as nu
from sjtu_tpmshx.models.tpms_calc import compute
from sjtu_tpmshx.tests.test_pipeline_2d_smoke import _shanghai_like_cfg
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
from sjtu_tpmshx.tests.test_worker_result_handoff import win as win


@pytest.mark.slow
@pytest.mark.parametrize('dimension', ['2d', '3d'])
def test_real_pipeline_warning_ownership_and_numerical_transparency(monkeypatch, dimension, win):
    cfg = _shanghai_like_cfg() if dimension == '2d' else _small_air_cfg()
    if dimension == '3d':
        # Fixed positive control: inlet Re=230 < 400, with original tolerances.
        cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, u_mps=1.0))
    geometry = cfg.geometry
    for fluid in (cfg.fluid_A, cfg.fluid_B):
        compute(geometry.tpms, geometry.L_cell_mm, geometry.t_wall_mm,
                fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa, geometry.k_s_W_mK,
                fluid.type)
    # No cache_clear: standalone warm-up must not consume a run's notices.
    original = nu._warn_extrap
    rounds = []

    def observe(*args):
        frame = inspect.currentframe().f_back
        while frame is not None:
            if frame.f_code.co_name in ('_step_2d', '_outer_step_3d'):
                rounds.append(frame.f_code.co_name)
                break
            frame = frame.f_back
        return original(*args)

    monkeypatch.setattr(nu, '_warn_extrap', observe)
    pipe = pipelines.pipeline_for(cfg)
    result = pipe.run()
    assert result.converged, result.diagnostics['convergence_detail']
    assert result.diagnostics['convergence_detail']['outer_iters'] > 1
    assert len(rounds) > 2  # actual first and later energy-coupling Nu calls
    assert any('[Nu extrap]' in message for message in result.warnings)
    assert result.extrap_reasons == []  # both cases remain inside the D-F grid
    win.write_result(result)
    assert win._has_extrap is False
    assert win._extrap_reasons == []
    assert win._diag_summary['warnings'] == result.warnings
    assert len(result.warnings) == len(set(result.warnings))

    repeated = pipe.run()
    assert repeated.warnings == result.warnings
    assert repeated.extrap_reasons == result.extrap_reasons
    # Suppress only collection in the comparator; every numerical call remains.
    with monkeypatch.context() as patch:
        patch.setattr(pipelines, 'warning_scope', lambda records: nullcontext(records))
        without_capture = pipe.run()
    for other in (repeated, without_capture):
        assert other.converged, other.diagnostics['convergence_detail']
        for name in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
            np.testing.assert_array_equal(getattr(result, name), getattr(other, name))
        for name, array in result.fields.items():
            if isinstance(array, np.ndarray):
                np.testing.assert_array_equal(array, other.fields[name])
