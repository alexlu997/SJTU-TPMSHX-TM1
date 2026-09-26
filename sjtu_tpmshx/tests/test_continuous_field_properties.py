"""Quantized property mapping keeps side inputs, cell order and failures."""
import numpy as np
import pytest

from sjtu_tpmshx.domain.run_warnings import record_warning, warning_scope, warning_messages
from sjtu_tpmshx.models import tpms_calc
from sjtu_tpmshx.models.continuous_field import props_from_Lt_fields


def test_quantized_properties_keep_cell_order_and_side_inputs(monkeypatch):
    calls = []

    def compute(topology, length, wall, velocity, temperature, pressure, k_s):
        calls.append((topology, length, wall, velocity, temperature, pressure, k_s))
        record_warning((length, velocity), f'{length}/{velocity}')
        return dict(epsilon=length, epsilon_A=wall, K_ff=length + velocity,
                    K_ss=k_s, H_sf=velocity, A_0=pressure / 1e5, D_h=length * 2)

    monkeypatch.setattr(tpms_calc, 'compute', compute)
    # Non-contiguous input, repeated pairs and an order different from unique().
    length = np.array([[6.02, 99., 4.99, 99., 6.02, 99.],
                       [4.99, 99., 6.02, 99., 4.99, 99.]])[:, ::2]
    wall = np.where(length > 6., .414, .393)
    with warning_scope({}) as records:
        actual = props_from_Lt_fields(length, wall, 'Gyroid', 17., 2., 3., 400., 300.,
                                      2e5, P_inB=3e5, quant_L=.1, quant_t=.02)
    expected_L = np.array([[6., 5., 6.], [5., 6., 5.]])
    expected_t = np.array([[.42, .4, .42], [.4, .42, .4]])
    expected = dict(eps_arr=expected_L, eps_f_arr=expected_t,
                    K_ffA_arr=expected_L + 2., K_ffB_arr=expected_L + 3.,
                    K_ss_arr=np.full((2, 3), 17.), h_vA_arr=np.full((2, 3), 4.),
                    h_vB_arr=np.full((2, 3), 9.), r_h_arr=expected_L,
                    A_0_arr=np.full((2, 3), 2.))
    assert set(actual) == {*expected, 'n_unique'} and actual['n_unique'] == 2
    for key, value in expected.items():
        assert actual[key].dtype == np.float64 and actual[key].flags.writeable
        np.testing.assert_array_equal(actual[key], value)
        assert not np.shares_memory(actual[key], length)
        assert not np.shares_memory(actual[key], wall)
        assert all(not np.shares_memory(actual[key], actual[other])
                   for other in expected if other != key)
    assert calls == [
        ('Gyroid', 5., .4, 2., 400., 2e5, 17.),
        ('Gyroid', 5., .4, 3., 300., 3e5, 17.),
        ('Gyroid', 6., .42, 2., 400., 2e5, 17.),
        ('Gyroid', 6., .42, 3., 300., 3e5, 17.),
    ]
    assert list(warning_messages(records)) == ['5.0/2.0', '5.0/3.0', '6.0/2.0', '6.0/3.0']


def test_quantized_properties_stop_at_original_compute_failure(monkeypatch):
    calls = []
    failure = RuntimeError('second geometry B failed')

    def compute(topology, length, wall, velocity, temperature, pressure, k_s):
        calls.append((length, velocity, pressure))
        if (length, velocity) == (6., 3.):
            raise failure
        return dict(epsilon=.5, epsilon_A=.25, K_ff=1e-9, K_ss=17.,
                    H_sf=10., A_0=2., D_h=.001)

    monkeypatch.setattr(tpms_calc, 'compute', compute)
    with pytest.raises(RuntimeError) as caught:
        props_from_Lt_fields(np.array([7., 6., 5.]), np.full(3, .4),
                             'Gyroid', 17., 2., 3., 400., 300., 2e5)
    assert caught.value is failure
    assert calls == [(5., 2., 2e5), (5., 3., 2e5), (6., 2., 2e5), (6., 3., 2e5)]


@pytest.mark.parametrize('shape', [(0,), (2, 0, 3)])
def test_empty_quantized_fields_do_not_compute(monkeypatch, shape):
    def unexpected(*args, **kwargs):
        raise AssertionError('empty field must not compute')
    monkeypatch.setattr(tpms_calc, 'compute', unexpected)
    actual = props_from_Lt_fields(np.empty(shape), np.empty(shape),
                                  'Gyroid', 17., 2., 3., 400., 300.)
    assert actual.pop('n_unique') == 0
    for value in actual.values():
        assert value.shape == shape and value.dtype == np.float64
