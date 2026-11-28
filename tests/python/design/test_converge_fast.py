"""Quick Design early stopping retains the fully iterated outlet temperature."""
from dataclasses import replace

import pytest

from tm1.applications.design.cases import DesignCase
from tm1.applications.design.forward import forward
from tm1.model_configs.model_parameters import load_quick_design_parameters

_CROSS = load_quick_design_parameters()['arrangements']['cross']
SIZING_QTOL, SIZING_CHUNK = _CROSS['qtol'], _CROSS['chunk']
from tm1.preprocess.api import prepare_quick_design
from tm1.solvers.api import run_case
from tm1.postprocess.api import evaluate


def _case():
    return DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                      None, 0.08, 0.08, dT=300.)


@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
def test_fast_converge_matches_reference(arrangement):
    case = prepare_quick_design(_case(), 'Diamond', 7., .5, .084, .084,
                                arrangement, case_id='full-budget-reference')
    controls = dict(case.parameters['controls'], qtol=None, chunk=None)
    reference = run_case(replace(case, parameters={**case.parameters, 'controls': controls}))
    fast = forward(_case(), 'Diamond', 7., .5, .084, .084, arrangement)
    assert abs(fast.T_out_hot - evaluate(reference).metrics['T_out_A'].value) < .05


def test_sizing_params_are_effective_thresholds():
    assert SIZING_QTOL >= 1e-5 and SIZING_CHUNK <= 200
