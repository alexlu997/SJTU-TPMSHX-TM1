"""Prepared input consumption is independent from input preparation."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.preprocess.two_d.preparation import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs, run_case


def test_effective_grid_and_design_are_consumed_without_preparation(monkeypatch):
    import sjtu_tpmshx.preprocess.two_d.preparation as preparation
    case = prepare_case(ComputeConfig(), case_id='prepared')
    def forbidden(*args, **kwargs):
        raise AssertionError('solver called preprocessing')
    monkeypatch.setattr(preparation, '_parse_inputs_cfg', forbidden)
    monkeypatch.setattr(preparation, '_prepare_grid', forbidden)
    cfg, grid = build_execution_inputs(replace(case, config_snapshot={}))
    np.testing.assert_array_equal(grid['energy_dx'], case.grid['dx'])
    assert cfg['N_x'] == len(case.grid['dx'])
    grid['energy_dx'][0] = 0.0
    assert case.grid['dx'][0] > 0.0
    refs = list(case.model_refs)
    refs[0] = ModelRef('fluid', 'unknown', {'fluid': 'air'})
    with pytest.raises(ValueError, match='unknown model'):
        build_execution_inputs(replace(case, model_refs=refs))
    design = dict(case.design_fields)
    design['eps_arr'] = np.zeros_like(design['eps_arr'])
    with pytest.raises(ValueError, match='uniform design'):
        build_execution_inputs(replace(case, design_fields=design))
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
