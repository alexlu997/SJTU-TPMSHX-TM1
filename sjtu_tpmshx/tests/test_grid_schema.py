"""Grid-array output contract for the active ZoneConfig builders."""
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
