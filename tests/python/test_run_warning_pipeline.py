"""Real production runs, including cached initial and iterative Nu calls."""
from contextlib import nullcontext
from dataclasses import replace

import numpy as np
import pytest

import importlib
from sjtu_tpmshx.applications.result_adapter import compute_result
from sjtu_tpmshx.physical_models.tpms_calc import compute
from tests.python.test_pipeline_2d_smoke import _shanghai_like_cfg
from tests.python.cases_3d import small_air_config
from tests.python.gui_worker_support import win as win


@pytest.mark.slow
@pytest.mark.parametrize('dimension', ['2d', '3d'])
def test_real_pipeline_warning_ownership_and_numerical_transparency(monkeypatch, dimension, win):
    from sjtu_tpmshx.cpp_interface.solver_library import stage_capture as owner
    if dimension == '2d':
        main_stage = 'main-hv'
        cfg = _shanghai_like_cfg()
    else:
        main_stage = 'main'
        cfg = small_air_config()
        # Fixed positive control: inlet Re=230 < 400, with original tolerances.
        cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, u_mps=1.0))
    geometry = cfg.geometry
    for fluid in (cfg.fluid_A, cfg.fluid_B):
        compute(geometry.tpms, geometry.L_cell_mm, geometry.t_wall_mm,
                fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa, geometry.k_s_W_mK,
                fluid.type)
    # No cache_clear: standalone warm-up must not consume a run's notices.
    original = owner.stage_closures
    observations = []

    def observe(records):
        rows, notices, last = original(records)
        observations.extend(rows)
        return rows, notices, last

    def main_nu_warnings(run):
        return [message for message in run.warnings
                if '[Nu extrap]' in message and f'stage={main_stage},' in message]

    monkeypatch.setattr(owner, 'stage_closures', observe)
    result = compute_result(cfg)
    assert result.converged, result.diagnostics['convergence_detail']
    assert result.diagnostics['convergence_detail']['outer_iters'] > 1
    local = [row for row in observations if row['view'] == 'nu' and
             row['model'] == 'air' and row['stage'] == main_stage]
    assert local
    # Native aggregation keeps the worst fraction from one cell snapshot.
    assert all(row['size'] == np.prod(row['shape']) for row in local)
    assert any(row['low'] or row['high'] for row in local)
    assert main_nu_warnings(result)
    assert result.extrap_reasons == []  # both cases remain inside the D-F grid
    win.results.publish(result)
    assert win.cache.get_result().extrap_reasons == []
    assert win.results.summary()['warnings'] == result.warnings
    assert len(result.warnings) == len(set(result.warnings))

    repeated = compute_result(cfg)
    assert repeated.warnings == result.warnings
    assert repeated.extrap_reasons == result.extrap_reasons
    observation_count = len(observations)
    # The comparison still runs all numerical calls with collection disabled.
    with monkeypatch.context() as patch:
        patch.setattr(importlib.import_module('sjtu_tpmshx.compute'), 'warning_scope', lambda records: nullcontext(records))
        patch.setattr(owner, 'stage_closures', lambda records: ([], {}, []))
        without_capture = compute_result(cfg)
    assert len(observations) == observation_count
    assert not main_nu_warnings(without_capture)
    for other in (repeated, without_capture):
        assert other.converged, other.diagnostics['convergence_detail']
        for name in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
            np.testing.assert_array_equal(getattr(result, name), getattr(other, name))
        for name, array in result.fields.items():
            if isinstance(array, np.ndarray):
                np.testing.assert_array_equal(array, other.fields[name])
