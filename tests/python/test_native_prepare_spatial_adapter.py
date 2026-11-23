"""Verify 2D spatial host preparation, caches, LUT paths, and rejection contracts."""
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest

from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.physical_models import sigmoid_field, tpms_calc, tpms_geometry
from sjtu_tpmshx.preprocess import api
from tests.python import native_preparation_abi
from tests.python.test_native_prepare_adapter import _capture, _same


@pytest.fixture(autouse=True)
def caches():
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()
    yield
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()


def configuration(monkeypatch, tmp_path, mode, topology='Gyroid'):
    config = native_preparation_abi._configuration_spatial(mode, topology)
    if mode == 'sigmoid':
        table = sigmoid_field.GeometryLUT(topology, n_L=2, n_t=2, N=16, cache_dir=tmp_path)
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: table)
        monkeypatch.setitem(sigmoid_field._lut_cache, (topology,), table)
    return config


@pytest.mark.parametrize('mode', ['continuous', 'x', 'y'])
def test_prepared_geometry_fields_use_only_preparation_library(monkeypatch, tmp_path, mode):
    config = (native_preparation_abi._configuration_continuous(pair=('air', 'air'))
              if mode == 'continuous' else native_preparation_abi._configuration_spatial(mode))
    if mode == 'y':
        config.geometry.delta_levelset = .15
    for stage in ('GEOMETRY', 'NATIVE_SOLVER', 'SOLVER', 'RESULT'):
        monkeypatch.setenv(f'TPMSHX_{stage}_LIBRARY', str(tmp_path / f'missing-{stage}'))
    case = api.prepare_case(config, case_id=mode)
    restored = load_case(save_case(case, tmp_path / 'case.yaml'))

    if mode == 'continuous':
        actual = case.design_fields['eps_f_arr']
        assert actual.dtype == np.dtype('float64')
        np.testing.assert_array_equal(actual, .5 * case.design_fields['eps_arr'])
        _same(restored.design_fields['eps_f_arr'], actual)
    else:
        actual = case.design_fields['zone_params']
        saved = restored.design_fields['zone_params']
        assert len(actual) == len(saved) == len(config.zones.config.zones)
        for row, saved_row in zip(actual, saved):
            assert isinstance(row['r_h'], np.float64)
            assert saved_row['name'] == row['name']
            assert saved_row['r_h'] == row['r_h'] == .5 * row['D_h']


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_complete_spatial_case_and_flow_consistency(monkeypatch, tmp_path, mode, topology):
    config = configuration(monkeypatch, tmp_path, mode, topology)
    before = deepcopy(asdict(config))
    caps, _, _, _ = _capture(monkeypatch, api, 'capacity', config)
    resolved, _, _, _ = _capture(monkeypatch, api, 'resolve', config, (.001, .001))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config, (.001, .001))
    for side in 'AB':
        expected_u = .001 / caps[side]
        assert getattr(resolved, 'fluid_' + side).u_mps == pytest.approx(expected_u, rel=1e-13)
        assert case.parameters['u_' + side] == pytest.approx(expected_u, rel=1e-13)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('nominal,spatial', [('Diamond', 'Gyroid'), ('Gyroid', 'Diamond')])
