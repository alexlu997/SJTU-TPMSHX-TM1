"""Prepared input consumption is independent from input preparation."""
from dataclasses import replace

import numpy as np
import pytest

from tm1.data_types.compute_config import ComputeConfig
from tm1.data_types.model_refs import ModelRef
from tm1.run_control.module_ports import RunControl
from tm1.run_control.cancellation import CancelledError
from tm1.preprocess.two_d.preparation import prepare_case
from tm1.solvers.api import run_case
from tests.python.native.stage_interception import stage_control


def test_effective_grid_and_design_are_consumed_without_preparation(monkeypatch):
    from tm1.preprocess.two_d import preparation as preparation
    case = prepare_case(ComputeConfig(), case_id='prepared')
    def forbidden(*args, **kwargs):
        raise AssertionError('solver called preprocessing')
    monkeypatch.setattr(preparation, 'prepare_case', forbidden)
    monkeypatch.setattr(preparation, '_execute', forbidden)
    states = []
    run_case(replace(case, config_snapshot={}), stage_control(), checkpoint=states.append)
    np.testing.assert_array_equal(states[-1]['input.grid.dx'], case.grid['dx'])
    assert len(states[-1]['input.grid.dx']) == len(case.grid['dx'])
    states[-1]['input.grid.dx'][0] = 0.0
    assert case.grid['dx'][0] > 0.0
    refs = list(case.model_refs)
    refs[0] = ModelRef(refs[0].name, 'unknown', refs[0].parameters)
    progress = []
    with pytest.raises(ValueError, match='unknown model'):
        run_case(replace(case, model_refs=refs), stage_control(progress=progress.append))
    design = dict(case.design_fields)
    design['eps_arr'] = np.zeros_like(design['eps_arr'])
    with pytest.raises(ValueError, match='uniform design'):
        run_case(replace(case, design_fields=design), stage_control(progress=progress.append))
    assert not progress
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
