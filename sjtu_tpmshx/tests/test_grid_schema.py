"""Grid-array output contract (solvers/grid_schema.py, refactor B1 1.6).

Pins the shared dict schema emitted by ZoneConfig.build_structured_arrays
and ContinuousFieldConfig.build_grid_arrays so a key added to one builder
cannot silently go missing from the other.
"""
import numpy as np
import pytest

from sjtu_tpmshx.models.grid_schema import GRID_ARRAY_KEYS, validate_grid_arrays


def _valid_dict(Nx=4, Ny=3):
    d = {k: np.ones((Nx, Ny), dtype=np.float64) for k in GRID_ARRAY_KEYS}
    d['zone_id'] = np.zeros((Nx, Ny), dtype=np.int32)
    d['axis'] = 'y'
    return d


def test_valid_dict_passes_and_returns_same_object():
    d = _valid_dict()
    assert validate_grid_arrays(d, 4, 3, where='test') is d


def test_extra_keys_allowed():
    d = _valid_dict()
    d['zone_params'] = [{'name': 'z0'}]
    d['cache_size'] = 1
    validate_grid_arrays(d, 4, 3, where='test')


@pytest.mark.parametrize('missing', list(GRID_ARRAY_KEYS) + ['zone_id', 'axis'])
def test_missing_key_raises(missing):
    d = _valid_dict()
    del d[missing]
    with pytest.raises(ValueError, match='test-builder'):
        validate_grid_arrays(d, 4, 3, where='test-builder')


def test_wrong_shape_raises():
    d = _valid_dict()
    d['K_ffA_arr'] = np.ones((3, 4), dtype=np.float64)  # transposed
    with pytest.raises(ValueError, match='K_ffA_arr'):
        validate_grid_arrays(d, 4, 3, where='test')


def test_wrong_dtype_raises():
    d = _valid_dict()
    d['eps_arr'] = np.ones((4, 3), dtype=np.float32)
    with pytest.raises(ValueError, match='eps_arr'):
        validate_grid_arrays(d, 4, 3, where='test')


def test_zone_id_must_be_integer_grid():
    d = _valid_dict()
    d['zone_id'] = np.zeros((4, 3), dtype=np.float64)
    with pytest.raises(ValueError, match='zone_id'):
        validate_grid_arrays(d, 4, 3, where='test')


def test_continuous_field_builder_conforms():
    """Integration: the real optimizer-path builder passes the validator
    (it is wired through validate_grid_arrays at its return)."""
    from sjtu_tpmshx.models.continuous_field import uniform_field
    fc = uniform_field(6.0, 0.4, 'Diamond', 15.0, 0.1, 0.1)
    arrays = fc.build_grid_arrays(8, 8, u_A=5.0, u_B=3.0,
                                  T_inA=400.0, T_inB=300.0)
    assert set(GRID_ARRAY_KEYS).issubset(arrays.keys())