def test_conflicting_spatial_material_keeps_public_rejection(monkeypatch, tmp_path, mode, nominal, spatial):
    config = configuration(monkeypatch, tmp_path, mode, nominal)
    config.geometry.k_s_W_mK = 15.
    config.zones.config.tpms_type, config.zones.config.k_s = spatial, 22.
    config.zones.grid.update(tpms_type=spatial, k_s=22.)
    with pytest.raises(ValueError):
        api.prepare_case(config, case_id='conflict')


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_spatial_host_does_not_reenter_python_preparation(monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.cpp_interface import _native_df, _native_geometry
    from sjtu_tpmshx.physical_models.zone_config import ZoneConfig
    config = configuration(monkeypatch, tmp_path, mode)

    def forbidden(*args, **kwargs):
        pytest.fail('native host reentered a Python numerical workflow')

    monkeypatch.setattr(_native_df, 'project_rows', forbidden)
    monkeypatch.setattr(_native_geometry, 'prepare_sides', forbidden)
    for name in ('compute_properties', 'build_structured_arrays', 'build_structured_geometry',
                 'build_grid_arrays', 'build_grid_geometry'):
        monkeypatch.setattr(ZoneConfig, name, forbidden)
    for name in ('build_continuous_arrays', 'build_continuous_geometry', 'get_geometry_lut'):
        monkeypatch.setattr(sigmoid_field, name, forbidden)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    assert np.all(np.isfinite(case.design_fields['eps_arr']))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_capacity_ignores_unconsumed_experimental_drag(monkeypatch, tmp_path, mode):
    config = configuration(monkeypatch, tmp_path, mode)
    config.df_mode = 'experimental'
    caps, _, _, _ = _capture(monkeypatch, api, 'capacity', config)
    assert caps['A'] > 0. and caps['B'] > 0.


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_default_lut_cold_memory_and_disk_paths(monkeypatch, tmp_path, topology):
    config = native_preparation_abi._configuration_spatial('sigmoid', topology)
    monkeypatch.delitem(sigmoid_field._lut_cache, (topology,), raising=False)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'native'))

    def forbidden(*args, **kwargs):
        pytest.fail('native cold LUT construction reentered Python geometry')

    monkeypatch.setattr(sigmoid_field.GeometryLUT, '_precompute', forbidden)
    monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', forbidden)
    first, _, _, _ = _capture(monkeypatch, api, 'full', config)
    created = sigmoid_field._lut_cache[topology,]
    second, _, _, _ = _capture(monkeypatch, api, 'full', config)
    assert sigmoid_field._lut_cache[topology,] is created
    _same(second.design_fields, first.design_fields)
    monkeypatch.delitem(sigmoid_field._lut_cache, (topology,))
    third, _, _, _ = _capture(monkeypatch, api, 'full', config)
    restored = sigmoid_field._lut_cache[topology,]
    assert restored is not created
    for name in ('L_vals', 't_vals', 'eps_table', 'A0_table'):
        _same(getattr(restored, name), getattr(created, name), name)
    _same(third.design_fields, first.design_fields)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_unsupported_spatial_fluid_raises_not_implemented_or_value_error(monkeypatch, tmp_path, mode):
    config = configuration(monkeypatch, tmp_path, mode)
    config.fluid_A.type, config.fluid_A.T_in_K = 'water', 330.
    with pytest.raises((ValueError, NotImplementedError)):
        api.prepare_case(config, case_id='bad-fluid')


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_spatial_saved_case_round_trip(monkeypatch, tmp_path, mode):
    config = configuration(monkeypatch, tmp_path, mode)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config, (.001, .001))
    save_case(case, tmp_path / 'native.yaml')
    restored = load_case(tmp_path / 'native.yaml')
    _same(restored.grid, case.grid)
    assert set(restored.design_fields) == set(case.design_fields)
    for key, expected in case.design_fields.items():
        actual = restored.design_fields[key]
        if key == 'zone_params':
            assert len(actual) == len(expected)
            for a_row, e_row in zip(actual, expected):
                assert set(a_row) == set(e_row)
                for field_name in e_row:
                    av, ev = a_row[field_name], e_row[field_name]
                    if isinstance(ev, (float, np.floating)):
                        assert float(av).hex() == float(ev).hex(), f'{key}.{field_name}'
                    else:
                        assert av == ev, f'{key}.{field_name}'
        else:
            _same(actual, expected, key)


@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
def test_geometry_cache_queries_receive_initialized_storage(monkeypatch, tmp_path, operation, targets):
    from sjtu_tpmshx.cpp_interface.preparation_host import PreparationCacheBridge
    original = PreparationCacheBridge.geometry_at
    lookups = []

    def observed(self, action, key, value):
        if not action:
            assert all(getattr(value, name) == 0. for name, _ in value._fields_)
            lookups.append((key.cell_length_mm, key.wall_thickness_mm))
        return original(self, action, key, value)

    config = configuration(monkeypatch, tmp_path, 'x')
    monkeypatch.setattr(PreparationCacheBridge, 'geometry_at', observed)
    _capture(monkeypatch, api, operation, config, targets)
    assert lookups


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf')])
def test_raw_spatial_model_rejects_invalid_conductivity(monkeypatch, tmp_path, value):
    from sjtu_tpmshx.cpp_interface import native_preparation
    config = configuration(monkeypatch, tmp_path, 'x')
    original = native_preparation._input

    def invalid(*args, **kwargs):
        source = original(*args, **kwargs)
        source.model.solid_conductivity_W_mK = value
        return source

    monkeypatch.setattr(native_preparation, '_input', invalid)
    with pytest.raises(ValueError, match='spatial.solid_conductivity_W_mK'):
        api.prepare_case(config, case_id='invalid-spatial-material')
