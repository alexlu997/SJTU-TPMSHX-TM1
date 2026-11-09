"""Capture each thermal grid's actual ordering without a numerical call."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.cpp.full_2d import _set_native_metadata
from sjtu_tpmshx.solvers.backends.cpp.full_2d_capture import _fine_evidence


@pytest.mark.parametrize('main_shape, red_black, expected', [
    ((80, 100), True, (False, True)),
    ((150, 200), True, (False, True)),
    ((75, 100), True, (False, False)),
    ((80, 100), False, (False, False)),
])
def test_main_and_fine_ordering_survive_fine_capture(main_shape, red_black, expected):
    fine_shape = tuple(2 * n for n in main_shape)
    algorithm = 'model_h_tface_sou_fou_strict_v3'
    raw = dict(main=dict(shape=main_shape, temperature_evidence=dict(algorithm=algorithm)),
               fine=dict(shape=fine_shape, temperature_evidence=dict(algorithm=algorithm)))
    _set_native_metadata(raw, 2, 'shared_fv_cc2d_tminmod_guarded_line_v1', red_black)
    for stage, ordering in zip((raw['main'], raw['fine']), expected):
        assert stage['native_metadata'] == dict(abi=2, algorithm=algorithm, red_black=ordering)
    assert raw['native_metadata'] == raw['main']['native_metadata']
    assert set(raw['native_metadata']) == {'abi', 'algorithm', 'red_black'}

    field = np.zeros(fine_shape)
    fine = dict(raw['fine'], temperature=(field, field, field),
                dx=np.ones(fine_shape[0]), dy=np.ones(fine_shape[1]), epsilon=field)
    for key in ('uc', 'vc', 'rho_cp'):
        fine[key] = (field, field)
    for key in ('inlet_profile', 'outlet_profile'):
        fine[key] = (np.ones(fine_shape[1]), np.ones(fine_shape[0]))
    fine['mass_x'] = tuple(np.zeros((fine_shape[0] + 1, fine_shape[1])) for _ in 'AB')
    fine['mass_y'] = tuple(np.zeros((fine_shape[0], fine_shape[1] + 1)) for _ in 'AB')
    captured = _fine_evidence(fine, None)
    assert captured['native'] == raw['fine']['native_metadata']
    assert captured['native']['red_black'] is expected[1]


def test_main_identity_without_a_refined_grid():
    raw = dict(main=dict(shape=(200, 200)), fine=None)
    _set_native_metadata(raw, 2, 'shared_fv_model_h2d_tface_defect_v1', True)
    assert raw['native_metadata']['red_black'] is True
    assert raw['fine'] is None
