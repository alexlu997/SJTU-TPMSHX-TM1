"""Audit the initial flow and thermal stages on the prepared 24-cubed grid.

Keep the original 20000-iteration limit, the 25/250-step probes, and the
six thermal gates. Candidate algebra is covered in test_anderson_candidate.
"""
import copy

import numpy as np
import pytest

from sjtu_tpmshx.tests.native import test_full_3d as full
from sjtu_tpmshx.tests.native import test_model_h_3d as model_h

native_full = full.native
native_thermal = model_h.native


@pytest.fixture(scope='module')
def first_thermal_entry(native_full):
    cfg, p = full.prepared('air-air', counts=(8, 8, 8), mesh='wall_refine_3d', port_wall_refine=True)
    p['max_outer'] = 1
    assert tuple(p['N'+axis] for axis in 'xyz') == (24, 24, 24)
    assert p['ltne_max_iter'] == 20000
    actual = native_full.run(cfg, p)
    full.audit_full(actual, cfg, p)
    assert actual[202][3] and not actual[202][1]
    case = full.thermal_case(actual, cfg, p)
    case.update(maxit=20000, chunk=250, warm=False, accelerate=True,
                rb=False, alpha=(.7, 1., .7), qtol=1e-4)
    case['state'] = [np.full(case['shape'], value) for value in (*case['tin'], .5*sum(case['tin']))]
    return cfg, p, actual, case


def test_refined_initial_flow_before_first_thermal(native_full, first_thermal_entry):
    cfg, p, _, _ = first_thermal_entry
    actual = native_full.run(cfg, p, cancel_before_thermal=True)
    assert actual['code'] == 0, actual['error']
    stats = actual[202]
    assert stats[0] == 2
    assert stats[1] == stats[3] == stats[4] == stats[7] == 0
    assert actual[200].shape == (0, 16)
    assert all(actual[key].size == 0 for key in range(27))
    full.audit_flow(actual, cfg, p)
    assert stats[26] == stats[36] == 1


def test_refined_first_thermal_from_identical_inputs(native_thermal, first_thermal_entry):
    _, _, full_result, inputs = first_thermal_entry
    case = copy.deepcopy(inputs)
    history = []
    actual = native_thermal(case, history=history)
    model_h.assert_actual_state(case, actual)
    model_h.assert_finishing_history(case, actual, history)
    assert actual[1][0] == 0 and 0 < actual[1][1] <= 20000
    assert actual[1][1] == full_result[200][0, 1]
    for side in range(3):
        np.testing.assert_allclose(case['state'][side].ravel(), full_result[side], rtol=2e-10, atol=2e-8)


@pytest.mark.parametrize('count,accelerate', [(25, False), (250, True)])
def test_refined_first_chunk_returned_equations(native_thermal, first_thermal_entry, count, accelerate):
    case = copy.deepcopy(first_thermal_entry[3])
    assert case['shape'] == (24, 24, 24)
    assert (case['maxit'], case['chunk'], case['alpha']) == (20000, 250, (.7, 1., .7))
    case.update(maxit=count, accelerate=accelerate)
    history = []
    result = native_thermal(case, history=history)
    assert result[0] == 0, result[-1]
    assert result[1][1] == count
    model_h.assert_actual_state(case, result)
    model_h.assert_finishing_history(case, result, history)
