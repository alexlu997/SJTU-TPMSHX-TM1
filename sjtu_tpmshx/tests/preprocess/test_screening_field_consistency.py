"""Prebuilt screening fields must share the physical configuration."""
import numpy as np
import pytest

from sjtu_tpmshx.models.continuous_field import from_decision_vector, uniform_field
from sjtu_tpmshx.preprocess.api import prepare_screening_2d


@pytest.mark.parametrize('key,value', [
    ('tpms_type', 'Gyroid'), ('k_s', 30.),
    ('L_domain', .2), ('H_domain', .1),
])
def test_prebuilt_field_rejects_conflicting_physical_defaults(key, value):
    geometry = dict(tpms_type='Diamond', k_s=17., L_domain=.1, H_domain=.05)
    geometry[key] = value
    field = uniform_field(6., .4, **geometry)
    with pytest.raises(ValueError, match=key):
        prepare_screening_2d(None, dict(Nx=4, Ny=4, u_A=5., u_B=5.),
                              fc=field, case_id='conflicting-field')


def test_evaluator_rejects_conflicting_field_before_solving(monkeypatch):
    from sjtu_tpmshx.optimization.evaluator import evaluate_design
    from sjtu_tpmshx.solvers import api

    def unexpected_solve(*args, **kwargs):
        pytest.fail('conflicting field reached the numerical solver')

    monkeypatch.setattr(api, 'run_case', unexpected_solve)
    field = uniform_field(6., .4, 'Gyroid', 17., .1, .05)
    with pytest.raises(ValueError, match='tpms_type'):
        evaluate_design(None, dict(Nx=4, Ny=4, u_A=5., u_B=5.), fc=field)


@pytest.mark.parametrize('per_cell_K', [False, True])
def test_matching_field_keeps_its_layout_and_matches_decoded_preparation(per_cell_K):
    geometry = dict(tpms_type='Gyroid', k_s=21., L_domain=.12, H_domain=.07)
    layout = dict(n_ctrl_x=3, n_ctrl_y=5, symmetric_y=False, spline_order=2,
                  L_bounds=(5., 7.), t_bounds=(.35, .5))
    decision = np.r_[np.linspace(5., 7., 15), np.linspace(.35, .5, 15)]
    field = from_decision_vector(decision, **geometry, **layout)
    cfg = dict(**geometry, Nx=4, Ny=4, u_A=5., u_B=5., per_cell_K=per_cell_K)
    actual = prepare_screening_2d(None, cfg, fc=field, case_id='prebuilt')
    expected = prepare_screening_2d(decision, {**cfg, **layout}, case_id='decoded')

    # The prebuilt field's 3x5 quadratic/clamped layout replaces default
    # decoder settings; the physical geometry must still agree with cfg.
    for group in ('grid', 'design_fields'):
        got, want = getattr(actual, group), getattr(expected, group)
        assert got.keys() == want.keys()
        for key in want:
            np.testing.assert_array_equal(got[key], want[key])
    for key in ('L_cell_m', 't_wall_m'):
        np.testing.assert_array_equal(actual.metadata['geometry_fields'][key],
                                      expected.metadata['geometry_fields'][key])
    for side in ('A', 'B'):
        got, want = (case.parameters['flow'][side] for case in (actual, expected))
        assert got.keys() == want.keys()
        for key in want:
            if key == 'initial':
                assert got[key].keys() == want[key].keys()
                for name in want[key]:
                    np.testing.assert_array_equal(got[key][name], want[key][name])
            else:
                np.testing.assert_array_equal(got[key], want[key])
    assert actual.parameters['rejection'] == expected.parameters['rejection'] is None
    assert actual.metadata['warnings'] == expected.metadata['warnings']
