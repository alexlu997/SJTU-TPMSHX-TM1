"""Verify 2D spatial host preparation, caches, LUT paths, and rejection contracts."""
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest

from tm1.file_io.case_io import load_case, save_case
from tm1.physical_models import sigmoid_field, tpms_calc, tpms_geometry
from tm1.preprocess import api
from tests.python import native_preparation_abi
from tests.python.native_adapters.test_native_prepare_adapter import _capture, _same


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
        native_preparation_abi.supply_sigmoid_table(monkeypatch, table)
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
    from tm1.cpp_interface import _native_df, _native_geometry
    from tm1.physical_models.zone_config import ZoneConfig
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
    from tm1.cpp_interface._native_lut import table_value

    table_value.cache_clear()
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    from tm1.cpp_interface import native_preparation
    run = native_preparation.run_preparation

    def fail_after_file(*args, validate, **kwargs):
        def check_grid(stage, side):
            if stage == 3:
                raise ArithmeticError('requested grid after first table')
            validate(stage, side)
        return run(*args, validate=check_grid, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(native_preparation, 'run_preparation', fail_after_file)
        with pytest.raises(ArithmeticError, match='requested grid after first table'):
            _capture(monkeypatch, api, 'full', config)
    assert (tmp_path / f'tm1/geometry/lut_{topology}_41x31_N256.npz').is_file()
    assert table_value.cache_info().currsize == 1
    first, first_events, first_ranges, _ = _capture(monkeypatch, api, 'full', config)
    file, = (tmp_path / 'tm1/geometry').glob('*.npz')
    with np.load(file, allow_pickle=False) as stored:
        assert stored['eps_table'].shape == (41, 31) and int(stored['N'][0]) == 256
    with monkeypatch.context() as warm:
        warm.setattr(sigmoid_field, '_read_table', lambda *args: pytest.fail('memory hit read an NPZ'))
        second, events, ranges, _ = _capture(monkeypatch, api, 'full', config)
    _same(second.design_fields, first.design_fields)
    assert events == first_events and ranges == first_ranges
    table_value.cache_clear()
    monkeypatch.setattr(sigmoid_field, '_write_table', lambda *args: pytest.fail('valid NPZ was replaced'))
    third, events, ranges, _ = _capture(monkeypatch, api, 'full', config)
    _same(third.design_fields, first.design_fields)
    assert events == first_events and ranges == first_ranges


@pytest.mark.parametrize('operation,targets,expected', [
    ('capacity', None, [3, 4, 'NPZ']),
    ('resolve', (.001, .001), [3, 4, 'NPZ']),
    ('full', (.001, .001), [3, 4, 'NPZ', 0, 4]),
    ('full', None, [0, 4, 'NPZ', 3]),
])
def test_sigmoid_file_access_follows_the_first_grid_validation(monkeypatch, tmp_path, operation, targets, expected):
    from tm1.cpp_interface import native_preparation
    from tm1.cpp_interface._native_lut import table_value
    from tm1.model_configs.df_domain import TRAIN_L, TRAIN_T

    config = native_preparation_abi._configuration_spatial('sigmoid')
    table_value.cache_clear()
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    seen = []
    fail_at_zone_check = True
    original = native_preparation.run_preparation

    def run(*args, validate, **kwargs):
        def record(stage, side):
            seen.append(stage)
            if stage == 4 and fail_at_zone_check:
                raise LookupError('zone validation')
            validate(stage, side)
        return original(*args, validate=record, **kwargs)

    monkeypatch.setattr(native_preparation, 'run_preparation', run)
    read = sigmoid_field._read_table

    def read_file(*args):
        seen.append('NPZ')
        return read(*args)

    monkeypatch.setattr(sigmoid_field, '_read_table', read_file)
    with pytest.raises(LookupError, match='zone validation'):
        _capture(monkeypatch, api, operation, config, targets)
    assert seen == expected[:expected.index('NPZ')]
    assert not (tmp_path / 'tm1').exists()

    fail_at_zone_check = False
    path = tmp_path / 'tm1/geometry/lut_Gyroid_41x31_N256.npz'
    path.parent.mkdir(parents=True)
    np.savez_compressed(path, L_vals=np.linspace(*TRAIN_L, 41), t_vals=np.linspace(*TRAIN_T, 31),
                        eps_table=np.full((41, 31), .7), A0_table=np.full((41, 31), 1300.),
                        tpms_type=['Gyroid'], N=[256])
    seen.clear()
    _capture(monkeypatch, api, operation, config, targets)
    assert seen == expected
    seen.clear()
    _capture(monkeypatch, api, operation, config, targets)
    assert seen == [stage for stage in expected if stage != 'NPZ']


def test_sigmoid_resolve_without_targets_skips_disk(monkeypatch, tmp_path):
    from tm1.cpp_interface._native_lut import table_value
    table_value.cache_clear()
    config = native_preparation_abi._configuration_spatial('sigmoid')
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setattr(sigmoid_field, 'load_default_table', lambda *args: pytest.fail('unexpected LUT request'))
    resolved, *_ = _capture(monkeypatch, api, 'resolve', config)
    assert resolved.fluid_A.u_mps == config.fluid_A.u_mps
    assert not (tmp_path / 'tm1').exists() and table_value.cache_info().currsize == 0


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
def test_spatial_geometry_is_available_to_standalone_queries(monkeypatch, tmp_path, operation, targets):
    from tm1.physical_models.tpms_geometry import compute_geometry

    config = configuration(monkeypatch, tmp_path, 'x')
    _capture(monkeypatch, api, operation, config, targets)
    before = compute_geometry.cache_info()
    compute_geometry(config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm)
    after = compute_geometry.cache_info()
    assert after.hits == before.hits + 1 and after.misses == before.misses


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf')])
def test_raw_spatial_model_rejects_invalid_conductivity(monkeypatch, tmp_path, value):
    from tm1.cpp_interface import native_preparation
    config = configuration(monkeypatch, tmp_path, 'x')
    original = native_preparation.pack_input

    def invalid(*args, **kwargs):
        source, error = original(*args, **kwargs)
        source.model.solid_conductivity_W_mK = value
        return source, error

    monkeypatch.setattr(native_preparation, 'pack_input', invalid)
    with pytest.raises(ValueError, match='spatial.solid_conductivity_W_mK'):
        api.prepare_case(config, case_id='invalid-spatial-material')
