"""Actual quick-mode controls and unsupported-input rejection."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.tests.design.test_forward import _case


def test_quick_mode_controls_and_native_unconverged_status(monkeypatch):
    case = prepare_quick_design(_case(), 'Diamond', 7., .5, .084, .05, case_id='controls')
    from sjtu_tpmshx.models import quick_design
    def forbidden(*args, **kwargs):
        raise AssertionError('execution attempted to rebuild fixed inlet pressure')
    monkeypatch.setattr(quick_design, '_dp_fractions', forbidden)
    invalid = {**case.parameters, 'inlet_pressure_fractions': {'A': -1., 'B': 0.}}
    with pytest.raises(ValueError, match='inlet pressure fractions'):
        run_case(replace(case, parameters=invalid))
    with pytest.raises(CancelledError):
        run_case(case, RunControl(cancel_check=lambda: True))
    with pytest.raises(ValueError, match='unsupported solver mode'):
        run_case(replace(case, metadata={**case.metadata, 'mode': 'unknown'}))
    with pytest.raises(ValueError, match='unsupported quick-design fields'):
        run_case(replace(case, design_fields={**case.design_fields, 'unconsumed': 1.}))
    nonuniform = np.array(case.design_fields['eps'])
    nonuniform[0, 0, 0] *= .9
    with pytest.raises(ValueError, match='uniform eps'):
        run_case(replace(case, design_fields={**case.design_fields, 'eps': nonuniform}))
    parameters = {**case.parameters, 'controls': {**case.parameters['controls'], 'maxit': 1, 'chunk': 1}}
    progress = []
    result = run_case(replace(case, parameters=parameters), RunControl(progress=progress.append))
    assert progress and progress[-1] == 100 and all(0 <= v <= 100 for v in progress)
    assert result.run_status['execution'] == 'completed'
    assert result.run_status['converged'] is False
    assert result.run_status['physical_validation'] == 'not_established'
    assert result.metadata['diagnostics']['warnings_list']
    metrics = evaluate(result).metrics
    assert metrics['Q'].status == 'available' and metrics['Q'].spec.unit == 'W'
    assert metrics['mass'].status == 'unsupported'
