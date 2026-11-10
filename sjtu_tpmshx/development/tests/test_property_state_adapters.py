"""State adapters retain error precedence, context and explicit causes."""
import numpy as np
import pytest

from sjtu_tpmshx.development.tests import eos_reference as reference
from sjtu_tpmshx.shared.models import fluid_props, sco2_props


def observation(function):
    try:
        function()
    except Exception as error:
        cause = error.__cause__
        return (type(error).__name__, error.args, str(error),
                None if cause is None else (type(cause).__name__, cause.args, str(cause)))
    return None


@pytest.mark.parametrize('temperature,pressure', [
    ([], []), (np.nan, 101325.), (300., 0.),
    ([420., np.nan], 200000.),
    (300., 30000000.), (260., 101325.), (420., 200000.), (1., 101325.),
    ([300., 310.], [101325., 200000., 300000.]),
])
def test_water_error_structure_matches_frozen_guard(temperature, pressure):
    kwargs = dict(where='adapter reference')
    actual = observation(lambda: fluid_props.check_water_state('water', temperature, pressure, **kwargs))
    expected = observation(lambda: reference.check_water_state('water', temperature, pressure, **kwargs))
    assert actual == expected


@pytest.mark.parametrize('where', [None, 'adapter reference'])
@pytest.mark.parametrize('temperature,pressure', [
    (np.array([np.nan, 300.]), np.array([9e6, 9e6, 9e6])),
    (np.array([[300., np.nan]]), np.array([9e6, 9e6, 9e6])),
    (np.nan, np.empty(0)),
    (np.array([[300., 280.], [710., 300.]]), np.array([9e6, 17e6])),
])
def test_sco2_bounds_and_shape_error_order(temperature, pressure, where):
    actual = observation(lambda: sco2_props._validate_state(temperature, pressure, where=where))
    expected = observation(lambda: reference.validate_sco2_state(temperature, pressure, where=where))
    assert actual == expected
