"""Real production runs, including cached initial and iterative Nu calls."""
from contextlib import nullcontext
from dataclasses import replace

import numpy as np
import pytest

import importlib
from sjtu_tpmshx.controllers.module_adapter import compute_result
from sjtu_tpmshx.models.tpms_calc import compute
from sjtu_tpmshx.tests.test_pipeline_2d_smoke import _shanghai_like_cfg
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
from sjtu_tpmshx.tests.gui_worker_support import win as win


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
    owner = importlib.import_module('sjtu_tpmshx.solvers.backends.cpp.' +
        ('full_2d_capture' if dimension == '2d' else 'full_3d'))
    original = owner.replay_range_observations
    observations = []

    def observe(rows):
        observations.extend(rows)
        return original(rows)

    monkeypatch.setattr(owner, 'replay_range_observations', observe)
    result = compute_result(cfg)
    assert result.converged, result.diagnostics['convergence_detail']
    assert result.diagnostics['convergence_detail']['outer_iters'] > 1
    local = [row for row in observations if row['view'] == 'nu' and
             row['model'] == 'air' and row['stage'] in ('main-hv', 'main')]
    assert local
    # Native aggregation keeps the worst fraction from one cell snapshot.
    assert all(row['size'] == np.prod(row['shape']) for row in local)
    assert any(row['low'] or row['high'] for row in local)
    assert any('[Nu extrap]' in message for message in result.warnings)
    assert result.extrap_reasons == []  # both cases remain inside the D-F grid
    win.write_result(result)
    assert win.cache.get_result().extrap_reasons == []
    assert win._result_summary()['warnings'] == result.warnings
    assert len(result.warnings) == len(set(result.warnings))

    repeated = compute_result(cfg)
    assert repeated.warnings == result.warnings
    assert repeated.extrap_reasons == result.extrap_reasons
    # Suppress only collection in the comparator; every numerical call remains.
    with monkeypatch.context() as patch:
        patch.setattr(importlib.import_module('sjtu_tpmshx.workflows.compute'), 'warning_scope', lambda records: nullcontext(records))
        patch.setattr(owner, 'replay_range_observations', lambda rows: [])
        without_capture = compute_result(cfg)
    for other in (repeated, without_capture):
        assert other.converged, other.diagnostics['convergence_detail']
        for name in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
            np.testing.assert_array_equal(getattr(result, name), getattr(other, name))
        for name, array in result.fields.items():
            if isinstance(array, np.ndarray):
                np.testing.assert_array_equal(array, other.fields[name])
