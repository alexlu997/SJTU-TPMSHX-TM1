"""Quick Design early stopping retains the fully iterated outlet temperature."""
from dataclasses import replace

import pytest

from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import forward
from sjtu_tpmshx.models.quick_design import SIZING_QTOL, SIZING_CHUNK
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate


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
